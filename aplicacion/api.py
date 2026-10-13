"""API del estudio digital: casos, ejecuciones, campañas y resultados."""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from aplicacion.base_datos import (
    ArchivoGenerado, Campana, CasoDiseno, ComparacionDigital, Ejecucion,
    InformeCalidad, InformeTopologia, VersionConjunto, crear_sesion, crear_tablas,
)
from aplicacion.campanas import cambiar_estado, crear_campana, previsualizar, resumen_campana, validar_matriz
from aplicacion.configuracion import (
    DIRECTORIO_ARTEFACTOS, MODELOS_DISPONIBLES, MODELOS_LOCALES, MOTORES_DISPONIBLES, URL_EVALUADOR,
    ESFUERZOS_DISPONIBLES, ESFUERZO_PREDETERMINADO, resolver_esfuerzo,
    MAXIMO_ITERACIONES_QUALITY_LOOP, MAXIMO_LLAMADAS_QUALITY_LOOP,
    MAXIMO_TOKENS_QUALITY_LOOP, MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR,
    NVIDIA_MODEL_GENERATOR,
)
from aplicacion.conjuntos import (
    cargar_conjunto_principal, importar_csv, importar_documento, resumen_conjunto,
    validar_documento,
)
from aplicacion.metricas import calcular_metricas_campana
from aplicacion.proveedores import modelos_configurados, verificar_modelo_local
from aplicacion.calidad.nvidia import ErrorNvidia, ProveedorNvidia, catalogo_roles
from aplicacion.proveedor_deepseek import ErrorProveedor
from aplicacion.proveedor_suscripcion import catalogos_cli, estado_puente, modelos_cli_configurados
from aplicacion.cli_suscripcion import proveedor_cli
from aplicacion.calidad.suscripcion import validar_revisores
from aplicacion.tareas import tarea_analisis, tarea_campana, tarea_generacion


aplicacion = FastAPI(title="Agente Ciel · Estudio CAD digital", version="0.2.0")
DIRECTORIO_WEB = Path(__file__).resolve().parent / "estaticos"
if (DIRECTORIO_WEB / "assets").exists():
    aplicacion.mount("/assets", StaticFiles(directory=DIRECTORIO_WEB / "assets"), name="assets")


class SolicitudGeneracion(BaseModel):
    descripcion: str | None = Field(default=None, max_length=4000)
    caso_identificador: str | None = None
    motor: str
    modelo: str
    esfuerzo_razonamiento: Literal["low", "high", "max"] | None = None
    modo: Literal["open-loop", "closed-loop", "quality-loop"] = "closed-loop"
    best_of_n: bool = False
    proveedor_revisores: str = Field(default="nvidia", min_length=1, max_length=60)


class SolicitudImportacion(BaseModel):
    documento: dict | None = None
    csv: str | None = None
    nombre: str | None = None
    version: str | None = None
    finalidad: str | None = None


class SolicitudCampana(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    conjunto_identificador: str
    modelos: list[str]
    esfuerzo_razonamiento: Literal["low", "high", "max"] | None = None
    motores: list[str]
    modos: list[str]
    repeticiones: int = Field(default=1, ge=1, le=5)
    semilla: int = 20261004
    tipo: str = "piloto"
    codigos_caso: list[str] | None = None
    presupuesto_usd: float | None = Field(default=None, gt=0)


class SolicitudPresupuesto(BaseModel):
    presupuesto_usd: float = Field(gt=0)


@aplicacion.on_event("startup")
def preparar_base_datos() -> None:
    crear_tablas()
    cargar_conjunto_principal()


@aplicacion.get("/api/salud")
def consultar_salud() -> dict:
    return {"estado": "disponible"}


@aplicacion.get("/api/opciones")
def consultar_opciones() -> dict:
    nvidia_configurada = bool(os.environ.get("NVIDIA_API_KEY", "").strip())
    suscripciones = modelos_cli_configurados()
    catalogos = catalogos_cli()
    revisores = {"nvidia": "NVIDIA · API"} if nvidia_configurada else {}
    for clave, nombre in suscripciones.items():
        origen = proveedor_cli(clave)
        if origen == "antigravity-cli" and nvidia_configurada:
            revisores[clave] = nombre + " · texto; NVIDIA · imágenes"
        elif origen == "codex-cli":
            detalle = catalogos.get(origen, {}).get("modelos", {}).get(clave, {})
            if "::" not in clave or "image" in detalle.get("modalidades", []):
                revisores[clave] = nombre + " · todos los roles"
    return {
        "motores": MOTORES_DISPONIBLES, "modelos": modelos_configurados(),
        "modelos_locales_catalogo": MODELOS_LOCALES,
        "esfuerzos_por_modelo": {modelo: ESFUERZOS_DISPONIBLES for modelo in MODELOS_DISPONIBLES},
        "esfuerzo_predeterminado": ESFUERZO_PREDETERMINADO,
        "modos": {"open-loop": "Una generación", "closed-loop": "Hasta cinco reparaciones",
                  "quality-loop": "Plan geométrico, métricas y hasta tres ciclos"},
        "intentos_maximos": 5,
        "suscripciones": {"configurados": suscripciones, "catalogos": catalogos,
            "estado_puente": estado_puente()},
        "quality_loop": {"disponible": nvidia_configurada or "codex-cli" in modelos_cli_configurados(),
            "proveedores_revisores": revisores,
            "maximo_iteraciones": MAXIMO_ITERACIONES_QUALITY_LOOP,
            "maximo_llamadas_ia": MAXIMO_LLAMADAS_QUALITY_LOOP,
            "maximo_tokens_estimados": MAXIMO_TOKENS_QUALITY_LOOP,
            "maximo_tokens_salida_generador": MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR,
            "candidatos_best_of_n": 3,
            "modelo_nvidia_generador": NVIDIA_MODEL_GENERATOR,
            "roles": catalogo_roles(),
            "referencia_habilitada": os.environ.get("QUALITY_ALLOW_REFERENCE_METRICS", "0") == "1"},
    }


@aplicacion.get("/api/proveedores/nvidia/catalogo")
def consultar_catalogo_nvidia() -> dict:
    try:
        modelos = ProveedorNvidia().listar_modelos()
    except ErrorNvidia as error:
        raise HTTPException(503, str(error)) from None
    return {"proveedor": "nvidia_nim", "modelos": modelos,
            "roles_configurados": catalogo_roles()}


@aplicacion.get("/api/modelos-locales/estado")
def estado_modelos_locales() -> dict:
    estados = {}
    for codigo in MODELOS_LOCALES:
        try:
            estados[codigo] = {"estado": "disponible", **verificar_modelo_local(codigo)}
        except ErrorProveedor as error:
            estados[codigo] = {"estado": "no_disponible", "diagnostico": str(error)}
    return estados


@aplicacion.get("/api/conjuntos")
def listar_conjuntos() -> list[dict]:
    with crear_sesion() as sesion:
        conjuntos = list(sesion.scalars(select(VersionConjunto).order_by(VersionConjunto.fecha_creacion)))
    return [resumen_conjunto(conjunto) for conjunto in conjuntos]


@aplicacion.get("/api/conjuntos/{identificador}")
def consultar_conjunto(identificador: str) -> dict:
    with crear_sesion() as sesion:
        conjunto = sesion.get(VersionConjunto, identificador)
        if conjunto is None:
            raise HTTPException(404, "Conjunto no encontrado")
        casos = list(sesion.scalars(select(CasoDiseno).where(
            CasoDiseno.conjunto_identificador == identificador
        ).order_by(CasoDiseno.codigo)))
        return {
            **resumen_conjunto(conjunto),
            "casos": [{
                "identificador": caso.identificador, "codigo": caso.codigo,
                "nivel": caso.nivel, "familia": caso.familia,
                "fundamento": caso.fundamento, "descripcion": caso.descripcion,
                "especificacion": caso.especificacion,
                "referencia_sha256": caso.referencia_sha256,
                "procedencia_referencia": caso.procedencia_referencia,
            } for caso in casos],
        }


@aplicacion.post("/api/conjuntos", status_code=201)
def crear_conjunto(solicitud: SolicitudImportacion) -> dict:
    try:
        if solicitud.documento is not None:
            conjunto = importar_documento(solicitud.documento)
        elif solicitud.csv is not None:
            conjunto = importar_csv(
                solicitud.csv, solicitud.nombre or "", solicitud.version or "",
                solicitud.finalidad or "",
            )
        else:
            raise ValueError("Proporcione documento JSON o CSV")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return resumen_conjunto(conjunto)


@aplicacion.post("/api/conjuntos/{identificador}/congelar")
def congelar_conjunto(identificador: str) -> dict:
    from aplicacion.base_datos import fecha_actual

    with crear_sesion() as sesion:
        conjunto = sesion.get(VersionConjunto, identificador)
        if conjunto is None:
            raise HTTPException(404, "Conjunto no encontrado")
        if conjunto.estado == "congelado":
            return resumen_conjunto(conjunto)
        casos = list(sesion.scalars(select(CasoDiseno).where(CasoDiseno.conjunto_identificador == identificador)))
        documento = {"nombre": conjunto.nombre, "version": conjunto.version,
                     "finalidad": conjunto.finalidad,
                     "casos": [{"codigo": c.codigo, "nivel": c.nivel, "familia": c.familia,
                                "fundamento": c.fundamento, "descripcion": c.descripcion,
                                "especificacion": c.especificacion} for c in casos]}
        validar_documento(documento)
        conjunto.estado = "congelado"
        conjunto.fecha_congelacion = fecha_actual()
        sesion.commit()
        return resumen_conjunto(conjunto)


@aplicacion.get("/api/conjuntos/{identificador}/exportar.json")
def exportar_conjunto(identificador: str) -> Response:
    datos = consultar_conjunto(identificador)
    documento = {clave: datos[clave] for clave in ("nombre", "version", "finalidad", "casos")}
    return Response(
        json.dumps(documento, ensure_ascii=False, indent=2), media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="conjunto-{identificador}.json"'},
    )


@aplicacion.put("/api/casos/{identificador}/referencia")
def cargar_referencia(
    identificador: str, datos: bytes = Body(media_type="application/octet-stream"),
    procedencia: str = Query(min_length=8, max_length=500),
) -> dict:
    if not 100 <= len(datos) <= 20_000_000:
        raise HTTPException(422, "El STEP debe tener entre 100 bytes y 20 MB")
    with crear_sesion() as sesion:
        caso = sesion.get(CasoDiseno, identificador)
        if caso is None:
            raise HTTPException(404, "Caso no encontrado")
        campanas = list(sesion.scalars(select(Campana).where(
            Campana.conjunto_identificador == caso.conjunto_identificador
        )))
        if any(campana.estado != "borrador" and caso.codigo in campana.configuracion.get("codigos_caso", [])
               for campana in campanas):
            raise HTTPException(409, "No se puede alterar una referencia de un caso ya ensayado")
        if caso.referencia_sha256:
            raise HTTPException(409, "La referencia ya existe; cree una nueva versión del conjunto")
    ruta = Path(DIRECTORIO_ARTEFACTOS) / "referencias" / identificador / "referencia.step"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(datos)
    try:
        with httpx.Client(timeout=60) as cliente:
            respuesta = cliente.post(f"{URL_EVALUADOR}/validar-referencia", json={
                "caso_identificador": identificador
            })
            respuesta.raise_for_status()
            validacion = respuesta.json()
    except (httpx.HTTPError, ValueError) as error:
        ruta.unlink(missing_ok=True)
        raise HTTPException(422, f"No se pudo validar el STEP: {type(error).__name__}") from error
    with crear_sesion() as sesion:
        caso = sesion.get(CasoDiseno, identificador)
        caso.referencia_ruta = str(ruta)
        caso.referencia_sha256 = hashlib.sha256(datos).hexdigest()
        caso.procedencia_referencia = procedencia.strip()
        sesion.commit()
    return {"caso_identificador": identificador, "sha256": caso.referencia_sha256,
            "volumen_mm3": validacion["volumen_mm3"], "procedencia": procedencia}


@aplicacion.post("/api/ejecuciones", status_code=202)
def iniciar_generacion(solicitud: SolicitudGeneracion) -> dict:
    if solicitud.motor not in MOTORES_DISPONIBLES:
        raise HTTPException(422, "Motor CAD no reconocido")
    if solicitud.modelo not in modelos_configurados():
        raise HTTPException(422, "Modelo de IA no configurado")
    try:
        esfuerzo = resolver_esfuerzo(solicitud.modelo, solicitud.esfuerzo_razonamiento)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if solicitud.modo == "quality-loop":
        try:
            validar_revisores(solicitud.proveedor_revisores,
                             bool(os.environ.get("NVIDIA_API_KEY", "").strip()))
        except ValueError as error:
            raise HTTPException(503, str(error)) from None
    elif solicitud.proveedor_revisores != "nvidia":
        raise HTTPException(422, "Los revisores solo se aplican a Quality Loop")
    if solicitud.best_of_n and solicitud.modo != "quality-loop":
        raise HTTPException(422, "best_of_n solo está disponible en Quality Loop")
    descripcion = (solicitud.descripcion or "").strip()
    if solicitud.caso_identificador:
        with crear_sesion() as sesion:
            caso = sesion.get(CasoDiseno, solicitud.caso_identificador)
            if caso is None:
                raise HTTPException(404, "Caso no encontrado")
            descripcion = caso.descripcion
    if not 12 <= len(descripcion) <= 4000:
        raise HTTPException(422, "La descripción debe tener entre 12 y 4000 caracteres")
    identificador = str(uuid4())
    with crear_sesion() as sesion:
        sesion.add(Ejecucion(
            identificador=identificador, descripcion=descripcion,
            motor=solicitud.motor, modelo=solicitud.modelo,
            esfuerzo_razonamiento=esfuerzo,
            caso_identificador=solicitud.caso_identificador,
            modo=solicitud.modo, maximo_intentos=(1 if solicitud.modo == "open-loop"
                else MAXIMO_ITERACIONES_QUALITY_LOOP if solicitud.modo == "quality-loop" else 5),
            configuracion_calidad={"best_of_n": solicitud.best_of_n,
                "proveedor_revisores": solicitud.proveedor_revisores} if solicitud.modo == "quality-loop" else None,
            estado="pendiente", mensaje="Trabajo en cola",
        ))
        sesion.commit()
    try:
        tarea_generacion.delay(identificador)
    except Exception as error:
        with crear_sesion() as sesion:
            ejecucion = sesion.get(Ejecucion, identificador)
            ejecucion.estado = "bloqueada"
            ejecucion.mensaje = "No fue posible programar el trabajo"
            sesion.commit()
        raise HTTPException(503, "La cola de generación no está disponible") from error
    return {"identificador": identificador, "estado": "pendiente"}


def serializar_ejecucion(ejecucion: Ejecucion, topologias: list, comparacion,
                         informes_calidad: list | None = None) -> dict:
    esfuerzo = ejecucion.esfuerzo_razonamiento or next((
        (intento.solicitud_modelo or {}).get("perfil", {}).get("reasoning_effort")
        for intento in ejecucion.intentos if (intento.solicitud_modelo or {}).get("perfil")
        and (intento.solicitud_modelo or {}).get("perfil", {}).get("reasoning_effort")
    ), None)
    return {
        "identificador": ejecucion.identificador, "descripcion": ejecucion.descripcion,
        "motor": ejecucion.motor, "modelo": ejecucion.modelo,
        "esfuerzo_razonamiento": esfuerzo,
        "modo": ejecucion.modo, "caso_identificador": ejecucion.caso_identificador,
        "campana_identificador": ejecucion.campana_identificador,
        "estado": ejecucion.estado, "mensaje": ejecucion.mensaje,
        "numero_intentos": ejecucion.numero_intentos,
        "primer_exito_ejecucion": ejecucion.primer_exito_ejecucion,
        "primer_exito_cad": ejecucion.primer_exito_cad,
        "primer_exito_exportacion": ejecucion.primer_exito_exportacion,
        "technical_success": ((ejecucion.configuracion_calidad or {}).get("technical_success")
                              if ejecucion.modo == "quality-loop"
                              else bool(ejecucion.primer_exito_exportacion)),
        "quality_success": ((ejecucion.configuracion_calidad or {}).get("quality_success")
                            if ejecucion.modo == "quality-loop" else None),
        "calidad": ejecucion.configuracion_calidad if ejecucion.modo == "quality-loop" else None,
        "informes_calidad": [{"iteracion": informe.iteracion,
            "candidate_id": informe.candidate_id, "parent_candidate_id": informe.parent_candidate_id,
            "intento_identificador": informe.intento_identificador,
            **informe.resultado} for informe in (informes_calidad or [])],
        "fecha_creacion": ejecucion.fecha_creacion,
        "fecha_inicio": ejecucion.fecha_inicio, "fecha_fin": ejecucion.fecha_fin,
        "intentos": [{
            "identificador": intento.identificador, "numero": intento.numero,
            "estado": intento.estado, "fase_error": intento.fase_error,
            "diagnostico": intento.diagnostico, "codigo": intento.codigo,
            "modelo_informado": intento.modelo_informado,
            "tokens_entrada": intento.tokens_entrada, "tokens_salida": intento.tokens_salida,
            "costo_estimado_usd": intento.costo_estimado_usd,
            "duracion_segundos": intento.duracion_segundos,
            "duracion_ia_segundos": intento.duracion_ia_segundos,
            "duracion_cad_segundos": intento.duracion_cad_segundos,
            "sintaxis_valida": intento.sintaxis_valida,
            "ejecucion_correcta": intento.ejecucion_correcta,
            "cad_valido": intento.cad_valido,
            "exportacion_valida": intento.exportacion_valida,
            "runtime_identificador": intento.runtime_identificador,
            "solicitud_modelo": intento.solicitud_modelo,
        } for intento in ejecucion.intentos],
        "archivos": [{
            "nombre": archivo.nombre, "rol": archivo.rol,
            "tamano_bytes": archivo.tamano_bytes, "sha256": archivo.sha256,
            "url": f"/api/ejecuciones/{ejecucion.identificador}/archivos/{archivo.nombre}",
        } for archivo in ejecucion.archivos],
        "topologia": [{
            "rol_malla": informe.rol_malla, "estado": informe.estado,
            "watertight": informe.watertight, "dang_el": informe.dang_el,
            "aristas_abiertas": informe.aristas_abiertas,
            "aristas_no_manifold": informe.aristas_no_manifold,
            "componentes": informe.componentes, "vertices": informe.vertices,
            "caras": informe.caras, "orientacion_consistente": informe.orientacion_consistente,
            "volumen_mm3": informe.volumen_mm3, "diagnostico": informe.diagnostico,
            "perfil": informe.perfil,
        } for informe in topologias],
        "comparacion_digital": None if comparacion is None else {
            "estado": comparacion.estado, "iou_brep": comparacion.iou_brep,
            "chamfer_digital_mm2": comparacion.chamfer_digital_mm2,
            "diferencia_volumen_mm3": comparacion.diferencia_volumen_mm3,
            "referencia_sha256": comparacion.referencia_sha256,
            "diagnostico": comparacion.diagnostico, "perfil": comparacion.perfil,
        },
    }


@aplicacion.get("/api/ejecuciones/{identificador}")
def consultar_ejecucion(identificador: str) -> dict:
    with crear_sesion() as sesion:
        ejecucion = sesion.get(Ejecucion, identificador)
        if ejecucion is None:
            raise HTTPException(404, "Ejecución no encontrada")
        topologias = list(sesion.scalars(select(InformeTopologia).where(
            InformeTopologia.ejecucion_identificador == identificador
        )))
        comparacion = sesion.scalar(select(ComparacionDigital).where(
            ComparacionDigital.ejecucion_identificador == identificador
        ))
        informes_calidad = list(sesion.scalars(select(InformeCalidad).where(
            InformeCalidad.ejecucion_identificador == identificador
        ).order_by(InformeCalidad.iteracion, InformeCalidad.identificador)))
        return serializar_ejecucion(ejecucion, topologias, comparacion, informes_calidad)


@aplicacion.post("/api/ejecuciones/{identificador}/reanalizar", status_code=202)
def reanalizar_ejecucion(identificador: str) -> dict:
    with crear_sesion() as sesion:
        ejecucion = sesion.get(Ejecucion, identificador)
        if ejecucion is None:
            raise HTTPException(404, "Ejecución no encontrada")
        if ejecucion.estado != "completada":
            raise HTTPException(409, "Solo se reanalizan ejecuciones con CAD exportado")
    tarea_analisis.delay(identificador)
    return {"identificador": identificador, "estado": "analisis_programado"}


@aplicacion.get("/api/ejecuciones/{identificador}/archivos/{nombre}")
def descargar_archivo(identificador: str, nombre: str) -> FileResponse:
    with crear_sesion() as sesion:
        archivo = sesion.scalar(select(ArchivoGenerado).where(
            ArchivoGenerado.ejecucion_identificador == identificador,
            ArchivoGenerado.nombre == nombre,
        ))
        if archivo is None or not Path(archivo.ruta).is_file():
            raise HTTPException(404, "Archivo no encontrado")
        return FileResponse(archivo.ruta, filename=archivo.nombre)


def _casos_solicitados(sesion, solicitud: SolicitudCampana) -> tuple[VersionConjunto, list[CasoDiseno]]:
    conjunto = sesion.get(VersionConjunto, solicitud.conjunto_identificador)
    if conjunto is None:
        raise HTTPException(404, "Conjunto no encontrado")
    todos = list(sesion.scalars(select(CasoDiseno).where(
        CasoDiseno.conjunto_identificador == solicitud.conjunto_identificador
    )))
    if solicitud.codigos_caso is None:
        return conjunto, todos
    mapa = {caso.codigo: caso for caso in todos}
    if len(set(solicitud.codigos_caso)) != len(solicitud.codigos_caso) or any(
        codigo not in mapa for codigo in solicitud.codigos_caso
    ):
        raise HTTPException(422, "Lista de casos duplicada o ajena al conjunto")
    return conjunto, [mapa[codigo] for codigo in solicitud.codigos_caso]


@aplicacion.post("/api/campanas/previsualizar")
def previsualizar_campana(solicitud: SolicitudCampana) -> dict:
    with crear_sesion() as sesion:
        conjunto, casos = _casos_solicitados(sesion, solicitud)
        try:
            if solicitud.esfuerzo_razonamiento is not None and not any(
                modelo in MODELOS_DISPONIBLES for modelo in solicitud.modelos
            ):
                raise ValueError("El nivel de esfuerzo requiere un modelo DeepSeek")
            validar_matriz(
                conjunto, casos, solicitud.modelos, solicitud.motores,
                solicitud.modos, solicitud.repeticiones, solicitud.tipo,
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return previsualizar(
            len(casos), solicitud.modelos, solicitud.motores,
            solicitud.modos, solicitud.repeticiones,
        )


@aplicacion.post("/api/campanas", status_code=201)
def registrar_campana(solicitud: SolicitudCampana) -> dict:
    try:
        campana = crear_campana(
            solicitud.nombre, solicitud.conjunto_identificador, solicitud.modelos,
            solicitud.motores, solicitud.modos, solicitud.repeticiones,
            solicitud.semilla, solicitud.tipo, solicitud.codigos_caso,
            solicitud.presupuesto_usd,
            solicitud.esfuerzo_razonamiento,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return resumen_campana(campana)


@aplicacion.get("/api/campanas")
def listar_campanas() -> list[dict]:
    with crear_sesion() as sesion:
        campanas = list(sesion.scalars(select(Campana).order_by(Campana.fecha_creacion.desc())))
    return [resumen_campana(campana) for campana in campanas]


@aplicacion.get("/api/campanas/{identificador}")
def consultar_campana(identificador: str) -> dict:
    with crear_sesion() as sesion:
        campana = sesion.get(Campana, identificador)
        if campana is None:
            raise HTTPException(404, "Campaña no encontrada")
    return resumen_campana(campana)


def _cambiar_campana(identificador: str, accion: str) -> dict:
    try:
        campana = cambiar_estado(identificador, accion)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    if accion == "iniciar":
        try:
            tarea_campana.delay(identificador)
        except Exception as error:
            cambiar_estado(identificador, "pausar")
            raise HTTPException(503, "La cola de campañas no está disponible") from error
    return resumen_campana(campana)


@aplicacion.post("/api/campanas/{identificador}/iniciar")
def iniciar_campana(identificador: str) -> dict:
    return _cambiar_campana(identificador, "iniciar")


@aplicacion.post("/api/campanas/{identificador}/pausar")
def pausar_campana(identificador: str) -> dict:
    return _cambiar_campana(identificador, "pausar")


@aplicacion.post("/api/campanas/{identificador}/cancelar")
def cancelar_campana(identificador: str) -> dict:
    return _cambiar_campana(identificador, "cancelar")


@aplicacion.patch("/api/campanas/{identificador}/presupuesto")
def actualizar_presupuesto(identificador: str, solicitud: SolicitudPresupuesto) -> dict:
    with crear_sesion() as sesion:
        campana = sesion.scalar(select(Campana).where(
            Campana.identificador == identificador
        ).with_for_update())
        if campana is None:
            raise HTTPException(404, "Campaña no encontrada")
        if campana.estado in {"completada", "cancelada"}:
            raise HTTPException(409, "La campaña ya terminó")
        if solicitud.presupuesto_usd < campana.gasto_estimado_usd:
            raise HTTPException(422, "El nuevo tope es inferior al gasto estimado registrado")
        campana.presupuesto_usd = solicitud.presupuesto_usd
        sesion.commit()
        return resumen_campana(campana)


@aplicacion.get("/api/campanas/{identificador}/ejecuciones")
def listar_ejecuciones_campana(
    identificador: str, limite: int = Query(default=100, ge=1, le=1000),
    desplazamiento: int = Query(default=0, ge=0),
) -> dict:
    with crear_sesion() as sesion:
        campana = sesion.get(Campana, identificador)
        if campana is None:
            raise HTTPException(404, "Campaña no encontrada")
        ejecuciones = list(sesion.scalars(select(Ejecucion).where(
            Ejecucion.campana_identificador == identificador
        ).order_by(Ejecucion.orden_campana).offset(desplazamiento).limit(limite)))
        casos = {caso.identificador: caso for caso in sesion.scalars(select(CasoDiseno).where(
            CasoDiseno.conjunto_identificador == campana.conjunto_identificador
        ))}
        return {"total": campana.total_ejecuciones, "desplazamiento": desplazamiento,
                "ejecuciones": [{
                    "identificador": e.identificador, "orden": e.orden_campana,
                    "caso": casos[e.caso_identificador].codigo, "nivel": casos[e.caso_identificador].nivel,
                    "modelo": e.modelo, "motor": e.motor, "modo": e.modo,
                    "esfuerzo_razonamiento": e.esfuerzo_razonamiento,
                    "repeticion": e.repeticion, "estado": e.estado,
                    "intentos": e.numero_intentos, "primer_exito_ejecucion": e.primer_exito_ejecucion,
                    "primer_exito_exportacion": e.primer_exito_exportacion,
                    "mensaje": e.mensaje,
                } for e in ejecuciones]}


@aplicacion.get("/api/campanas/{identificador}/metricas")
def consultar_metricas(identificador: str) -> dict:
    try:
        return calcular_metricas_campana(identificador)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@aplicacion.get("/api/campanas/{identificador}/metricas.csv")
def descargar_metricas(identificador: str) -> Response:
    datos = consultar_metricas(identificador)
    salida = io.StringIO()
    columnas = ["modelo", "esfuerzo_razonamiento", "motor", "modo", "nivel", "n_planificado", "n_evaluable",
                "n_pendiente", "n_bloqueado", "n_cancelado", "final",
                "primer_exito_ejecucion", "primer_exito_cad_exportable",
                "compile_rate_acumulado_pct", "exito_cad_acumulado_pct",
                "ir_cad_pct", "sin_exito_ejecucion", "sin_cad_exportable",
                "intentos_observados", "tokens_entrada", "tokens_salida",
                "costo_estimado_usd", "latencia_ia_media_s", "latencia_cad_media_s",
                "tiempo_total_mediana_s", "topologia", "topologia_comun", "referencias"]
    escritor = csv.DictWriter(salida, fieldnames=columnas)
    escritor.writeheader()
    for fila in datos["filas"]:
        escritor.writerow({columna: json.dumps(fila[columna], ensure_ascii=False)
                          if isinstance(fila.get(columna), (list, dict)) else fila.get(columna)
                          for columna in columnas})
    return Response(salida.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="metricas-{identificador}.csv"'})


@aplicacion.get("/api/campanas/{identificador}/datos.json")
def descargar_datos(identificador: str) -> Response:
    campana = consultar_campana(identificador)
    metricas = consultar_metricas(identificador)
    with crear_sesion() as sesion:
        ejecuciones = list(sesion.scalars(select(Ejecucion).where(
            Ejecucion.campana_identificador == identificador
        ).options(selectinload(Ejecucion.intentos), selectinload(Ejecucion.archivos))
          .order_by(Ejecucion.orden_campana)))
        identificadores = [e.identificador for e in ejecuciones]
        informes = {}
        comparaciones = {}
        if identificadores:
            for informe in sesion.scalars(select(InformeTopologia).where(
                InformeTopologia.ejecucion_identificador.in_(identificadores)
            )):
                informes.setdefault(informe.ejecucion_identificador, []).append(informe)
            for comparacion in sesion.scalars(select(ComparacionDigital).where(
                ComparacionDigital.ejecucion_identificador.in_(identificadores)
            )):
                comparaciones[comparacion.ejecucion_identificador] = comparacion
        datos = [{
            "identificador": e.identificador, "caso_identificador": e.caso_identificador,
            "condicion_identificador": e.condicion_identificador,
            "orden": e.orden_campana, "repeticion": e.repeticion,
            "modelo": e.modelo, "motor": e.motor, "modo": e.modo,
            "esfuerzo_razonamiento": e.esfuerzo_razonamiento,
            "estado": e.estado, "primer_exito_ejecucion": e.primer_exito_ejecucion,
            "primer_exito_cad": e.primer_exito_cad,
            "primer_exito_exportacion": e.primer_exito_exportacion,
            "archivos": [{"nombre": a.nombre, "rol": a.rol, "sha256": a.sha256,
                          "tamano_bytes": a.tamano_bytes, "intento_identificador": a.intento_identificador}
                         for a in e.archivos],
            "topologia": [{"rol_malla": t.rol_malla, "estado": t.estado,
                           "sha256_malla": t.sha256_malla, "watertight": t.watertight,
                           "dang_el": t.dang_el, "aristas_abiertas": t.aristas_abiertas,
                           "aristas_no_manifold": t.aristas_no_manifold,
                           "componentes": t.componentes, "caras": t.caras,
                           "perfil": t.perfil, "diagnostico": t.diagnostico}
                          for t in informes.get(e.identificador, [])],
            "comparacion_digital": None if e.identificador not in comparaciones else {
                "estado": comparaciones[e.identificador].estado,
                "referencia_sha256": comparaciones[e.identificador].referencia_sha256,
                "iou_brep": comparaciones[e.identificador].iou_brep,
                "chamfer_digital_mm2": comparaciones[e.identificador].chamfer_digital_mm2,
                "diferencia_volumen_mm3": comparaciones[e.identificador].diferencia_volumen_mm3,
                "perfil": comparaciones[e.identificador].perfil,
                "diagnostico": comparaciones[e.identificador].diagnostico,
            },
            "intentos": [{"numero": i.numero, "estado": i.estado,
                          "fase_error": i.fase_error, "diagnostico": i.diagnostico,
                          "codigo": i.codigo, "respuesta_modelo": i.respuesta_modelo,
                          "solicitud_modelo": i.solicitud_modelo,
                          "sintaxis_valida": i.sintaxis_valida,
                          "ejecucion_correcta": i.ejecucion_correcta,
                          "cad_valido": i.cad_valido,
                          "exportacion_valida": i.exportacion_valida,
                          "tokens_entrada": i.tokens_entrada,
                          "tokens_salida": i.tokens_salida,
                          "duracion_ia_segundos": i.duracion_ia_segundos,
                          "duracion_cad_segundos": i.duracion_cad_segundos,
                          "costo_estimado_usd": i.costo_estimado_usd,
                          "runtime_identificador": i.runtime_identificador}
                         for i in e.intentos],
        } for e in ejecuciones]
    return Response(json.dumps({"campana": campana, "metricas": metricas,
                                "ejecuciones": datos}, ensure_ascii=False, default=str),
                    media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="datos-{identificador}.json"'})


@aplicacion.get("/")
def mostrar_interfaz() -> FileResponse:
    return FileResponse(DIRECTORIO_WEB / "index.html")
