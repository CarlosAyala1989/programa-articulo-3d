"""Única capa con acceso al socket de Docker; nunca recibe la clave de IA."""

import base64
import json
import time

import docker
import requests
from docker.errors import DockerException
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from requests.exceptions import ReadTimeout


aplicacion = FastAPI(title="Supervisor CAD")
IMAGENES = {
    "cadquery": "ciel-cadquery:piloto",
    "build123d": "ciel-build123d:piloto",
    "freecad": "ciel-freecad:piloto",
}
PREFIJO_SALIDA = "SALIDA_CAD:"
URL_EVALUADOR = "http://evaluador:8200"


class SolicitudEjecucion(BaseModel):
    motor: str
    codigo: str = Field(min_length=1, max_length=90_000)

    @field_validator("codigo")
    @classmethod
    def validar_tamano_utf8(cls, codigo: str) -> str:
        if len(codigo.encode("utf-8")) > 90_000:
            raise ValueError("El programa excede 90.000 bytes UTF-8")
        return codigo


@aplicacion.get("/salud")
def consultar_salud() -> dict:
    return {"estado": "disponible"}


@aplicacion.get("/imagenes")
def consultar_imagenes() -> dict:
    cliente = docker.from_env(timeout=12)
    try:
        return {motor: cliente.images.get(etiqueta).id[:25]
                for motor, etiqueta in IMAGENES.items()}
    except DockerException as error:
        raise HTTPException(503, f"No se pudo identificar una imagen CAD: {type(error).__name__}") from error
    finally:
        cliente.close()


@aplicacion.post("/ejecutar")
def ejecutar_codigo(solicitud: SolicitudEjecucion) -> dict:
    if solicitud.motor not in IMAGENES:
        raise HTTPException(422, "Motor CAD no reconocido")
    cliente = docker.from_env(timeout=100)
    contenedor = None
    inicio = time.monotonic()
    try:
        contenedor = cliente.containers.create(
            image=IMAGENES[solicitud.motor],
            detach=True,
            network_disabled=True,
            read_only=True,
            tmpfs={"/tmp": "rw,nosuid,nodev,size=256m"},
            environment={
                "CODIGO_BASE64": base64.b64encode(solicitud.codigo.encode()).decode(),
                "HOME": "/tmp",
                "TMPDIR": "/tmp",
            },
            mem_limit="4g",
            nano_cpus=2_000_000_000,
            pids_limit=128,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            user="10001:10001",
        )
        contenedor.start()
        estado = contenedor.wait(timeout=100)
        salida = contenedor.logs(stdout=True, stderr=True)
        if len(salida) > 35_000_000:
            return {
                "correcto": False, "fase_error": "salida",
                "diagnostico": "La salida CAD excede el límite",
                "sintaxis_valida": None, "ejecucion_correcta": False,
                "cad_valido": None, "exportacion_valida": None,
                "runtime_identificador": contenedor.image.id[:25],
                "duracion_supervisor_segundos": time.monotonic() - inicio,
            }
        for linea in reversed(salida.decode("utf-8", "replace").splitlines()):
            if linea.startswith(PREFIJO_SALIDA):
                resultado = json.loads(linea[len(PREFIJO_SALIDA) :])
                if resultado.get("correcto") is True:
                    try:
                        verificacion = requests.post(
                            f"{URL_EVALUADOR}/verificar-exportacion",
                            json={"archivos": resultado["archivos"]}, timeout=75,
                        )
                    except requests.RequestException as error:
                        raise HTTPException(503, f"Verificador STEP/STL no disponible: {type(error).__name__}") from error
                    if verificacion.status_code == 422:
                        detalle = str(verificacion.json().get("detail", "archivo ilegible"))[:1000]
                        resultado = {
                            "correcto": False, "fase_error": "exportacion",
                            "diagnostico": f"STEP o STL nativo ilegible: {detalle}",
                            "sintaxis_valida": True, "ejecucion_correcta": True,
                            "cad_valido": True, "exportacion_valida": False,
                        }
                    elif verificacion.status_code != 200:
                        raise HTTPException(503, "El verificador de STEP/STL falló")
                resultado["runtime_identificador"] = contenedor.image.id[:25]
                resultado["duracion_supervisor_segundos"] = time.monotonic() - inicio
                return resultado
        if estado.get("StatusCode") != 0:
            raise HTTPException(503, "El runtime CAD terminó sin un resultado estructurado")
        raise HTTPException(503, "El runtime CAD no produjo una respuesta")
    except ReadTimeout:
        imagen_identificador = contenedor.image.id[:25] if contenedor is not None else None
        if contenedor is not None:
            contenedor.kill()
        return {
            "correcto": False, "fase_error": "tiempo", "diagnostico": "El script excedió 100 segundos",
            "sintaxis_valida": None, "ejecucion_correcta": False,
            "cad_valido": None, "exportacion_valida": None,
            "runtime_identificador": imagen_identificador,
            "duracion_supervisor_segundos": time.monotonic() - inicio,
        }
    except DockerException as error:
        raise HTTPException(503, f"Runtime CAD no disponible: {type(error).__name__}") from error
    except json.JSONDecodeError as error:
        raise HTTPException(503, "Respuesta CAD mal formada") from error
    finally:
        if contenedor is not None:
            try:
                contenedor.remove(force=True)
            except DockerException:
                pass
        cliente.close()
