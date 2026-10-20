"""Catálogos obtenidos de los CLI instalados, sin ejecutar turnos de inferencia."""

import json
import os
import selectors
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from aplicacion.cli_suscripcion import (
    ErrorCLI, ESFUERZOS_CLI, MODELOS_SUSCRIPCION, _ejecutar, _entorno_cli, _terminar,
    ejecutable_cli, proveedor_cli,
)


_cache: dict = {}
_bloqueo = threading.Lock()


def _ruta_catalogo(proveedor: str) -> Path:
    directorio = os.environ.get("CLI_CATALOGO_DIRECTORIO")
    if not directorio:
        base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_STATE_HOME")
        directorio = str((Path(base) if base else Path.home() / ".local/state") / "agente-ciel/catalogos")
    return Path(directorio).expanduser() / f"{proveedor}.json"


def _guardar_catalogo(proveedor: str, modelos: dict) -> None:
    try:
        ruta = _ruta_catalogo(proveedor)
        ruta.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=ruta.parent,
                                         prefix=".catalogo-", delete=False) as archivo:
            temporal = Path(archivo.name)
        try:
            with temporal.open("w", encoding="utf-8") as archivo:
                json.dump({"version": 1, "modelos": modelos}, archivo, ensure_ascii=False)
                archivo.flush()
                os.fsync(archivo.fileno())
            temporal.replace(ruta)
        finally:
            temporal.unlink(missing_ok=True)
    except OSError:
        pass  # Una ruta sin permisos no impide usar el catálogo consultado.


def _leer_catalogo(proveedor: str) -> dict:
    try:
        datos = json.loads(_ruta_catalogo(proveedor).read_text(encoding="utf-8"))
        if not isinstance(datos, dict) or datos.get("version") != 1:
            return {}
        modelos = datos.get("modelos")
        if not isinstance(modelos, dict):
            return {}
        return {clave: modelo for clave, modelo in modelos.items()
                if proveedor_cli(clave) == proveedor and "::" in clave
                and isinstance(modelo, dict) and isinstance(modelo.get("nombre"), str)
                and modelo.get("identificador") == clave.partition("::")[2]
                and isinstance(modelo.get("modalidades"), list)}
    except (OSError, ValueError):
        return {}


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


def _esfuerzo_antigravity(ejecutable: str, modelo: str, directorio: str, timeout: int) -> dict:
    try:
        datos = json.loads(_ejecutar([ejecutable, "--print", "/effort", "--model", modelo,
                                     "--output-format", "json"], "", directorio, timeout))
        if datos.get("status") == "SUCCESS" and datos.get("num_turns") == 0:
            comando = datos.get("command") or {}
            if comando.get("name") == "effort" and isinstance(comando.get("data"), dict):
                return comando["data"]
    except (ErrorCLI, ValueError, AttributeError):
        pass
    return {}


def consultar_catalogo_cli(proveedor: str) -> dict:
    if proveedor not in MODELOS_SUSCRIPCION:
        raise ErrorCLI("Proveedor CLI desconocido")
    with _bloqueo:
        anterior = _cache.get(proveedor)
        vigencia = 300 if anterior and anterior[1]["estado"] == "disponible" else 10
        if anterior and time.monotonic() - anterior[0] < vigencia:
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
                    # /effort es una consulta local: exigir cero turnos antes de aceptar metadatos.
                    limite = time.monotonic() + 20
                    def consultar_esfuerzo(original: dict) -> None:
                        identificador = original["model"]
                        if not proveedor_cli(f"{proveedor}::{identificador}") or time.monotonic() >= limite:
                            return
                        original["esfuerzo"] = _esfuerzo_antigravity(ejecutable, identificador, directorio,
                            max(1, int(limite - time.monotonic())))
                    with ThreadPoolExecutor(max_workers=3) as consultas:
                        list(consultas.map(consultar_esfuerzo, originales))
            modelos = {}
            anteriores = (anterior[1]["modelos"] if anterior else {}) or _leer_catalogo(proveedor)
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
                detalle = modelos[clave]
                if proveedor == "codex-cli":
                    niveles = original.get("supportedReasoningEfforts") or []
                    detalle["esfuerzos"] = {nivel["reasoningEffort"]: ESFUERZOS_CLI[nivel["reasoningEffort"]]
                        for nivel in niveles if isinstance(nivel, dict) and nivel.get("reasoningEffort") in ESFUERZOS_CLI}
                    detalle["esfuerzo_predeterminado"] = original.get("defaultReasoningEffort")
                    detalle["esfuerzo_informado"] = detalle["esfuerzo_predeterminado"]
                else:
                    esfuerzo = original.get("esfuerzo") or {}
                    detalle["esfuerzos"] = {nivel: ESFUERZOS_CLI[nivel] for nivel in esfuerzo.get("available", [])
                        if nivel in ESFUERZOS_CLI} if esfuerzo.get("adjustable") else {}
                    detalle["esfuerzo_predeterminado"] = esfuerzo.get("current")
                    detalle["esfuerzo_informado"] = esfuerzo.get("current")
                    detalle["esfuerzo_ajustable"] = esfuerzo.get("adjustable")
                    if not esfuerzo.get("current") and esfuerzo.get("adjustable") is False:
                        sufijo = identificador.rsplit("-", 1)[-1]
                        detalle["esfuerzo_informado"] = sufijo if sufijo in ESFUERZOS_CLI else None
                    if not esfuerzo and clave in anteriores:
                        detalle.update({campo: anteriores[clave][campo] for campo in (
                            "esfuerzos", "esfuerzo_predeterminado", "esfuerzo_informado", "esfuerzo_ajustable",
                            "modelos_por_esfuerzo") if campo in anteriores[clave]})
            if proveedor == "antigravity-cli":
                # Si el esfuerzo cambia de variante, mantener su identidad exacta en la ejecución.
                for clave, detalle in modelos.items():
                    actual = detalle.get("esfuerzo_predeterminado")
                    base, separador, sufijo = detalle["identificador"].rpartition("-")
                    if actual and separador and sufijo == actual:
                        destinos = {nivel: f"{proveedor}::{base}-{nivel}" for nivel in detalle["esfuerzos"]
                                    if f"{proveedor}::{base}-{nivel}" in modelos}
                        detalle["esfuerzos"] = {nivel: detalle["esfuerzos"][nivel] for nivel in destinos}
                        detalle["modelos_por_esfuerzo"] = destinos
            if not modelos:
                raise ErrorCLI("El CLI no anunció modelos seleccionables")
            _guardar_catalogo(proveedor, modelos)
            resultado = {"modelos": modelos, "estado": "disponible", "acceso_verificado": False}
        except ErrorCLI as error:
            modelos = (anterior[1]["modelos"] if anterior else {}) or _leer_catalogo(proveedor)
            resultado = {"modelos": modelos, "estado": "guardado" if modelos else "no_disponible", "error": str(error),
                         "acceso_verificado": False}
        _cache[proveedor] = (time.monotonic(), resultado)
        return resultado
