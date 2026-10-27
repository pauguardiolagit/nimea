import json

import numpy as np

from nimea_robot.api import ApiNimea
from nimea_robot.bienestar import Sesion
from nimea_robot.tools import DEFINICIONES, Herramientas, MemoriaLocal, validar


class Cuerpo:
    def __init__(self):
        self.dicho, self.gestos = [], []

    def decir(self, t): self.dicho.append(t)
    def reproducir(self, pcm): pass
    def grabar(self, segundos_max): return np.zeros(1600, dtype=np.float32), "Era Suspiros de España"
    def gesto(self, n): self.gestos.append(n)
    def foto_jpeg(self): return b"\xff\xd8jpeg"


class ApiFalsa(ApiNimea):
    def __init__(self, carpeta):
        super().__init__("", "", carpeta)
        self.enviado = []

    def _encolar(self, metodo, ruta, datos):
        self.enviado.append((ruta, datos))


def _herr(tmp_path, contexto):
    api = ApiFalsa(tmp_path)
    return Herramientas(api, contexto, Sesion(), Cuerpo(), MemoriaLocal(tmp_path)), api


def test_esquemas_bien_formados():
    for d in DEFINICIONES:
        assert d["input_schema"]["additionalProperties"] is False
        assert d["eager_input_streaming"] is True
        assert set(d["input_schema"]["required"]) <= set(d["input_schema"]["properties"])


def test_validacion():
    assert validar("anotar_bienestar", {"dimension": "alegria", "valor": 4, "nota": "ríe"}) is None
    assert "valor" in validar("anotar_bienestar", {"dimension": "alegria", "valor": 9, "nota": "x"})
    assert validar("anotar_bienestar", {"dimension": "salud", "valor": 3, "nota": "x"})
    assert validar("gesto", {"nombre": "alegria", "extra": 1})
    assert validar("gesto", "alegria")
    assert validar("no_existe", {})


def test_flujo_reto_de_la_nieta(tmp_path, contexto):
    h, api = _herr(tmp_path, contexto)
    texto, err = h.ejecutar("reproducir_mensaje", {"mensaje_id": "msg1"})
    assert not err and "Léeselo" in texto and "canción" in texto  # el reto lo lee Nimea
    texto, err = h.ejecutar("grabar_respuesta", {"mensaje_id": "msg1"})
    assert not err and "Suspiros" in texto
    rutas = [r for r, _ in api.enviado]
    assert rutas == ["/robot/mensaje/msg1/entregado", "/robot/mensaje"]
    assert api.enviado[1][1]["para_familiar_id"] == "f3"
    assert contexto.mensaje("msg1") is None


def test_pastilla_avisa_a_la_agenda(tmp_path, contexto):
    h, api = _herr(tmp_path, contexto)
    resueltas = []
    h.al_resolver_toma = lambda m, hora: resueltas.append((m, hora))
    h.ejecutar("confirmar_pastilla", {"medicacion_id": "m1", "hora_prevista": "09:00", "estado": "confirmada"})
    assert resueltas == [("m1", "09:00")]
    assert h.sesion.bienestar[0]["dimension"] == "rutina"


def test_error_de_entrada_vuelve_como_error(tmp_path, contexto):
    h, _ = _herr(tmp_path, contexto)
    contenido, err = h.ejecutar("registrar_reto", {"tipo": "memoria"})
    assert err and "INVALID_INPUT" in json.loads(contenido)


def test_mirar_devuelve_imagen(tmp_path, contexto):
    h, _ = _herr(tmp_path, contexto)
    contenido, err = h.ejecutar("mirar", {})
    assert not err and contenido[0]["type"] == "image"


def test_terminar_y_memoria(tmp_path, contexto):
    h, _ = _herr(tmp_path, contexto)
    h.ejecutar("guardar_recuerdo", {"titulo": "Pepa", "descripcion": "Su hermana", "privado": False})
    h.ejecutar("terminar_conversacion", {"resumen": "Charla alegre", "frase_destacada": "Qué bien",
                                         "temas": ["geranios"], "personas_mencionadas": ["Lucía"]})
    assert h.terminada and h.sesion.para_api()["temas"] == ["geranios"]
    assert MemoriaLocal(tmp_path).recuerdos()[0]["titulo"] == "Pepa"
