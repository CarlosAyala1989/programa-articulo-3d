"""Comparaciones físicas anexas e inmutables, con carga local y trabajo en segundo plano."""

import hashlib
import json
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from starlette.background import BackgroundTask

from aplicacion.base_datos import ComparacionFisica, Ejecucion, ArchivoGenerado, Campana, CasoDiseno, PlanCotas, PerfilMetrologia, crear_sesion, fecha_actual
from aplicacion.configuracion import DIRECTORIO_ARTEFACTOS, MODO_NATIVO

rutas = APIRouter()
REGISTRO = logging.getLogger(__name__)
EJECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ciel-metrologia')
MAXIMO_ESCANEO = 250 * 1024 * 1024
FORMATOS = {'.stl', '.obj', '.ply', '.pcd', '.asc', '.xyz'}


class PuntoPareado(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    escaneo: tuple[float, float, float]
    nominal: tuple[float, float, float]


class CotaCritica(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    nombre: str = Field(min_length=1, max_length=100)
    nominal_mm: float = Field(gt=0, le=100000)
    mediciones_mm: list[Annotated[float, Field(gt=0, le=100000)]] = Field(min_length=1, max_length=100)
    metodo: str = Field(min_length=3, max_length=150)


class SolicitudComparacion(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    pieza: str = Field(min_length=1, max_length=120)
    escaner: str = Field(default='Creality CR-Scan Otter', min_length=1, max_length=120)
    serie_escaner: str = Field(default='', max_length=100)
    software: str = Field(default='CrealityScan', max_length=100)
    fecha_escaneo: date | None = None
    calibracion_realizada: bool = False
    fecha_calibracion: date | None = None
    notas_calibracion: str = Field(default='', max_length=1000)
    impresora: str = Field(default='', max_length=100)
    material: str = Field(default='', max_length=100)
    altura_capa_mm: float | None = Field(default=None, gt=0, le=10)
    parametros_impresion: str = Field(default='', max_length=2000)
    unidad: Literal['mm', 'cm', 'm', 'in'] = 'mm'
    tolerancia_mm: float = Field(default=.3, ge=.0001, le=100)
    umbral_icp_mm: float = Field(default=2, ge=.001, le=1000)
    mapa_limite_mm: float = Field(default=.5, ge=.0001, le=100)
    muestras: int = Field(default=20000, ge=2000, le=100000)
    alineacion: Literal['automatica', 'conservar', 'puntos'] = 'automatica'
    puntos_pareados: list[PuntoPareado] = Field(default_factory=list, max_length=12)
    cotas: list[CotaCritica] = Field(default_factory=list, max_length=30)
    medir_cotas_automaticas: bool = True
    banda_cotas_mm: float = Field(default=.5, ge=.01, le=10)
    plan_identificador: UUID | None = None
    perfil_identificador: UUID | None = None
    notas: str = Field(default='', max_length=4000)


CAMPOS_PERFIL = {'escaner', 'serie_escaner', 'software', 'impresora', 'material', 'altura_capa_mm',
    'parametros_impresion', 'unidad', 'tolerancia_mm', 'umbral_icp_mm', 'mapa_limite_mm', 'muestras', 'banda_cotas_mm'}


class SolicitudPerfil(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nombre: str = Field(min_length=1, max_length=100)
    configuracion: dict


class SeleccionCotas(BaseModel):
    model_config = ConfigDict(extra='forbid')
    origen_identificador: UUID
    codigos: list[str] = Field(min_length=1, max_length=30)


@rutas.get('/api/metrologia/perfiles')
def listar_perfiles() -> list[dict]:
    with crear_sesion() as sesion:
        return [{'identificador': p.identificador, 'nombre': p.nombre, 'configuracion': p.configuracion}
                for p in sesion.scalars(select(PerfilMetrologia).order_by(PerfilMetrologia.fecha_creacion.desc()))]


@rutas.post('/api/metrologia/perfiles', status_code=201)
def guardar_perfil(solicitud: SolicitudPerfil) -> dict:
    if set(solicitud.configuracion) - CAMPOS_PERFIL:
        raise HTTPException(422, 'Un perfil no puede reutilizar fechas, calibraciones, medidas ni datos de otra pieza.')
    from pydantic import ValidationError
    try:
        datos = SolicitudComparacion(pieza='Perfil', **solicitud.configuracion).model_dump(mode='json')
    except ValidationError as error:
        raise HTTPException(422, 'Comprueba las unidades y los valores del perfil.') from error
    registro = PerfilMetrologia(identificador=str(uuid4()), nombre=solicitud.nombre,
                                configuracion={k: datos[k] for k in CAMPOS_PERFIL})
    with crear_sesion() as sesion:
        sesion.add(registro); sesion.commit()
    return {'identificador': registro.identificador, 'nombre': registro.nombre, 'configuracion': registro.configuracion}


def ultimo_plan(sesion, ejecucion: str):
    return sesion.scalar(select(PlanCotas).where(PlanCotas.ejecucion_identificador == ejecucion)
                        .order_by(PlanCotas.fecha_creacion.desc()))


def datos_plan(registro) -> dict:
    return {'identificador': registro.identificador, 'sha256': registro.sha256, 'documento': registro.documento} if registro else {'identificador': None, 'documento': None}


@rutas.get('/api/ejecuciones/{ejecucion}/plan-cotas')
def obtener_plan(ejecucion: UUID) -> dict:
    with crear_sesion() as sesion:
        return datos_plan(ultimo_plan(sesion, str(ejecucion)))


def proponer_desde_copia(carpeta: Path) -> dict:
    try:
        with httpx.Client(timeout=180, trust_env=False) as cliente:
            respuesta = cliente.post(os.environ.get('URL_METROLOGIA', 'http://127.0.0.1:8023') + '/proponer-cotas',
                                     json={'comparacion_identificador': carpeta.name})
    except httpx.HTTPError as error:
        raise HTTPException(503, 'El servicio de metrología no respondió. Reinicia la aplicación y vuelve a detectar las cotas.') from error
    if respuesta.status_code != 200:
        raise HTTPException(422, 'No se detectaron regiones nominales válidas. Revisa el STL o usa cotas manuales.')
    return respuesta.json()


def conservar_plan(sesion, ejecucion: str, documento: dict):
    from evaluador.protocolo_cotas import huella_plan
    # Este import solo usa el hash: el API nativo no requiere dependencias CAD/metrológicas.
    registro = PlanCotas(identificador=str(uuid4()), ejecucion_identificador=ejecucion,
        nominal_sha256=documento['nominal_sha256'], documento=documento, sha256=huella_plan(documento))
    sesion.add(registro); sesion.flush()
    return registro


@rutas.post('/api/ejecuciones/{ejecucion}/plan-cotas')
def seleccionar_cotas(ejecucion: UUID, solicitud: SeleccionCotas) -> dict:
    with crear_sesion() as sesion:
        origen = sesion.get(PlanCotas, str(solicitud.origen_identificador))
        if origen is None or origen.ejecucion_identificador != str(ejecucion):
            raise HTTPException(404, 'Plan de cotas no encontrado para este modelo.')
        seleccionadas = set(solicitud.codigos)
        cotas = [c for c in origen.documento['cotas'] if c['codigo'] in seleccionadas]
        if len(cotas) != len(seleccionadas):
            raise HTTPException(422, 'Selecciona únicamente cotas detectadas en este nominal.')
        nuevo = conservar_plan(sesion, str(ejecucion), {**origen.documento, 'cotas': cotas})
        sesion.commit(); return datos_plan(nuevo)


def carpeta_comparacion(identificador: str) -> Path:
    return Path(DIRECTORIO_ARTEFACTOS) / 'metrologia' / str(UUID(identificador))


def huella_archivo(ruta: Path) -> str:
    resumen = hashlib.sha256()
    with ruta.open('rb') as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b''):
            resumen.update(bloque)
    return resumen.hexdigest()


def buscar(sesion, identificador: str) -> ComparacionFisica:
    registro = sesion.get(ComparacionFisica, identificador)
    if registro is None:
        raise HTTPException(404, 'Comparación física no encontrada.')
    return registro


def serializar(registro: ComparacionFisica) -> dict:
    datos = {c.name: getattr(registro, c.name) for c in ComparacionFisica.__table__.columns}
    carpeta = carpeta_comparacion(registro.identificador)
    datos['archivos'] = [{'nombre': p.name, 'url': f'/api/comparaciones-fisicas/{registro.identificador}/archivos/{p.name}'}
                         for p in sorted(carpeta.iterdir()) if p.is_file() and not p.name.endswith('.tmp')]
    return datos


@rutas.get('/api/ejecuciones/{ejecucion}/comparaciones-fisicas')
def listar_comparaciones(ejecucion: UUID) -> list[dict]:
    with crear_sesion() as sesion:
        if sesion.get(Ejecucion, str(ejecucion)) is None:
            raise HTTPException(404, 'Trabajo no encontrado.')
        registros = sesion.scalars(select(ComparacionFisica).where(
            ComparacionFisica.ejecucion_identificador == str(ejecucion)).order_by(ComparacionFisica.fecha_creacion.desc()))
        return [serializar(r) for r in registros]


@rutas.post('/api/ejecuciones/{ejecucion}/plan-cotas/proponer')
def detectar_cotas(ejecucion: UUID) -> dict:
    carpeta = carpeta_comparacion(str(uuid4()))
    with crear_sesion() as sesion:
        trabajo = sesion.get(Ejecucion, str(ejecucion))
        archivo = sesion.scalar(select(ArchivoGenerado).where(
            ArchivoGenerado.ejecucion_identificador == str(ejecucion), ArchivoGenerado.nombre == 'pieza.stl'))
        if trabajo is None or trabajo.estado != 'completada' or archivo is None:
            raise HTTPException(409, 'Se necesita un trabajo exitoso con su STL nominal.')
        ruta = Path(archivo.ruta)
        if not ruta.is_file() or ruta.is_symlink() or not ruta.resolve().is_relative_to(Path(DIRECTORIO_ARTEFACTOS).resolve()) or huella_archivo(ruta) != archivo.sha256:
            raise HTTPException(409, 'El STL cambió respecto a su hash registrado.')
        carpeta.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copyfile(ruta, carpeta / 'nominal.stl')
            documento = proponer_desde_copia(carpeta)
            if documento.get('nominal_sha256') != archivo.sha256:
                raise HTTPException(409, 'El plan no corresponde al nominal guardado.')
            plan = conservar_plan(sesion, str(ejecucion), documento)
            sesion.commit(); return datos_plan(plan)
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)


@rutas.post('/api/ejecuciones/{ejecucion}/comparaciones-fisicas', status_code=201)
def crear_comparacion(ejecucion: UUID, solicitud: SolicitudComparacion) -> dict:
    if solicitud.alineacion == 'puntos' and len(solicitud.puntos_pareados) < 3:
        raise HTTPException(422, 'Introduce al menos tres pares XYZ no colineales.')
    if solicitud.calibracion_realizada and not solicitud.fecha_calibracion:
        raise HTTPException(422, 'Registra la fecha de la calibración realizada.')
    if solicitud.fecha_calibracion and solicitud.fecha_escaneo and solicitud.fecha_calibracion > solicitud.fecha_escaneo:
        raise HTTPException(422, 'La calibración debe ser anterior o igual al escaneo.')
    identificador = str(uuid4())
    carpeta = carpeta_comparacion(identificador)
    with crear_sesion() as sesion:
        trabajo = sesion.get(Ejecucion, str(ejecucion))
        if trabajo is None:
            raise HTTPException(404, 'Trabajo no encontrado.')
        if trabajo.estado != 'completada':
            raise HTTPException(409, 'La comparación requiere una generación técnicamente exitosa.')
        archivo = sesion.scalar(select(ArchivoGenerado).where(
            ArchivoGenerado.ejecucion_identificador == str(ejecucion), ArchivoGenerado.nombre == 'pieza.stl'))
        if archivo is None:
            raise HTTPException(409, 'El trabajo no conserva su STL nominal.')
        ruta = Path(archivo.ruta)
        if (not ruta.is_file() or ruta.is_symlink() or
                not ruta.resolve().is_relative_to(Path(DIRECTORIO_ARTEFACTOS).resolve()) or huella_archivo(ruta) != archivo.sha256):
            raise HTTPException(409, 'El STL nominal está ausente o cambió respecto a su hash registrado.')
        carpeta.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copyfile(ruta, carpeta / 'nominal.stl')
            if huella_archivo(carpeta / 'nominal.stl') != archivo.sha256:
                raise HTTPException(409, 'El nominal cambió mientras se copiaba. Vuelve a abrir el trabajo.')
            configuracion = solicitud.model_dump(mode='json')
            if solicitud.perfil_identificador:
                perfil = sesion.get(PerfilMetrologia, str(solicitud.perfil_identificador))
                if perfil is None:
                    raise HTTPException(404, 'Perfil de metrología no encontrado.')
                configuracion = SolicitudComparacion(**{**perfil.configuracion,
                    **solicitud.model_dump(mode='json', exclude_unset=True)}).model_dump(mode='json')
                configuracion['perfil_nombre'] = perfil.nombre
            configuracion['protocolo'] = 'ciel-metrologia-otter-v2'
            if solicitud.medir_cotas_automaticas:
                plan = sesion.get(PlanCotas, str(solicitud.plan_identificador)) if solicitud.plan_identificador else ultimo_plan(sesion, str(ejecucion))
                if plan and (plan.ejecucion_identificador != str(ejecucion) or plan.nominal_sha256 != archivo.sha256):
                    raise HTTPException(409, 'El plan de cotas corresponde a otro nominal. Vuelve a detectar las cotas.')
                if plan is None:
                    documento = proponer_desde_copia(carpeta)
                    if documento.get('nominal_sha256') != archivo.sha256:
                        raise HTTPException(409, 'El plan devuelto no corresponde al STL guardado.')
                    plan = conservar_plan(sesion, str(ejecucion), documento)
                configuracion.update(plan_identificador=plan.identificador, plan_cotas=plan.documento,
                                     plan_cotas_sha256=plan.sha256)
            registro = ComparacionFisica(identificador=identificador, ejecucion_identificador=str(ejecucion),
                nominal_sha256=archivo.sha256, configuracion=configuracion, estado='borrador')
            sesion.add(registro)
            sesion.commit()
            return serializar(registro)
        except Exception:
            shutil.rmtree(carpeta, ignore_errors=True)
            raise


async def recibir(request: Request, destino: Path, limite: int) -> str:
    temporal = destino.with_suffix(destino.suffix + '.' + uuid4().hex + '.tmp')
    total, resumen = 0, hashlib.sha256()
    try:
        with temporal.open('wb') as archivo:
            async for bloque in request.stream():
                total += len(bloque)
                if total > limite:
                    raise HTTPException(413, f'El archivo excede el límite de {limite // (1024 * 1024)} MB.')
                resumen.update(bloque)
                archivo.write(bloque)
        if not total:
            raise HTTPException(422, 'Selecciona un archivo con contenido.')
        temporal.replace(destino)
        return resumen.hexdigest()
    finally:
        temporal.unlink(missing_ok=True)


@rutas.put('/api/comparaciones-fisicas/{identificador}/foto')
async def cargar_foto(identificador: UUID, request: Request) -> dict:
    from PIL import Image, ImageOps
    clave = str(identificador)
    with crear_sesion() as sesion:
        buscar(sesion, clave)
        cambio = sesion.execute(update(ComparacionFisica).where(ComparacionFisica.identificador == clave,
            ComparacionFisica.estado == 'borrador').values(estado='recibiendo_foto'))
        if cambio.rowcount != 1:
            raise HTTPException(409, 'Adjunta la foto antes del escaneo. Para cambiarla, crea otra comparación.')
        sesion.commit()
    carpeta = carpeta_comparacion(clave)
    destino = carpeta / 'foto-original'
    try:
        await recibir(request, destino, 20 * 1024 * 1024)
        with Image.open(destino) as imagen:
            if imagen.format not in {'JPEG', 'PNG', 'WEBP'} or imagen.width * imagen.height > 40_000_000:
                raise ValueError('Formato o tamaño de foto no compatible.')
            foto = ImageOps.exif_transpose(imagen).convert('RGB')
            foto.thumbnail((2000, 2000))
            foto.save(carpeta / 'foto-pieza.png')
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        destino.unlink(missing_ok=True)
        raise HTTPException(422, 'Usa una fotografía PNG, JPG o WebP de hasta 40 megapíxeles.') from error
    finally:
        with crear_sesion() as sesion:
            registro = buscar(sesion, clave)
            registro.estado = 'borrador'
            sesion.commit()
    return {'estado': 'foto_guardada', 'sha256': huella_archivo(destino)}


@rutas.put('/api/comparaciones-fisicas/{identificador}/escaneo', status_code=202)
async def cargar_escaneo(identificador: UUID, request: Request, nombre: str) -> dict:
    clave = str(identificador)
    nombre = nombre.replace('\\', '/').split('/')[-1][:200]
    extension = Path(nombre).suffix.lower()
    if extension not in FORMATOS:
        raise HTTPException(422, 'Selecciona STL, OBJ, PLY, PCD, ASC o XYZ; exporta el proyecto desde CrealityScan.')
    with crear_sesion() as sesion:
        registro = buscar(sesion, clave)
        cambio = sesion.execute(update(ComparacionFisica).where(ComparacionFisica.identificador == clave,
            ComparacionFisica.estado == 'borrador').values(estado='recibiendo'))
        if cambio.rowcount != 1:
            raise HTTPException(409, 'El escaneo ya se recibió. Crea otra comparación para otro archivo.')
        sesion.commit()
    carpeta = carpeta_comparacion(clave)
    try:
        resumen = await recibir(request, carpeta / ('escaneo' + extension), MAXIMO_ESCANEO)
        with crear_sesion() as sesion:
            registro = buscar(sesion, clave)
            registro.escaneo_sha256, registro.nombre_escaneo = resumen, nombre
            registro.configuracion = {**registro.configuracion, 'extension': extension,
                'escaneo_sha256': resumen, 'nominal_sha256': registro.nominal_sha256, 'protocolo': registro.configuracion.get('protocolo', 'ciel-metrologia-otter-v1')}
            (carpeta / 'configuracion.json').write_text(json.dumps(registro.configuracion, ensure_ascii=False, indent=2), encoding='utf-8')
            registro.estado = 'pendiente'
            sesion.commit()
        EJECUTOR.submit(procesar_comparacion, clave)
    except BaseException:
        with crear_sesion() as sesion:
            registro = buscar(sesion, clave)
            if registro.estado == 'recibiendo':
                registro.estado = 'borrador'
                sesion.commit()
        raise
    return {'identificador': clave, 'estado': 'pendiente'}


def procesar_comparacion(identificador: str) -> None:
    with crear_sesion() as sesion:
        registro = buscar(sesion, identificador)
        if registro.estado != 'pendiente':
            return
        registro.estado, registro.diagnostico = 'procesando', 'Alineando el escaneo y calculando distancias de superficie.'
        sesion.commit()
    try:
        with httpx.Client(timeout=900, trust_env=False) as cliente:
            respuesta = cliente.post(os.environ.get('URL_METROLOGIA', 'http://127.0.0.1:8023') + '/comparar',
                                     json={'comparacion_identificador': identificador})
            if respuesta.status_code != 200:
                try:
                    detalle = respuesta.json().get('detail', 'No se pudo procesar el escaneo.')
                except ValueError:
                    detalle = 'El servicio no pudo procesar el archivo. Exporta de nuevo desde CrealityScan o reduce la malla.'
                raise ValueError(str(detalle))
            datos = respuesta.json()
            if datos.get('protocolo') != registro.configuracion.get('protocolo', 'ciel-metrologia-otter-v1') or 'hausdorff_maximo_mm' not in datos:
                raise ValueError('El servicio devolvió una respuesta metrológica incompleta.')
        with crear_sesion() as sesion:
            registro = buscar(sesion, identificador)
            registro.resultado, registro.estado = datos, 'completada'
            registro.diagnostico = 'Revisa la superposición y confirma la alineación.'
            registro.fecha_fin = fecha_actual()
            sesion.commit()
        sincronizar_medicion(registro.ejecucion_identificador)
    except Exception as error:
        REGISTRO.exception('Falló la comparación física %s', identificador)
        with crear_sesion() as sesion:
            registro = buscar(sesion, identificador)
            registro.estado = 'fallida'
            registro.diagnostico = str(error)[:1500] if isinstance(error, ValueError) else 'El servicio de metrología no respondió. Reinicia la aplicación y pulsa Reintentar.'
            registro.fecha_fin = fecha_actual()
            sesion.commit()


def sincronizar_medicion(ejecucion: str) -> None:
    if not MODO_NATIVO:
        return
    try:
        with crear_sesion() as sesion:
            trabajo = sesion.get(Ejecucion, ejecucion)
            campana = trabajo.campana_identificador if trabajo else None
        if campana:
            from aplicacion.archivado import guardar_resumen
            guardar_resumen(campana, copia_sqlite=True)
    except Exception:
        REGISTRO.exception('La medición se conserva, pero no se actualizó la copia de la campaña')


def recuperar_interrumpidas() -> None:
    with crear_sesion() as sesion:
        sesion.execute(update(ComparacionFisica).where(ComparacionFisica.estado.in_(
            ['pendiente', 'recibiendo', 'recibiendo_foto', 'procesando'])).values(estado='fallida',
            diagnostico='La aplicación se cerró durante la comparación. El archivo recibido se conserva; pulsa Reintentar o vuelve a cargarlo.'))
        sesion.commit()


@rutas.post('/api/comparaciones-fisicas/{identificador}/reintentar', status_code=202)
def reintentar(identificador: UUID) -> dict:
    clave = str(identificador)
    with crear_sesion() as sesion:
        registro = buscar(sesion, clave)
        if registro.estado != 'fallida' or not registro.escaneo_sha256:
            raise HTTPException(409, 'Crea otra comparación y vuelve a seleccionar el archivo del escáner.')
        registro.estado, registro.diagnostico = 'pendiente', ''
        sesion.commit()
    EJECUTOR.submit(procesar_comparacion, clave)
    return {'estado': 'pendiente'}


@rutas.post('/api/comparaciones-fisicas/{identificador}/confirmar')
def confirmar(identificador: UUID) -> dict:
    with crear_sesion() as sesion:
        registro = buscar(sesion, str(identificador))
        if registro.estado != 'completada':
            raise HTTPException(409, 'Espera a que termine el cálculo antes de confirmar.')
        registro.alineacion_confirmada = True
        registro.diagnostico = 'Alineación revisada y confirmada. Consulta los entregables de la medición.'
        sesion.commit()
        (carpeta_comparacion(str(identificador)) / 'revision.json').write_text(json.dumps({
            'alineacion_confirmada': True, 'fecha': fecha_actual().isoformat()}), encoding='utf-8')
        respuesta = serializar(registro)
    sincronizar_medicion(registro.ejecucion_identificador)
    return respuesta


@rutas.get('/api/comparaciones-fisicas/{identificador}/archivos/{nombre}')
def descargar_archivo(identificador: UUID, nombre: str) -> FileResponse:
    with crear_sesion() as sesion:
        buscar(sesion, str(identificador))
    carpeta = carpeta_comparacion(str(identificador))
    ruta = carpeta / nombre
    if Path(nombre).name != nombre or ruta.is_symlink() or not ruta.is_file() or ruta.suffix == '.tmp':
        raise HTTPException(404, 'Archivo no encontrado.')
    return FileResponse(ruta, filename=nombre)


@rutas.get('/api/comparaciones-fisicas/{identificador}/entregables.zip')
def descargar_comparacion(identificador: UUID):
    from aplicacion.informe_fisico import crear_zip, respuesta_zip
    with crear_sesion() as sesion:
        registro = buscar(sesion, str(identificador))
        return respuesta_zip(crear_zip([serializar(registro)]), 'comparacion-' + str(identificador) + '.zip')


@rutas.get('/api/campanas/{identificador}/metrologia')
def consultar_campana(identificador: UUID) -> list[dict]:
    with crear_sesion() as sesion:
        if sesion.get(Campana, str(identificador)) is None:
            raise HTTPException(404, 'Campaña no encontrada.')
        return [serializar(r) for r in sesion.scalars(select(ComparacionFisica).join(Ejecucion).where(
            Ejecucion.campana_identificador == str(identificador)).order_by(ComparacionFisica.fecha_creacion))]


@rutas.get('/api/campanas/{identificador}/entregables-fisicos.zip')
def descargar_campana(identificador: UUID):
    from aplicacion.informe_fisico import crear_zip, respuesta_zip
    return respuesta_zip(crear_zip(consultar_campana(identificador)), 'metrologia-' + str(identificador) + '.zip')


@rutas.get('/api/campanas/{identificador}/manufacturabilidad.csv')
def descargar_manufacturabilidad(identificador: UUID) -> Response:
    from aplicacion.metricas import calcular_metricas_campana
    from aplicacion.resultados import convertir_csv, filas_manufacturabilidad
    try:
        filas = filas_manufacturabilidad(calcular_metricas_campana(str(identificador)))
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return Response(convertir_csv(filas, list(filas[0]) if filas else ['modelo']), media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="manufacturabilidad.csv"'})


@rutas.post('/api/campanas/{identificador}/actualizar-entregables')
def actualizar_entregables(identificador: UUID) -> dict:
    from aplicacion.archivado import guardar_resumen, guardar_ejecucion
    with crear_sesion() as sesion:
        if sesion.get(Campana, str(identificador)) is None:
            raise HTTPException(404, 'Campaña no encontrada.')
        ids = list(sesion.scalars(select(Ejecucion.identificador).where(Ejecucion.campana_identificador == str(identificador))))
    try:
        for clave in ids:
            guardar_ejecucion(clave)
        guardar_resumen(str(identificador), figuras=True)
    except (OSError, ValueError) as error:
        raise HTTPException(503, 'No se pudieron actualizar los archivos. Cierra los CSV abiertos en Excel y vuelve a intentarlo.') from error
    return {'estado': 'archivos_actualizados', 'campana': str(identificador)}
