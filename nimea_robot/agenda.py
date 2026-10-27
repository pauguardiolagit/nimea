"""Cuándo debe Nimea tomar la iniciativa: pastillas, mensajes nuevos y buenos días."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as hora

from .api import Contexto

MARGEN_TOMA = timedelta(minutes=50)  # después, la app avisa a la familia
ENTRE_RECORDATORIOS = timedelta(minutes=20)
ENTRE_AVISOS_MENSAJE = timedelta(minutes=45)
MAX_INTENTOS = 3


def _hhmm(texto: str) -> hora:
    h, m = texto.strip().split(":")
    return hora(int(h), int(m))


def en_descanso(ahora: datetime, desde: str, hasta: str) -> bool:
    """True si estamos en el horario de descanso (que puede cruzar la medianoche)."""
    inicio, fin, t = _hhmm(desde), _hhmm(hasta), ahora.time()
    if inicio <= fin:
        return inicio <= t < fin
    return t >= inicio or t < fin


@dataclass
class Motivo:
    tipo: str  # pastilla | mensajes | buenos_dias
    texto: str
    tomas: list[dict] = field(default_factory=list)


@dataclass
class Agenda:
    descanso: tuple[str, str] = ("22:30", "08:30")
    _recordado: dict[tuple, tuple[datetime, int]] = field(default_factory=dict)
    _resueltas: set[tuple] = field(default_factory=set)
    _mensajes_avisados: dict[str, tuple[datetime, int]] = field(default_factory=dict)
    _buenos_dias: str = ""

    def resolver_toma(self, medicacion_id: str, hora_prevista: str, dia: str) -> None:
        self._resueltas.add((medicacion_id, hora_prevista, dia))

    def tomas_pendientes(self, ctx: Contexto, ahora: datetime) -> list[dict]:
        """Tomas de ahora mismo que aún no se han resuelto."""
        dia = ahora.strftime("%Y-%m-%d")
        pendientes = []
        for med in ctx.medicacion:
            dias = med.get("dias") or []
            if dias and ahora.weekday() not in dias:
                continue
            for h in med.get("horas") or []:
                prevista = datetime.combine(ahora.date(), _hhmm(h))
                clave = (med.get("id"), h, dia)
                if clave in self._resueltas or not (prevista <= ahora <= prevista + MARGEN_TOMA):
                    continue
                pendientes.append({"medicacion_id": med.get("id"), "nombre": med.get("nombre"),
                                   "hora": h, "clave": clave})
        return pendientes

    def siguiente(self, ctx: Contexto, ahora: datetime) -> Motivo | None:
        """Decide si Nimea debe despertarse por su cuenta y por qué."""
        if en_descanso(ahora, *self.descanso):
            return None

        tomas = [t for t in self.tomas_pendientes(ctx, ahora) if self._toca(self._recordado, t["clave"], ahora,
                                                                             ENTRE_RECORDATORIOS)]
        if tomas:
            for t in tomas:
                self._marcar(self._recordado, t["clave"], ahora)
            nombres = " y ".join(t["nombre"] for t in tomas)
            return Motivo("pastilla", f"Es la hora de {nombres}. Recuérdaselo con cariño.", tomas)

        nuevos = [m for m in ctx.mensajes_pendientes if not m.get("escuchado")
                  and self._toca(self._mensajes_avisados, m.get("id"), ahora, ENTRE_AVISOS_MENSAJE)]
        if nuevos:
            for m in nuevos:
                self._marcar(self._mensajes_avisados, m.get("id"), ahora)
            autores = sorted({m.get("autor_nombre", "tu familia") for m in nuevos})
            return Motivo("mensajes", f"Han llegado mensajes de {', '.join(autores)}. Cuéntaselo con ilusión.")

        hoy = ahora.strftime("%Y-%m-%d")
        levantarse = (ctx.persona.get("horario") or {}).get("levantarse", "09:00")
        inicio = datetime.combine(ahora.date(), _hhmm(levantarse)) + timedelta(minutes=30)
        if self._buenos_dias != hoy and inicio <= ahora <= inicio + timedelta(hours=3):
            self._buenos_dias = hoy
            return Motivo("buenos_dias", "Es por la mañana: dale los buenos días, pregúntale qué tal ha "
                                         "dormido y cuéntale qué hay hoy (visitas, mensajes).")
        return None

    @staticmethod
    def _toca(registro: dict, clave, ahora: datetime, intervalo: timedelta) -> bool:
        ultimo = registro.get(clave)
        if ultimo is None:
            return True
        cuando, intentos = ultimo
        return intentos < MAX_INTENTOS and ahora - cuando >= intervalo

    @staticmethod
    def _marcar(registro: dict, clave, ahora: datetime) -> None:
        _, intentos = registro.get(clave, (ahora, 0))
        registro[clave] = (ahora, intentos + 1)
