import threading
from types import SimpleNamespace as NS

import numpy as np

from nimea_robot.api import ApiNimea
from nimea_robot.bienestar import Sesion
from nimea_robot.config import Config
from nimea_robot.realtime import ConversacionVoz, a_base64_24k, de_base64_24k, herramientas_openai
from nimea_robot.tools import Herramientas, MemoriaLocal


class Conn:
    """Conexión Realtime falsa: devuelve eventos guionizados y apunta lo que se le manda."""

    def __init__(self, eventos):
        self.eventos = eventos
        self.enviado = []
        self.session = NS(update=lambda session: self.enviado.append(("session.update", session)))
        self.conversation = NS(item=NS(create=lambda item: self.enviado.append(("item", item))))
        self.response = NS(create=lambda response=None: self.enviado.append(("response.create", response)))
        self.input_audio_buffer = NS(append=lambda audio: self.enviado.append(("audio", len(audio))))

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self): return iter(self.eventos)
    def close(self): pass


class Audio:
    def __init__(self): self.empujado = 0.0
    def leer(self): return None
    def empujar(self, pcm):
        self.empujado += len(pcm) / 16000
        return 0.0
    def reproducir(self, pcm): pass
    def descartar_entrada(self): pass
    def cortar(self): pass


class Cuerpo:
    def gesto(self, n): self.ultimo = n


def test_audio_ida_y_vuelta():
    pcm = (0.3 * np.sin(np.arange(1600) / 5)).astype(np.float32)
    assert np.allclose(de_base64_24k(a_base64_24k(pcm)), pcm, atol=0.01)


def test_herramientas_en_formato_openai():
    h = herramientas_openai()
    assert all(t["type"] == "function" and "parameters" in t for t in h)
    assert "eager_input_streaming" not in h[0]


def test_conversacion_por_voz(tmp_path, contexto):
    voz = a_base64_24k(np.zeros(2400, dtype=np.float32))
    eventos = [
        NS(type="response.created"),
        NS(type="response.output_audio.delta", delta=voz),
        NS(type="response.done"),
        NS(type="conversation.item.input_audio_transcription.completed", transcript="Muy bien, regando los geranios"),
        NS(type="response.created"),
        NS(type="response.function_call_arguments.done", name="gesto", call_id="c1", arguments='{"nombre": "alegria"}'),
        NS(type="response.function_call_arguments.done", name="terminar_conversacion", call_id="c2",
           arguments='{"resumen": "Charla sobre sus geranios", "frase_destacada": "Están preciosos", '
                     '"temas": ["geranios"], "personas_mencionadas": []}'),
        NS(type="response.done"),
        NS(type="response.created"),
        NS(type="response.output_audio.delta", delta=voz),
        NS(type="response.done"),
        NS(type="response.output_audio.delta", delta=voz),  # no debe llegar a procesarse
    ]
    conn = Conn(eventos)
    cliente = NS(realtime=NS(connect=lambda model: conn))
    sesion = Sesion()
    audio = Audio()
    h = Herramientas(ApiNimea("", "", tmp_path), contexto, sesion, Cuerpo(), MemoriaLocal(tmp_path))
    cfg = Config(carpeta_datos=tmp_path)
    cv = ConversacionVoz(cfg, audio, h, cliente)
    cv.ejecutar("instrucciones", "Hola", threading.Event(), espera_silencio=30, espera_primera=30)

    assert cv.ha_hablado and h.terminada and sesion.temas == ["geranios"]
    assert h.cuerpo.ultimo == "alegria"
    tipos = [t for t, _ in conn.enviado]
    sesion_cfg = conn.enviado[0][1]
    assert sesion_cfg["audio"]["output"]["voice"] == "marin"
    assert sesion_cfg["audio"]["input"]["turn_detection"]["interrupt_response"] is False
    salidas = [x for t, x in conn.enviado if t == "item" and x["type"] == "function_call_output"]
    assert [s["call_id"] for s in salidas] == ["c1", "c2"]
    # Saludo inicial y despedida tras cerrar: dos peticiones de respuesta.
    assert tipos.count("response.create") == 2
    assert abs(audio.empujado - 0.3) < 0.01  # dos trozos de 0,15 s; el tercero no llega a sonar


def test_argumentos_rotos_vuelven_como_error(tmp_path, contexto):
    eventos = [NS(type="response.function_call_arguments.done", name="gesto", call_id="c1", arguments='{"nom'),
               NS(type="error", error=NS(message="x")), NS(type="error", error=NS(message="x")),
               NS(type="error", error=NS(message="x")), NS(type="error", error=NS(message="x"))]
    conn = Conn(eventos)
    h = Herramientas(ApiNimea("", "", tmp_path), contexto, Sesion(), Cuerpo(), MemoriaLocal(tmp_path))
    cv = ConversacionVoz(Config(carpeta_datos=tmp_path), Audio(), h, NS(realtime=NS(connect=lambda model: conn)))
    cv.ejecutar("i", "Hola", threading.Event(), 30, 30)
    salida = next(x for t, x in conn.enviado if t == "item" and x["type"] == "function_call_output")
    assert salida["output"].startswith("ERROR: ") and "INVALID_JSON" in salida["output"]
