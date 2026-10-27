"""Conversación voz a voz con la API Realtime de OpenAI.

El audio del micrófono va directo al modelo y su voz vuelve en streaming: sin pasar
por texto, contesta en menos de un segundo y suena natural. Las herramientas son las
mismas que con Claude (tools.py).
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Any

import numpy as np

from .audio import FS, Audio, de_pcm16, remuestrear
from .tools import DEFINICIONES, Herramientas

log = logging.getLogger("nimea.realtime")

FS_OPENAI = 24_000

CIERRE_POR_SILENCIO = (
    "Ella lleva un rato sin contestar. Despídete con una sola frase muy corta y cariñosa, "
    "por ejemplo que te quedas por aquí y que te llame si te necesita, y usa terminar_conversacion "
    "con el resumen para la familia."
)


def herramientas_openai() -> list[dict[str, Any]]:
    return [{"type": "function", "name": d["name"], "description": d["description"],
             "parameters": d["input_schema"]} for d in DEFINICIONES]


def a_base64_24k(pcm16k: np.ndarray) -> str:
    pcm = remuestrear(pcm16k, FS, FS_OPENAI)
    return base64.b64encode((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()).decode()


def de_base64_24k(datos: str) -> np.ndarray:
    return remuestrear(de_pcm16(base64.b64decode(datos)), FS_OPENAI, FS)


class Reproductor:
    """Manda la voz al altavoz según llega y sabe cuándo termina de sonar."""

    def __init__(self, audio: Audio) -> None:
        self.audio = audio
        self._fin = 0.0
        self._lock = threading.Lock()

    def encolar(self, pcm: np.ndarray) -> None:
        duracion = self.audio.empujar(pcm)
        with self._lock:
            self._fin = max(self._fin, time.monotonic()) + duracion

    @property
    def ocupado(self) -> bool:
        return time.monotonic() < self._fin

    def esperar(self) -> None:
        while self.ocupado:
            time.sleep(0.05)
        time.sleep(0.15)  # que se apague el eco

    def cortar(self) -> None:
        self.audio.cortar()
        with self._lock:
            self._fin = 0.0


class ConversacionVoz:
    def __init__(self, cfg, audio: Audio, herramientas: Herramientas, cliente: Any | None = None) -> None:
        self.cfg = cfg
        self.audio = audio
        self.herramientas = herramientas
        self.cliente = cliente
        self.reproductor = Reproductor(audio)
        self.ha_hablado = False
        self.segundos_habla = 0.0
        self._conn: Any = None
        self._fin = threading.Event()
        self._micro_pausado = threading.Event()
        self._respuesta_activa = False
        self._falta_responder = False
        self._cerrando = False
        self._actividad = time.monotonic()
        self._errores = 0

    # Arranque

    def ejecutar(self, instrucciones: str, entrada: str, parar: threading.Event,
                 espera_silencio: float, espera_primera: float, ya_ha_hablado: bool = False) -> None:
        """Mantiene la conversación hasta que termina o se queda en silencio."""
        self.ha_hablado = ya_ha_hablado
        cliente = self.cliente
        if cliente is None:
            from openai import OpenAI

            cliente = OpenAI(api_key=self.cfg.openai_api_key or None)
        with cliente.realtime.connect(model=self.cfg.openai_modelo_realtime) as conn:
            self._conn = conn
            conn.session.update(session=self._config_sesion(instrucciones))
            conn.conversation.item.create(item={
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": entrada}],
            })
            self._pedir_respuesta()
            hilos = [
                threading.Thread(target=self._micro, daemon=True, name="micro"),
                threading.Thread(target=self._vigilar, args=(parar, espera_silencio, espera_primera),
                                 daemon=True, name="vigia"),
            ]
            for h in hilos:
                h.start()
            try:
                for evento in conn:
                    if self._procesar(evento):
                        break
            except Exception as e:  # conexión cerrada por nosotros o caída de red
                if not self._fin.is_set():
                    log.warning("Conversación cortada: %s", e)
            finally:
                self._fin.set()
                self.reproductor.esperar()

    def _config_sesion(self, instrucciones: str) -> dict[str, Any]:
        return {
            "type": "realtime",
            "instructions": instrucciones,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": FS_OPENAI},
                    "noise_reduction": {"type": "far_field"},
                    "transcription": {"model": "gpt-4o-mini-transcribe", "language": "es"},
                    # Semántico y sin prisa: las personas mayores hacen pausas al hablar.
                    "turn_detection": {"type": "semantic_vad", "eagerness": "low",
                                       "create_response": True,
                                       "interrupt_response": self.cfg.interrumpir},
                },
                "output": {"format": {"type": "audio/pcm", "rate": FS_OPENAI},
                           "voice": self.cfg.openai_voz, "speed": 0.95},
            },
            "tools": herramientas_openai(),
            "tool_choice": "auto",
        }

    # Eventos del servidor

    def _procesar(self, evento: Any) -> bool:
        """Atiende un evento. Devuelve True cuando la conversación ha terminado."""
        tipo = evento.type
        if tipo == "response.output_audio.delta":
            self.reproductor.encolar(de_base64_24k(evento.delta))
        elif tipo == "response.created":
            self._respuesta_activa = True
        elif tipo == "input_audio_buffer.speech_started":
            self._actividad = time.monotonic()
            if self.cfg.interrumpir and self.reproductor.ocupado:
                self.reproductor.cortar()
        elif tipo == "conversation.item.input_audio_transcription.completed":
            texto = (evento.transcript or "").strip()
            if texto:
                log.info("Ella: %s", texto)
                self.ha_hablado = True
                self.segundos_habla += 0.4 * len(texto.split())
                self._actividad = time.monotonic()
        elif tipo == "response.output_audio_transcript.done":
            log.info("Nimea: %s", evento.transcript)
        elif tipo == "response.function_call_arguments.done":
            self._herramienta(evento.name, evento.call_id, evento.arguments)
        elif tipo == "response.done":
            self._respuesta_activa = False
            if self.herramientas.terminada:
                if self._falta_responder and not self._cerrando:
                    # Que se despida después de cerrar.
                    self._falta_responder = False
                    self._pedir_respuesta()
                    return False
                return True
            if self._falta_responder:
                self._falta_responder = False
                self._pedir_respuesta()
            self._actividad = time.monotonic()
        elif tipo == "error":
            self._errores += 1
            log.error("Error de OpenAI: %s", getattr(evento.error, "message", evento.error))
            if self._errores > 3:
                return True
        return False

    def _herramienta(self, nombre: str, call_id: str, argumentos: str) -> None:
        # Mientras la herramienta trabaja (grabar, poner un audio) el micro no va al modelo.
        self._micro_pausado.set()
        try:
            self.reproductor.esperar()
            try:
                args = json.loads(argumentos or "{}")
            except ValueError:
                contenido, error = json.dumps({"INVALID_JSON": argumentos}), True
            else:
                contenido, error = self.herramientas.ejecutar(nombre, args)
            imagen = None
            if isinstance(contenido, list):
                imagen = next((c["source"]["data"] for c in contenido if c.get("type") == "image"), None)
                contenido = "Te paso la imagen de lo que tienes delante."
            self._conn.conversation.item.create(item={
                "type": "function_call_output", "call_id": call_id,
                "output": ("ERROR: " if error else "") + str(contenido),
            })
            if imagen:
                self._conn.conversation.item.create(item={
                    "type": "message", "role": "user",
                    "content": [{"type": "input_image", "image_url": f"data:image/jpeg;base64,{imagen}"}],
                })
            self._falta_responder = True
            log.info("Herramienta %s -> %s", nombre, contenido)
        finally:
            self.audio.descartar_entrada()
            self._micro_pausado.clear()
            self._actividad = time.monotonic()

    def _pedir_respuesta(self, **respuesta: Any) -> None:
        self._respuesta_activa = True
        if respuesta:
            self._conn.response.create(response=respuesta)
        else:
            self._conn.response.create()

    # Hilos

    def _micro(self) -> None:
        bloque: list[np.ndarray] = []
        while not self._fin.is_set():
            pcm = self.audio.leer()
            if pcm is None:
                time.sleep(0.01)
                continue
            # Sin cancelación de eco fiable, mientras Nimea habla no le mandamos su propia voz.
            if self._micro_pausado.is_set() or (self.reproductor.ocupado and not self.cfg.interrumpir):
                bloque = []
                continue
            bloque.append(pcm)
            if sum(len(b) for b in bloque) >= FS // 10:
                try:
                    self._conn.input_audio_buffer.append(audio=a_base64_24k(np.concatenate(bloque)))
                except Exception:
                    if not self._fin.is_set():
                        log.exception("No se pudo enviar audio")
                bloque = []

    def _vigilar(self, parar: threading.Event, espera_silencio: float, espera_primera: float) -> None:
        while not self._fin.wait(0.5):
            if parar.is_set():
                self._cerrar_conexion()
                return
            if self._cerrando or self._respuesta_activa or self.reproductor.ocupado \
                    or self._micro_pausado.is_set():
                continue
            espera = espera_silencio if self.ha_hablado else espera_primera
            if time.monotonic() - self._actividad < espera:
                continue
            self._cerrando = True
            if self.ha_hablado:
                self._pedir_respuesta(instructions=CIERRE_POR_SILENCIO)
            else:
                self._cerrar_conexion()  # no ha contestado: lo intentará más tarde
                return

    def _cerrar_conexion(self) -> None:
        self._fin.set()
        try:
            self._conn.close()
        except Exception:
            pass
