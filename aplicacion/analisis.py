"""Persistencia de evaluaciones digitales, sin alterar el éxito nativo CAD."""

import hashlib
from pathlib import Path

import httpx
from sqlalchemy import select

from aplicacion.base_datos import (
    ArchivoGenerado, ComparacionDigital, Ejecucion, InformeTopologia, crear_sesion,
)
from aplicacion.configuracion import DIRECTORIO_ARTEFACTOS, URL_EVALUADOR


def _informe(sesion, identificador: str, rol: str) -> InformeTopologia:
    informe = sesion.scalar(select(InformeTopologia).where(
        InformeTopologia.ejecucion_identificador == identificador,
        InformeTopologia.rol_malla == rol,
    ))
    if informe is None:
        informe = InformeTopologia(
            ejecucion_identificador=identificador, rol_malla=rol,
            sha256_malla="", estado="pendiente",
        )
        sesion.add(informe)
    return informe


def _comparacion(sesion, identificador: str) -> ComparacionDigital:
    comparacion = sesion.scalar(select(ComparacionDigital).where(
        ComparacionDigital.ejecucion_identificador == identificador
    ))
    if comparacion is None:
        comparacion = ComparacionDigital(ejecucion_identificador=identificador, estado="pendiente")
        sesion.add(comparacion)
    return comparacion


def registrar_incidencia(identificador: str, diagnostico: str) -> None:
    with crear_sesion() as sesion:
        for rol in ("nativa", "comun"):
            informe = _informe(sesion, identificador, rol)
            informe.estado = "no_calculable"
            informe.diagnostico = diagnostico[:3000]
        comparacion = _comparacion(sesion, identificador)
        comparacion.estado = "no_calculable"
        comparacion.diagnostico = diagnostico[:3000]
        sesion.commit()


def analizar_ejecucion(identificador: str) -> None:
    with crear_sesion() as sesion:
        ejecucion = sesion.get(Ejecucion, identificador)
        if ejecucion is None or ejecucion.estado != "completada":
            return
        caso = ejecucion.caso_identificador
    try:
        with httpx.Client(timeout=180) as cliente:
            respuesta = cliente.post(f"{URL_EVALUADOR}/analizar", json={
                "ejecucion_identificador": identificador,
                "caso_identificador": caso,
            })
            respuesta.raise_for_status()
            datos = respuesta.json()
    except (httpx.HTTPError, ValueError, KeyError) as error:
        registrar_incidencia(
            identificador, f"Evaluador no disponible o análisis inválido: {type(error).__name__}"
        )
        return
    with crear_sesion() as sesion:
        for rol in ("nativa", "comun"):
            resultado = datos[rol]
            informe = _informe(sesion, identificador, rol)
            informe.estado = resultado["estado"]
            informe.sha256_malla = resultado.get("sha256", "")
            informe.watertight = resultado.get("watertight")
            informe.dang_el = resultado.get("dang_el")
            informe.aristas_abiertas = resultado.get("aristas_abiertas")
            informe.aristas_no_manifold = resultado.get("aristas_no_manifold")
            informe.componentes = resultado.get("componentes")
            informe.vertices = resultado.get("vertices")
            informe.caras = resultado.get("caras")
            informe.orientacion_consistente = resultado.get("orientacion_consistente")
            informe.volumen_mm3 = resultado.get("volumen_mm3")
            informe.perfil = resultado.get("perfil") or {}
            informe.diagnostico = resultado.get("diagnostico", "")
        ruta = Path(DIRECTORIO_ARTEFACTOS) / "ejecuciones" / identificador / "pieza_comun.stl"
        if ruta.is_file():
            datos_stl = ruta.read_bytes()
            archivo = sesion.scalar(select(ArchivoGenerado).where(
                ArchivoGenerado.ejecucion_identificador == identificador,
                ArchivoGenerado.nombre == "pieza_comun.stl",
            ))
            if archivo is None:
                sesion.add(ArchivoGenerado(
                    ejecucion_identificador=identificador, nombre="pieza_comun.stl",
                    ruta=str(ruta), tamano_bytes=len(datos_stl),
                    sha256=hashlib.sha256(datos_stl).hexdigest(), rol="comun",
                ))
        comparacion = _comparacion(sesion, identificador)
        resultado = datos["comparacion"]
        comparacion.estado = resultado["estado"]
        comparacion.diagnostico = resultado.get("diagnostico", "")
        comparacion.referencia_sha256 = resultado.get("referencia_sha256")
        comparacion.iou_brep = resultado.get("iou_brep")
        comparacion.chamfer_digital_mm2 = resultado.get("chamfer_digital_mm2")
        comparacion.diferencia_volumen_mm3 = resultado.get("diferencia_volumen_mm3")
        comparacion.perfil = resultado.get("perfil") or {}
        sesion.commit()
