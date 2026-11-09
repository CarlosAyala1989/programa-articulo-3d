"""Servicio físico separado: sus dependencias no cambian los runtimes CAD congelados."""
import os
import hashlib
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from evaluador.metrologia import procesar_carpeta

aplicacion = FastAPI(title='Metrología física Agente Ciel', version='1.0.0')
RAIZ = Path(os.environ.get('DIRECTORIO_ARTEFACTOS', '/datos'))


class SolicitudMetrologia(BaseModel):
    comparacion_identificador: UUID


@aplicacion.get('/salud')
def salud() -> dict:
    return {'estado': 'disponible', 'protocolo': 'ciel-metrologia-otter-v2',
            'compatibles': ['ciel-metrologia-otter-v1', 'ciel-metrologia-otter-v2']}


@aplicacion.post('/proponer-cotas')
def proponer(solicitud: SolicitudMetrologia) -> dict:
    from evaluador.metrologia import cargar_geometria
    from evaluador.cotas_automaticas import proponer_cotas
    ruta = RAIZ / 'metrologia' / str(solicitud.comparacion_identificador) / 'nominal.stl'
    try:
        return proponer_cotas(cargar_geometria(ruta), hashlib.sha256(ruta.read_bytes()).hexdigest())
    except (ValueError, OSError) as error:
        raise HTTPException(422, str(error)[:1200]) from error


@aplicacion.post('/comparar')
def comparar(solicitud: SolicitudMetrologia) -> dict:
    carpeta = RAIZ / 'metrologia' / str(solicitud.comparacion_identificador)
    try:
        return procesar_carpeta(carpeta)
    except (ValueError, OSError, KeyError, IndexError) as error:
        raise HTTPException(422, str(error)[:1200]) from error
