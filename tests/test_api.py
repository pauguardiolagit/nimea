import json

import httpx

from nimea_robot.api import ApiNimea


def _api(tmp_path, manejador):
    return ApiNimea("https://app.test/functions", "tok", tmp_path, httpx.Client(transport=httpx.MockTransport(manejador)))


def test_contexto_y_cache(tmp_path):
    def ok(req):
        assert req.headers["X-Nimea-Token"] == "tok" and "Authorization" not in req.headers
        assert req.method == "POST" and req.url.path == "/functions/robotContexto"
        return httpx.Response(200, json={"persona": {"nombre": "Carmen"}})

    assert _api(tmp_path, ok).contexto().nombre == "Carmen"

    def caido(req):
        raise httpx.ConnectError("sin red")

    assert _api(tmp_path, caido).contexto().nombre == "Carmen"  # copia local


def test_cola_sin_conexion_y_reenvio(tmp_path):
    recibidos = []
    hay_red = {"v": False}

    def manejador(req):
        if not hay_red["v"]:
            raise httpx.ConnectError("sin red")
        recibidos.append((req.url.path, json.loads(req.content or b"{}")))
        return httpx.Response(200, json={})

    api = _api(tmp_path, manejador)
    api.toma("m1", "09:00", "confirmada")
    api.respuesta("msg1", "f3", "Era un pasodoble", b"RIFF")
    assert api.pendientes() == 2 and recibidos == []

    hay_red["v"] = True
    assert api.latido("en_linea")
    rutas = [r[0] for r in recibidos]
    assert rutas == ["/functions/robotEstado", "/functions/robotToma", "/functions/robotMensaje"]
    assert recibidos[2][1]["responde_a"] == "msg1"
    assert api.pendientes() == 0


def test_error_4xx_se_descarta(tmp_path):
    api = _api(tmp_path, lambda req: httpx.Response(422, text="malo"))
    api.aviso("prueba", "hola")
    assert api.pendientes() == 0


def test_entregado_lleva_el_id_en_el_cuerpo(tmp_path):
    recibidos = []

    def manejador(req):
        recibidos.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={"ok": True})

    _api(tmp_path, manejador).mensaje_entregado("msg7", "escuchado")
    assert recibidos == [("/functions/robotEntregado", {"estado": "escuchado", "id": "msg7"})]
