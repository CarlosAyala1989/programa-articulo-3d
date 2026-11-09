"""Protocolo físico v1: registro rígido y distancias de superficie en milímetros.

No aplica escala de ajuste, no elimina puntos en las métricas y no interpreta
la precisión comercial del escáner como incertidumbre de la medición.
"""

import hashlib
import itertools
import importlib.metadata
import json
import math
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree

VERSION = 'ciel-metrologia-otter-v1'
VERSION_ACTUAL = 'ciel-metrologia-otter-v2'
SEMILLA = 20261106
FACTORES_MM = {'mm': 1.0, 'cm': 10.0, 'm': 1000.0, 'in': 25.4}
FORMATOS = {'.stl', '.obj', '.ply', '.pcd', '.asc', '.xyz'}
MAXIMO_VERTICES = 5_000_000


def leer_pcd(ruta: Path) -> np.ndarray:
    """PCD ASCII/binario sin comprimir; conserva los XYZ, omite otros campos."""
    with ruta.open('rb') as archivo:
        cabecera = {}
        for _ in range(100):
            linea = archivo.readline(65536).decode('ascii').strip()
            if not linea or linea.startswith('#'):
                continue
            clave, *valores = linea.split()
            cabecera[clave.upper()] = valores
            if clave.upper() == 'DATA':
                break
        else:
            raise ValueError('Cabecera PCD inválida.')
        campos = cabecera.get('FIELDS', [])
        if not {'x', 'y', 'z'}.issubset(campos):
            raise ValueError('El PCD debe contener campos x, y, z.')
        cantidad = int(cabecera.get('POINTS', ['0'])[0])
        if not 30 <= cantidad <= MAXIMO_VERTICES:
            raise ValueError('El PCD debe contener entre 30 y 5.000.000 puntos.')
        modo = cabecera['DATA'][0]
        if modo == 'ascii':
            datos = np.loadtxt(archivo, max_rows=MAXIMO_VERTICES + 1, ndmin=2)
            indices, desplazamiento = {}, 0
            for campo, cuenta in zip(campos, cabecera.get('COUNT', ['1'] * len(campos))):
                indices[campo] = desplazamiento
                desplazamiento += int(cuenta)
            return datos[:, [indices[c] for c in ('x', 'y', 'z')]]
        if modo != 'binary':
            raise ValueError('Exporta el PCD como ASCII o binario sin comprimir, o utiliza PLY.')
        mapa = {('F', 4): '<f4', ('F', 8): '<f8', ('U', 1): 'u1', ('U', 2): '<u2',
                ('U', 4): '<u4', ('I', 1): 'i1', ('I', 2): '<i2', ('I', 4): '<i4'}
        tipos = []
        for campo, tipo, tamano, cuenta in zip(campos, cabecera['TYPE'], cabecera['SIZE'],
                                              cabecera.get('COUNT', ['1'] * len(campos))):
            tipos.append((campo, mapa[(tipo, int(tamano))], (int(cuenta),)))
        datos = np.frombuffer(archivo.read(), dtype=np.dtype(tipos), count=cantidad)
        return np.column_stack([datos[c][:, 0] for c in ('x', 'y', 'z')])


def cargar_geometria(ruta: Path, factor: float = 1.0):
    extension = ruta.suffix.lower()
    if extension not in FORMATOS:
        raise ValueError('Usa un archivo STL, OBJ, PLY, PCD, ASC o XYZ.')
    if extension == '.pcd':
        geometria = trimesh.points.PointCloud(leer_pcd(ruta))
    elif extension in {'.asc', '.xyz'}:
        puntos = np.loadtxt(ruta, max_rows=MAXIMO_VERTICES + 1, ndmin=2)
        if puntos.shape[1] < 3:
            raise ValueError('La nube debe contener tres columnas XYZ.')
        geometria = trimesh.points.PointCloud(puntos[:, :3])
    else:
        # El OBJ se lee sin texturas ni resolutores de archivos externos.
        with ruta.open('rb') as archivo:
            geometria = trimesh.load(archivo, file_type=extension[1:], process=False,
                                     resolver=None, skip_materials=True)
        if isinstance(geometria, trimesh.Scene):
            partes = geometria.dump()
            if not len(partes):
                raise ValueError('El archivo no contiene geometría.')
            if all(isinstance(p, trimesh.Trimesh) for p in partes):
                geometria = trimesh.util.concatenate(partes)
            else:
                geometria = trimesh.points.PointCloud(np.vstack([p.vertices for p in partes]))
    puntos = np.asarray(geometria.vertices, dtype=float)
    if not 30 <= len(puntos) <= MAXIMO_VERTICES or not np.isfinite(puntos).all():
        # Un STL muy simple puede tener ocho vértices: una malla válida sí se admite.
        if not (isinstance(geometria, trimesh.Trimesh) and 4 <= len(puntos) <= MAXIMO_VERTICES
                and np.isfinite(puntos).all()):
            raise ValueError('Geometría vacía, demasiado grande o con coordenadas no finitas.')
    if np.linalg.norm(np.ptp(puntos, axis=0)) <= 1e-8:
        raise ValueError('La geometría tiene tamaño nulo.')
    geometria.vertices = puntos * factor
    if isinstance(geometria, trimesh.Trimesh):
        if len(geometria.faces) == 0 or len(geometria.faces) > 5_000_000 or geometria.area <= 0:
            raise ValueError('La malla no contiene una superficie válida.')
        if len(np.unique(geometria.faces)) < len(geometria.vertices):
            # Conservar también puntos aislados del archivo para el Hausdorff
            # discreto v2; la superficie v1 mantiene su interpretación histórica.
            geometria.metadata['puntos_importados_hausdorff'] = np.array(geometria.vertices, copy=True)
        geometria.remove_unreferenced_vertices()
        # Unir vértices duplicados del STL permite evaluar su cierre sin reparar huecos.
        geometria.merge_vertices()
    return geometria


def muestrear(geometria, cantidad: int, semilla: int) -> np.ndarray:
    azar = np.random.default_rng(semilla)
    if not isinstance(geometria, trimesh.Trimesh):
        puntos = np.asarray(geometria.vertices)
        return puntos[azar.choice(len(puntos), min(cantidad, len(puntos)), replace=False)]
    areas = geometria.area_faces
    caras = azar.choice(len(areas), cantidad, p=areas / areas.sum())
    triangulos = geometria.triangles[caras]
    u, v = azar.random((2, cantidad))
    raiz = np.sqrt(u)
    return ((1 - raiz)[:, None] * triangulos[:, 0] +
            (raiz * (1 - v))[:, None] * triangulos[:, 1] + (raiz * v)[:, None] * triangulos[:, 2])


def transformar(puntos: np.ndarray, matriz: np.ndarray) -> np.ndarray:
    return puntos @ matriz[:3, :3].T + matriz[:3, 3]


def ajuste_rigido(origen: np.ndarray, destino: np.ndarray) -> np.ndarray:
    if len(origen) < 3 or np.linalg.matrix_rank(origen - origen.mean(axis=0)) < 2:
        raise ValueError('La alineación necesita al menos tres puntos no colineales.')
    a, b = origen.mean(axis=0), destino.mean(axis=0)
    u, _, vt = np.linalg.svd((origen - a).T @ (destino - b))
    correccion = np.eye(3)
    correccion[2, 2] = np.linalg.det(vt.T @ u.T)
    rotacion = vt.T @ correccion @ u.T
    matriz = np.eye(4)
    matriz[:3, :3], matriz[:3, 3] = rotacion, b - rotacion @ a
    return matriz


def icp(origen: np.ndarray, destino: np.ndarray, inicial: np.ndarray,
        umbral: float, iteraciones: int = 50) -> tuple[np.ndarray, int]:
    arbol = cKDTree(destino)
    matriz, anterior, total = inicial.copy(), math.inf, 0
    for multiplicador in (4, 2, 1):
        for _ in range(iteraciones):
            movidos = transformar(origen, matriz)
            distancias, indices = arbol.query(movidos, workers=1)
            validos = distancias <= umbral * multiplicador
            if validos.sum() < 12:
                break
            # Recorte SOLO del registro; las métricas posteriores conservan todos los puntos.
            corte = np.quantile(distancias[validos], .90)
            validos &= distancias <= corte + 1e-12
            cambio = ajuste_rigido(movidos[validos], destino[indices[validos]])
            matriz = cambio @ matriz
            error = float(np.mean(distancias[validos] ** 2))
            total += 1
            if abs(anterior - error) < 1e-10:
                break
            anterior = error
    return matriz, total


def alinear(escaneo: np.ndarray, nominal: np.ndarray, configuracion: dict) -> tuple[np.ndarray, dict]:
    umbral = configuracion['umbral_icp_mm']
    modo = configuracion.get('alineacion', 'automatica')
    if modo == 'conservar':
        return np.eye(4), {'metodo': 'Coordenadas conservadas por el usuario', 'iteraciones': 0}
    pares = configuracion.get('puntos_pareados') or []
    if modo == 'puntos':
        if len(pares) < 3:
            raise ValueError('Indica al menos tres pares de puntos correspondientes.')
        inicial = ajuste_rigido(np.array([p['escaneo'] for p in pares]) * FACTORES_MM[configuracion['unidad']],
                               np.array([p['nominal'] for p in pares]))
        matriz, total = icp(escaneo, nominal, inicial, umbral)
        return matriz, {'metodo': 'Pares de puntos + ICP rígido', 'iteraciones': total}
    a, b = escaneo.mean(axis=0), nominal.mean(axis=0)
    _, bases_a = np.linalg.eigh(np.cov((escaneo - a).T))
    _, bases_b = np.linalg.eigh(np.cov((nominal - b).T))
    candidatos = []
    arbol = cKDTree(nominal)
    for permutacion in itertools.permutations(range(3)):
        for signos in itertools.product((-1, 1), repeat=3):
            rotacion = bases_b[:, permutacion] @ np.diag(signos) @ bases_a.T
            if np.linalg.det(rotacion) < .99:
                continue
            matriz = np.eye(4)
            matriz[:3, :3], matriz[:3, 3] = rotacion, b - rotacion @ a
            distancias = arbol.query(transformar(escaneo, matriz), workers=1)[0]
            candidatos.append((float(np.mean(np.sort(distancias)[:max(12, int(.9 * len(distancias)))] ** 2)), matriz))
    identidad = np.eye(4)
    identidad[:3, 3] = b - a
    candidatos.append((float(np.mean(arbol.query(transformar(escaneo, identidad))[0] ** 2)), identidad))
    mejor, error_mejor, total_mejor = None, math.inf, 0
    for _, inicial in sorted(candidatos, key=lambda p: p[0])[:5]:
        matriz, total = icp(escaneo, nominal, inicial, umbral, 30)
        distancias = arbol.query(transformar(escaneo, matriz), workers=1)[0]
        error = float(np.mean(np.sort(distancias)[:max(12, int(.9 * len(distancias)))] ** 2))
        if error < error_mejor:
            mejor, error_mejor, total_mejor = matriz, error, total
    return mejor, {'metodo': '24 orientaciones PCA + ICP rígido multiumbral', 'iteraciones': total_mejor,
                   'recorte_solo_registro_pct': 10}


def distancias_superficie(puntos: np.ndarray, geometria) -> tuple[np.ndarray, np.ndarray | None]:
    if not isinstance(geometria, trimesh.Trimesh):
        return cKDTree(geometria.vertices).query(puntos, workers=1)[0], None
    distancias, signos = [], []
    for inicio in range(0, len(puntos), 512):
        bloque = puntos[inicio:inicio + 512]
        cercanos, valores, caras = trimesh.proximity.closest_point(geometria, bloque)
        distancias.append(valores)
        signos.append(np.sum((bloque - cercanos) * geometria.face_normals[caras], axis=1))
    return np.concatenate(distancias), np.concatenate(signos)


def refinar_superficie(puntos: np.ndarray, nominal, matriz: np.ndarray, umbral: float) -> tuple[np.ndarray, int]:
    """ICP con correspondencias en triángulos: evita ajustar al ruido del muestreo nominal."""
    if not isinstance(nominal, trimesh.Trimesh):
        return matriz, 0
    anterior = math.inf
    for iteracion in range(80):
        movidos = transformar(puntos, matriz)
        cercanos, distancias, _ = trimesh.proximity.closest_point(nominal, movidos)
        validos = distancias <= umbral
        if validos.sum() < 12:
            break
        # El refinamiento usa todas las correspondencias dentro del umbral.
        # Recortar las caras de mayor error sesgaría el ajuste de una pieza contraída.
        cambio = ajuste_rigido(movidos[validos], cercanos[validos])
        matriz = cambio @ matriz
        error = float(np.mean(distancias[validos] ** 2))
        if abs(anterior - error) < 1e-12:
            return matriz, iteracion + 1
        anterior = error
    return matriz, iteracion + 1


def resumen_cotas(cotas: list[dict]) -> tuple[list[dict], dict]:
    filas, deltas = [], []
    for cota in cotas:
        mediciones = np.asarray(cota['mediciones_mm'], dtype=float)
        errores = mediciones - cota['nominal_mm']
        deltas.extend(errores.tolist())
        filas.append({**cota, 'n': len(mediciones), 'medido_media_mm': float(mediciones.mean()),
                      'delta_media_mm': float(errores.mean()),
                      'delta_desviacion_estandar_mm': float(errores.std(ddof=1)) if len(errores) > 1 else None})
    return filas, {'n_mediciones': len(deltas), 'delta_media_mm': float(np.mean(deltas)) if deltas else None,
                   'delta_absoluto_medio_mm': float(np.mean(np.abs(deltas))) if deltas else None,
                   'delta_desviacion_estandar_mm': float(np.std(deltas, ddof=1)) if len(deltas) > 1 else None}


def hausdorff_discreto(a: np.ndarray, b: np.ndarray) -> float:
    """Máximo bidireccional exacto de los conjuntos XYZ completos, sin recorte."""
    maximos = []
    for origen, destino in ((a, b), (b, a)):
        arbol = cKDTree(destino)
        maximo = 0.0
        for inicio in range(0, len(origen), 65536):
            maximo = max(maximo, float(arbol.query(origen[inicio:inicio + 65536], workers=1)[0].max()))
        maximos.append(maximo)
    return max(maximos)


def calcular(nominal, escaneo, configuracion: dict) -> tuple[dict, np.ndarray, np.ndarray]:
    if configuracion.get('protocolo', VERSION) not in {VERSION, VERSION_ACTUAL}:
        raise ValueError('Protocolo de metrología no compatible.')
    cantidad = configuracion.get('muestras', 20000)
    p_nominal = muestrear(nominal, cantidad, SEMILLA)
    p_escaneo = muestrear(escaneo, cantidad, SEMILLA + 1)
    if len(p_escaneo) < 30:
        raise ValueError('El escaneo necesita al menos 30 puntos o una superficie con área positiva.')
    # La elección explícita de unidades ocurre antes del registro, nunca se estima una escala.
    diagonal = float(np.linalg.norm(np.ptp(p_nominal, axis=0)))
    razon = float(np.linalg.norm(np.ptp(p_escaneo, axis=0)) / diagonal)
    if not .2 <= razon <= 5:
        raise ValueError('El tamaño del escaneo difiere mucho del modelo. Comprueba las unidades y retira la base de escaneo.')
    matriz, registro = alinear(p_escaneo[:5000], p_nominal[:5000], configuracion)
    if configuracion.get('alineacion', 'automatica') != 'conservar':
        matriz, iteraciones = refinar_superficie(p_escaneo[:5000], nominal, matriz, configuracion['umbral_icp_mm'])
        registro['iteraciones_superficie'] = iteraciones
    if not np.isfinite(matriz).all() or abs(np.linalg.det(matriz[:3, :3]) - 1) > 1e-5:
        raise ValueError('No se obtuvo una transformación rígida válida.')
    alineado = escaneo.copy()
    alineado.apply_transform(matriz)
    puntos = transformar(p_escaneo, matriz)
    hacia_nominal, signos = distancias_superficie(puntos, nominal)
    hacia_escaneo, _ = distancias_superficie(p_nominal, alineado)
    tolerancia = configuracion['tolerancia_mm']
    cobertura = float(100 * np.mean(hacia_escaneo <= configuracion['umbral_icp_mm']))
    coincidencia = float(100 * np.mean(hacia_nominal <= configuracion['umbral_icp_mm']))
    if cobertura < 20 or coincidencia < 20:
        raise ValueError('La alineación tiene poca coincidencia. Recorta la mesa en CrealityScan o utiliza puntos correspondientes.')
    firmado = bool(isinstance(nominal, trimesh.Trimesh) and nominal.is_watertight
                   and nominal.is_winding_consistent and nominal.volume > 0)
    desviaciones = hacia_nominal * np.where(signos >= 0, 1, -1) if firmado else hacia_nominal
    cotas, dimensional = resumen_cotas(configuracion.get('cotas', []))
    envolvente_nominal = np.ptp(nominal.vertices, axis=0)
    envolvente_escaneo = np.ptp(alineado.vertices, axis=0)
    resultado = {
        'protocolo': VERSION, 'unidad': 'mm', 'semilla': SEMILLA, 'escala_ajuste': 1.0,
        'bibliotecas': {nombre: importlib.metadata.version(nombre) for nombre in ('numpy', 'scipy', 'trimesh', 'rtree', 'Pillow')},
        'transformacion_escaneo_a_nominal': matriz.tolist(), 'registro': registro,
        'muestras_nominal': len(p_nominal), 'muestras_escaneo': len(puntos),
        'tipo_escaneo': 'malla' if isinstance(escaneo, trimesh.Trimesh) else 'nube_de_puntos',
        'metodo_distancias': 'Puntos muestreados a triángulos de superficie; hacia nube: vecino más próximo',
        'hausdorff_maximo_mm': float(max(hacia_nominal.max(), hacia_escaneo.max())),
        'hausdorff_p95_mm': float(max(np.percentile(hacia_nominal, 95), np.percentile(hacia_escaneo, 95))),
        'chamfer_fisico_mm2': float(np.mean(hacia_nominal ** 2) + np.mean(hacia_escaneo ** 2)),
        'chamfer_medio_mm': float((hacia_nominal.mean() + hacia_escaneo.mean()) / 2),
        'desviacion_absoluta_media_mm': float(hacia_nominal.mean()),
        'desviacion_estandar_superficie_mm': float(desviaciones.std(ddof=1)),
        'rmse_superficie_mm': float(np.sqrt(np.mean(hacia_nominal ** 2))),
        'dentro_tolerancia_pct': float(100 * np.mean(hacia_nominal <= tolerancia)),
        'cobertura_nominal_pct': cobertura, 'coincidencia_escaneo_pct': coincidencia,
        'mapa_firmado': firmado, 'mapa_limite_mm': configuracion['mapa_limite_mm'],
        'tolerancia_mm': tolerancia, 'cotas_criticas': cotas, 'error_dimensional': dimensional,
        'envolvente_mm': [{'eje': eje, 'nominal_mm': float(a), 'escaneo_mm': float(b), 'delta_mm': float(b - a)}
                          for eje, a, b in zip('XYZ', envolvente_nominal, envolvente_escaneo)],
        'limitaciones': ['Hausdorff y Chamfer estimados mediante muestreo de superficies; no son máximos continuos certificados.',
                         'El registro ICP es un ajuste global; revisa la superposición antes de confirmar.',
                         'Las cotas críticas proceden de las mediciones declaradas; la envolvente no mide agujeros ni espesores.',
                         'La precisión nominal del Otter no se utiliza como incertidumbre ni tolerancia.'],
    }
    if configuracion.get('protocolo') == VERSION_ACTUAL:
        from evaluador.cotas_automaticas import medir_cotas
        resultado['protocolo'] = VERSION_ACTUAL
        resultado['hausdorff_superficie_muestreado_mm'] = resultado['hausdorff_maximo_mm']
        vertices_nominal = np.asarray(nominal.metadata.get('puntos_importados_hausdorff', nominal.vertices))
        vertices_escaneo = transformar(np.asarray(escaneo.metadata.get('puntos_importados_hausdorff', escaneo.vertices)), matriz)
        resultado['hausdorff_maximo_mm'] = hausdorff_discreto(vertices_nominal, vertices_escaneo)
        resultado['hausdorff_alcance'] = 'Discreto exacto, todos los vértices/puntos importados; dependiente de la densidad de discretización'
        resultado['puntos_hausdorff_nominal'] = len(vertices_nominal)
        resultado['puntos_hausdorff_escaneo'] = len(vertices_escaneo)
        resultado['limitaciones'][0] = ('Hausdorff discreto usa todos los puntos/vértices y depende de su densidad. '
            'El máximo de superficie, P95 y Chamfer se estiman por muestreo; no hay máximo continuo certificado.')
        plan = configuracion.get('plan_cotas')
        if plan:
            automaticas = medir_cotas(alineado, plan, configuracion.get('banda_cotas_mm', .5), SEMILLA + 2)
            resultado['cotas_automaticas'] = automaticas
            validas = [{'nombre': c['nombre'], 'nominal_mm': c['nominal_mm'], 'mediciones_mm': [c['medido_mm']],
                        'metodo': c['metodo']} for c in automaticas if c['estado'] == 'medida']
            _, resumen = resumen_cotas(validas)
            resultado['error_dimensional_declarado'] = dimensional
            resultado['error_dimensional'] = {**resumen, 'origen': 'cotas_automaticas',
                'alcance_desviacion': 'Dispersión de ΔD entre cotas de esta pieza; no repetibilidad del escáner',
                'cotas_planificadas': len(automaticas), 'cotas_medidas': len(validas),
                'completo': len(validas) == len(automaticas) and len(validas) > 0}
            resultado['limitaciones'][2] = ('Las cotas automáticas se ajustan en regiones del STL nominal; '
                'revisa su selección y cobertura. Una medida por cota no estima repetibilidad. '
                'Las medidas manuales se conservan por separado.')
    return resultado, puntos, desviaciones


def procesar_carpeta(carpeta: Path) -> dict:
    from evaluador.informes_metrologia import generar_archivos
    configuracion = json.loads((carpeta / 'configuracion.json').read_text(encoding='utf-8'))
    ruta_scan = carpeta / ('escaneo' + configuracion['extension'])
    ruta_nominal = carpeta / 'nominal.stl'
    for ruta, clave in ((ruta_scan, 'escaneo_sha256'), (ruta_nominal, 'nominal_sha256')):
        if hashlib.sha256(ruta.read_bytes()).hexdigest() != configuracion[clave]:
            raise ValueError('Un archivo cambió después de registrarse. Crea otra comparación con el archivo correcto.')
    if configuracion.get('plan_cotas'):
        from evaluador.cotas_automaticas import huella_plan, VERSION_COTAS
        plan = configuracion['plan_cotas']
        if (plan.get('protocolo') != VERSION_COTAS or plan.get('nominal_sha256') != configuracion['nominal_sha256']
                or huella_plan(plan) != configuracion.get('plan_cotas_sha256')):
            raise ValueError('El plan de cotas no corresponde al nominal o cambió su hash.')
    nominal = cargar_geometria(ruta_nominal)
    escaneo = cargar_geometria(ruta_scan, FACTORES_MM[configuracion['unidad']])
    resultado, puntos, desviaciones = calcular(nominal, escaneo, configuracion)
    generar_archivos(carpeta, nominal, puntos, desviaciones, resultado, configuracion)
    return resultado
