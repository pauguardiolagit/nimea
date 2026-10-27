import threading
from types import SimpleNamespace as NS

import numpy as np

from nimea_robot.agenda import Motivo
from nimea_robot.api import ApiNimea
from nimea_robot.brain import Cerebro
from nimea_robot.companion import Nimea
from nimea_robot.config import Config
from tests.test_brain import Cliente, Stream, _final

FS = 16000


class AudioFalso:
    """Micro que entrega una frase hablada y luego silencio."""

    def __init__(self):
        t = np.arange(FS) / FS
        voz = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        silencio = np.zeros(FS // 10, dtype=np.float32)
        self.trozos = [silencio] * 3 + [voz] + [silencio] * 20
        self.sonado = 0

    def leer(self):
        return self.trozos.pop(0) if self.trozos else np.zeros(FS // 10, dtype=np.float32)

    def reproducir(self, pcm):
        self.sonado += 1

    def descartar_entrada(self):
        pass


class Gestos:
    def __init__(self):
        self.hechos = []

    def despertar(self): self.hechos.append("despertar")
    def dormir(self): self.hechos.append("dormir")
    def escuchar(self): self.hechos.append("escuchar")
    def hacer(self, n): self.hechos.append(n)


class ApiFalsa(ApiNimea):
    def __init__(self, carpeta):
        super().__init__("", "", carpeta)
        self.enviado = []

    def _encolar(self, metodo, ruta, datos):
        self.enviado.append((ruta, datos))


def test_conversacion_completa(tmp_path, contexto):
    fin = NS(type="tool_use", id="t1", name="terminar_conversacion", input={
        "resumen": "Ha contado que sus geranios han florecido.", "frase_destacada": "Están preciosos",
        "temas": ["geranios"], "personas_mencionadas": []})
    cliente = Cliente([
        Stream(["¡Hola, Carmen! ¿Qué tal tus geranios?"], _final([NS(type="text", text="¡Hola, Carmen! ¿Qué tal tus geranios?")])),
        Stream([], _final([fin], "tool_use")),
        Stream(["Me alegro mucho. Hasta luego."], _final([NS(type="text", text="Me alegro mucho. Hasta luego.")])),
    ])
    cfg = Config(carpeta_datos=tmp_path)
    api = ApiFalsa(tmp_path)
    gestos = Gestos()
    stt = NS(transcribir=lambda pcm: "Muy bien, han florecido todos")
    voz = NS(sintetizar=lambda texto: np.zeros(160, dtype=np.float32))
    nimea = Nimea(cfg, AudioFalso(), stt, voz, api, Cerebro(cfg, cliente), gestos, stt_palabra=stt)
    nimea.contexto = contexto

    nimea.conversar(Motivo("llamada", "Te ha llamado."), threading.Event())

    assert gestos.hechos[0] == "despertar" and gestos.hechos[-1] == "dormir"
    rutas = [r for r, _ in api.enviado]
    assert rutas == ["/robot/sesion"]
    sesion = api.enviado[0][1]
    assert sesion["temas"] == ["geranios"] and sesion["frase_destacada"] == "Están preciosos"
    assert nimea.memoria.resumenes()[0]["resumen"].startswith("Ha contado")
    # La segunda llamada a la IA lleva lo que ella dijo.
    assert cliente.llamadas[1]["messages"][2]["content"] == "Muy bien, han florecido todos"
