"""Palabra de activación: "Nimea".

Dos modos:
- Modelo openWakeWord entrenado para "Nimea" (recomendado: local, ligero, siempre escuchando).
- Mientras no tengamos ese modelo, detectamos la palabra en la transcripción de frases
  cortas con Whisper en local. Nada de lo que se oye antes de "Nimea" sale de casa.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

import numpy as np

# Palabras del español que suenan parecido y no deben despertarla.
FALSOS_AMIGOS = {"animate", "animame", "animal", "animo", "minima", "anemia"}


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-zñ ]+", " ", texto).strip()


@dataclass
class Deteccion:
    activada: bool
    resto: str = ""  # lo que dijo después de "Nimea", para no hacerle repetir


def buscar_palabra(texto: str, palabra: str = "nimea", umbral: float = 0.8) -> Deteccion:
    """Busca la palabra en un texto transcrito, tolerando errores típicos de transcripción.

    "Nimea, ¿qué hora es?" activa y devuelve "¿qué hora es?".
    "Ni mea", "Nimeá" o "Nimia" también activan; "anímate" no.
    """
    original = texto.split()
    tokens = [normalizar(t) for t in original]
    objetivo = normalizar(palabra)
    for i in range(len(tokens)):
        candidatos = [(tokens[i], 1)]
        if i + 1 < len(tokens):
            candidatos.append((tokens[i] + tokens[i + 1], 2))
        for candidato, n in candidatos:
            candidato = candidato.replace(" ", "")
            if not candidato or candidato in FALSOS_AMIGOS:
                continue
            parecido = difflib.SequenceMatcher(None, candidato, objetivo).ratio()
            if parecido >= umbral and abs(len(candidato) - len(objetivo)) <= 2:
                resto = " ".join(original[i + n:]).strip(" ,.;:!¡")
                return Deteccion(True, resto)
    return Deteccion(False)


class DetectorModelo:
    """openWakeWord con un modelo propio (.onnx o .tflite) para "Nimea"."""

    TROZO = 1280  # 80 ms a 16 kHz, lo que espera openWakeWord

    def __init__(self, ruta_modelo: str, umbral: float = 0.5) -> None:
        from openwakeword.model import Model

        framework = "tflite" if ruta_modelo.endswith(".tflite") else "onnx"
        self.modelo = Model(wakeword_models=[ruta_modelo], inference_framework=framework)
        self.umbral = umbral
        self._pendiente = np.zeros(0, dtype=np.int16)

    def alimentar(self, audio: np.ndarray) -> bool:
        enteros = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        self._pendiente = np.concatenate([self._pendiente, enteros])
        activada = False
        while len(self._pendiente) >= self.TROZO:
            trozo, self._pendiente = self._pendiente[:self.TROZO], self._pendiente[self.TROZO:]
            puntuaciones = self.modelo.predict(trozo)
            if max(puntuaciones.values(), default=0.0) >= self.umbral:
                activada = True
        if activada:
            self.modelo.reset()
            self._pendiente = np.zeros(0, dtype=np.int16)
        return activada
