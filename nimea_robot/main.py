"""App de Nimea para el Reachy Mini.

Se instala como app del Reachy Mini (ver README) o se lanza a mano con:
    python -m nimea_robot.main
"""

from __future__ import annotations

import logging
import threading

from reachy_mini import ReachyMini, ReachyMiniApp

from . import stt, tts
from .api import ApiNimea
from .audio import AudioReachy
from .brain import Cerebro
from .companion import Nimea
from .config import Config
from .gestures import Gestos


class NimeaApp(ReachyMiniApp):
    custom_app_url: str | None = None
    request_media_backend: str | None = None  # usamos cámara (mirar y seguir la cara) y audio

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
        cfg = Config.desde_entorno()
        audio = AudioReachy(reachy_mini, volumen=cfg.volumen)
        # Transcripción: para grabar las respuestas a la familia (y la charla con Claude).
        transcriptor = stt.crear(cfg)
        # Para oír "Nimea" sin modelo propio usamos Whisper en local, nunca la nube.
        stt_palabra = None
        if not cfg.modelo_palabra:
            stt_palabra = transcriptor if cfg.stt == "whisper" else stt.TranscriptorWhisper("base")
        claude = cfg.motor == "claude"
        nimea = Nimea(
            cfg,
            audio=audio,
            stt=transcriptor,
            voz=tts.crear(cfg) if claude else None,
            api=ApiNimea(cfg.api_url, cfg.api_token, cfg.carpeta_datos),
            cerebro=Cerebro(cfg) if claude else None,
            gestos=Gestos(reachy_mini),
            foto=reachy_mini.media.get_frame_jpeg,
            stt_palabra=stt_palabra,
        )
        try:
            nimea.ejecutar(stop_event)
        finally:
            audio.cerrar()


if __name__ == "__main__":
    app = NimeaApp()
    try:
        app.wrapped_run()
    except KeyboardInterrupt:
        app.stop()
