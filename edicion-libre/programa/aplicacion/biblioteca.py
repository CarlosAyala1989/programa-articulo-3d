"""Biblioteca y exportación legible, sin modificar los artefactos históricos."""
import base64
import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from starlette.background import BackgroundTask

from aplicacion.base_datos import ArchivoGenerado, Campana, CasoDiseno, ComparacionDigital, ComparacionFisica, Ejecucion, InformeTopologia, VersionConjunto, crear_sesion
from aplicacion.configuracion import DIRECTORIO_ARTEFACTOS, URL_EVALUADOR

rutas = APIRouter()


def solicitud_variante(contexto: dict) -> str:
    return ("Modifica el programa CAD siguiente. Conserva los rasgos no afectados por el cambio. "
            "Entrega un programa completo, en milímetros, que asigne resultado.\n"
            f"Descripción de origen:\n{contexto['descripcion']}\n"
            f"Cambios solicitados:\n{contexto['modificacion']}\n"
            f"Programa de origen completo:\n```python\n{contexto['codigo']}\n```\n")


def intento_reutilizable(ejecucion, intento) -> bool:
    if not intento.codigo or intento.cad_valido is False or intento.exportacion_valida is False:
        return False
    if intento.cad_valido and intento.exportacion_valida:
        return True
    # En bases anteriores las banderas pueden faltar: exigir evidencia histórica.
    if intento.estado != 'correcto':
        return False
    if ejecucion.primer_exito_exportacion == intento.numero:
        return True
    archivos = {a.nombre for a in ejecucion.archivos if a.intento_identificador == intento.identificador}
    if not archivos and intento == ejecucion.intentos[-1]:
        archivos = {a.nombre for a in ejecucion.archivos if a.intento_identificador is None}
    return {'pieza.step', 'pieza.stl'}.issubset(archivos)


def estado_legible(ejecucion) -> str:
    if ejecucion.primer_exito_exportacion or any(intento_reutilizable(ejecucion, i) for i in ejecucion.intentos):
        return 'EXITO-TECNICO'
    return {'fallida': 'FALLIDA', 'bloqueada': 'BLOQUEADA', 'pendiente': 'PENDIENTE',
            'generando': 'EN-CURSO'}.get(ejecucion.estado, 'SIN-DETERMINAR')


def resumen(sesion, ejecucion) -> dict:
    caso = sesion.get(CasoDiseno, ejecucion.caso_identificador) if ejecucion.caso_identificador else None
    conjunto = sesion.get(VersionConjunto, caso.conjunto_identificador) if caso else None
    codigo = caso.codigo if caso else ('SIN-CODIGO' if ejecucion.caso_identificador else 'LIBRE-' + ejecucion.identificador[:8])
    miniatura = next((a for a in ejecucion.archivos if a.nombre == 'vista-miniatura.png'), None)
    return {'identificador': ejecucion.identificador, 'codigo_prompt': codigo,
            'conjunto': {'nombre': conjunto.nombre, 'version': conjunto.version} if conjunto else None,
            'descripcion': ejecucion.descripcion, 'motor': ejecucion.motor, 'modelo': ejecucion.modelo,
            'modo': ejecucion.modo, 'estado': ejecucion.estado, 'resultado': estado_legible(ejecucion),
            'fecha_creacion': ejecucion.fecha_creacion, 'campana_identificador': ejecucion.campana_identificador,
            'origen_identificador': ejecucion.origen_identificador,
            'miniatura': f'/api/ejecuciones/{ejecucion.identificador}/archivos/{miniatura.nombre}' if miniatura else None}


def nombre_carpeta(datos: dict, longitud: int = 8) -> str:
    def limpiar(valor):
        return re.sub(r'[^A-Za-z0-9_-]', '-', str(valor))[:40].strip('-') or 'SIN-CODIGO'
    libreria = {'cadquery': 'CadQuery', 'build123d': 'build123d', 'freecad': 'FreeCAD'}.get(datos['motor'], datos['motor'])
    return '__'.join([limpiar(datos['codigo_prompt']), *(['VARIANTE'] if datos.get('origen_identificador') else []),
                     limpiar(libreria), datos['resultado'], limpiar(datos['modo']), datos['identificador'][:longitud]])


@rutas.get('/api/ejecuciones')
def historial(busqueda: str = '', motor: str = '', modelo: str = '', estado: str = '',
              campana: str = '', desplazamiento: int = Query(0, ge=0)) -> dict:
    with crear_sesion() as sesion:
        consulta = select(Ejecucion).outerjoin(CasoDiseno, Ejecucion.caso_identificador == CasoDiseno.identificador)
        if busqueda:
            consulta = consulta.where(or_(Ejecucion.descripcion.contains(busqueda, autoescape=True),
                Ejecucion.identificador.contains(busqueda, autoescape=True), CasoDiseno.codigo.contains(busqueda, autoescape=True)))
        for columna, valor in ((Ejecucion.motor, motor), (Ejecucion.modelo, modelo),
                               (Ejecucion.estado, estado), (Ejecucion.campana_identificador, campana)):
            if valor:
                consulta = consulta.where(columna == valor)
        total = sesion.scalar(select(func.count()).select_from(consulta.subquery()))
        filas = sesion.scalars(consulta.order_by(Ejecucion.fecha_creacion.desc(), Ejecucion.identificador)
                              .offset(desplazamiento).limit(24))
        return {'total': total, 'ejecuciones': [resumen(sesion, e) for e in filas]}


class SolicitudVariante(BaseModel):
    model_config = ConfigDict(extra='forbid')
    intento_identificador: int
    modificacion: str = Field(min_length=1, max_length=4000)
    modelo: str
    modo: str = Field(default='closed-loop', pattern=r'^(open-loop|closed-loop)$')


@rutas.post('/api/ejecuciones/{identificador}/variantes', status_code=202)
def crear_variante(identificador: str, solicitud: SolicitudVariante) -> dict:
    from aplicacion.proveedores import modelos_configurados
    from aplicacion.configuracion import MODO_NATIVO
    if MODO_NATIVO:
        from aplicacion.tareas_nativas import tarea_generacion
    else:
        from aplicacion.tareas import tarea_generacion
    if solicitud.modelo not in modelos_configurados():
        raise HTTPException(422, 'Modelo de IA no disponible')
    if not solicitud.modificacion.strip():
        raise HTTPException(422, 'Escribe la modificación')
    nuevo = str(uuid4())
    with crear_sesion() as sesion:
        origen = sesion.get(Ejecucion, identificador)
        if origen is None:
            raise HTTPException(404, 'Trabajo de origen no encontrado')
        intento = next((i for i in origen.intentos if i.identificador == solicitud.intento_identificador), None)
        if not intento or not intento_reutilizable(origen, intento):
            raise HTTPException(409, 'Selecciona un intento con código y CAD exportado válidos')
        contexto = {'version': 'ciel-variantes-v1', 'intento_identificador': intento.identificador,
                    'descripcion': origen.descripcion, 'codigo': intento.codigo,
                    'codigo_sha256': hashlib.sha256(intento.codigo.encode()).hexdigest(),
                    'modificacion': solicitud.modificacion.strip()}
        sesion.add(Ejecucion(identificador=nuevo, descripcion=origen.descripcion,
            origen_identificador=identificador, contexto_variante=contexto,
            caso_identificador=origen.caso_identificador, motor=origen.motor, modelo=solicitud.modelo,
            modo=solicitud.modo, maximo_intentos=1 if solicitud.modo == 'open-loop' else 5,
            estado='pendiente', mensaje='Variante en cola'))
        sesion.commit()
    try:
        tarea_generacion.delay(nuevo)
    except Exception as error:
        with crear_sesion() as sesion:
            ejecucion = sesion.get(Ejecucion, nuevo)
            ejecucion.estado, ejecucion.mensaje = 'bloqueada', 'No fue posible programar la variante'
            sesion.commit()
        raise HTTPException(503, 'La cola no está disponible') from error
    return {'identificador': nuevo, 'estado': 'pendiente'}


def generar_vistas(identificador: str) -> None:
    with crear_sesion() as sesion:
        ejecucion = sesion.get(Ejecucion, identificador)
        if ejecucion is None:
            raise HTTPException(404, 'Ejecución no encontrada')
        archivo = next((a for a in ejecucion.archivos if a.nombre == 'pieza.stl'), None)
        if not archivo or not Path(archivo.ruta).is_file():
            raise HTTPException(409, 'No se conserva el STL necesario para generar vistas')
        intento_id = archivo.intento_identificador
        contenido = base64.b64encode(Path(archivo.ruta).read_bytes()).decode('ascii')
    with httpx.Client(timeout=180) as cliente:
        respuesta = cliente.post(f'{URL_EVALUADOR}/vistas-biblioteca', json={'archivos': {'pieza.stl': contenido}})
        respuesta.raise_for_status()
        datos = respuesta.json()
    carpeta = Path(DIRECTORIO_ARTEFACTOS) / 'ejecuciones' / identificador
    carpeta.mkdir(parents=True, exist_ok=True)
    permitidos = {f'vista-{n}.png' for n in ('frontal', 'posterior', 'izquierda', 'derecha', 'superior', 'inferior', 'isometrica', 'lamina', 'miniatura')}
    archivos = {n: base64.b64decode(c, validate=True) for n, c in datos['archivos'].items() if n in permitidos}
    archivos['vistas-perfil.json'] = json.dumps(datos['perfil'], ensure_ascii=False, indent=2).encode()
    with crear_sesion() as sesion:
        for nombre, bruto in archivos.items():
            ruta = carpeta / nombre
            temporal = ruta.with_suffix(ruta.suffix + '.tmp')
            temporal.write_bytes(bruto)
            temporal.replace(ruta)
            archivo = sesion.scalar(select(ArchivoGenerado).where(ArchivoGenerado.ejecucion_identificador == identificador,
                                                                 ArchivoGenerado.nombre == nombre))
            if archivo is None:
                archivo = ArchivoGenerado(ejecucion_identificador=identificador, nombre=nombre)
                sesion.add(archivo)
            archivo.ruta, archivo.tamano_bytes, archivo.sha256 = str(ruta), len(bruto), hashlib.sha256(bruto).hexdigest()
            archivo.rol, archivo.intento_identificador = 'vistas-biblioteca-v1', intento_id
        sesion.commit()


@rutas.post('/api/ejecuciones/{identificador}/vistas')
def crear_vistas(identificador: str) -> dict:
    try:
        generar_vistas(identificador)
    except (httpx.HTTPError, ValueError, OSError, KeyError) as error:
        raise HTTPException(503, 'No se pudieron generar las vistas. El CAD se conserva; puedes reintentar.') from error
    return {'estado': 'vistas_disponibles'}


def crear_paquete(identificadores: list[str], destino: Path) -> str:
    indice, huellas, ausentes, usados = [], [], [], set()
    with crear_sesion() as sesion, zipfile.ZipFile(destino, 'w', zipfile.ZIP_DEFLATED) as paquete:
        def agregar(nombre, contenido):
            bruto = contenido.encode('utf-8') if isinstance(contenido, str) else contenido
            paquete.writestr(nombre, bruto)
            huellas.append({'archivo': nombre, 'sha256': hashlib.sha256(bruto).hexdigest()})
        for identificador in identificadores:
            e = sesion.get(Ejecucion, identificador)
            if e is None:
                raise HTTPException(404, 'Ejecución no encontrada')
            datos = resumen(sesion, e)
            longitud = 8
            carpeta = nombre_carpeta(datos, longitud)
            while carpeta in usados and longitud < 36:
                longitud += 4
                carpeta = nombre_carpeta(datos, longitud)
            usados.add(carpeta)
            indice.append({**{k: v for k, v in datos.items() if k not in {'miniatura', 'conjunto'}}, 'carpeta': carpeta})
            contexto = e.contexto_variante or {}
            datos.update({'intentos': e.numero_intentos, 'modificacion': contexto.get('modificacion'),
                          'intento_origen': contexto.get('intento_identificador'),
                          'codigo_origen_sha256': contexto.get('codigo_sha256'),
                          'calidad': (e.configuracion_calidad or {}).get('quality_success', 'No registrado')})
            agregar(carpeta + '/resumen.json', json.dumps(datos, ensure_ascii=False, default=str, indent=2))
            def registro_publico(registro):
                return metadatos_publicos({c.name: getattr(registro, c.name) for c in registro.__table__.columns})
            metricas = {
                'topologia': [registro_publico(t) for t in sesion.scalars(select(InformeTopologia).where(
                    InformeTopologia.ejecucion_identificador == identificador))],
                'comparacion_digital': [registro_publico(c) for c in sesion.scalars(select(ComparacionDigital).where(
                    ComparacionDigital.ejecucion_identificador == identificador))],
                'calidad': metadatos_publicos(e.configuracion_calidad),
                'primer_exito_ejecucion': e.primer_exito_ejecucion,
                'primer_exito_cad': e.primer_exito_cad,
                'primer_exito_exportacion': e.primer_exito_exportacion,
            }
            agregar(carpeta + '/metricas.json', json.dumps(metricas, ensure_ascii=False, default=str, indent=2))
            agregar(carpeta + '/prompt.txt', e.descripcion)
            if contexto:
                agregar(carpeta + '/modificacion.txt', contexto['modificacion'])
                agregar(carpeta + '/codigo-origen.py', contexto['codigo'])
            lineas = [f'{k}: {v if v is not None else "No registrado"}' for k, v in datos.items() if k != 'miniatura']
            lineas += ['', 'EXITO-TECNICO significa CAD exportado; la fidelidad de la modificación requiere revisión.',
                       'Los fallos previos se conservan en intentos/. Los datos ausentes no se reconstruyen.']
            filas = []
            for i in e.intentos:
                estado = 'EXITO-TECNICO' if intento_reutilizable(e, i) else ('EN-CURSO' if i.estado == 'consultando_ia' else 'FALLIDO')
                prefijo = f'{carpeta}/intentos/intento-{i.numero:02d}__{estado}/'
                agregar(prefijo + 'codigo.py', i.codigo or '')
                agregar(prefijo + 'respuesta.txt', i.respuesta_modelo or '')
                agregar(prefijo + 'solicitud.json', json.dumps(metadatos_publicos(i.solicitud_modelo or {}), ensure_ascii=False, default=str, indent=2))
                fila = {'numero': i.numero, 'estado': i.estado, 'resultado': estado, 'diagnostico': i.diagnostico,
                        'runtime': i.runtime_identificador or 'No registrado', 'modelo': i.modelo_informado,
                        'tokens_entrada': i.tokens_entrada, 'tokens_salida': i.tokens_salida,
                        'duracion_segundos': i.duracion_segundos}
                filas.append(fila)
                agregar(prefijo + 'diagnostico.json', json.dumps(fila, ensure_ascii=False, indent=2))
                lineas.append(f"Intento {i.numero}: {estado}; runtime: {i.runtime_identificador or 'No registrado'}; {i.diagnostico}")
            agregar(carpeta + '/intentos.csv', texto_csv(filas))
            agregar(carpeta + '/LEEME.txt', '\n'.join(lineas))
            archivos = []
            for a in e.archivos:
                ruta = Path(a.ruta)
                # Solo se leen artefactos registrados dentro de la raíz local.
                if (Path(a.nombre).name != a.nombre or ruta.is_symlink() or not ruta.resolve().is_relative_to(Path(DIRECTORIO_ARTEFACTOS).resolve())
                        or not ruta.is_file()):
                    ausentes.append({'ejecucion': identificador, 'archivo': a.nombre, 'estado': 'ausente'})
                    continue
                bruto = ruta.read_bytes()
                if hashlib.sha256(bruto).hexdigest() != a.sha256:
                    ausentes.append({'ejecucion': identificador, 'archivo': a.nombre, 'estado': 'hash_distinto'})
                    continue
                sub = 'imagenes' if a.rol == 'vistas-biblioteca-v1' else 'modelo'
                agregar(f'{carpeta}/{sub}/{a.nombre}', bruto)
                archivos.append({'nombre': a.nombre, 'intento_identificador': a.intento_identificador, 'sha256': a.sha256})
            agregar(carpeta + '/archivos.json', json.dumps(archivos, ensure_ascii=False, indent=2))
            from aplicacion.metrologia import serializar as serializar_fisica
            from aplicacion.informe_fisico import crear_zip
            fisicas = [serializar_fisica(r) for r in sesion.scalars(select(ComparacionFisica).where(
                ComparacionFisica.ejecucion_identificador == identificador))]
            if fisicas:
                ruta_fisica = crear_zip(fisicas)
                try:
                    destino_fisico = carpeta + '/comparaciones-fisicas.zip'
                    paquete.write(ruta_fisica, destino_fisico)
                    from aplicacion.metrologia import huella_archivo
                    huellas.append({'archivo': destino_fisico, 'sha256': huella_archivo(ruta_fisica)})
                finally:
                    ruta_fisica.unlink(missing_ok=True)
        agregar('indice.csv', texto_csv(indice))
        manifiesto = {'version': 'ciel-exportacion-legible-v1', 'archivos': huellas, 'archivos_ausentes': ausentes}
        paquete.writestr('manifiesto.json', json.dumps(manifiesto, ensure_ascii=False, indent=2))
    return next(iter(usados)) if len(usados) == 1 else 'campana-legible'


def metadatos_publicos(valor):
    if isinstance(valor, dict):
        return {k: metadatos_publicos(v) for k, v in valor.items()
                if not any(p in k.lower() for p in ('api_key', 'authorization', 'password', 'secret'))
                and not k.lower().startswith(('ruta', 'directorio'))}
    if isinstance(valor, list):
        return [metadatos_publicos(v) for v in valor]
    if isinstance(valor, str):
        valor = valor.replace(str(Path(DIRECTORIO_ARTEFACTOS)), '<artefactos>')
        valor = re.sub(r'[A-Za-z]:[\\/]Users[\\/][^\s"<>]+', '<ruta-local>', valor)
        valor = re.sub(r'/(?:home|Users)/[^\s"<>]+', '<ruta-local>', valor)
    return valor


def texto_csv(filas: list[dict]) -> str:
    salida = io.StringIO(newline='')
    escritor = csv.DictWriter(salida, fieldnames=list(filas[0]) if filas else ['numero'])
    escritor.writeheader()
    escritor.writerows(filas)
    return '\ufeff' + salida.getvalue()


def descargar_paquete(ids: list[str]) -> FileResponse:
    import os
    descriptor, nombre = tempfile.mkstemp(suffix='.zip')
    os.close(descriptor)
    ruta = Path(nombre)
    try:
        titulo = crear_paquete(ids, ruta)
    except Exception:
        ruta.unlink(missing_ok=True)
        raise
    return FileResponse(ruta, media_type='application/zip', filename=titulo + '.zip',
                        background=BackgroundTask(ruta.unlink, missing_ok=True))


@rutas.get('/api/ejecuciones/{identificador}/exportacion-legible')
def exportar_trabajo(identificador: str):
    return descargar_paquete([identificador])


@rutas.get('/api/campanas/{identificador}/exportacion-legible')
def exportar_campana(identificador: str):
    with crear_sesion() as sesion:
        if sesion.get(Campana, identificador) is None:
            raise HTTPException(404, 'Campaña no encontrada')
        ids = list(sesion.scalars(select(Ejecucion.identificador).where(Ejecucion.campana_identificador == identificador)
                                 .order_by(Ejecucion.orden_campana)))
    return descargar_paquete(ids)
