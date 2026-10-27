"""Detección de voz por energía: corta el audio del micrófono en frases."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

import numpy as np

from .audio import FS

BLOQUE = FS // 50  # 20 ms


class DetectorVoz:
    """Detecta cuándo empieza y termina una frase.

    El umbral se adapta al ruido de fondo de la casa (tele, nevera...), de modo
    que solo dispara cuando alguien habla claramente por encima de ese ruido.
    """

    def __init__(
        self,
        factor: float = 3.0,
        nivel_minimo: float = 0.008,
        inicio_ms: int = 80,
        silencio_fin_ms: int = 900,
        preroll_ms: int = 300,
        max_segundos: float = 30.0,
    ) -> None:
        self.factor = factor
        self.nivel_minimo = nivel_minimo
        self.bloques_inicio = max(1, inicio_ms // 20)
        self.bloques_fin = max(1, silencio_fin_ms // 20)
        self.preroll = deque(maxlen=max(1, preroll_ms // 20))
        self.max_bloques = int(max_segundos * 50)
        self.ruido = nivel_minimo / 2
        self._pendiente = np.zeros(0, dtype=np.float32)
        self.reiniciar()

    def reiniciar(self) -> None:
        self.en_voz = False
        self._seguidos = 0
        self._silencio = 0
        self._frase: list[np.ndarray] = []
        self.preroll.clear()

    def umbral(self) -> float:
        return max(self.ruido * self.factor, self.nivel_minimo)

    def alimentar(self, audio: np.ndarray) -> list[np.ndarray]:
        """Procesa audio y devuelve las frases completas que se hayan cerrado."""
        self._pendiente = np.concatenate([self._pendiente, audio.astype(np.float32)])
        frases = []
        while len(self._pendiente) >= BLOQUE:
            bloque, self._pendiente = self._pendiente[:BLOQUE], self._pendiente[BLOQUE:]
            frase = self._bloque(bloque)
            if frase is not None:
                frases.append(frase)
        return frases

    def _bloque(self, bloque: np.ndarray) -> np.ndarray | None:
        rms = float(np.sqrt(np.mean(bloque ** 2)))
        habla = rms > self.umbral()
        if not self.en_voz:
            self.preroll.append(bloque)
            if habla:
                self._seguidos += 1
                if self._seguidos >= self.bloques_inicio:
                    self.en_voz = True
                    self._frase = list(self.preroll)
                    self._silencio = 0
            else:
                self._seguidos = 0
                # Solo aprendemos el ruido de fondo cuando nadie habla.
                self.ruido = 0.95 * self.ruido + 0.05 * rms
            return None
        self._frase.append(bloque)
        self._silencio = 0 if habla else self._silencio + 1
        if self._silencio >= self.bloques_fin or len(self._frase) >= self.max_bloques:
            frase = np.concatenate(self._frase)
            self.reiniciar()
            return frase
        return None


def escuchar_frase(
    leer: Callable[[], np.ndarray | None],
    detector: DetectorVoz,
    espera_max: float,
    parar: Callable[[], bool] = lambda: False,
) -> np.ndarray | None:
    """Espera una frase completa. Devuelve None si nadie empieza a hablar a tiempo."""
    detector.reiniciar()
    limite = time.monotonic() + espera_max
    while not parar():
        audio = leer()
        if audio is None:
            time.sleep(0.01)
        else:
            frases = detector.alimentar(audio)
            if frases:
                return frases[0]
        if not detector.en_voz and time.monotonic() > limite:
            return None
    return None
