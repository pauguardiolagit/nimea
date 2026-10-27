"""Texto a voz."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np

from .audio import FS, de_pcm16, remuestrear

log = logging.getLogger("nimea.tts")


class Sintetizador(Protocol):
    def sintetizar(self, texto: str) -> np.ndarray: ...


class VozElevenLabs:
    """Voz cálida y natural en español. Elige la voz en ELEVENLABS_VOZ."""

    def __init__(self, api_key: str, voz: str, modelo: str, http: httpx.Client | None = None) -> None:
        if not api_key or not voz:
            raise ValueError("Faltan ELEVENLABS_API_KEY o ELEVENLABS_VOZ")
        self.api_key = api_key
        self.voz = voz
        self.modelo = modelo
        self.http = http or httpx.Client(timeout=30.0)

    def sintetizar(self, texto: str) -> np.ndarray:
        r = self.http.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voz}",
            params={"output_format": "pcm_16000"},
            headers={"xi-api-key": self.api_key},
            json={
                "text": texto,
                "model_id": self.modelo,
                "language_code": "es",
                # Algo más pausada y estable de lo normal: se le entiende mejor.
                "voice_settings": {"stability": 0.6, "similarity_boost": 0.8, "speed": 0.92},
            },
        )
        r.raise_for_status()
        return de_pcm16(r.content)


class VozPiper:
    """Voz local con Piper, por si no hay conexión o para pruebas."""

    def __init__(self, modelo: str) -> None:
        if not shutil.which("piper"):
            raise RuntimeError("Piper no está instalado")
        self.modelo = modelo
        conf = Path(modelo + ".json")
        self.fs = json.loads(conf.read_text())["audio"]["sample_rate"] if conf.is_file() else 22050

    def sintetizar(self, texto: str) -> np.ndarray:
        salida = subprocess.run(
            ["piper", "--model", self.modelo, "--output-raw"],
            input=texto.encode("utf-8"), capture_output=True, check=True,
        )
        return remuestrear(de_pcm16(salida.stdout), self.fs, FS)


class VozOpenAI:
    """Voz de OpenAI (la misma familia de voces que el modo voz de ChatGPT).

    Solo pone la voz: lo que dice lo sigue decidiendo Claude.
    """

    URL = "https://api.openai.com/v1/audio/speech"
    FS_OPENAI = 24_000  # el formato "pcm" de OpenAI es 16 bits, mono, 24 kHz

    def __init__(self, api_key: str, voz: str, modelo: str, http: httpx.Client | None = None) -> None:
        if not api_key:
            raise ValueError("Falta OPENAI_API_KEY")
        self.api_key = api_key
        self.voz = voz
        self.modelo = modelo
        self.http = http or httpx.Client(timeout=30.0)

    def sintetizar(self, texto: str) -> np.ndarray:
        r = self.http.post(
            self.URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.modelo,
                "voice": self.voz,
                "input": texto,
                "response_format": "pcm",
                "instructions": ("Habla en español de España, con calidez y cercanía, algo más "
                                 "despacio de lo normal y vocalizando bien, como quien charla con "
                                 "una persona mayor a la que aprecia."),
            },
        )
        r.raise_for_status()
        return remuestrear(de_pcm16(r.content), self.FS_OPENAI, FS)


def crear(cfg) -> Sintetizador:
    if cfg.tts == "piper":
        return VozPiper(cfg.piper_modelo)
    if cfg.tts == "openai":
        return VozOpenAI(cfg.openai_api_key, cfg.openai_voz, cfg.openai_modelo_tts)
    return VozElevenLabs(cfg.elevenlabs_api_key, cfg.elevenlabs_voz, cfg.elevenlabs_modelo_tts)
