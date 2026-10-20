"""Supervisor HTTP local que ejecuta los tres motores nativos sin Docker."""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from aplicacion.generacion import revisar_codigo
from aplicacion.configuracion import MAXIMO_BYTES_CODIGO
from nativo.procesos_windows import ejecutar_limitado


aplicacion = FastAPI(title="Supervisor CAD nativo Windows")
BLOQUEO = threading.Lock()


class SolicitudCAD(BaseModel):
    motor: str
    codigo: str = Field(min_length=1, max_length=MAXIMO_BYTES_CODIGO)


def configuracion() -> dict:
    return json.loads(Path(os.environ["CIEL_RUNTIMES_NATIVOS"]).read_text(encoding="utf-8"))


@aplicacion.get("/salud")
def salud() -> dict:
    return {"estado": "disponible", "plataforma": sys.platform}


@aplicacion.get("/imagenes")
def runtimes() -> dict:
    return {motor: datos["identificador"] for motor, datos in configuracion()["motores"].items()}


@aplicacion.post("/ejecutar")
def ejecutar(solicitud: SolicitudCAD) -> dict:
    if sys.platform != "win32":
        raise HTTPException(503, "Este supervisor solo permite ejecutar en Windows")
    try:
        revisar_codigo(solicitud.codigo, solicitud.motor)
    except (ValueError, SyntaxError, KeyError) as error:
        raise HTTPException(422, str(error)) from error
    config = configuracion()
    if solicitud.motor not in config["motores"]:
        raise HTTPException(422, "Motor nativo no configurado")
    motor = config["motores"][solicitud.motor]
    programa = Path(__file__).resolve().parents[1]
    inicio = time.monotonic()
    with BLOQUEO, tempfile.TemporaryDirectory(prefix="ciel-cad-", dir=config["temporales"]) as temporal:
        carpeta = Path(temporal)
        (carpeta / "solicitud.json").write_text(json.dumps({"motor": solicitud.motor, "codigo": solicitud.codigo,
            "programa": str(programa), "freecad_bin": config["freecad_bin"]}), encoding="utf-8")
        entorno = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", TEMP=str(carpeta), TMP=str(carpeta))
        # Ninguna respuesta larga se transporta como variable de entorno de Windows.
        argumentos = [motor["python"], "-I", str(programa / "nativo/ejecutar_cad.py"), str(carpeta)]
        try:
            resultado, mediciones = ejecutar_limitado(argumentos, entorno, carpeta)
        except (OSError, ValueError, RuntimeError) as error:
            raise HTTPException(503, f"No se pudo crear el proceso nativo: {error}") from error
        if resultado.get("correcto"):
            try:
                with httpx.Client(timeout=75, trust_env=False) as cliente:
                    respuesta = cliente.post(os.environ["URL_EVALUADOR"] + "/verificar-exportacion", json={"archivos": resultado["archivos"]})
                if respuesta.status_code == 422:
                    resultado = {"correcto": False, "fase_error": "exportacion", "diagnostico": str(respuesta.json().get("detail"))[:3000],
                        "sintaxis_valida": True, "ejecucion_correcta": True, "cad_valido": True, "exportacion_valida": False}
                else:
                    respuesta.raise_for_status()
            except httpx.HTTPError as error:
                raise HTTPException(503, f"El evaluador nativo no respondió: {type(error).__name__}") from error
        resultado.update({"runtime_identificador": motor["identificador"], "metricas_proceso": mediciones,
            "duracion_supervisor_segundos": time.monotonic() - inicio})
        return resultado
