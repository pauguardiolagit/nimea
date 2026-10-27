from datetime import datetime

from nimea_robot.agenda import Agenda, en_descanso


def test_descanso_cruza_medianoche():
    assert en_descanso(datetime(2026, 10, 27, 23, 0), "22:30", "08:30")
    assert en_descanso(datetime(2026, 10, 27, 7, 0), "22:30", "08:30")
    assert not en_descanso(datetime(2026, 10, 27, 12, 0), "22:30", "08:30")


def test_recuerda_la_pastilla_y_no_insiste_enseguida(contexto):
    contexto.mensajes_pendientes = []
    agenda = Agenda()
    m = agenda.siguiente(contexto, datetime(2026, 10, 27, 9, 5))
    assert m and m.tipo == "pastilla" and m.tomas[0]["medicacion_id"] == "m1"
    otro = agenda.siguiente(contexto, datetime(2026, 10, 27, 9, 10))
    assert otro is None or otro.tipo != "pastilla"
    assert agenda.siguiente(contexto, datetime(2026, 10, 27, 9, 26)).tipo == "pastilla"


def test_toma_resuelta_no_se_repite(contexto):
    contexto.mensajes_pendientes = []
    agenda = Agenda()
    agenda.resolver_toma("m1", "09:00", "2026-10-27")
    m = agenda.siguiente(contexto, datetime(2026, 10, 27, 9, 5))
    assert m is None or m.tipo != "pastilla"


def test_avisa_de_mensajes_nuevos(contexto):
    contexto.medicacion = []
    m = Agenda().siguiente(contexto, datetime(2026, 10, 27, 12, 0))
    assert m.tipo == "mensajes" and "Lucía" in m.texto


def test_buenos_dias_una_vez(contexto):
    contexto.medicacion, contexto.mensajes_pendientes = [], []
    agenda = Agenda()
    assert agenda.siguiente(contexto, datetime(2026, 10, 27, 9, 30)).tipo == "buenos_dias"
    assert agenda.siguiente(contexto, datetime(2026, 10, 27, 10, 0)) is None


def test_en_descanso_no_molesta(contexto):
    assert Agenda().siguiente(contexto, datetime(2026, 10, 27, 23, 30)) is None
