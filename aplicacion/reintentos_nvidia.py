"""Recuperación operativa NVIDIA, separada de los intentos del protocolo CAD."""

import time
from collections.abc import Callable
from datetime import datetime, timezone

from aplicacion.calidad.nvidia import ErrorNvidia
from aplicacion.configuracion import VERSION_REINTENTOS_NVIDIA


CODIGOS_RECUPERABLES = frozenset({
    "timeout", "transport_error", "rate_limited", "service_unavailable",
    "server_error", "http_408", "malformed_response",
})


class ReintentoNvidiaCancelado(Exception):
    """La campaña se canceló mientras NVIDIA esperaba recuperación."""


def reintentar_nvidia(operacion: Callable, modelo: str, registrar: Callable | None = None,
                      comprobar: Callable | None = None):
    incidencias = []
    while True:
        if comprobar:
            comprobar()
        try:
            return operacion(), incidencias
        except ErrorNvidia as error:
            if error.codigo not in CODIGOS_RECUPERABLES:
                raise
            numero = len(incidencias) + 1
            espera = min(60, 5 * 2 ** min(numero - 1, 4))
            if error.espera_segundos is not None:
                espera = max(espera, error.espera_segundos)
            incidencia = {
                "numero": numero, "modelo": modelo, "codigo": error.codigo,
                "fecha": datetime.now(timezone.utc).isoformat(),
                "espera_segundos": espera, "request_id": error.request_id,
                "consumo_desconocido": True,
                "timeout_segundos": getattr(error, "timeout_segundos", None),
            }
            incidencias.append(incidencia)
            if registrar:
                registrar(incidencia)
            # Comprobar la cancelación durante la espera, sin otra llamada al proveedor.
            restante = espera
            while restante > 0:
                if comprobar:
                    comprobar()
                paso = min(1, restante)
                time.sleep(paso)
                restante -= paso
