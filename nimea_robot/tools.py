"""Herramientas que la IA puede usar durante la conversación."""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np

from .api import ApiNimea, Contexto
from .audio import a_wav, decodificar
from .bienestar import DIMENSIONES, RESULTADOS_RETO, TIPOS_RETO, Sesion

log = logging.getLogger("nimea.tools")

GESTOS = ["alegria", "asentir", "pensar", "sorpresa", "carino", "baile", "escuchar"]


class Cuerpo(Protocol):
    """Lo que el robot sabe hacer con el cuerpo. Lo implementa el Reachy (o la consola)."""

    def decir(self, texto: str) -> None: ...
    def reproducir(self, pcm: np.ndarray) -> None: ...
    def grabar(self, segundos_max: float) -> tuple[np.ndarray | None, str]: ...
    def gesto(self, nombre: str) -> None: ...
    def foto_jpeg(self) -> bytes | None: ...


def _obj(propiedades: dict[str, Any], requeridas: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": propiedades, "required": requeridas,
            "additionalProperties": False}


TEXTO = {"type": "string"}

DEFINICIONES: list[dict[str, Any]] = [
    {
        "name": "reproducir_mensaje",
        "description": "Pone el audio de un familiar o lee en voz alta su mensaje o reto. Úsala "
                       "después de preguntar si quiere oírlo. Tras escucharlo, pregúntale si quiere "
                       "contestar.",
        "input_schema": _obj({"mensaje_id": TEXTO}, ["mensaje_id"]),
    },
    {
        "name": "grabar_respuesta",
        "description": "Graba la respuesta en voz de la persona para el familiar que envió el "
                       "mensaje y se la manda a su móvil. Úsala solo cuando haya dicho que quiere "
                       "contestar; ella hablará justo después del pitido. Devuelve lo que ha dicho.",
        "input_schema": _obj({"mensaje_id": TEXTO}, ["mensaje_id"]),
    },
    {
        "name": "enviar_audio_a_familiar",
        "description": "Graba un audio nuevo de la persona para un familiar (sin que haya un "
                       "mensaje previo) y se lo manda. Úsala cuando quiera decirle algo a alguien "
                       "de su familia.",
        "input_schema": _obj({"familiar_id": TEXTO}, ["familiar_id"]),
    },
    {
        "name": "confirmar_pastilla",
        "description": "Registra si se ha tomado una pastilla. Solo con su confirmación clara; "
                       "si duda, usa 'pospuesta'.",
        "input_schema": _obj({
            "medicacion_id": TEXTO,
            "hora_prevista": {"type": "string", "description": "HH:MM de la toma"},
            "estado": {"type": "string", "enum": ["confirmada", "no_confirmada", "pospuesta"]},
        }, ["medicacion_id", "hora_prevista", "estado"]),
    },
    {
        "name": "registrar_reto",
        "description": "Anota un reto o juego de mente que acabáis de hacer y cómo ha ido.",
        "input_schema": _obj({
            "tipo": {"type": "string", "enum": TIPOS_RETO},
            "enunciado": TEXTO,
            "resultado": {"type": "string", "enum": RESULTADOS_RETO},
        }, ["tipo", "enunciado", "resultado"]),
    },
    {
        "name": "anotar_bienestar",
        "description": "Anota en silencio algo que has notado de su día, para el resumen de la "
                       "familia. Valor de 1 (bajo) a 5 (muy bien). No la interrogues: anota lo "
                       "que surja de forma natural. Dimensiones: "
                       + " ".join(DIMENSIONES.values()),
        "input_schema": _obj({
            "dimension": {"type": "string", "enum": list(DIMENSIONES)},
            "valor": {"type": "integer", "minimum": 1, "maximum": 5},
            "nota": {"type": "string", "description": "Una frase corta y amable"},
        }, ["dimension", "valor", "nota"]),
    },
    {
        "name": "guardar_recuerdo",
        "description": "Guarda algo importante que te ha contado (una persona, un lugar, una "
                       "anécdota, una receta, un gusto) para recordarlo en otras charlas. Si te "
                       "pide que sea un secreto, márcalo como privado y no se compartirá.",
        "input_schema": _obj({
            "titulo": TEXTO,
            "descripcion": TEXTO,
            "privado": {"type": "boolean"},
        }, ["titulo", "descripcion", "privado"]),
    },
    {
        "name": "avisar_familia",
        "description": "Manda un aviso a la familia. 'importante' solo si pide ayuda, se ha "
                       "caído, se encuentra mal o algo te preocupa de verdad; 'informativo' para "
                       "peticiones normales (que la llamen, que le traigan algo).",
        "input_schema": _obj({
            "texto": TEXTO,
            "nivel": {"type": "string", "enum": ["informativo", "importante"]},
        }, ["texto", "nivel"]),
    },
    {
        "name": "gesto",
        "description": "Mueve la cabeza y las antenas para acompañar lo que dices: alegria, "
                       "asentir, pensar, sorpresa, carino, baile (cuando suena música o celebráis "
                       "algo) o escuchar.",
        "input_schema": _obj({"nombre": {"type": "string", "enum": GESTOS}}, ["nombre"]),
    },
    {
        "name": "mirar",
        "description": "Mira con la cámara lo que tienes delante, solo cuando ella te pida que "
                       "mires algo (una foto, una planta, lo que lleva puesto). La imagen no se "
                       "guarda ni se envía a la familia.",
        "input_schema": _obj({}, []),
    },
    {
        "name": "terminar_conversacion",
        "description": "Cierra la conversación cuando se despida o la charla haya terminado de "
                       "forma natural. Después de esto Nimea se queda en reposo hasta que la "
                       "llamen. Resume en tono cálido para la familia, sin incluir nada privado.",
        "input_schema": _obj({
            "resumen": TEXTO,
            "frase_destacada": {"type": "string", "description": "Una frase bonita que haya dicho ella"},
            "temas": {"type": "array", "items": TEXTO},
            "personas_mencionadas": {"type": "array", "items": TEXTO},
        }, ["resumen", "frase_destacada", "temas", "personas_mencionadas"]),
    },
]

for _d in DEFINICIONES:
    # Con streaming, los argumentos llegan según se generan; los validamos nosotros.
    _d["eager_input_streaming"] = True

ESQUEMAS = {d["name"]: d["input_schema"] for d in DEFINICIONES}


def validar(nombre: str, args: Any) -> str | None:
    """Comprueba los argumentos contra el esquema. Devuelve el error o None si son válidos."""
    esquema = ESQUEMAS.get(nombre)
    if esquema is None:
        return f"Herramienta desconocida: {nombre}"
    if not isinstance(args, dict):
        return "Los argumentos deben ser un objeto"
    props = esquema["properties"]
    for req in esquema["required"]:
        if req not in args:
            return f"Falta el campo '{req}'"
    for clave, valor in args.items():
        if clave not in props:
            return f"Campo no permitido: '{clave}'"
        p = props[clave]
        tipo = p.get("type")
        if tipo == "string" and not isinstance(valor, str):
            return f"'{clave}' debe ser texto"
        if tipo == "boolean" and not isinstance(valor, bool):
            return f"'{clave}' debe ser verdadero o falso"
        if tipo == "integer" and (not isinstance(valor, int) or isinstance(valor, bool)):
            return f"'{clave}' debe ser un número entero"
        if tipo == "array" and not (isinstance(valor, list) and all(isinstance(v, str) for v in valor)):
            return f"'{clave}' debe ser una lista de textos"
        if "enum" in p and valor not in p["enum"]:
            return f"'{clave}' debe ser uno de {p['enum']}"
        if tipo == "integer" and not (p.get("minimum", valor) <= valor <= p.get("maximum", valor)):
            return f"'{clave}' fuera de rango"
    return None


class Herramientas:
    def __init__(
        self,
        api: ApiNimea,
        contexto: Contexto,
        sesion: Sesion,
        cuerpo: Cuerpo,
        memoria: "MemoriaLocal",
    ) -> None:
        self.api = api
        self.contexto = contexto
        self.sesion = sesion
        self.cuerpo = cuerpo
        self.memoria = memoria
        self.terminada = False
        # Avisa a la agenda de que una toma ya está resuelta (para no repetir el recordatorio).
        self.al_resolver_toma: Callable[[str, str], None] | None = None
        self._acciones: dict[str, Callable[[dict[str, Any]], Any]] = {
            d["name"]: getattr(self, "_" + d["name"]) for d in DEFINICIONES
        }

    def ejecutar(self, nombre: str, args: Any) -> tuple[Any, bool]:
        """Ejecuta una herramienta. Devuelve (contenido para la IA, es_error)."""
        error = validar(nombre, args)
        if error:
            return json.dumps({"INVALID_INPUT": error}, ensure_ascii=False), True
        try:
            return self._acciones[nombre](args), False
        except Exception as e:  # una herramienta rota no debe tumbar la conversación
            log.exception("Fallo en la herramienta %s", nombre)
            return f"No se ha podido completar: {e}", True

    # Mensajes de la familia

    def _reproducir_mensaje(self, a: dict[str, Any]) -> str:
        m = self.contexto.mensaje(a["mensaje_id"])
        if not m:
            return "Ese mensaje no existe o ya se entregó."
        autor = m.get("autor_nombre", "tu familia")
        if m.get("tipo") == "audio" and m.get("audio_url"):
            self.cuerpo.reproducir(decodificar(self.api.descargar(m["audio_url"])))
        else:
            self.cuerpo.decir(m.get("texto", ""))
        self.api.mensaje_entregado(m["id"], "escuchado")
        m["escuchado"] = True
        return f"Mensaje de {autor} reproducido. Contenido: {m.get('texto') or '(audio)'}"

    def _grabar_respuesta(self, a: dict[str, Any]) -> str:
        m = self.contexto.mensaje(a["mensaje_id"])
        if not m:
            return "Ese mensaje no existe."
        pcm, texto = self.cuerpo.grabar(segundos_max=60)
        if pcm is None or not texto:
            return "No se ha oído nada. Pregúntale si quiere intentarlo otra vez."
        self.api.respuesta(m["id"], m.get("autor_id"), texto, a_wav(pcm))
        self.contexto.mensajes_pendientes.remove(m)
        return f"Respuesta enviada a {m.get('autor_nombre', 'su familiar')}. Ha dicho: {texto}"

    def _enviar_audio_a_familiar(self, a: dict[str, Any]) -> str:
        familiar = next((f for f in self.contexto.familiares if f.get("id") == a["familiar_id"]), None)
        if not familiar:
            return "No encuentro a ese familiar. Usa uno de los id de la lista de familia."
        pcm, texto = self.cuerpo.grabar(segundos_max=60)
        if pcm is None or not texto:
            return "No se ha oído nada."
        self.api.respuesta(None, familiar["id"], texto, a_wav(pcm))
        return f"Audio enviado a {familiar.get('nombre')}. Ha dicho: {texto}"

    # Rutina y bienestar

    def _confirmar_pastilla(self, a: dict[str, Any]) -> str:
        med = next((m for m in self.contexto.medicacion if m.get("id") == a["medicacion_id"]), None)
        if not med:
            return "No encuentro esa medicación."
        self.api.toma(med["id"], a["hora_prevista"], a["estado"])
        if a["estado"] != "pospuesta" and self.al_resolver_toma:
            self.al_resolver_toma(med["id"], a["hora_prevista"])
        valor = {"confirmada": 5, "pospuesta": 3, "no_confirmada": 2}[a["estado"]]
        self.sesion.anotar("rutina", valor, f"{med.get('nombre')} de las {a['hora_prevista']}: {a['estado']}")
        return f"Anotado: {med.get('nombre')} {a['estado']}."

    def _registrar_reto(self, a: dict[str, Any]) -> str:
        self.sesion.reto(a["tipo"], a["enunciado"], a["resultado"])
        return "Anotado."

    def _anotar_bienestar(self, a: dict[str, Any]) -> str:
        self.sesion.anotar(a["dimension"], a["valor"], a["nota"])
        return "Anotado."

    def _guardar_recuerdo(self, a: dict[str, Any]) -> str:
        self.memoria.guardar(a["titulo"], a["descripcion"], a["privado"])
        return "Guardado."

    def _avisar_familia(self, a: dict[str, Any]) -> str:
        self.api.aviso("peticion_persona_mayor", a["texto"], a["nivel"])
        return "Aviso enviado a la familia."

    # Cuerpo

    def _gesto(self, a: dict[str, Any]) -> str:
        self.cuerpo.gesto(a["nombre"])
        return "Hecho."

    def _mirar(self, a: dict[str, Any]) -> Any:
        jpeg = self.cuerpo.foto_jpeg()
        if not jpeg:
            return "La cámara no está disponible ahora."
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(jpeg).decode()}},
            {"type": "text", "text": "Esto es lo que tienes delante ahora mismo."},
        ]

    def _terminar_conversacion(self, a: dict[str, Any]) -> str:
        self.sesion.resumen = a["resumen"]
        self.sesion.frase_destacada = a["frase_destacada"]
        self.sesion.temas = a["temas"]
        self.sesion.personas = a["personas_mencionadas"]
        self.terminada = True
        return "Conversación cerrada. Despídete con una frase muy corta y cariñosa."


class MemoriaLocal:
    """Recuerdos que Nimea aprende hablando y resúmenes de charlas anteriores.

    Se guardan en el robot para que recuerde lo que le contaron ayer.
    """

    def __init__(self, carpeta: Path) -> None:
        carpeta.mkdir(parents=True, exist_ok=True)
        self.ruta_recuerdos = carpeta / "recuerdos_nimea.jsonl"
        self.ruta_resumenes = carpeta / "resumenes.jsonl"

    def guardar(self, titulo: str, descripcion: str, privado: bool) -> None:
        self._anadir(self.ruta_recuerdos, {"titulo": titulo, "descripcion": descripcion,
                                           "privado": privado, "fecha": time.strftime("%Y-%m-%d")})

    def guardar_resumen(self, resumen: str) -> None:
        if resumen:
            self._anadir(self.ruta_resumenes, {"fecha": time.strftime("%Y-%m-%d %H:%M"), "resumen": resumen})

    def recuerdos(self, n: int = 60) -> list[dict[str, Any]]:
        return self._leer(self.ruta_recuerdos)[-n:]

    def resumenes(self, n: int = 6) -> list[dict[str, Any]]:
        return self._leer(self.ruta_resumenes)[-n:]

    @staticmethod
    def _anadir(ruta: Path, item: dict[str, Any]) -> None:
        with ruta.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    @staticmethod
    def _leer(ruta: Path) -> list[dict[str, Any]]:
        if not ruta.is_file():
            return []
        return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines() if x.strip()]
