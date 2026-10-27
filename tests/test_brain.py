from types import SimpleNamespace as NS

import anthropic

from nimea_robot.api import ApiNimea
from nimea_robot.bienestar import Sesion
from nimea_robot.brain import NO_ENTIENDO, Cerebro
from nimea_robot.config import Config
from nimea_robot.tools import Herramientas, MemoriaLocal


class Stream:
    def __init__(self, textos, final):
        self.textos, self.final = textos, final

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self): return iter(NS(type="text", text=t) for t in self.textos)
    def get_final_message(self): return self.final


class Cliente:
    def __init__(self, guion):
        self.guion = list(guion)
        self.llamadas = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **params):
        self.llamadas.append(params)
        paso = self.guion.pop(0)
        if isinstance(paso, Exception):
            raise paso
        return paso


def _final(contenido, stop="end_turn"):
    return NS(content=contenido, stop_reason=stop)


def _herr(tmp_path, contexto):
    class Cuerpo:
        def gesto(self, n): self.ultimo = n
    return Herramientas(ApiNimea("", "", tmp_path), contexto, Sesion(), Cuerpo(), MemoriaLocal(tmp_path))


def test_turno_con_herramienta_y_voz_por_frases(tmp_path, contexto):
    uso = NS(type="tool_use", id="t1", name="gesto", input={"nombre": "alegria"})
    cliente = Cliente([
        Stream(["¡Hola, Carmen! "], _final([NS(type="text", text="¡Hola, Carmen!"), uso], "tool_use")),
        Stream(["Qué alegría oírte.", " ¿Qué tal?"], _final([NS(type="text", text="Qué alegría oírte. ¿Qué tal?")])),
    ])
    cfg = Config()
    cerebro = Cerebro(cfg, cliente)
    cerebro.nueva_conversacion("sistema")
    dichas = []
    h = _herr(tmp_path, contexto)
    r = cerebro.turno("Hola", h, dichas.append)
    assert dichas == ["¡Hola, Carmen!", "Qué alegría oírte.", "¿Qué tal?"]
    assert h.cuerpo.ultimo == "alegria" and not r.terminada
    p = cliente.llamadas[0]
    assert p["model"] == "claude-opus-5-5" and p["fallbacks"] == "default"
    assert p["output_config"] == {"effort": "low"} and "tool_choice" not in p and "temperature" not in p
    assert [m["role"] for m in cerebro.mensajes] == ["user", "assistant", "user", "assistant"]


def test_rechazo_deja_historial_valido(tmp_path, contexto):
    cliente = Cliente([Stream([], _final([], "refusal"))])
    cerebro = Cerebro(Config(), cliente)
    cerebro.nueva_conversacion("s")
    dichas = []
    r = cerebro.turno("algo", _herr(tmp_path, contexto), dichas.append)
    assert r.texto == NO_ENTIENDO and cerebro.mensajes == []


def test_error_de_api(tmp_path, contexto):
    err = anthropic.APIConnectionError(request=None)
    cerebro = Cerebro(Config(), Cliente([err]))
    cerebro.nueva_conversacion("s")
    dichas = []
    cerebro.turno("hola", _herr(tmp_path, contexto), dichas.append)
    assert dichas == [NO_ENTIENDO] and cerebro.mensajes == []


def test_json_ilegible_se_reintenta(tmp_path, contexto):
    cliente = Cliente([ValueError("json"), Stream(["Vale, perfecto."], _final([NS(type="text", text="Vale, perfecto.")]))])
    cerebro = Cerebro(Config(), cliente)
    cerebro.nueva_conversacion("s")
    dichas = []
    cerebro.turno("hola", _herr(tmp_path, contexto), dichas.append)
    assert dichas == ["Vale, perfecto."] and len(cliente.llamadas) == 2
