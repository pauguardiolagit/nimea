import pytest

from nimea_robot.wakeword import buscar_palabra


@pytest.mark.parametrize("texto", ["Nimea", "nimea, ¿qué hora es?", "Oye Nimeá", "Ni mea ven",
                                   "NIMEA!", "Nimia cuéntame algo"])
def test_activa(texto):
    assert buscar_palabra(texto).activada


@pytest.mark.parametrize("texto", ["anímate mujer", "qué animal tan bonito", "tengo anemia",
                                   "mira la tele", "", "eso es una nimiedad"])
def test_no_activa(texto):
    assert not buscar_palabra(texto).activada


def test_devuelve_lo_que_dijo_despues():
    assert buscar_palabra("Nimea, ¿qué tiempo hace hoy?").resto == "¿qué tiempo hace hoy?"
    assert buscar_palabra("Ni mea, pon música").resto == "pon música"
