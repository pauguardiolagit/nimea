"""Cliente de la API de la app de la familia (backend en Base44).

El robot se identifica con su token de dispositivo. Todo lo que el robot envía
pasa por una cola en disco: si no hay conexión, se guarda y se reintenta en el
siguiente latido, para no perder nunca una respuesta de la abuela.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("nimea.api")

VERSION = "0.1.0"


@dataclass
class Contexto:
    """Lo que el robot sabe de la persona mayor y de su familia."""

    persona: dict[str, Any] = field(default_factory=dict)
    familiares: list[dict[str, Any]] = field(default_factory=list)
    recuerdos: list[dict[str, Any]] = field(default_factory=list)
    medicacion: list[dict[str, Any]] = field(default_factory=list)
    mensajes_pendientes: list[dict[str, Any]] = field(default_factory=list)
    visitas: list[dict[str, Any]] = field(default_factory=list)
    pautas: list[dict[str, Any]] = field(default_factory=list)
    ajustes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def desde_dict(cls, datos: dict[str, Any]) -> "Contexto":
        return cls(
            persona=datos.get("persona") or {},
            familiares=datos.get("familiares") or [],
            recuerdos=datos.get("recuerdos") or [],
            medicacion=datos.get("medicacion") or [],
            mensajes_pendientes=datos.get("mensajes_pendientes") or [],
            visitas=datos.get("visitas") or [],
            pautas=datos.get("pautas") or [],
            ajustes=datos.get("ajustes") or {},
        )

    @property
    def nombre(self) -> str:
        return self.persona.get("apodo") or self.persona.get("nombre") or ""

    def mensaje(self, mensaje_id: str) -> dict[str, Any] | None:
        return next((m for m in self.mensajes_pendientes if m.get("id") == mensaje_id), None)


class ApiNimea:
    def __init__(
        self,
        url: str,
        token: str,
        carpeta_datos: Path,
        cliente: httpx.Client | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.carpeta = carpeta_datos
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self._cola = self.carpeta / "cola.jsonl"
        self._cache = self.carpeta / "contexto.json"
        self._lock = threading.Lock()
        self._http = cliente or httpx.Client(timeout=20.0)

    @property
    def configurada(self) -> bool:
        return bool(self.url and self.token)

    def _cabeceras(self) -> dict[str, str]:
        # Base44 reserva Authorization para la sesión de usuario: el token del robot va aparte.
        return {"X-Nimea-Token": self.token, "X-Nimea-Version": VERSION}

    def _enviar(self, ruta: str, datos: dict[str, Any]) -> httpx.Response:
        funcion, datos = _funcion_base44(ruta, datos)
        return self._http.post(f"{self.url}/{funcion}", headers=self._cabeceras(), json=datos)

    # Lectura

    def contexto(self) -> Contexto:
        """Descarga el contexto; si falla, usa la última copia guardada."""
        if self.configurada:
            try:
                r = self._enviar("/robot/contexto", {})
                r.raise_for_status()
                datos = r.json()
                self._cache.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
                return Contexto.desde_dict(datos)
            except (httpx.HTTPError, ValueError) as e:
                log.warning("No se pudo descargar el contexto (%s); uso la copia local", e)
        if self._cache.is_file():
            return Contexto.desde_dict(json.loads(self._cache.read_text(encoding="utf-8")))
        return Contexto()

    def descargar(self, url: str) -> bytes:
        r = self._http.get(url, follow_redirects=True)
        r.raise_for_status()
        return r.content

    # Escritura (siempre a través de la cola)

    def sesion(self, datos: dict[str, Any]) -> None:
        self._encolar("POST", "/robot/sesion", datos)

    def toma(self, medicacion_id: str, prevista: str, estado: str) -> None:
        self._encolar(
            "POST",
            "/robot/toma",
            {
                "medicacion_id": medicacion_id,
                "hora_prevista": prevista,
                "estado": estado,
                "hora_confirmacion": _ahora_iso() if estado == "confirmada" else None,
            },
        )

    def respuesta(self, mensaje_id: str | None, para_familiar_id: str | None,
                  transcripcion: str, wav: bytes | None) -> None:
        self._encolar(
            "POST",
            "/robot/mensaje",
            {
                "responde_a": mensaje_id,
                "para_familiar_id": para_familiar_id,
                "transcripcion": transcripcion,
                "audio_wav_base64": base64.b64encode(wav).decode() if wav else None,
                "fecha": _ahora_iso(),
            },
        )

    def mensaje_entregado(self, mensaje_id: str, estado: str = "entregado") -> None:
        self._encolar("POST", f"/robot/mensaje/{mensaje_id}/entregado", {"estado": estado})

    def aviso(self, tipo: str, texto: str, nivel: str = "informativo") -> None:
        self._encolar("POST", "/robot/aviso", {"tipo": tipo, "texto": texto, "nivel": nivel,
                                               "fecha": _ahora_iso()})

    def latido(self, estado: str, conexion: str = "wifi") -> bool:
        """Envía el latido y vacía la cola. Devuelve True si hay conexión."""
        if not self.configurada:
            return False
        try:
            r = self._enviar("/robot/estado", {"estado": estado, "conexion": conexion, "version": VERSION,
                                               "pendientes": self.pendientes()})
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.info("Sin conexión con la app (%s)", e)
            return False
        self.vaciar_cola()
        return True

    # Cola

    def _encolar(self, metodo: str, ruta: str, datos: dict[str, Any]) -> None:
        with self._lock:
            with self._cola.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"metodo": metodo, "ruta": ruta, "datos": datos,
                                    "t": time.time()}, ensure_ascii=False) + "\n")
        self.vaciar_cola()

    def pendientes(self) -> int:
        if not self._cola.is_file():
            return 0
        return sum(1 for linea in self._cola.read_text(encoding="utf-8").splitlines() if linea)

    def vaciar_cola(self) -> int:
        """Envía lo pendiente en orden. Se detiene en el primer fallo de red."""
        if not self.configurada:
            return 0
        with self._lock:
            if not self._cola.is_file():
                return 0
            lineas = [x for x in self._cola.read_text(encoding="utf-8").splitlines() if x]
            enviadas = 0
            for linea in lineas:
                item = json.loads(linea)
                try:
                    r = self._enviar(item["ruta"], item["datos"])
                    if r.status_code >= 500:
                        break
                    if r.status_code >= 400:
                        # Un 4xx no se arregla reintentando: se descarta y se registra.
                        log.error("La app rechazó %s %s: %s", item["metodo"], item["ruta"], r.text[:200])
                except httpx.HTTPError:
                    break
                enviadas += 1
            resto = lineas[enviadas:]
            if resto:
                self._cola.write_text("\n".join(resto) + "\n", encoding="utf-8")
            else:
                self._cola.unlink(missing_ok=True)
            return enviadas


# Cada ruta del contrato es una función de Base44, servida en <NIMEA_API_URL>/<función>.
FUNCIONES = {
    "/robot/contexto": "robotContexto",
    "/robot/sesion": "robotSesion",
    "/robot/toma": "robotToma",
    "/robot/mensaje": "robotMensaje",
    "/robot/aviso": "robotAviso",
    "/robot/estado": "robotEstado",
}
_ENTREGADO = re.compile(r"^/robot/mensaje/([^/]+)/entregado$")


def _funcion_base44(ruta: str, datos: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Traduce una ruta del contrato a su función. El id de /mensaje/{id}/entregado pasa al cuerpo."""
    if m := _ENTREGADO.match(ruta):
        return "robotEntregado", {**datos, "id": m.group(1)}
    return FUNCIONES[ruta], datos


def _ahora_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
