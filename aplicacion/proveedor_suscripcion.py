"""Transporte de inferencia al CLI local o al puente del escritorio."""

import base64
import os
import time

import httpx

from aplicacion.cli_suscripcion import (
    ErrorCLI, MODELOS_SUSCRIPCION, ejecutar_cli, ejecutable_cli, tiempo_espera_cli,
)
from aplicacion.catalogo_cli import consultar_catalogo_cli


_catalogos: tuple[float, str, dict] | None = None


def catalogos_cli() -> dict:
    global _catalogos
    socket = os.environ.get("CLI_PUENTE_SOCKET", "").strip()
    identidad = socket + "|" + os.environ.get("CLI_LOCAL_HABILITADO", "0") + "|" + os.environ.get("CLI_PROVEEDORES", "")
    if _catalogos and _catalogos[1] == identidad and time.monotonic() - _catalogos[0] < 300:
        return _catalogos[2]
    if socket:
        try:
            with httpx.Client(transport=httpx.HTTPTransport(uds=socket), timeout=45) as cliente:
                respuesta = cliente.get("http://localhost/modelos")
                respuesta.raise_for_status()
                resultado = respuesta.json()
                if not isinstance(resultado, dict):
                    raise ValueError
        except (httpx.HTTPError, ValueError):
            resultado = {}
    elif os.environ.get("CLI_LOCAL_HABILITADO", "0") == "1":
        resultado = {p: consultar_catalogo_cli(p) for p in MODELOS_SUSCRIPCION if ejecutable_cli(p)}
    else:
        resultado = {}
    _catalogos = (time.monotonic(), identidad, resultado)
    return resultado


def modelos_cli_configurados() -> dict:
    if os.environ.get("CLI_PUENTE_SOCKET", "").strip():
        habilitados = os.environ.get("CLI_PROVEEDORES", "codex-cli,antigravity-cli").split(",")
        resultado = {m: n for m, n in MODELOS_SUSCRIPCION.items() if m in habilitados}
    elif os.environ.get("CLI_LOCAL_HABILITADO", "0") == "1":
        resultado = {m: n for m, n in MODELOS_SUSCRIPCION.items() if ejecutable_cli(m)}
    else:
        return {}
    catalogos = catalogos_cli()
    for proveedor in list(resultado):
        resultado[proveedor] += " · predeterminado"
        prefijo = "Codex" if proveedor == "codex-cli" else "Antigravity"
        for clave, modelo in catalogos.get(proveedor, {}).get("modelos", {}).items():
            resultado[clave] = f"{prefijo} · {modelo['nombre']} · suscripción"
    return resultado


def solicitar_cli(modelo: str, mensajes: list[dict], imagenes_png: list[bytes] | None = None) -> dict:
    if modelo not in modelos_cli_configurados():
        raise ErrorCLI("Proveedor de suscripción no habilitado en el backend")
    socket = os.environ.get("CLI_PUENTE_SOCKET", "").strip()
    if not socket:
        return ejecutar_cli(modelo, mensajes, imagenes_png)
    cuerpo = {"modelo": modelo, "mensajes": mensajes,
              "imagenes_png": [base64.b64encode(i).decode("ascii") for i in imagenes_png or []]}
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds=socket),
                          timeout=tiempo_espera_cli() + 30) as cliente:
            respuesta = cliente.post("http://localhost/generar", json=cuerpo)
            datos = respuesta.json()
    except httpx.TimeoutException:
        raise ErrorCLI("Timeout del puente CLI; no se reenvía la llamada", "timeout") from None
    except (httpx.HTTPError, ValueError):
        raise ErrorCLI("Puente CLI no disponible; inicia el servicio local de suscripciones") from None
    if not isinstance(datos, dict):
        raise ErrorCLI("Respuesta del puente CLI malformada", "malformed_response")
    if respuesta.status_code != 200:
        raise ErrorCLI(datos.get("error", "El puente CLI rechazó la solicitud"),
                       datos.get("codigo", "provider_error"))
    if not isinstance(datos.get("texto"), str):
        raise ErrorCLI("Respuesta del puente CLI malformada", "malformed_response")
    return datos


def estado_puente() -> dict:
    socket = os.environ.get("CLI_PUENTE_SOCKET", "").strip()
    if not socket:
        return {"transporte": "local", "configurados": modelos_cli_configurados(),
                "sesion_comprobada": False}
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds=socket), timeout=3) as cliente:
            respuesta = cliente.get("http://localhost/salud")
            respuesta.raise_for_status()
            return respuesta.json()
    except (httpx.HTTPError, ValueError):
        return {"estado": "no_disponible", "sesion_comprobada": False}
