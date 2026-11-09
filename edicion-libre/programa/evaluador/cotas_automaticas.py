"""Cotas geométricas v1: planos opuestos y cilindros de la malla nominal.

Las regiones se fijan antes de medir el escaneo. No se usa la envolvente como
sustituto de agujeros ni se atribuye repetibilidad a un ajuste geométrico.
"""
import numpy as np
import trimesh
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from evaluador.protocolo_cotas import VERSION_COTAS, huella_plan


def base_eje(eje: np.ndarray) -> np.ndarray:
    auxiliar = np.eye(3)[np.argmin(abs(eje))]
    u = np.cross(eje, auxiliar); u /= np.linalg.norm(u)
    return np.column_stack([u, np.cross(eje, u), eje])


def eje_canonico(eje: np.ndarray) -> np.ndarray:
    eje = eje / np.linalg.norm(eje)
    return eje if eje[np.argmax(abs(eje))] > 0 else -eje


def region_plana(malla, caras, eje, base):
    puntos = malla.vertices[np.unique(malla.faces[caras])]
    xy = puntos @ base[:, :2]
    envolvente = ConvexHull(xy)
    return {'posicion': float(np.mean(puntos @ eje)),
            'poligono': xy[envolvente.vertices].tolist(), 'area_mm2': float(malla.area_faces[caras].sum())}


def proponer_cotas(malla, nominal_sha256: str) -> dict:
    if not isinstance(malla, trimesh.Trimesh):
        raise ValueError('El nominal debe ser una malla triangular.')
    propuestas, planos = [], []
    minimo_area = max(float(malla.area) * .002, 1e-6)
    for caras in malla.facets:
        if malla.area_faces[caras].sum() < minimo_area:
            continue
        eje = eje_canonico(malla.face_normals[caras[0]])
        base = base_eje(eje)
        planos.append((eje, base, region_plana(malla, caras, eje, base), malla.face_normals[caras[0]]))
    pares_vistos = set()
    # Planos opuestos con solapamiento en sus dos coordenadas locales.
    for i, (eje, base, a, normal) in enumerate(planos):
        for eje_b, _, b_original, normal_b in planos[i + 1:]:
            if np.dot(eje, eje_b) < 1 - 1e-7 or np.dot(normal, normal_b) > -.999:
                continue
            # Ambas regiones se expresan en la misma base canónica.
            a_xy, b_xy = np.array(a['poligono']), np.array(b_original['poligono'])
            if np.any(np.minimum(a_xy.max(0), b_xy.max(0)) - np.maximum(a_xy.min(0), b_xy.min(0)) <= 1e-6):
                continue
            distancia = abs(a['posicion'] - b_original['posicion'])
            if distancia <= 1e-5:
                continue
            clave = tuple(np.round(np.r_[eje, sorted([a['posicion'], b_original['posicion']])], 6))
            if clave in pares_vistos:
                continue
            pares_vistos.add(clave)
            propuestas.append({'tipo': 'distancia_planos', 'nombre': f'Separación entre planos {len(pares_vistos)}',
                'nominal_mm': distancia, 'eje': eje.tolist(), 'base': base.tolist(), 'regiones': [a, b_original]})
    # Cada componente suave es candidata a cilindro. Las aristas vivas separan las tapas.
    adyacencia = malla.face_adjacency
    suaves = adyacencia[malla.face_adjacency_angles < np.deg2rad(22)]
    grafo = coo_matrix((np.ones(len(suaves) * 2),
        (np.r_[suaves[:, 0], suaves[:, 1]], np.r_[suaves[:, 1], suaves[:, 0]])),
        shape=(len(malla.faces), len(malla.faces)))
    _, etiquetas = connected_components(grafo, directed=False)
    cilindros = 0
    for etiqueta in np.unique(etiquetas):
        caras = np.flatnonzero(etiquetas == etiqueta)
        if len(caras) < 20:
            continue
        normales = malla.face_normals[caras]
        valores, vectores = np.linalg.eigh(normales.T @ normales / len(normales))
        if valores[0] > .001 or valores[1] < .15:
            continue
        eje = eje_canonico(vectores[:, 0]); base = base_eje(eje)
        puntos = malla.vertices[np.unique(malla.faces[caras])]
        locales = puntos @ base
        xy = locales[:, :2]
        matriz = np.column_stack([2 * xy, np.ones(len(xy))])
        solucion = np.linalg.lstsq(matriz, (xy ** 2).sum(1), rcond=None)[0]
        centro = solucion[:2]; radio2 = solucion[2] + centro @ centro
        if radio2 <= 0:
            continue
        radio = float(np.sqrt(radio2)); residuos = np.linalg.norm(xy - centro, axis=1) - radio
        if np.max(abs(residuos)) > max(.002, radio * .0005):
            continue
        z = locales[:, 2]; longitud = float(np.ptp(z))
        if longitud < max(.05, radio * .02):
            continue
        radial = malla.triangles_center[caras] @ base[:, :2] - centro
        interior = np.median(np.sum(radial * (normales @ base[:, :2]), axis=1)) < 0
        cilindros += 1
        propuestas.append({'tipo': 'diametro', 'nombre': f'{"Agujero" if interior else "Cilindro exterior"} {cilindros} · diámetro',
            'nominal_mm': 2 * radio, 'eje': eje.tolist(), 'base': base.tolist(),
            'centro_xy': centro.tolist(), 'limites_z': [float(z.min()), float(z.max())],
            'interior': bool(interior)})
    propuestas.sort(key=lambda c: (c['tipo'] != 'diametro', -c['nominal_mm'], c['nombre']))
    propuestas = propuestas[:30]
    for i, cota in enumerate(propuestas):
        cota['codigo'] = f'C{i + 1:02d}'
    return {'protocolo': VERSION_COTAS, 'nominal_sha256': nominal_sha256, 'cotas': propuestas,
        'regiones_asociacion': [dict(c) for c in propuestas if c['tipo'] == 'diametro'],
        'origen_nominal': 'Geometría de la malla STL nominal; diámetros ajustados a sus vértices.',
        'limites': 'Detecta planos paralelos y cilindros completos. Roscas, dientes, conos y superficies libres necesitan un plan específico o medición complementaria.'}


def cobertura_angular(xy: np.ndarray) -> float:
    angulos = np.sort(np.mod(np.arctan2(xy[:, 1], xy[:, 0]), 2 * np.pi))
    return float(360 - np.rad2deg(np.diff(np.r_[angulos, angulos[0] + 2 * np.pi]).max()))


def medir_cotas(geometria, plan: dict, banda_mm: float, semilla: int) -> list[dict]:
    """Ajuste robusto local: banda de asociación explícita, mínimos de cobertura.

    Los planos usan área muestreada; los cilindros usan vértices de paredes laterales.
    El residuo del ajuste se informa separado de la desviación entre repeticiones.
    """
    from evaluador.metrologia import muestrear
    puntos = muestrear(geometria, 120000, semilla)
    if isinstance(geometria, trimesh.Trimesh):
        # Repite la selección determinista de caras del muestreo, sin búsquedas espaciales.
        azar = np.random.default_rng(semilla)
        caras = azar.choice(len(geometria.faces), len(puntos),
                            p=geometria.area_faces / geometria.area_faces.sum())
        normales = geometria.face_normals[caras]
    else:
        normales = None
    filas = []
    for cota in plan['cotas']:
        fila = {k: cota[k] for k in ('codigo', 'nombre', 'tipo', 'nominal_mm')}
        fila.update(estado='sin_cobertura', diagnostico='', medido_mm=None, delta_mm=None,
                    residuo_ajuste_rmse_mm=None, n_puntos=0)
        base = np.asarray(cota['base']); locales = puntos @ base
        normales_locales = normales @ base if normales is not None else None
        try:
            if cota['tipo'] == 'diametro':
                centro = np.asarray(cota['centro_xy']); radio = cota['nominal_mm'] / 2
                z0, z1 = cota['limites_z']; margen = (z1 - z0) * .12
                if isinstance(geometria, trimesh.Trimesh):
                    caras_laterales = abs(geometria.face_normals @ base[:, 2]) < .35
                    vertices_laterales = np.unique(geometria.faces[caras_laterales])
                    candidatos = np.asarray(geometria.vertices)[vertices_laterales] @ base
                    # Un STL CAD puede tener solo dos anillos de vértices. Son medidas
                    # de la pared, aunque coincidan con sus límites axiales.
                    margen = -banda_mm
                else:
                    candidatos = np.asarray(geometria.vertices) @ base
                radial = candidatos[:, :2] - centro
                mascara = ((abs(np.linalg.norm(radial, axis=1) - radio) <= banda_mm) &
                           (candidatos[:, 2] > z0 + margen) & (candidatos[:, 2] < z1 - margen))
                seleccion = candidatos[mascara]
                # Resolver escalones/avellanados: cada punto se asocia a la pared
                # nominal más cercana, aunque esa otra cota no esté seleccionada.
                propios = np.sqrt((np.linalg.norm(seleccion[:, :2] - centro, axis=1) - radio) ** 2 +
                    np.maximum(np.maximum(z0 - seleccion[:, 2], seleccion[:, 2] - z1), 0) ** 2)
                mundo = seleccion @ base.T
                conservar = np.ones(len(seleccion), dtype=bool)
                for otra in plan.get('regiones_asociacion', plan['cotas']):
                    if otra['tipo'] != 'diametro' or otra['codigo'] == cota['codigo']:
                        continue
                    otros = mundo @ np.asarray(otra['base'])
                    oz0, oz1 = otra['limites_z']
                    distancia = np.sqrt((np.linalg.norm(otros[:, :2] - otra['centro_xy'], axis=1) - otra['nominal_mm'] / 2) ** 2 +
                        np.maximum(np.maximum(oz0 - otros[:, 2], otros[:, 2] - oz1), 0) ** 2)
                    conservar &= propios <= distancia + 1e-8
                seleccion = seleccion[conservar]; fila['n_puntos'] = len(seleccion)
                if len(seleccion) < (16 if isinstance(geometria, trimesh.Trimesh) else 40):
                    raise ValueError('Pocos puntos en la pared cilíndrica; vuelve a escanear esa zona.')
                xy = seleccion[:, :2] - centro
                cobertura = cobertura_angular(xy); fila['cobertura_angular_grados'] = cobertura
                if cobertura < 270:
                    raise ValueError('La pared no cubre 270°; el diámetro queda sin medir.')
                def residuo(parametros):
                    return np.linalg.norm(seleccion[:, :2] - parametros[:2], axis=1) - parametros[2]
                ajuste = least_squares(residuo, np.r_[centro, radio], loss='soft_l1', f_scale=.02,
                    bounds=(np.r_[centro - banda_mm, max(1e-5, radio - banda_mm)],
                            np.r_[centro + banda_mm, radio + banda_mm]))
                valor = float(2 * ajuste.x[2]); residuos = residuo(ajuste.x)
                fila['metodo'] = 'Círculo robusto en sección perpendicular al eje nominal; banda local'
            else:
                posiciones, residuos_totales, cuentas = [], [], []
                for region in cota['regiones']:
                    xy = np.asarray(region['poligono']); ecuaciones = ConvexHull(xy).equations
                    mascara = abs(locales[:, 2] - region['posicion']) <= min(banda_mm, cota['nominal_mm'] * .45)
                    # Interior del polígono: evita aristas, paredes y rebabas del contorno.
                    mascara &= np.all(locales[:, :2] @ ecuaciones[:, :2].T + ecuaciones[:, 2] < -min(.1, banda_mm / 2), axis=1)
                    if normales_locales is not None:
                        mascara &= abs(normales_locales[:, 2]) > .95
                    seleccion = locales[mascara]
                    cuentas.append(len(seleccion))
                    if len(seleccion) < 40:
                        raise ValueError('Falta cobertura de uno de los dos planos; no se sustituye por la envolvente.')
                    if np.linalg.det(np.cov(seleccion[:, :2].T)) < 1e-8:
                        raise ValueError('Los puntos del plano son colineales.')
                    area = ConvexHull(seleccion[:, :2]).volume
                    if area < .25 * region['area_mm2']:
                        raise ValueError('La región plana cubre menos del 25 % del área nominal.')
                    matriz = np.column_stack([seleccion[:, :2], np.ones(len(seleccion))])
                    ajuste = least_squares(lambda p: matriz @ p - seleccion[:, 2],
                        [0, 0, region['posicion']], loss='soft_l1', f_scale=.02)
                    # Evaluar ambos planos en el mismo punto XY evita mezclar inclinación y espesor.
                    referencia = np.mean(np.asarray(cota['regiones'][0]['poligono']), axis=0)
                    posiciones.append(float(np.r_[referencia, 1] @ ajuste.x))
                    residuos_totales.extend((matriz @ ajuste.x - seleccion[:, 2]).tolist())
                valor = abs(posiciones[1] - posiciones[0]); residuos = np.asarray(residuos_totales)
                fila['n_puntos'] = sum(cuentas)
                fila['metodo'] = 'Dos planos robustos; separación en la referencia local nominal'
            rmse = float(np.sqrt(np.mean(residuos ** 2)))
            if rmse > banda_mm / 3:
                raise ValueError('El residuo del ajuste es alto; revisa la región o el escaneo.')
            if abs(valor - cota['nominal_mm']) >= 1.8 * banda_mm:
                raise ValueError('El ajuste alcanzó el límite de asociación; amplía la banda y revisa la región.')
            fila.update(estado='medida', medido_mm=valor, delta_mm=valor - cota['nominal_mm'],
                residuo_ajuste_rmse_mm=rmse, diagnostico='Una medida geométrica; sin estimación de repetibilidad.')
        except (ValueError, np.linalg.LinAlgError) as error:
            fila['diagnostico'] = str(error)
        filas.append(fila)
    return filas
