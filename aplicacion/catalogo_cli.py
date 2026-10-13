"""Catálogos obtenidos de los CLI instalados, sin ejecutar turnos de inferencia."""

import json
import os
import selectors
import subprocess
import tempfile
import threading
import time

from aplicacion.cli_suscripcion import (
    ErrorCLI, MODELOS_SUSCRIPCION, _ejecutar, _entorno_cli, _terminar,
    ejecutable_cli, proveedor_cli,
)


_cache: dict = {}
_bloqueo = threading.Lock()


def _modelos_codex(ejecutable: str, directorio: str) -> list[dict]:
    try:
        proceso = subprocess.Popen(
            [ejecutable, "app-server", "--listen", "stdio://", "-c", "mcp_servers={}"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=directorio, env=_entorno_cli(), start_new_session=os.name == "posix",
        )
    except OSError:
        raise ErrorCLI("No se pudo consultar el catálogo de Codex") from None
    def enviar(datos: dict) -> None:
        proceso.stdin.write((json.dumps(datos) + "\n").encode("utf-8"))
        proceso.stdin.flush()
    try:
        enviar({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "agente_ciel", "version": "0.2.0"}}})
        limite = time.monotonic() + 20
        recibidos = b""
        modelos = []
        with selectors.DefaultSelector() as selector:
            selector.register(proceso.stdout, selectors.EVENT_READ)
            while time.monotonic() < limite:
                if not selector.select(timeout=min(1, max(0, limite - time.monotonic()))):
                    continue
                fragmento = os.read(proceso.stdout.fileno(), 65536)
                if not fragmento:
                    break
                recibidos += fragmento
                while b"\n" in recibidos:
                    linea, recibidos = recibidos.split(b"\n", 1)
                    datos = json.loads(linea)
                    if datos.get("id") == 1:
                        if "error" in datos:
                            raise ErrorCLI("Codex rechazó la consulta de modelos")
                        enviar({"method": "initialized", "params": {}})
                        enviar({"id": 2, "method": "model/list", "params": {"limit": 100, "includeHidden": False}})
                    elif datos.get("id") == 2:
                        if "error" in datos:
                            raise ErrorCLI("Codex no pudo listar modelos")
                        resultado = datos["result"]
                        modelos.extend(resultado["data"])
                        cursor = resultado.get("nextCursor")
                        if not cursor:
                            return modelos
                        enviar({"id": 2, "method": "model/list", "params": {
                            "limit": 100, "includeHidden": False, "cursor": cursor}})
        raise ErrorCLI("Timeout al consultar modelos de Codex", "timeout")
    except (OSError, ValueError, KeyError, TypeError):
        raise ErrorCLI("Catálogo de Codex malformado") from None
    finally:
        _terminar(proceso)


def consultar_catalogo_cli(proveedor: str) -> dict:
    with _bloqueo:
        anterior = _cache.get(proveedor)
        if anterior and time.monotonic() - anterior[0] < 300:
            return anterior[1]
        try:
            ejecutable = ejecutable_cli(proveedor)
            if not ejecutable or proveedor not in MODELOS_SUSCRIPCION:
                raise ErrorCLI("CLI no instalado")
            with tempfile.TemporaryDirectory(prefix="ciel-catalogo-") as directorio:
                if proveedor == "codex-cli":
                    originales = _modelos_codex(ejecutable, directorio)
                else:
                    salida = _ejecutar([ejecutable, "models"], "", directorio, 20)
                    originales = []
                    for linea in salida.splitlines():
                        partes = linea.strip().split(maxsplit=1)
                        if len(partes) == 2:
                            originales.append({"model": partes[0], "displayName": partes[1],
                                               "inputModalities": ["text"]})
            modelos = {}
            for original in originales:
                if not isinstance(original, dict):
                    continue
                identificador = original.get("model", "")
                if not isinstance(identificador, str):
                    continue
                clave = f"{proveedor}::{identificador}"
                if not proveedor_cli(clave):
                    continue
                modelos[clave] = {"identificador": identificador,
                    "nombre": str(original.get("displayName") or identificador)[:120],
                    "modalidades": original.get("inputModalities") or ["text", "image"],
                    "predeterminado": bool(original.get("isDefault"))}
            if not modelos:
                raise ErrorCLI("El CLI no anunció modelos seleccionables")
            resultado = {"modelos": modelos, "estado": "disponible", "acceso_verificado": False}
        except ErrorCLI as error:
            resultado = {"modelos": {}, "estado": "no_disponible", "error": str(error),
                         "acceso_verificado": False}
        _cache[proveedor] = (time.monotonic(), resultado)
        return resultado
