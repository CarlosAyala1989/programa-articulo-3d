"""Comparación por caso con resultados externos explícitos; nunca deriva Compile Rate de IR."""
import hashlib
import json
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select

from aplicacion.base_datos import Campana, CasoDiseno, Ejecucion, ResultadoExterno, crear_sesion

rutas = APIRouter()
CRITERIO = 'ejecucion_sin_excepcion_y_cad_valido_exportable_v1'


class CasoExterno(BaseModel):
    model_config = ConfigDict(extra='forbid')
    codigo: str = Field(min_length=1, max_length=20)
    repeticion: int = Field(ge=1, le=5)
    ejecucion_correcta: StrictBool
    cad_exportable: StrictBool


class SolicitudResultadosExternos(BaseModel):
    model_config = ConfigDict(extra='forbid')
    protocolo: Literal['ciel-resultados-externos-v1'] = 'ciel-resultados-externos-v1'
    metodo: str = Field(min_length=2, max_length=120)
    fuente: str = Field(min_length=8, max_length=2000)
    condiciones: str = Field(min_length=10, max_length=4000)
    conjunto_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    criterio: Literal['ejecucion_sin_excepcion_y_cad_valido_exportable_v1']
    modo: Literal['open-loop', 'closed-loop']
    casos: list[CasoExterno] = Field(min_length=1, max_length=500)


def cargar_campana(sesion, identificador: str):
    campana = sesion.get(Campana, identificador)
    if campana is None:
        raise HTTPException(404, 'Campaña no encontrada.')
    return campana


@rutas.get('/api/campanas/{identificador}/plantilla-resultados-externos.json')
def plantilla(identificador: UUID) -> Response:
    with crear_sesion() as sesion:
        c = cargar_campana(sesion, str(identificador))
        casos = {r.identificador: r.codigo for r in sesion.scalars(select(CasoDiseno).where(
            CasoDiseno.conjunto_identificador == c.conjunto_identificador))}
        filas = sorted({(casos[e.caso_identificador], e.repeticion) for e in sesion.scalars(select(Ejecucion).where(
            Ejecucion.campana_identificador == str(identificador)))})
        documento = {'protocolo': 'ciel-resultados-externos-v1', 'metodo': 'Nombre y versión del método externo', 'fuente': 'URL, publicación o ubicación de trazas',
            'condiciones': 'Modelo, versión, motor CAD, parámetros y política de intentos del ensayo externo',
            'conjunto_sha256': (c.configuracion or {})['conjunto_sha256'], 'criterio': CRITERIO, 'modo': 'open-loop',
            'casos': [{'codigo': codigo, 'repeticion': repeticion, 'ejecucion_correcta': None, 'cad_exportable': None}
                      for codigo, repeticion in filas]}
        return Response(json.dumps(documento, ensure_ascii=False, indent=2), media_type='application/json',
            headers={'Content-Disposition': 'attachment; filename="resultados-externos-plantilla.json"'})


@rutas.post('/api/campanas/{identificador}/resultados-externos', status_code=201)
def importar(identificador: UUID, solicitud: SolicitudResultadosExternos) -> dict:
    documento = solicitud.model_dump()
    claves = [(r.codigo, r.repeticion) for r in solicitud.casos]
    if len(set(claves)) != len(claves):
        raise HTTPException(422, 'El archivo repite un caso y repetición.')
    if any(r.cad_exportable and not r.ejecucion_correcta for r in solicitud.casos):
        raise HTTPException(422, 'Un CAD exportable requiere una ejecución correcta.')
    with crear_sesion() as sesion:
        c = cargar_campana(sesion, str(identificador))
        if solicitud.conjunto_sha256 != (c.configuracion or {}).get('conjunto_sha256'):
            raise HTTPException(422, 'La huella del conjunto externo no coincide con esta campaña.')
        por_id = {r.identificador: r.codigo for r in sesion.scalars(select(CasoDiseno).where(
            CasoDiseno.conjunto_identificador == c.conjunto_identificador))}
        esperados = {(por_id[e.caso_identificador], e.repeticion) for e in sesion.scalars(select(Ejecucion).where(
            Ejecucion.campana_identificador == str(identificador), Ejecucion.modo == solicitud.modo))}
        if not esperados or set(claves) != esperados:
            raise HTTPException(422, 'Aporta exactamente los casos y repeticiones seleccionados para esa estrategia.')
        canonico = json.dumps(documento, ensure_ascii=False, sort_keys=True)
        huella = hashlib.sha256(canonico.encode()).hexdigest()
        previo = sesion.scalar(select(ResultadoExterno).where(ResultadoExterno.campana_identificador == str(identificador),
                                                              ResultadoExterno.sha256 == huella))
        if previo:
            return {'identificador': previo.identificador, 'sha256': huella, 'estado': 'ya_registrado'}
        registro = ResultadoExterno(identificador=str(uuid4()), campana_identificador=str(identificador),
                                    documento=documento, sha256=huella)
        sesion.add(registro); sesion.commit()
        return {'identificador': registro.identificador, 'sha256': huella, 'estado': 'registrado'}


def filas_externas(sesion, campana: Campana) -> list[dict]:
    filas = []
    niveles = {c.codigo: c.nivel for c in sesion.scalars(select(CasoDiseno).where(
        CasoDiseno.conjunto_identificador == campana.conjunto_identificador))}
    for r in sesion.scalars(select(ResultadoExterno).where(ResultadoExterno.campana_identificador == campana.identificador)):
        d = r.documento
        for nivel in ('todos', 'basico', 'intermedio', 'complejo'):
            casos = [c for c in d['casos'] if nivel == 'todos' or niveles[c['codigo']] == nivel]
            if not casos:
                continue
            filas.append({'origen': 'ensayo_externo_aportado', 'metodo': d['metodo'], 'modo': d['modo'], 'nivel': nivel,
                'n_evaluable': len(casos), 'compile_rate_pct': 100 * sum(c['ejecucion_correcta'] for c in casos) / len(casos),
                'ir_codigo_pct': 100 * sum(not c['ejecucion_correcta'] for c in casos) / len(casos),
                'ir_cad_pct': 100 * sum(not c['cad_exportable'] for c in casos) / len(casos),
                'fuente': d['fuente'], 'dataset': d['conjunto_sha256'], 'comparacion_directa': True,
                'nota': 'Mismos casos y criterio declarado; ejecución externa aportada, no replicada por Ciel. ' + d['condiciones'],
                'sha256_resultados_externos': r.sha256})
    return filas
