"""Nimea en marcha: escucha, se despierta, conversa, toma la iniciativa y vuelve a reposo."""

from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import Callable

import numpy as np

from . import prompts
from .agenda import Agenda, Motivo, en_descanso
from .api import ApiNimea, Contexto
from .audio import Audio, pitido
from .bienestar import Sesion
from .brain import Cerebro
from .realtime import ConversacionVoz
from .stt import Transcriptor
from .tools import Herramientas, MemoriaLocal
from .tts import Sintetizador
from .vad import DetectorVoz, escuchar_frase
from .wakeword import DetectorModelo, buscar_palabra

log = logging.getLogger("nimea")

LATIDO = 300  # segundos
REFRESCO_CONTEXTO = 600
REVISAR_AGENDA = 30


class Hablante:
    """Convierte frases en voz y las reproduce en orden.

    Mientras suena una frase ya se está sintetizando la siguiente, para que no haya
    silencios entre frases.
    """

    def __init__(self, voz: Sintetizador, audio: Audio) -> None:
        self.voz = voz
        self.audio = audio
        self._sintesis = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts")
        self._cola: queue.Queue[Future | None] = queue.Queue()
        self._ocupado = threading.Event()
        threading.Thread(target=self._reproducir, daemon=True, name="voz").start()

    def decir(self, frase: str) -> None:
        log.info("Nimea: %s", frase)
        self._ocupado.set()
        self._cola.put(self._sintesis.submit(self.voz.sintetizar, frase))

    def esperar(self) -> None:
        self._cola.join()
        self._ocupado.clear()

    def _reproducir(self) -> None:
        while True:
            futuro = self._cola.get()
            try:
                if futuro is not None:
                    self.audio.reproducir(futuro.result())
            except Exception:
                log.exception("No se pudo decir una frase")
            finally:
                self._cola.task_done()


class CuerpoNimea:
    """Lo que las herramientas de la IA pueden hacer con el robot."""

    def __init__(self, hablante: Hablante, audio: Audio, stt: Transcriptor,
                 gesto: Callable[[str], None], foto: Callable[[], bytes | None]) -> None:
        self.hablante = hablante
        self.audio = audio
        self.stt = stt
        self._gesto = gesto
        self._foto = foto

    def decir(self, texto: str) -> None:
        self.hablante.decir(texto)
        self.hablante.esperar()

    def reproducir(self, pcm: np.ndarray) -> None:
        self.hablante.esperar()
        self.audio.reproducir(pcm)

    def grabar(self, segundos_max: float) -> tuple[np.ndarray | None, str]:
        self.hablante.esperar()
        self.audio.reproducir(pitido())
        self.audio.descartar_entrada()
        detector = DetectorVoz(silencio_fin_ms=1600, max_segundos=segundos_max)
        pcm = escuchar_frase(self.audio.leer, detector, espera_max=10)
        self.audio.reproducir(pitido(660))
        if pcm is None:
            return None, ""
        return pcm, self.stt.transcribir(pcm)

    def gesto(self, nombre: str) -> None:
        self._gesto(nombre)

    def foto_jpeg(self) -> bytes | None:
        return self._foto()


class Nimea:
    def __init__(
        self,
        cfg,
        audio: Audio,
        stt: Transcriptor,
        voz: Sintetizador | None,
        api: ApiNimea,
        cerebro: Cerebro | None,
        gestos,
        foto: Callable[[], bytes | None] = lambda: None,
        stt_palabra: Transcriptor | None = None,
        cliente_openai=None,
    ) -> None:
        self.cfg = cfg
        self.audio = audio
        self.stt = stt
        self.api = api
        self.cerebro = cerebro
        self.cliente_openai = cliente_openai
        self.gestos = gestos
        self.hablante = Hablante(voz, audio)
        self.cuerpo = CuerpoNimea(self.hablante, audio, stt, gestos.hacer, foto)
        self.memoria = MemoriaLocal(cfg.carpeta_datos)
        self.agenda = Agenda(descanso=cfg.horario_descanso)
        self.contexto = Contexto()
        self.estado = "en_linea"

        # Palabra de activación: modelo propio si lo hay; si no, Whisper local sobre frases cortas.
        self.detector_modelo = DetectorModelo(cfg.modelo_palabra, cfg.umbral_palabra) if cfg.modelo_palabra else None
        self.stt_palabra = stt_palabra
        if not self.detector_modelo and not self.stt_palabra:
            raise RuntimeError("Hace falta NIMEA_MODELO_PALABRA o faster-whisper para oír 'Nimea'")
        self.vad_reposo = DetectorVoz(max_segundos=6)

    # Bucle principal

    def ejecutar(self, parar: threading.Event) -> None:
        self.contexto = self.api.contexto()
        self.gestos.dormir()
        t_latido = t_contexto = t_agenda = 0.0
        while not parar.is_set():
            ahora = time.monotonic()
            if ahora - t_latido > LATIDO:
                t_latido = ahora
                self.api.latido(self.estado)
            if ahora - t_contexto > REFRESCO_CONTEXTO:
                t_contexto = ahora
                self.contexto = self.api.contexto()
            if ahora - t_agenda > REVISAR_AGENDA:
                t_agenda = ahora
                motivo = self.agenda.siguiente(self.contexto, datetime.now())
                if motivo:
                    self.contexto = self.api.contexto()
                    self.conversar(motivo, parar)
                    continue

            activada, resto = self._escuchar_palabra()
            if activada:
                motivo = Motivo("llamada", "Te ha llamado por tu nombre.")
                self.conversar(motivo, parar, primera_frase=resto)

    def _escuchar_palabra(self) -> tuple[bool, str]:
        audio = self.audio.leer()
        if audio is None:
            time.sleep(0.01)
            return False, ""
        if self.detector_modelo:
            return self.detector_modelo.alimentar(audio), ""
        for frase in self.vad_reposo.alimentar(audio):
            texto = self.stt_palabra.transcribir(frase)
            d = buscar_palabra(texto, self.cfg.palabra)
            if d.activada:
                log.info("Me han llamado: %r", texto)
                return True, d.resto
        return False, ""

    # Conversación

    def conversar(self, motivo: Motivo, parar: threading.Event, primera_frase: str = "") -> None:
        self.estado = "conversando"
        self.gestos.despertar()
        sesion = Sesion()
        herramientas = Herramientas(self.api, self.contexto, sesion, self.cuerpo, self.memoria)
        hoy = datetime.now().strftime("%Y-%m-%d")
        herramientas.al_resolver_toma = lambda med, h: self.agenda.resolver_toma(med, h, hoy)
        if self.cerebro:
            self.cerebro.nueva_conversacion(prompts.sistema(self.contexto, self.memoria))

        tomas = self.agenda.tomas_pendientes(self.contexto, datetime.now())
        entrada = prompts.situacion(self.contexto, motivo.texto, tomas_pendientes=tomas) + "\n"
        if primera_frase:
            entrada += f"Ella acaba de decir: {primera_frase}"
        elif motivo.tipo == "llamada":
            entrada += "Ella te acaba de llamar. Salúdala y pregúntale qué tal."
        else:
            entrada += "Empiezas tú la conversación: llámala por su nombre con suavidad."

        ha_hablado = False
        try:
            if self.cfg.motor == "openai":
                ha_hablado = self._conversar_openai(entrada, herramientas, sesion, motivo, parar,
                                                    bool(primera_frase))
            else:
                ha_hablado = self._conversar_claude(entrada, herramientas, sesion, motivo, parar,
                                                    bool(primera_frase))
        finally:
            self._cerrar(sesion, herramientas, ha_hablado)

    def _conversar_openai(self, entrada: str, herramientas: Herramientas, sesion: Sesion,
                          motivo: Motivo, parar: threading.Event, ha_hablado: bool) -> bool:
        voz = ConversacionVoz(self.cfg, self.audio, herramientas, self.cliente_openai)
        voz.ejecutar(
            prompts.sistema(self.contexto, self.memoria), entrada, parar,
            espera_silencio=self.cfg.segundos_silencio_para_dormir,
            espera_primera=self.cfg.segundos_silencio_para_dormir if motivo.tipo == "llamada" else 20.0,
            ya_ha_hablado=ha_hablado,
        )
        sesion.segundos_habla += voz.segundos_habla
        return voz.ha_hablado

    def _conversar_claude(self, entrada: str, herramientas: Herramientas, sesion: Sesion,
                          motivo: Motivo, parar: threading.Event, ha_hablado: bool) -> bool:
        while not parar.is_set():
            self.cerebro.turno(entrada, herramientas, self.hablante.decir)
            self.hablante.esperar()
            if herramientas.terminada:
                break
            self.audio.descartar_entrada()  # fuera el eco de su propia voz
            self.gestos.escuchar()
            espera = 20.0 if not ha_hablado and motivo.tipo != "llamada" else self.cfg.segundos_silencio_para_dormir
            pcm = escuchar_frase(self.audio.leer, DetectorVoz(), espera_max=espera, parar=parar.is_set)
            if pcm is None:
                if ha_hablado:
                    self.hablante.decir("Me quedo por aquí tranquila. Si me necesitas, llámame.")
                    self.hablante.esperar()
                break
            texto = self.stt.transcribir(pcm)
            if not texto:
                entrada = "(No se ha entendido lo que ha dicho; pídele con cariño que lo repita.)"
                continue
            log.info("Ella: %s", texto)
            ha_hablado = True
            sesion.segundos_habla += len(pcm) / 16000
            entrada = texto
        return ha_hablado

    def _cerrar(self, sesion: Sesion, herramientas: Herramientas, ha_hablado: bool) -> None:
        sesion.fin = time.time()
        if ha_hablado and not sesion.resumen and self.cerebro:
            datos = self.cerebro.resumir() or {}
            sesion.resumen = datos.get("resumen", "")
            sesion.frase_destacada = datos.get("frase_destacada", "")
            sesion.temas = datos.get("temas", [])
            sesion.personas = datos.get("personas_mencionadas", [])
        if not sesion.vacia:
            self.api.sesion(sesion.para_api())
            self.memoria.guardar_resumen(sesion.resumen)
        self.gestos.dormir()
        self.estado = "descansando" if en_descanso(datetime.now(), *self.cfg.horario_descanso) else "en_linea"
        self.vad_reposo.reiniciar()
        self.audio.descartar_entrada()
