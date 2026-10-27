from datetime import datetime

from nimea_robot import prompts
from nimea_robot.tools import MemoriaLocal


def test_sistema_estable_y_completo(tmp_path, contexto):
    memoria = MemoriaLocal(tmp_path)
    s1 = prompts.sistema(contexto, memoria)
    assert "Carmen" in s1 and "Lucía" in s1 and "id m1" in s1 and "punto de encuentro" in s1
    assert s1 == prompts.sistema(contexto, memoria)  # sin hora: cacheable


def test_situacion(contexto):
    s = prompts.situacion(contexto, "prueba", datetime(2026, 10, 27, 9, 5),
                          [{"medicacion_id": "m1", "nombre": "la pastilla", "hora": "09:00"}])
    assert "martes 27 de octubre" in s and "id msg1" in s and "09:00" in s
