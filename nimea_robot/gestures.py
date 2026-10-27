"""Lenguaje corporal de Nimea: cabeza, antenas y cuerpo."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger("nimea.gestos")

# Antenas: [derecha, izquierda] en radianes. Cerca de 0 = tiesas y atentas;
# cuanto más se alejan de 0, más caídas (dormida = ±3).
ATENTAS = [-0.17, 0.17]
CONTENTAS = [-0.05, 0.05]
SUAVES = [-0.7, 0.7]


class Gestos:
    """Ejecuta gestos en segundo plano para no frenar la voz."""

    def __init__(self, reachy) -> None:
        self.r = reachy
        self._hilo: threading.Thread | None = None
        self._lock = threading.Lock()
        from reachy_mini.utils import create_head_pose

        self._pose = create_head_pose

    # Estados

    def despertar(self) -> None:
        self.r.wake_up()
        self._activar_seguimiento(True)
        try:
            self.r.enable_wobbling()  # la cabeza se mueve sutilmente al hablar
        except Exception:
            log.debug("Sin balanceo al hablar")

    def dormir(self) -> None:
        self._activar_seguimiento(False)
        try:
            self.r.disable_wobbling()
        except Exception:
            pass
        self.r.goto_sleep()

    def escuchar(self) -> None:
        self._mover(lambda: self.r.goto_target(self._pose(roll=6, pitch=-4), antennas=ATENTAS, duration=0.4))

    # Gestos que puede pedir la IA

    def hacer(self, nombre: str) -> None:
        accion: dict[str, Callable[[], None]] = {
            "alegria": self._alegria,
            "asentir": self._asentir,
            "pensar": self._pensar,
            "sorpresa": self._sorpresa,
            "carino": self._carino,
            "baile": self._baile,
            "escuchar": self.escuchar,
        }
        if nombre in accion:
            self._mover(accion[nombre])

    def _alegria(self) -> None:
        # Antenas que se agitan, como quien mueve la cola.
        for roll, antenas in ((8, [-0.45, 0.05]), (-8, [-0.05, 0.45]), (0, CONTENTAS)):
            self.r.goto_target(self._pose(roll=roll, pitch=-5), antennas=antenas, duration=0.25)

    def _asentir(self) -> None:
        for pitch in (8, -2, 6, 0):
            self.r.goto_target(self._pose(pitch=pitch), duration=0.22)

    def _pensar(self) -> None:
        self.r.goto_target(self._pose(yaw=14, pitch=-10, roll=-5), antennas=[-0.5, 0.1], duration=0.6)

    def _sorpresa(self) -> None:
        self.r.goto_target(self._pose(z=8, pitch=-6, mm=True), antennas=CONTENTAS, duration=0.2)
        time.sleep(0.4)
        self.r.goto_target(self._pose(), antennas=ATENTAS, duration=0.5)

    def _carino(self) -> None:
        self.r.goto_target(self._pose(roll=14, pitch=4), antennas=SUAVES, duration=1.0)
        time.sleep(0.8)
        self.r.goto_target(self._pose(roll=4), antennas=ATENTAS, duration=1.0)

    def _baile(self) -> None:
        for i in range(6):
            lado = 1 if i % 2 == 0 else -1
            antenas = [-0.45, 0.05] if lado > 0 else [-0.05, 0.45]
            self.r.goto_target(self._pose(roll=10 * lado), antennas=antenas,
                               body_yaw=0.25 * lado, duration=0.35)
        self.r.goto_target(self._pose(), antennas=ATENTAS, body_yaw=0.0, duration=0.4)

    # Utilidades

    def _mover(self, accion: Callable[[], None]) -> None:
        if self._hilo and self._hilo.is_alive():
            return  # ya está haciendo un gesto: no los encadenamos
        def correr() -> None:
            with self._lock:
                try:
                    accion()
                except Exception:
                    log.exception("Fallo en un gesto")
        self._hilo = threading.Thread(target=correr, daemon=True)
        self._hilo.start()

    def _activar_seguimiento(self, activo: bool) -> None:
        """Seguir la cara de la persona con la mirada mientras habláis."""
        try:
            if activo:
                self.r.start_head_tracking(weight=0.6)
            else:
                self.r.stop_head_tracking()
        except Exception:
            log.debug("Seguimiento de cara no disponible")
