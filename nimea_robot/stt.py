"""Voz a texto."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx
import numpy as np

from .audio import a_wav

log = logging.getLogger("nimea.stt")


class Transcriptor(Protocol):
    def transcribir(self, audio: np.ndarray) -> str: ...


class TranscriptorElevenLabs:
    """Scribe de ElevenLabs: muy bueno con voces mayores y acentos del español."""

    URL = "https://api.elevenlabs.io/v1/speech-to-text"

    def __init__(self, api_key: str, modelo: str = "scribe_v1", http: httpx.Client | None = None) -> None:
        if not api_key:
            raise ValueError("Falta ELEVENLABS_API_KEY")
        self.api_key = api_key
        self.modelo = modelo
        self.http = http or httpx.Client(timeout=30.0)

    def transcribir(self, audio: np.ndarray) -> str:
        r = self.http.post(
            self.URL,
            headers={"xi-api-key": self.api_key},
            data={"model_id": self.modelo, "language_code": "spa", "tag_audio_events": "false"},
            files={"file": ("frase.wav", a_wav(audio), "audio/wav")},
        )
        r.raise_for_status()
        return (r.json().get("text") or "").strip()


class TranscriptorWhisper:
    """Whisper en local (faster-whisper). Sin nube: lo que se oye no sale de casa."""

    def __init__(self, modelo: str = "small") -> None:
        from faster_whisper import WhisperModel

        self.modelo = WhisperModel(modelo, device="cpu", compute_type="int8")

    def transcribir(self, audio: np.ndarray) -> str:
        segmentos, _ = self.modelo.transcribe(audio, language="es", vad_filter=True, beam_size=1)
        return " ".join(s.text.strip() for s in segmentos).strip()


def crear(cfg) -> Transcriptor:
    if cfg.stt == "whisper":
        return TranscriptorWhisper(cfg.whisper_modelo)
    return TranscriptorElevenLabs(cfg.elevenlabs_api_key)
