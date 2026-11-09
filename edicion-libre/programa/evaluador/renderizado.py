"""Renders ortográficos reproducibles de un STL digital, sin modificar su geometría."""

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def vistas_para_frente(orientacion_frente: str) -> tuple:
    ejes = {"+X": (1, 0, 0), "-X": (-1, 0, 0),
            "+Y": (0, 1, 0), "-Y": (0, -1, 0),
            "+Z": (0, 0, 1), "-Z": (0, 0, -1)}
    if orientacion_frente not in ejes:
        raise ValueError("La orientación del frente debe ser un eje cartesiano con signo")
    frente = np.asarray(ejes[orientacion_frente], dtype=float)
    arriba = np.asarray((0, 1, 0) if abs(frente[2]) == 1 else (0, 0, 1), dtype=float)
    derecha = np.cross(arriba, frente)
    return (
        ("FRONT", tuple(derecha), tuple(arriba)),
        ("BACK", tuple(-derecha), tuple(arriba)),
        ("LEFT", tuple(frente), tuple(arriba)),
        ("RIGHT", tuple(-frente), tuple(arriba)),
        ("TOP", tuple(derecha), tuple(-frente)),
        ("BOTTOM", tuple(derecha), tuple(frente)),
        ("ISO_A", tuple(derecha), tuple(-frente + 2 * arriba)),
        ("ISO_B", tuple(-derecha), tuple(frente + 2 * arriba)),
    )


VISTAS = vistas_para_frente("+Y")
PERFIL_RENDER = {
    "version": "ciel-ortho-render-v2", "proyeccion": "ortografica",
    "fondo_rgb": [242, 244, 247], "resolucion_lamina": [1024, 1024],
    "caras_maximas_por_vista": 12000, "luz": [0.3, 0.5, 0.8],
}


def _normalizar(vector):
    vector = np.asarray(vector, dtype=float)
    norma = np.linalg.norm(vector)
    return vector / norma if norma else vector


def _renderizar_vista(malla, etiqueta: str, vistas=VISTAS,
                     ancho: int = 512, alto: int = 512) -> Image.Image:
    vertices = np.asarray(malla.vertices, dtype=float)
    caras_todas = np.asarray(malla.faces, dtype=np.int64)
    centro = (np.asarray(malla.bounds[0]) + np.asarray(malla.bounds[1])) / 2
    indice = next(i for i, vista in enumerate(vistas) if vista[0] == etiqueta)
    _, horizontal, vertical = vistas[indice]
    eje_x = _normalizar(horizontal)
    eje_y = _normalizar(vertical)
    profundidad = _normalizar(np.cross(eje_x, eje_y))
    centrados = vertices - centro
    px = centrados @ eje_x
    py = centrados @ eje_y
    pz = centrados @ profundidad
    escala = max(float(np.linalg.norm(np.asarray(malla.extents))), 1e-6)
    margen = 38
    factor = min((ancho - 2 * margen) / escala, (alto - 2 * margen) / escala)
    x_pantalla = (ancho / 2 + px * factor).astype(float)
    y_pantalla = (alto / 2 - py * factor).astype(float)
    indices_caras = np.arange(len(caras_todas))
    if len(indices_caras) > PERFIL_RENDER["caras_maximas_por_vista"]:
        indices_caras = np.linspace(0, len(indices_caras) - 1,
                                    PERFIL_RENDER["caras_maximas_por_vista"], dtype=np.int64)
    caras = caras_todas[indices_caras]
    orden = np.argsort(pz[caras].mean(axis=1), kind="stable")
    normales = np.asarray(malla.face_normals)
    if len(normales) != len(malla.faces):
        normales = np.zeros((len(malla.faces), 3), dtype=float)
    luz = _normalizar(np.asarray(PERFIL_RENDER["luz"], dtype=float))
    imagen = Image.new("RGB", (ancho, alto), tuple(PERFIL_RENDER["fondo_rgb"]))
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rounded_rectangle((7, 7, ancho - 8, alto - 8), radius=12, outline=(209, 214, 221), width=1)
    for i in orden:
        triangulo = caras[i]
        puntos = [(float(x_pantalla[j]), float(y_pantalla[j])) for j in triangulo]
        if max(p[0] for p in puntos) < 0 or min(p[0] for p in puntos) >= ancho:
            continue
        if max(p[1] for p in puntos) < 0 or min(p[1] for p in puntos) >= alto:
            continue
        intensidad = 0.48 + 0.42 * max(0.0, float(np.dot(normales[indices_caras[i]], luz)))
        tono = int(74 + 110 * intensidad)
        dibujo.polygon(puntos, fill=(tono, min(255, tono + 3), min(255, tono + 8)))
    try:
        fuente = ImageFont.truetype("DejaVuSans.ttf", 15)
    except OSError:
        fuente = ImageFont.load_default()
    dibujo.rounded_rectangle((14, 13, 104, 39), radius=6, fill=(255, 255, 255))
    dibujo.text((22, 18), etiqueta, font=fuente, fill=(44, 52, 64))
    return imagen


def renderizar_lamina(malla, orientacion_frente: str = "+Y") -> tuple[bytes, dict]:
    if not len(malla.faces) or not np.isfinite(malla.vertices).all():
        raise ValueError("No se puede renderizar un STL vacío o no finito")
    vistas = vistas_para_frente(orientacion_frente)
    lamina = Image.new("RGB", (1024, 1024), tuple(PERFIL_RENDER["fondo_rgb"]))
    for indice, (etiqueta, _, _) in enumerate(vistas):
        columna, fila = indice % 2, indice // 2
        vista = _renderizar_vista(malla, etiqueta, vistas=vistas, ancho=512, alto=256)
        lamina.paste(vista, (columna * 512, fila * 256))
    salida = io.BytesIO()
    lamina.save(salida, format="PNG", optimize=True)
    return salida.getvalue(), {**PERFIL_RENDER, "orientacion_frente": orientacion_frente}


def comparar_siluetas(malla_a, malla_b, orientacion_frente: str = "+Y") -> dict:
    """IoU binario en cuatro cámaras ortográficas con escala y encuadre comunes."""
    vistas = ("FRONT", "LEFT", "TOP", "ISO_A")
    definiciones_vistas = vistas_para_frente(orientacion_frente)
    limites_min = np.minimum(malla_a.bounds[0], malla_b.bounds[0])
    limites_max = np.maximum(malla_a.bounds[1], malla_b.bounds[1])
    centro_comun = (limites_min + limites_max) / 2
    escala_comun = max(float(np.linalg.norm(limites_max - limites_min)), 1e-6)

    def mascara(malla, etiqueta):
        vertices = np.asarray(malla.vertices, dtype=float)
        caras = np.asarray(malla.faces, dtype=np.int64)
        indice = next(i for i, vista in enumerate(definiciones_vistas) if vista[0] == etiqueta)
        _, horizontal, vertical = definiciones_vistas[indice]
        eje_x, eje_y = _normalizar(horizontal), _normalizar(vertical)
        centrados = vertices - centro_comun
        factor = 220 / escala_comun
        xs = 128 + centrados @ eje_x * factor
        ys = 128 - centrados @ eje_y * factor
        imagen = Image.new("1", (256, 256), 0)
        dibujo = ImageDraw.Draw(imagen)
        if len(caras) > 12000:
            indices = np.linspace(0, len(caras) - 1, 12000, dtype=np.int64)
            caras = caras[indices]
        for triangulo in caras:
            dibujo.polygon([(float(xs[i]), float(ys[i])) for i in triangulo], fill=1)
        return np.asarray(imagen, dtype=bool)

    por_vista = {}
    for vista in vistas:
        a, b = mascara(malla_a, vista), mascara(malla_b, vista)
        union = int(np.logical_or(a, b).sum())
        por_vista[vista] = float(np.logical_and(a, b).sum() / union) if union else None
    disponibles = [valor for valor in por_vista.values() if valor is not None]
    return {"estado": "calculated" if disponibles else "not_available",
            "iou_medio": float(np.mean(disponibles)) if disponibles else None,
            "por_vista": por_vista, "unidad": "ratio", "muestras": 4,
            "semilla": None, "algoritmo": "IoU binario raster ortográfico 256x256, FRONT/LEFT/TOP/ISO_A",
            "perfil": PERFIL_RENDER["version"], "orientacion_frente": orientacion_frente}


def renderizar_biblioteca(malla) -> tuple[dict[str, bytes], dict]:
    """Perfil independiente; no modifica las láminas científicas históricas."""
    if not len(malla.faces) or not np.isfinite(malla.vertices).all():
        raise ValueError("No se puede renderizar un STL vacío o no finito")
    nombres = ('frontal', 'posterior', 'izquierda', 'derecha', 'superior', 'inferior', 'isometrica')
    imagenes = {}
    lamina = Image.new('RGB', (1536, 1536), tuple(PERFIL_RENDER['fondo_rgb']))
    for indice, (nombre, vista) in enumerate(zip(nombres, vistas_para_frente('+Y')[:7])):
        imagen = _renderizar_vista(malla, vista[0], ancho=512, alto=512)
        lamina.paste(imagen, ((indice % 3) * 512, (indice // 3) * 512))
        imagenes['vista-' + nombre + '.png'] = imagen
    imagenes['vista-lamina.png'] = lamina
    imagenes['vista-miniatura.png'] = imagenes['vista-isometrica.png'].resize((256, 256))
    archivos = {}
    for nombre, imagen in imagenes.items():
        salida = io.BytesIO()
        imagen.save(salida, format='PNG')
        archivos[nombre] = salida.getvalue()
    return archivos, {**PERFIL_RENDER, 'version': 'ciel-biblioteca-render-v1',
                       'orientacion_frente': '+Y', 'resolucion_vista': [512, 512],
                       'resolucion_lamina': [1536, 1536]}
