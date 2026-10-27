"""Configuración de Nimea, leída de variables de entorno (o de un fichero .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _cargar_env(ruta: Path) -> None:
    """Carga un .env sencillo (CLAVE=valor) sin pisar variables ya definidas."""
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


def _bool(valor: str | None, defecto: bool) -> bool:
    if valor is None or valor == "":
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


@dataclass
class Config:
    # App de la familia (Base44)
    api_url: str = ""
    api_token: str = ""

    # IA. "openai": conversación voz a voz con la API Realtime de OpenAI (por defecto).
    # "claude": Claude como cerebro, con voz y transcripción aparte.
    motor: str = "openai"
    openai_modelo_realtime: str = "gpt-realtime-2.1-mini"
    # Si se puede interrumpir a Nimea mientras habla. Solo con un micro que cancele bien el eco.
    interrumpir: bool = False
    modelo: str = "claude-opus-5-5"
    # Esfuerzo de razonamiento en la charla. "low" para que conteste rápido,
    # que en una conversación por voz cada segundo de silencio se nota.
    esfuerzo: str = "low"
    fallbacks: bool = True

    # Voz
    stt: str = "openai"  # openai | elevenlabs | whisper
    tts: str = "openai"  # openai | elevenlabs | piper
    elevenlabs_api_key: str = ""
    elevenlabs_voz: str = ""
    elevenlabs_modelo_tts: str = "eleven_multilingual_v2"
    openai_api_key: str = ""
    openai_voz: str = "marin"
    openai_modelo_tts: str = "gpt-4o-mini-tts"
    whisper_modelo: str = "small"
    piper_modelo: str = ""

    # Palabra de activación
    palabra: str = "nimea"
    modelo_palabra: str = ""  # ruta a un modelo openWakeWord entrenado para "Nimea"
    umbral_palabra: float = 0.5

    # Comportamiento
    segundos_silencio_para_dormir: float = 25.0
    horario_descanso: tuple[str, str] = ("22:30", "08:30")
    volumen: float = 0.9

    # Datos locales (cola sin conexión, contexto en caché)
    carpeta_datos: Path = field(default_factory=lambda: Path.home() / ".nimea")

    @classmethod
    def desde_entorno(cls, env_file: str | Path | None = ".env") -> "Config":
        if env_file:
            _cargar_env(Path(env_file))
        e = os.environ.get
        descanso = e("NIMEA_HORARIO_DESCANSO", "22:30-08:30").split("-")
        return cls(
            api_url=e("NIMEA_API_URL", "").rstrip("/"),
            api_token=e("NIMEA_API_TOKEN", ""),
            motor=e("NIMEA_MOTOR", cls.motor),
            openai_modelo_realtime=e("OPENAI_MODELO_REALTIME", cls.openai_modelo_realtime),
            interrumpir=_bool(e("NIMEA_INTERRUMPIR"), False),
            modelo=e("NIMEA_MODELO", cls.modelo),
            esfuerzo=e("NIMEA_ESFUERZO", cls.esfuerzo),
            fallbacks=_bool(e("NIMEA_FALLBACKS"), True),
            stt=e("NIMEA_STT", cls.stt),
            tts=e("NIMEA_TTS", cls.tts),
            elevenlabs_api_key=e("ELEVENLABS_API_KEY", ""),
            elevenlabs_voz=e("ELEVENLABS_VOZ", ""),
            elevenlabs_modelo_tts=e("ELEVENLABS_MODELO_TTS", cls.elevenlabs_modelo_tts),
            openai_api_key=e("OPENAI_API_KEY", ""),
            openai_voz=e("OPENAI_VOZ", cls.openai_voz),
            openai_modelo_tts=e("OPENAI_MODELO_TTS", cls.openai_modelo_tts),
            whisper_modelo=e("NIMEA_WHISPER_MODELO", cls.whisper_modelo),
            piper_modelo=e("NIMEA_PIPER_MODELO", ""),
            palabra=e("NIMEA_PALABRA", cls.palabra).lower(),
            modelo_palabra=e("NIMEA_MODELO_PALABRA", ""),
            umbral_palabra=float(e("NIMEA_UMBRAL_PALABRA", "0.5")),
            segundos_silencio_para_dormir=float(e("NIMEA_SILENCIO_DORMIR", "25")),
            horario_descanso=(descanso[0].strip(), descanso[-1].strip()),
            volumen=float(e("NIMEA_VOLUMEN", "0.9")),
            carpeta_datos=Path(e("NIMEA_DATOS", str(Path.home() / ".nimea"))).expanduser(),
        )
