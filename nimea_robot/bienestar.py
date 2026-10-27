"""Lo que Nimea anota de cada conversación para el resumen de la familia.

Las siete dimensiones coinciden con la pestaña Bienestar de la app. Nimea no hace
encuestas: anota lo que observa de forma natural mientras charla.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

DIMENSIONES = {
    "alegria": "Alegría: cómo se le nota, si ríe, cómo dice estar.",
    "mente": "Mente despierta: retos, ganas de jugar, memoria de lo hablado.",
    "movimiento": "Movimiento: ejercicios, paseos, si se ha movido por casa.",
    "alimentacion": "Alimentación: si ha comido y qué.",
    "conexion": "Conexión: contacto con la familia y otras personas.",
    "descanso": "Descanso: cómo dice haber dormido.",
    "rutina": "Rutina: pastillas y horarios.",
}

TIPOS_RETO = ["memoria", "lenguaje", "calculo", "orientacion", "refranes", "adivinanzas"]
RESULTADOS_RETO = ["acertado", "con_ayuda", "no_acertado"]


@dataclass
class Sesion:
    inicio: float = field(default_factory=time.time)
    fin: float | None = None
    segundos_habla: float = 0.0
    retos: list[dict[str, str]] = field(default_factory=list)
    bienestar: list[dict[str, Any]] = field(default_factory=list)
    temas: list[str] = field(default_factory=list)
    personas: list[str] = field(default_factory=list)
    frase_destacada: str = ""
    resumen: str = ""

    @property
    def vacia(self) -> bool:
        return (self.segundos_habla < 5 and not self.resumen and not self.retos
                and not self.bienestar)

    def anotar(self, dimension: str, valor: int, nota: str) -> None:
        self.bienestar.append({"dimension": dimension, "valor": int(valor), "nota": nota})

    def reto(self, tipo: str, enunciado: str, resultado: str) -> None:
        self.retos.append({"tipo": tipo, "enunciado": enunciado, "resultado": resultado})

    def para_api(self) -> dict[str, Any]:
        fin = self.fin or time.time()
        return {
            "inicio": _iso(self.inicio),
            "fin": _iso(fin),
            "minutos": round((fin - self.inicio) / 60, 1),
            "retos": self.retos,
            "temas": self.temas,
            "personas_mencionadas": self.personas,
            "frase_destacada": self.frase_destacada,
            "resumen": self.resumen,
            "bienestar": self.bienestar,
        }


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t))
