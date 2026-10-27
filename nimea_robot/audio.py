"""Entrada y salida de audio. Todo el audio interno es mono, float32, 16 kHz."""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import time
import wave
from typing import Protocol

import numpy as np

log = logging.getLogger("nimea.audio")

FS = 16_000


class Audio(Protocol):
    def leer(self) -> np.ndarray | None:
        """Devuelve el siguiente bloque del micrófono, o None si aún no hay datos."""

    def reproducir(self, pcm: np.ndarray) -> None:
        """Reproduce y espera a que termine."""

    def descartar_entrada(self) -> None:
        """Tira lo acumulado en el micrófono (por ejemplo, el eco de lo que ha dicho Nimea)."""


class AudioReachy:
    """Micrófonos y altavoz del Reachy Mini a través de su SDK."""

    def __init__(self, reachy, volumen: float = 0.9) -> None:
        self.media = reachy.media
        self.volumen = volumen
        self.fs_in = self.media.get_input_audio_samplerate()
        self.fs_out = self.media.get_output_audio_samplerate()
        self.media.start_recording()
        self.media.start_playing()

    def leer(self) -> np.ndarray | None:
        bloque = self.media.get_audio_sample()
        if bloque is None or len(bloque) == 0:
            return None
        return remuestrear(a_mono(bloque), self.fs_in, FS)

    def reproducir(self, pcm: np.ndarray) -> None:
        if len(pcm) == 0:
            return
        datos = np.clip(remuestrear(pcm, FS, self.fs_out) * self.volumen, -1.0, 1.0)
        trozo = self.fs_out // 5
        inicio = time.monotonic()
        for i in range(0, len(datos), trozo):
            self.media.push_audio_sample(datos[i:i + trozo].astype(np.float32))
        # push_audio_sample no bloquea: esperamos a que suene entero.
        restante = len(datos) / self.fs_out - (time.monotonic() - inicio)
        if restante > 0:
            time.sleep(restante + 0.1)

    def descartar_entrada(self) -> None:
        while self.media.get_audio_sample() is not None:
            pass

    def cerrar(self) -> None:
        self.media.stop_recording()
        self.media.stop_playing()


def a_mono(bloque: np.ndarray) -> np.ndarray:
    bloque = np.asarray(bloque, dtype=np.float32)
    if bloque.ndim == 2:
        # El SDK entrega (muestras, canales).
        eje = 1 if bloque.shape[1] <= bloque.shape[0] else 0
        bloque = bloque.mean(axis=eje)
    return bloque


def remuestrear(x: np.ndarray, fs_origen: int, fs_destino: int) -> np.ndarray:
    if fs_origen == fs_destino or len(x) == 0:
        return x.astype(np.float32)
    n = int(round(len(x) * fs_destino / fs_origen))
    t_origen = np.arange(len(x)) / fs_origen
    t_destino = np.arange(n) / fs_destino
    return np.interp(t_destino, t_origen, x).astype(np.float32)


def a_wav(pcm: np.ndarray, fs: int = FS) -> bytes:
    enteros = (np.clip(pcm, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(enteros.tobytes())
    return buf.getvalue()


def de_pcm16(datos: bytes) -> np.ndarray:
    return np.frombuffer(datos, dtype="<i2").astype(np.float32) / 32768.0


def decodificar(datos: bytes) -> np.ndarray:
    """Convierte un audio en cualquier formato (m4a, mp3, ogg, wav...) a mono 16 kHz con ffmpeg."""
    if datos[:4] == b"RIFF":
        with wave.open(io.BytesIO(datos)) as w:
            if w.getsampwidth() == 2:
                pcm = de_pcm16(w.readframes(w.getnframes()))
                if w.getnchannels() > 1:
                    pcm = pcm.reshape(-1, w.getnchannels()).mean(axis=1)
                return remuestrear(pcm, w.getframerate(), FS)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Hace falta ffmpeg para reproducir audios que no sean WAV")
    salida = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-ac", "1", "-ar", str(FS), "-f", "s16le", "pipe:1"],
        input=datos, capture_output=True, check=True,
    )
    return de_pcm16(salida.stdout)


def pitido(frecuencia: float = 880.0, duracion: float = 0.18) -> np.ndarray:
    """Un tono suave para indicar "te escucho, puedes hablar"."""
    t = np.arange(int(FS * duracion)) / FS
    envolvente = np.sin(np.pi * t / duracion) ** 2
    return (0.25 * envolvente * np.sin(2 * np.pi * frecuencia * t)).astype(np.float32)
