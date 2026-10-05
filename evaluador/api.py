"""Evaluador común de STEP y STL, separado de los runtimes que ejecutan código."""

import base64
import hashlib
import re
import tempfile
from pathlib import Path

import cadquery as cq
import numpy as np
import trimesh
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from scipy.spatial import cKDTree


aplicacion = FastAPI(title="Evaluador CAD digital")
RAIZ = Path("/datos")
IDENTIFICADOR = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PUNTOS_CHAMFER = 8192
SEMILLA_CHAMFER = 20261004


class SolicitudAnalisis(BaseModel):
    ejecucion_identificador: str
    caso_identificador: str | None = None


class SolicitudReferencia(BaseModel):
    caso_identificador: str


class SolicitudVerificacion(BaseModel):
    archivos: dict[str, str]


def ruta_ejecucion(identificador: str, nombre: str) -> Path:
    if not IDENTIFICADOR.fullmatch(identificador):
        raise HTTPException(422, "Identificador de ejecución inválido")
    return RAIZ / "ejecuciones" / identificador / nombre


def ruta_referencia(identificador: str) -> Path:
    if not IDENTIFICADOR.fullmatch(identificador):
        raise HTTPException(422, "Identificador de caso inválido")
    return RAIZ / "referencias" / identificador / "referencia.step"


def leer_forma(ruta: Path):
    if not ruta.is_file() or ruta.is_symlink():
        raise ValueError("No existe el archivo STEP")
    forma = cq.importers.importStep(str(ruta)).val()
    if not forma.isValid() or len(forma.Solids()) != 1 or forma.Volume() <= 0:
        raise ValueError("El STEP debe contener un solo sólido B-Rep válido y positivo")
    return forma


def leer_malla(ruta: Path):
    if not ruta.is_file() or ruta.is_symlink():
        raise ValueError("No existe el STL")
    malla = trimesh.load_mesh(str(ruta), file_type="stl", process=True)
    if not isinstance(malla, trimesh.Trimesh) or len(malla.faces) == 0:
        raise ValueError("El STL no contiene una malla triangular")
    return malla


def analizar_malla(ruta: Path) -> dict:
    malla = leer_malla(ruta)
    incidencias = np.bincount(malla.edges_unique_inverse, minlength=len(malla.edges_unique))
    abiertas = int(np.sum(incidencias == 1))
    no_manifold = int(np.sum(incidencias > 2))
    dang_el = int(np.sum(incidencias != 2))
    return {
        "estado": "analizada", "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(),
        "watertight": bool(malla.is_watertight), "dang_el": dang_el,
        "aristas_abiertas": abiertas, "aristas_no_manifold": no_manifold,
        "componentes": len(malla.split(only_watertight=False)),
        "vertices": len(malla.vertices), "caras": len(malla.faces),
        "orientacion_consistente": bool(malla.is_winding_consistent),
        "volumen_mm3": float(abs(malla.volume)) if malla.is_watertight else None,
        "perfil": {"indexacion": "trimesh process=True y edges_unique_inverse",
                    "biblioteca": trimesh.__version__},
    }


def analizar_malla_segura(ruta: Path) -> dict:
    try:
        return analizar_malla(ruta)
    except Exception as error:
        return {"estado": "no_calculable", "sha256": "",
                "diagnostico": f"Malla no analizable: {type(error).__name__}"}


def muestrear_superficie(malla, cantidad: int, semilla: int):
    areas = malla.area_faces
    total = float(areas.sum())
    if total <= 0:
        raise ValueError("La malla no tiene área superficial positiva")
    azar = np.random.default_rng(semilla)
    indices = azar.choice(len(areas), size=cantidad, p=areas / total)
    triangulos = malla.triangles[indices]
    u = azar.random(cantidad)
    v = azar.random(cantidad)
    raiz = np.sqrt(u)
    return ((1 - raiz)[:, None] * triangulos[:, 0] +
            (raiz * (1 - v))[:, None] * triangulos[:, 1] +
            (raiz * v)[:, None] * triangulos[:, 2])


def comparar(forma, referencia, malla_generada, malla_referencia) -> dict:
    interseccion = forma.intersect(referencia)
    union = forma.fuse(referencia)
    volumen_interseccion = max(0.0, float(interseccion.Volume()))
    volumen_union = float(union.Volume())
    if volumen_union <= 0:
        raise ValueError("La unión B-Rep tiene volumen nulo")
    iou = max(0.0, min(1.0, volumen_interseccion / volumen_union))
    puntos_a = muestrear_superficie(malla_generada, PUNTOS_CHAMFER, SEMILLA_CHAMFER)
    puntos_b = muestrear_superficie(malla_referencia, PUNTOS_CHAMFER, SEMILLA_CHAMFER)
    distancias_ab = cKDTree(puntos_b).query(puntos_a, k=1)[0]
    distancias_ba = cKDTree(puntos_a).query(puntos_b, k=1)[0]
    chamfer = float(np.mean(distancias_ab ** 2) + np.mean(distancias_ba ** 2))
    return {
        "estado": "calculada", "iou_brep": iou,
        "chamfer_digital_mm2": chamfer,
        "diferencia_volumen_mm3": float(forma.Volume() - referencia.Volume()),
        "perfil": {"metodo_iou": "booleano B-Rep OCP", "metodo_chamfer": "cuadratico bidireccional",
                    "puntos_superficie": PUNTOS_CHAMFER, "semilla": SEMILLA_CHAMFER,
                    "unidad": "mm", "teselacion": "CadQuery tolerance=0.1, angularTolerance=0.1"},
    }


@aplicacion.get("/salud")
def salud() -> dict:
    return {"estado": "disponible"}


@aplicacion.post("/verificar-exportacion")
def verificar_exportacion(solicitud: SolicitudVerificacion) -> dict:
    try:
        with tempfile.TemporaryDirectory(prefix="ciel-verificar-") as directorio:
            rutas = {}
            for nombre in ("pieza.step", "pieza.stl"):
                contenido = base64.b64decode(solicitud.archivos[nombre], validate=True)
                if not contenido or len(contenido) > 20_000_000:
                    raise ValueError(f"{nombre} vacío o demasiado grande")
                ruta = Path(directorio) / nombre
                ruta.write_bytes(contenido)
                rutas[nombre] = ruta
            forma = leer_forma(rutas["pieza.step"])
            malla = leer_malla(rutas["pieza.stl"])
            if not np.isfinite(malla.vertices).all():
                raise ValueError("El STL contiene coordenadas no finitas")
            return {"valida": True, "volumen_step_mm3": float(forma.Volume()),
                    "caras_stl": len(malla.faces)}
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(422, f"Exportación ilegible: {type(error).__name__}: {error}") from error


@aplicacion.post("/validar-referencia")
def validar_referencia(solicitud: SolicitudReferencia) -> dict:
    try:
        ruta = ruta_referencia(solicitud.caso_identificador)
        forma = leer_forma(ruta)
        return {"valida": True, "volumen_mm3": float(forma.Volume()),
                "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest()}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@aplicacion.post("/analizar")
def analizar(solicitud: SolicitudAnalisis) -> dict:
    try:
        ruta_step = ruta_ejecucion(solicitud.ejecucion_identificador, "pieza.step")
        ruta_nativa = ruta_ejecucion(solicitud.ejecucion_identificador, "pieza.stl")
        forma = leer_forma(ruta_step)
        ruta_comun = ruta_ejecucion(solicitud.ejecucion_identificador, "pieza_comun.stl")
        cq.exporters.export(forma, str(ruta_comun), exportType="STL", tolerance=0.1, angularTolerance=0.1)
        nativa = analizar_malla_segura(ruta_nativa)
        comun = analizar_malla_segura(ruta_comun)
        respuesta = {"step_verificado": True, "volumen_step_mm3": float(forma.Volume()),
                     "nativa": nativa, "comun": comun}
        if solicitud.caso_identificador is None:
            respuesta["comparacion"] = {"estado": "sin_referencia", "diagnostico": "Ejecución sin caso asociado"}
            return respuesta
        ruta_ref = ruta_referencia(solicitud.caso_identificador)
        if not ruta_ref.is_file():
            respuesta["comparacion"] = {"estado": "sin_referencia", "diagnostico": "No hay referencia independiente"}
            return respuesta
        try:
            referencia = leer_forma(ruta_ref)
            ruta_ref_stl = ruta_ref.with_suffix(".stl")
            if not ruta_ref_stl.is_file():
                cq.exporters.export(referencia, str(ruta_ref_stl), exportType="STL", tolerance=0.1, angularTolerance=0.1)
            resultado = comparar(forma, referencia, leer_malla(ruta_comun), leer_malla(ruta_ref_stl))
            resultado["referencia_sha256"] = hashlib.sha256(ruta_ref.read_bytes()).hexdigest()
            respuesta["comparacion"] = resultado
        except Exception as error:
            respuesta["comparacion"] = {
                "estado": "no_calculable",
                "diagnostico": f"Referencia o comparación no calculable: {type(error).__name__}",
            }
        return respuesta
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
