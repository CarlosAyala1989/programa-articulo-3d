"""Evaluador común de STEP y STL, separado de los runtimes que ejecutan código."""

import base64
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import cadquery as cq
import numpy as np
import trimesh
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree

from evaluador.renderizado import comparar_siluetas, renderizar_lamina


aplicacion = FastAPI(title="Evaluador CAD digital")
RAIZ = Path(os.environ.get("DIRECTORIO_ARTEFACTOS", "/datos"))
IDENTIFICADOR = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PUNTOS_CHAMFER = 8192
SEMILLA_CHAMFER = 20261004
VERSION_METRICAS_CALIDAD = "ciel-quality-metrics-v2"


def metadatos_metrica(unidad: str, algoritmo: str, muestras: int | None = None,
                      semilla: int | None = None, tolerancia: float | None = None) -> dict:
    return {"unidad": unidad, "algoritmo": algoritmo, "numero_muestras": muestras,
            "semilla": semilla, "tolerancia": tolerancia,
            "perfil": VERSION_METRICAS_CALIDAD, "version": VERSION_METRICAS_CALIDAD}


class SolicitudAnalisis(BaseModel):
    ejecucion_identificador: str
    caso_identificador: str | None = None


class SolicitudReferencia(BaseModel):
    caso_identificador: str


class SolicitudVerificacion(BaseModel):
    archivos: dict[str, str]


class SolicitudInspeccionCalidad(BaseModel):
    archivos: dict[str, str]
    plan_geometrico: dict = Field(max_length=200)
    caso_identificador: str | None = None
    usar_referencia: bool = False


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


def _cajas(forma) -> dict:
    caja = forma.BoundingBox()
    centro = forma.Center()
    return {
        "bounding_box_mm": {"x": float(caja.xlen), "y": float(caja.ylen), "z": float(caja.zlen)},
        "centroide_mm": [float(centro.x), float(centro.y), float(centro.z)],
        "volumen_mm3": float(forma.Volume()), "area_mm2": float(forma.Area()),
        "solidos": len(forma.Solids()), "brep_valido": bool(forma.isValid()),
        "metadatos": {
            "bounding_box_mm": metadatos_metrica("mm", "OCP B-Rep BoundingBox"),
            "centroide_mm": metadatos_metrica("mm", "OCP B-Rep Center"),
            "volumen_mm3": metadatos_metrica("mm3", "OCP B-Rep Volume"),
            "area_mm2": metadatos_metrica("mm2", "OCP B-Rep Area"),
            "solidos": metadatos_metrica("count", "OCP B-Rep Solids"),
            "brep_valido": metadatos_metrica("boolean", "OCP B-Rep isValid"),
        },
    }


def _cilindros(forma) -> list[dict]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    encontrados = []
    for cara in forma.Faces():
        if cara.geomType() != "CYLINDER":
            continue
        cilindro = BRepAdaptor_Surface(cara.wrapped).Cylinder()
        eje = cilindro.Axis().Direction()
        origen = cilindro.Axis().Location()
        punto = cara.positionAt(0.3, 0.5)
        normal = cara.normalAt(0.3, 0.5)[0]
        direccion = np.asarray([eje.X(), eje.Y(), eje.Z()], dtype=float)
        desplazamiento = np.asarray([punto.x - origen.X(), punto.y - origen.Y(),
                                     punto.z - origen.Z()], dtype=float)
        radial = desplazamiento - np.dot(desplazamiento, direccion) * direccion
        # La normal exterior del sólido apunta hacia el eje en una pared de agujero.
        # Una superficie cilíndrica exterior apunta fuera y no es un agujero.
        if np.dot(radial, [normal.x, normal.y, normal.z]) >= -0.5 * cilindro.Radius():
            continue
        datos = {"radio_mm": float(cilindro.Radius()),
                 "eje": [float(eje.X()), float(eje.Y()), float(eje.Z())],
                 "origen_eje_mm": [float(origen.X()), float(origen.Y()), float(origen.Z())]}
        duplicado = False
        for previo in encontrados:
            mismo_radio = abs(previo["radio_mm"] - datos["radio_mm"]) < 0.01
            paralelo = abs(float(np.dot(previo["eje"], datos["eje"]))) > 0.999
            delta = np.asarray(datos["origen_eje_mm"]) - np.asarray(previo["origen_eje_mm"])
            distancia_ejes = np.linalg.norm(delta - np.dot(delta, previo["eje"]) * np.asarray(previo["eje"]))
            if mismo_radio and paralelo and distancia_ejes < 0.02:
                duplicado = True
                break
        if not duplicado:
            encontrados.append(datos)
    return encontrados


def _verificar_agujeros(plan: dict, cilindros: list[dict]) -> dict:
    features = {}
    for feature in plan.get("features", []):
        tipo = str(feature.get("tipo", "")).casefold()
        if not any(termino in tipo for termino in ("hole", "agujero")):
            continue
        feature_id = feature.get("feature_id")
        if not isinstance(feature_id, str):
            continue
        dimensiones = feature.get("dimensiones") or {}
        dimension = next((d for n, d in dimensiones.items()
                          if n.casefold() in {"diameter", "diametro", "diámetro"}
                          and isinstance(d, dict) and isinstance(d.get("valor"), (int, float))), None)
        cantidad_dimension = next((d for n, d in dimensiones.items()
                          if n.casefold() in {"count", "cantidad", "number"}
                          and isinstance(d, dict) and isinstance(d.get("valor"), (int, float))), None)
        esperado = float(dimension["valor"]) if dimension else None
        cantidad_esperada = float(cantidad_dimension["valor"]) if cantidad_dimension else None
        eje_esperado = feature.get("eje")
        posicion = feature.get("posicion") or {}
        posicion_esperada = [posicion.get(eje, {}).get("valor") for eje in ("x", "y", "z")]
        candidatos = []
        for cilindro in cilindros:
            if eje_esperado and isinstance(eje_esperado, (list, tuple)) and len(eje_esperado) == 3:
                alineacion = abs(float(np.dot(cilindro["eje"], np.asarray(eje_esperado, dtype=float))))
                if alineacion < 0.98:
                    continue
            if all(isinstance(valor, (int, float)) for valor in posicion_esperada):
                delta = np.asarray(posicion_esperada) - np.asarray(cilindro["origen_eje_mm"])
                eje = np.asarray(cilindro["eje"])
                if np.linalg.norm(delta - np.dot(delta, eje) * eje) > 0.5:
                    continue
            candidatos.append(cilindro)
        features[feature_id] = {"estado": "calculated", "verification_status": "calculated",
                                "cantidad": len(candidatos),
                                "cantidad_esperada": cantidad_esperada,
                                "diametro_esperado_mm": esperado,
                                "diametro_mm": 2 * candidatos[0]["radio_mm"] if candidatos else None,
                                "diametros_observados_mm": sorted(2 * c["radio_mm"] for c in candidatos),
                                "cilindros_verificados": candidatos,
                                "algoritmo": "OCP BRepAdaptor_Surface CYLINDER; normal interior, agrupación por radio y eje",
                                "unidad": "mm", "numero_muestras": len(cilindros),
                                "semilla": None, "tolerancia": 0.15,
                                "perfil": "ciel-quality-metrics-v2", "version": "ciel-quality-metrics-v2"}
    for feature in plan.get("features", []):
        identificador = feature.get("feature_id")
        if isinstance(identificador, str) and identificador not in features:
            features[identificador] = {
                "estado": "unsupported", "verification_status": "unsupported",
                "motivo": "No existe una medición B-Rep fiable para este tipo de feature",
                "algoritmo": "sin medición determinista", "unidad": "unitless",
                "numero_muestras": None, "semilla": None, "tolerancia": None,
                "perfil": "ciel-quality-metrics-v2", "version": "ciel-quality-metrics-v2",
            }
    for criterio in plan.get("criterios_verificables", []):
        if criterio.get("medicion") not in {"hole_count", "hole_diameter"}:
            continue
        identificador = criterio.get("feature_id") or criterio.get("identificador")
        if identificador in features and features[identificador]["estado"] == "calculated":
            continue
        diametros = sorted(2 * c["radio_mm"] for c in cilindros)
        if criterio.get("medicion") == "hole_diameter" and len({round(d, 3) for d in diametros}) != 1:
            features[identificador] = {"estado": "unsupported", "verification_status": "unsupported",
                "motivo": "No hay un diámetro único atribuible al criterio global",
                "algoritmo": "OCP; diámetro de cilindros interiores", "unidad": "mm",
                "numero_muestras": len(cilindros), "semilla": None,
                "tolerancia": criterio.get("tolerancia"),
                "perfil": "ciel-quality-metrics-v2", "version": "ciel-quality-metrics-v2"}
            continue
        features[identificador] = {"estado": "calculated", "verification_status": "calculated",
                                   "cantidad": len(cilindros),
                                   "diametro_mm": diametros[0] if diametros else None,
                                   "diametros_observados_mm": sorted(2 * c["radio_mm"] for c in cilindros),
                                   "algoritmo": "Conteo de cilindros interiores B-Rep deduplicados",
                                   "unidad": "mm" if criterio.get("medicion") == "hole_diameter" else "unitless",
                                   "numero_muestras": len(cilindros),
                                   "semilla": None, "tolerancia": criterio.get("tolerancia"),
                                   "perfil": "ciel-quality-metrics-v2", "version": "ciel-quality-metrics-v2"}
    return features


def _comparar_superficies(forma, referencia, malla_a, malla_b,
                         orientacion_frente: str = "+Y") -> dict:
    resultado = comparar(forma, referencia, malla_a, malla_b)
    puntos_a = muestrear_superficie(malla_a, PUNTOS_CHAMFER, SEMILLA_CHAMFER)
    puntos_b = muestrear_superficie(malla_b, PUNTOS_CHAMFER, SEMILLA_CHAMFER)
    cercanos_b, _ = cKDTree(puntos_b).query(puntos_a, k=1)
    cercanos_a, _ = cKDTree(puntos_a).query(puntos_b, k=1)
    hausdorff = {f"p{percentil}": float(max(np.percentile(cercanos_b, percentil),
                                             np.percentile(cercanos_a, percentil)))
                 for percentil in (95, 99)}
    hausdorff["maximo"] = float(max(cercanos_b.max(), cercanos_a.max()))
    centroides = np.asarray(forma.Center().toTuple()) - np.asarray(referencia.Center().toTuple())
    area_referencia = float(referencia.Area())
    caja_a, caja_b = forma.BoundingBox(), referencia.BoundingBox()
    dimensiones_a = np.asarray([caja_a.xlen, caja_a.ylen, caja_a.zlen], dtype=float)
    dimensiones_b = np.asarray([caja_b.xlen, caja_b.ylen, caja_b.zlen], dtype=float)
    # Muestras estables en vértices; la métrica se etiqueta como aproximación por vértices.
    indices_vertices_a = np.linspace(0, len(malla_a.vertices) - 1,
                                     min(PUNTOS_CHAMFER, len(malla_a.vertices)), dtype=np.int64)
    indices_vertices_b = np.linspace(0, len(malla_b.vertices) - 1,
                                     min(PUNTOS_CHAMFER, len(malla_b.vertices)), dtype=np.int64)
    puntos_vertices_a = malla_a.vertices[indices_vertices_a]
    puntos_vertices_b = malla_b.vertices[indices_vertices_b]
    normales_a = malla_a.vertex_normals[indices_vertices_a]
    normales_b = malla_b.vertex_normals[indices_vertices_b]
    _, cercanos_ab = cKDTree(puntos_vertices_b).query(puntos_vertices_a, k=1)
    _, cercanos_ba = cKDTree(puntos_vertices_a).query(puntos_vertices_b, k=1)
    acuerdo_ab = np.sum(normales_a * normales_b[cercanos_ab], axis=1)
    acuerdo_ba = np.sum(normales_b * normales_a[cercanos_ba], axis=1)
    normal_consistency = float((np.maximum(0, acuerdo_ab).mean() + np.maximum(0, acuerdo_ba).mean()) / 2)
    diferencias_caja = {e: abs(float(a) - float(b)) for e, a, b in zip("xyz", dimensiones_a, dimensiones_b)}
    diferencias_caja = {e: 0.0 if valor < 1e-9 else valor for e, valor in diferencias_caja.items()}
    error_centroide = float(np.linalg.norm(centroides))
    if error_centroide < 1e-9:
        error_centroide = 0.0
    resultado.update({
        "bounding_box_error_mm": diferencias_caja,
        "centroid_error_mm": error_centroide,
        "surface_area_error_relative": abs(float(forma.Area()) - area_referencia) / area_referencia
        if area_referencia else None,
        "hausdorff_robusto_mm": hausdorff,
        "normal_consistency": normal_consistency,
        "silhouette_iou": comparar_siluetas(malla_a, malla_b, orientacion_frente),
        "perfil_calidad": {"semilla": SEMILLA_CHAMFER, "puntos_superficie": PUNTOS_CHAMFER,
                           "normal_consistency": "dot normal orientada de vértices más cercanos; remuestreo por índice uniforme",
                           "version": "ciel-quality-metrics-v2"},
    })
    resultado["metadatos"] = {
        "iou_brep": metadatos_metrica("ratio", "Intersección / unión booleana B-Rep"),
        "chamfer_digital_mm2": metadatos_metrica("mm2", "Chamfer cuadrático bidireccional",
                                                 PUNTOS_CHAMFER, SEMILLA_CHAMFER),
        "diferencia_volumen_mm3": metadatos_metrica("mm3", "Diferencia de volumen B-Rep"),
        "bounding_box_error_mm": metadatos_metrica("mm", "Diferencia absoluta de cajas B-Rep por eje"),
        "centroid_error_mm": metadatos_metrica("mm", "Distancia euclídea de centroides B-Rep"),
        "surface_area_error_relative": metadatos_metrica("ratio", "Diferencia relativa de área B-Rep"),
        "hausdorff_robusto_mm": metadatos_metrica("mm", "P95/P99/máximo bidireccional de muestras STL",
                                                   PUNTOS_CHAMFER, SEMILLA_CHAMFER),
        "normal_consistency": metadatos_metrica("ratio", "Producto escalar de normales de vértices próximos",
                                                 min(len(indices_vertices_a), len(indices_vertices_b))),
        "silhouette_iou": metadatos_metrica("ratio", "IoU raster ortográfico de cuatro vistas", 4),
    }
    return resultado


def _simetrias(plan: dict, malla) -> dict:
    declaradas = plan.get("simetrias", [])
    if not declaradas:
        return {"estado": "not_applicable", "valor": None, "unidad": "ratio",
                "algoritmo": "El GeometricPlan no declara simetría objetivo"}
    origen = np.asarray((plan.get("sistema_coordenadas") or {}).get("origen", (0, 0, 0)), dtype=float)
    puntos = np.asarray(malla.vertices, dtype=float)
    if len(puntos) > PUNTOS_CHAMFER:
        puntos = puntos[np.linspace(0, len(puntos) - 1, PUNTOS_CHAMFER, dtype=np.int64)]
    diagon = max(float(np.linalg.norm(malla.extents)), 1e-9)
    resultados = []
    for declaracion in declaradas:
        eje = str(declaracion.get("eje", "")).casefold()
        if eje not in {"x", "y", "z"}:
            resultados.append({"estado": "unsupported", "eje": eje})
            continue
        reflejados = puntos.copy()
        indice = "xyz".index(eje)
        reflejados[:, indice] = 2 * origen[indice] - reflejados[:, indice]
        distancias = cKDTree(puntos).query(reflejados, k=1)[0]
        resultados.append({"estado": "calculated", "eje": eje,
                           "error_p95_mm": float(np.percentile(distancias, 95)),
                           "error_p99_mm": float(np.percentile(distancias, 99)),
                           "score": max(0.0, 1.0 - float(np.percentile(distancias, 95)) / diagon),
                           "algoritmo": "Distancia del vecino más cercano tras reflexión; STL de detalle-v2"})
    disponibles = [r["score"] for r in resultados if r.get("estado") == "calculated"]
    return {"estado": "calculated" if disponibles else "not_available",
            "valor": float(np.mean(disponibles)) if disponibles else None,
            "por_eje": resultados, "unidad": "ratio", "muestras": len(puntos),
            "semilla": None, "perfil": "ciel-quality-metrics-v2",
            "version": VERSION_METRICAS_CALIDAD, "tolerancia": None}


@aplicacion.get("/salud")
def salud() -> dict:
    return {"estado": "disponible"}


@aplicacion.post("/inspeccionar-calidad")
def inspeccionar_calidad(solicitud: SolicitudInspeccionCalidad) -> dict:
    """Mide el CAD candidato y crea evidencia multivista; no entrega STEP al proveedor IA."""
    if not {"pieza.step", "pieza.stl"}.issubset(solicitud.archivos):
        raise HTTPException(422, "La inspección requiere STEP y STL")
    try:
        with tempfile.TemporaryDirectory(prefix="ciel-calidad-") as directorio:
            ruta_step = Path(directorio) / "pieza.step"
            ruta_stl = Path(directorio) / "pieza.stl"
            for nombre, ruta in (("pieza.step", ruta_step), ("pieza.stl", ruta_stl)):
                contenido = base64.b64decode(solicitud.archivos[nombre], validate=True)
                if not contenido or len(contenido) > 20_000_000:
                    raise ValueError(f"{nombre} vacío o supera 20 MB")
                ruta.write_bytes(contenido)
            forma = leer_forma(ruta_step)
            malla = leer_malla(ruta_stl)
            if not np.isfinite(malla.vertices).all():
                raise ValueError("STL contiene coordenadas no finitas")
            topologia = analizar_malla(ruta_stl)
            geometria = _cajas(forma)
            geometria.update({"technical_success": True,
                              "watertight": topologia["watertight"],
                              "dang_el": topologia["dang_el"],
                              "componentes_malla": topologia["componentes"],
                              "stl_sha256": topologia["sha256"],
                              "step_sha256": hashlib.sha256(ruta_step.read_bytes()).hexdigest()})
            geometria["metadatos"].update({
                "watertight": metadatos_metrica("boolean", "trimesh is_watertight"),
                "dang_el": metadatos_metrica("count", "Aristas STL con incidencia distinta de dos"),
                "componentes_malla": metadatos_metrica("count", "trimesh split"),
            })
            cilindros = _cilindros(forma)
            geometria["features"] = _verificar_agujeros(solicitud.plan_geometrico, cilindros)
            geometria["cylinders_detected"] = len(cilindros)
            geometria["symmetry"] = _simetrias(solicitud.plan_geometrico, malla)
            orientacion_frente = (solicitud.plan_geometrico.get("sistema_coordenadas") or {}).get(
                "orientacion_frente", "+Y"
            )
            lamina, perfil_render = renderizar_lamina(malla, orientacion_frente)
            comparacion_referencia = {
                "estado": "not_available", "motivo": "No se autorizó una referencia para este protocolo"
            }
            if solicitud.usar_referencia and os.environ.get("QUALITY_ALLOW_REFERENCE_METRICS") == "1":
                if not solicitud.caso_identificador:
                    comparacion_referencia = {"estado": "not_available", "motivo": "No hay caso asociado"}
                else:
                    ruta_ref = ruta_referencia(solicitud.caso_identificador)
                    referencia = leer_forma(ruta_ref)
                    ruta_ref_malla = Path(directorio) / "referencia.stl"
                    cq.exporters.export(referencia, str(ruta_ref_malla), exportType="STL",
                                        tolerance=0.1, angularTolerance=0.1)
                    malla_ref = leer_malla(ruta_ref_malla)
                    comparacion_referencia = _comparar_superficies(
                        forma, referencia, malla, malla_ref, orientacion_frente
                    )
                    comparacion_referencia["referencia_sha256"] = hashlib.sha256(ruta_ref.read_bytes()).hexdigest()
                    comparacion_referencia["protocolo"] = "quality-v2-reference-authorized"
            elif solicitud.usar_referencia:
                comparacion_referencia = {
                    "estado": "not_available",
                    "motivo": "La referencia está deshabilitada en QUALITY_ALLOW_REFERENCE_METRICS",
                }
            return {
                "technical_success": True,
                "geometric_metrics": geometria,
                "reference_metrics": comparacion_referencia,
                "multiview_png_base64": base64.b64encode(lamina).decode("ascii"),
                "multiview_profile": perfil_render,
            }
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(422, f"No se pudo inspeccionar el CAD: {type(error).__name__}") from None


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
        if os.environ.get("CIEL_MODO_NATIVO") == "1":
            respuesta["geometria"] = _cajas(forma)
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


@aplicacion.post('/vistas-biblioteca')
def vistas_biblioteca(solicitud: SolicitudVerificacion) -> dict:
    from evaluador.renderizado import renderizar_biblioteca
    try:
        bruto = base64.b64decode(solicitud.archivos['pieza.stl'], validate=True)
        if len(bruto) > 20_000_000:
            raise ValueError('STL demasiado grande')
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'pieza.stl'
            ruta.write_bytes(bruto)
            archivos, perfil = renderizar_biblioteca(leer_malla(ruta))
        return {'archivos': {n: base64.b64encode(b).decode('ascii') for n, b in archivos.items()}, 'perfil': perfil}
    except (ValueError, KeyError) as error:
        raise HTTPException(422, 'STL ausente o inválido') from error
