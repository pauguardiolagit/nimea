"""Habla con Nimea escribiendo, sin robot. Sirve para probar su forma de conversar,
las herramientas y la conexión con la app.

    python -m nimea_robot.consola                  # OpenAI, con los datos de demostración (Carmen)
    python -m nimea_robot.consola --motor claude   # con Claude
    python -m nimea_robot.consola --app            # con los datos reales de la app
"""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np

from . import prompts
from .api import ApiNimea, Contexto
from .bienestar import Sesion
from .brain import Cerebro
from .config import Config
from .realtime import herramientas_openai
from .tools import Herramientas, MemoriaLocal

DEMO = Path(__file__).with_name("demo.json")


class CuerpoConsola:
    def decir(self, texto: str) -> None:
        print(f"  Nimea (lee en voz alta): {texto}")

    def reproducir(self, pcm: np.ndarray) -> None:
        print(f"  [suena un audio de {len(pcm) / 16000:.0f} s]")

    def grabar(self, segundos_max: float) -> tuple[np.ndarray | None, str]:
        texto = input("  [pitido: graba tu respuesta] > ").strip()
        return (np.zeros(16000, dtype=np.float32), texto) if texto else (None, "")

    def gesto(self, nombre: str) -> None:
        print(f"  [gesto: {nombre}]")

    def foto_jpeg(self) -> bytes | None:
        return None


class ApiDemo(ApiNimea):
    """La API de verdad, pero sin red: lo que se enviaría se enseña en pantalla."""

    def _encolar(self, metodo: str, ruta: str, datos: dict) -> None:
        resumen = {k: (v if k != "audio_wav_base64" else "...") for k, v in datos.items()}
        print(f"  [a la app: {metodo} {ruta} {json.dumps(resumen, ensure_ascii=False)}]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Nimea en modo texto")
    parser.add_argument("--app", action="store_true", help="usar los datos reales de la app")
    parser.add_argument("--motivo", default="llamada", choices=["llamada", "pastilla", "mensajes", "buenos_dias"])
    parser.add_argument("--motor", choices=["openai", "claude"], help="cerebro (por defecto, el de la configuración)")
    parser.add_argument("-v", action="store_true", help="ver los registros internos")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.v else logging.WARNING)

    cfg = Config.desde_entorno()
    if args.motor:
        cfg.motor = args.motor
    if args.app:
        api = ApiNimea(cfg.api_url, cfg.api_token, cfg.carpeta_datos)
        contexto = api.contexto()
        memoria = MemoriaLocal(cfg.carpeta_datos)
    else:
        carpeta = Path(tempfile.mkdtemp(prefix="nimea-demo-"))
        api = ApiDemo("", "", carpeta)
        contexto = Contexto.desde_dict(json.loads(DEMO.read_text(encoding="utf-8")))
        memoria = MemoriaLocal(carpeta)

    sesion = Sesion()
    herramientas = Herramientas(api, contexto, sesion, CuerpoConsola(), memoria)
    sistema = prompts.sistema(contexto, memoria)

    tomas = []
    textos = {
        "llamada": "Te ha llamado por tu nombre.",
        "pastilla": "Es la hora de una pastilla. Recuérdaselo con cariño.",
        "mensajes": "Han llegado mensajes de la familia. Cuéntaselo con ilusión.",
        "buenos_dias": "Es por la mañana: dale los buenos días.",
    }
    if args.motivo == "pastilla" and contexto.medicacion:
        med = contexto.medicacion[0]
        tomas = [{"medicacion_id": med["id"], "nombre": med["nombre"], "hora": (med.get("horas") or ["09:00"])[0]}]
    entrada = prompts.situacion(contexto, textos[args.motivo], datetime.now(), tomas) + "\n"
    entrada += ("Ella te acaba de llamar. Salúdala." if args.motivo == "llamada"
                else "Empiezas tú la conversación: llámala por su nombre con suavidad.")

    print("Nimea en modo texto. Escribe como si fueras la persona mayor. Ctrl+C para salir.\n")
    try:
        if cfg.motor == "openai":
            _charla_openai(cfg, sistema, entrada, herramientas)
        else:
            _charla_claude(cfg, sistema, entrada, herramientas, sesion)
    except (KeyboardInterrupt, EOFError):
        print()
    print("\nResumen para la familia:")
    print(json.dumps(sesion.para_api(), ensure_ascii=False, indent=2))


def _charla_claude(cfg: Config, sistema: str, entrada: str, herramientas: Herramientas, sesion: Sesion) -> None:
    cerebro = Cerebro(cfg)
    cerebro.nueva_conversacion(sistema)
    try:
        while True:
            cerebro.turno(entrada, herramientas, lambda frase: print(f"Nimea: {frase}"))
            if herramientas.terminada:
                break
            entrada = input("\nTú: ").strip() or "(silencio)"
    finally:
        if not sesion.resumen:
            sesion.resumen = (cerebro.resumir() or {}).get("resumen", "")


def _charla_openai(cfg: Config, sistema: str, entrada: str, herramientas: Herramientas) -> None:
    """La misma sesión Realtime que usa el robot, pero con texto en vez de voz."""
    from openai import OpenAI

    cliente = OpenAI(api_key=cfg.openai_api_key or None)
    with cliente.realtime.connect(model=cfg.openai_modelo_realtime) as conn:
        conn.session.update(session={
            "type": "realtime", "instructions": sistema, "output_modalities": ["text"],
            "tools": herramientas_openai(), "tool_choice": "auto",
        })
        while True:
            conn.conversation.item.create(item={"type": "message", "role": "user",
                                                "content": [{"type": "input_text", "text": entrada}]})
            conn.response.create()
            for evento in conn:
                if evento.type == "response.output_text.done":
                    print(f"Nimea: {evento.text}")
                elif evento.type == "response.function_call_arguments.done":
                    try:
                        args = json.loads(evento.arguments or "{}")
                    except ValueError:
                        args = None  # ejecutar() lo devuelve como error de entrada
                    contenido, error = herramientas.ejecutar(evento.name, args)
                    if isinstance(contenido, list):
                        contenido = "(imagen)"
                    conn.conversation.item.create(item={
                        "type": "function_call_output", "call_id": evento.call_id,
                        "output": ("ERROR: " if error else "") + str(contenido)})
                    print(f"  [herramienta {evento.name}]")
                elif evento.type == "error":
                    print(f"  [error: {evento.error.message}]")
                elif evento.type == "response.done":
                    salidas = evento.response.output or []
                    if any(getattr(o, "type", "") == "function_call" for o in salidas):
                        conn.response.create()  # que siga hablando tras usar herramientas
                        continue
                    break
            if herramientas.terminada:
                return
            entrada = input("\nTú: ").strip() or "(silencio)"


if __name__ == "__main__":
    main()
