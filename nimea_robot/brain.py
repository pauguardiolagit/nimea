"""El cerebro de Nimea: la conversación con la IA (Claude)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

import anthropic

from .tools import DEFINICIONES, Herramientas

log = logging.getLogger("nimea.brain")

BETA_FALLBACK = "server-side-fallback-2026-07-01"
NO_ENTIENDO = "Perdona, se me ha ido el santo al cielo. ¿Me lo repites?"
MAX_PASOS = 8


class Frases:
    """Corta el texto que llega en streaming en frases completas, para empezar a hablar
    en cuanto la primera está lista en vez de esperar a la respuesta entera."""

    FIN = re.compile(r"[.!?…:;](\s+)")

    def __init__(self, decir: Callable[[str], None], minimo: int = 12) -> None:
        self.decir = decir
        self.minimo = minimo
        self.buffer = ""

    def alimentar(self, texto: str) -> None:
        self.buffer += texto
        desde = 0
        for m in self.FIN.finditer(self.buffer):
            # Las frases muy cortas ("Vaya.") se juntan con la siguiente para que suene natural.
            if len(self.buffer[desde:m.start() + 1].strip()) >= self.minimo:
                self._emitir(self.buffer[desde:m.start() + 1])
                desde = m.end()
        self.buffer = self.buffer[desde:]

    def cerrar(self) -> None:
        if self.buffer.strip():
            self._emitir(self.buffer)
        self.buffer = ""

    def _emitir(self, frase: str) -> None:
        frase = frase.strip()
        if frase:
            self.decir(frase)


@dataclass
class Respuesta:
    texto: str
    terminada: bool


class Cerebro:
    def __init__(self, cfg, cliente: Any | None = None) -> None:
        self.cfg = cfg
        self.cliente = cliente or anthropic.Anthropic()
        self.sistema = ""
        self.mensajes: list[dict[str, Any]] = []

    def nueva_conversacion(self, sistema: str) -> None:
        # El historial solo crece dentro de una conversación: no se recorta ni se reescribe,
        # así el razonamiento de turnos anteriores sigue siendo válido y la caché funciona.
        self.sistema = sistema
        self.mensajes = []

    def turno(self, texto: str, herramientas: Herramientas, decir: Callable[[str], None]) -> Respuesta:
        """Procesa lo que ha dicho la persona y va diciendo la respuesta frase a frase."""
        inicio = len(self.mensajes)
        self.mensajes.append({"role": "user", "content": texto})
        dicho: list[str] = []

        def decir_y_guardar(frase: str) -> None:
            dicho.append(frase)
            decir(frase)

        reintentos = 0
        for _ in range(MAX_PASOS):
            frases = Frases(decir_y_guardar)
            try:
                final = self._llamar(frases)
            except ValueError:
                # JSON de argumentos imposible de leer: se repite el turno (pocas veces).
                reintentos += 1
                if reintentos > 2:
                    self._deshacer(inicio)
                    decir(NO_ENTIENDO)
                    return Respuesta(NO_ENTIENDO, False)
                continue
            except anthropic.APIError as e:
                log.error("Error de la API: %s", e)
                self._deshacer(inicio)
                decir(NO_ENTIENDO)
                return Respuesta(NO_ENTIENDO, False)
            frases.cerrar()

            if final.stop_reason == "refusal":
                log.warning("Rechazo: %s", getattr(final, "stop_details", None))
                self._deshacer(inicio)
                decir(NO_ENTIENDO)
                return Respuesta(NO_ENTIENDO, False)

            self.mensajes.append({"role": "assistant", "content": final.content})
            usos = [b for b in final.content if b.type == "tool_use"]
            if not usos:
                break
            if final.stop_reason == "max_tokens":
                # Argumentos cortados: no se ejecuta nada a medias.
                self.mensajes.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                     "content": "Respuesta cortada; inténtalo de forma más breve."} for b in usos]})
                continue

            resultados = []
            for b in usos:
                contenido, error = herramientas.ejecutar(b.name, b.input)
                log.info("Herramienta %s(%s) -> %s", b.name, json.dumps(b.input, ensure_ascii=False),
                         contenido if isinstance(contenido, str) else "[imagen]")
                resultados.append({"type": "tool_result", "tool_use_id": b.id,
                                   "content": contenido, "is_error": error})
            self.mensajes.append({"role": "user", "content": resultados})
        return Respuesta(" ".join(dicho), herramientas.terminada)

    def _params(self, mensajes: list[dict[str, Any]]) -> dict[str, Any]:
        params: dict[str, Any] = dict(
            model=self.cfg.modelo,
            max_tokens=4096,
            system=self.sistema,
            messages=mensajes,
            tools=DEFINICIONES,
            output_config={"effort": self.cfg.esfuerzo},
            cache_control={"type": "ephemeral"},
        )
        if self.cfg.fallbacks:
            # Si el modelo rechazara una petición, la API la repite con el modelo de respaldo.
            params.update(betas=[BETA_FALLBACK], fallbacks="default")
        return params

    def _llamar(self, frases: Frases):
        params = self._params(self.mensajes)
        with self.cliente.beta.messages.stream(**params) as stream:
            for evento in stream:
                if evento.type == "text":
                    frases.alimentar(evento.text)
            return stream.get_final_message()

    def _deshacer(self, inicio: int) -> None:
        """Tras un fallo, borra el turno entero para que el historial siga siendo válido."""
        del self.mensajes[inicio:]

    def resumir(self) -> dict[str, Any] | None:
        """Resumen de una charla que terminó sin despedida (por silencio)."""
        if not self.mensajes:
            return None
        esquema = {
            "type": "object",
            "properties": {
                "resumen": {"type": "string"},
                "frase_destacada": {"type": "string"},
                "temas": {"type": "array", "items": {"type": "string"}},
                "personas_mencionadas": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["resumen", "frase_destacada", "temas", "personas_mencionadas"],
            "additionalProperties": False,
        }
        peticion = {"type": "text", "text": (
            "La charla ha terminado. Resúmela para la familia en dos frases cálidas, sin nada "
            "que te haya pedido guardar en privado.")}
        if self.mensajes[-1]["role"] == "user":
            # El último turno ya es nuestro (p. ej. resultados de herramientas): lo ampliamos.
            ultimo = self.mensajes[-1]
            mensajes = self.mensajes[:-1] + [{"role": "user", "content": _como_lista(ultimo["content"]) + [peticion]}]
        else:
            mensajes = self.mensajes + [{"role": "user", "content": [peticion]}]
        try:
            params = self._params(mensajes)
            params["output_config"] = {"effort": "low",
                                       "format": {"type": "json_schema", "schema": esquema}}
            r = self.cliente.beta.messages.create(**params)
        except anthropic.APIError as e:
            log.error("No se pudo resumir: %s", e)
            return None
        if r.stop_reason != "end_turn":
            return None
        texto = next((b.text for b in r.content if b.type == "text"), "")
        try:
            return json.loads(texto)
        except ValueError:
            return None


def _como_lista(contenido: Any) -> list[Any]:
    return list(contenido) if isinstance(contenido, list) else [{"type": "text", "text": contenido}]
