"""Figuras reproducibles de desviación, sin GPU, con escalas explícitas en mm."""

import csv
import io
import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont


from evaluador.fuentes import fuente


def colores(valores: np.ndarray, limite: float, firmado: bool = True) -> np.ndarray:
    normalizados = np.clip(np.asarray(valores) / limite, -1 if firmado else 0, 1)
    verde, rojo, azul = np.array([40, 164, 89]), np.array([211, 48, 48]), np.array([40, 94, 205])
    extremos = np.where((normalizados >= 0)[:, None], rojo, azul)
    peso = np.abs(normalizados)[:, None]
    return np.asarray(verde * (1 - peso) + extremos * peso, dtype=np.uint8)


def panel_puntos(puntos: np.ndarray, rgb: np.ndarray, ancho: int, alto: int,
                 direccion: tuple, centro: np.ndarray, escala: float) -> Image.Image:
    frente = np.asarray(direccion, dtype=float)
    frente /= np.linalg.norm(frente)
    arriba = np.array([0., 0., 1.]) if abs(frente[2]) < .95 else np.array([0., 1., 0.])
    horizontal = np.cross(arriba, frente)
    horizontal /= np.linalg.norm(horizontal)
    vertical = np.cross(frente, horizontal)
    locales = puntos - centro
    x = locales @ horizontal * escala + ancho / 2
    y = -locales @ vertical * escala + alto / 2
    imagen = Image.new('RGB', (ancho, alto), '#f5f7f9')
    dibujo = ImageDraw.Draw(imagen)
    for i in np.argsort(locales @ frente):
        if 2 <= x[i] < ancho - 2 and 2 <= y[i] < alto - 2:
            dibujo.ellipse((int(x[i]) - 1, int(y[i]) - 1, int(x[i]) + 1, int(y[i]) + 1), fill=tuple(rgb[i]))
    return imagen


def crear_mapa(puntos: np.ndarray, desviaciones: np.ndarray, resultado: dict) -> Image.Image:
    imagen = Image.new('RGB', (1100, 850), 'white')
    dibujo = ImageDraw.Draw(imagen)
    firmado = resultado['mapa_firmado']
    limite = resultado['mapa_limite_mm']
    rgb = colores(desviaciones, limite, firmado)
    centro = (puntos.min(axis=0) + puntos.max(axis=0)) / 2
    escala = 295 / max(float(np.linalg.norm(np.ptp(puntos, axis=0))), 1e-6)
    dibujo.text((30, 18), 'Desviación del escaneo respecto al modelo virtual', fill='#203040', font=fuente(26))
    for indice, (nombre, direccion) in enumerate((('Isométrica', (1, -1, 1)), ('Frontal', (0, -1, 0)),
                                                 ('Lateral', (1, 0, 0)), ('Superior', (0, 0, 1)))):
        x, y = 30 + (indice % 2) * 470, 72 + (indice // 2) * 335
        imagen.paste(panel_puntos(puntos, rgb, 445, 295, direccion, centro, escala), (x, y))
        dibujo.text((x + 10, y + 8), nombre, fill='#203040', font=fuente(18))
    for y in range(600):
        valor = limite * (1 - (2 if firmado else 1) * y / 599)
        color = tuple(colores(np.array([valor]), limite, firmado)[0])
        dibujo.line((1000, 90 + y, 1025, 90 + y), fill=color)
    for valor, y in ((limite, 90), (0, 390 if firmado else 690), (-limite, 690)):
        if valor < 0 and not firmado:
            continue
        dibujo.text((1033, y - 7), f'{valor:g}', fill='#203040', font=fuente(15))
    dibujo.text((997, 62), 'mm', fill='#203040', font=fuente(18))
    leyenda = 'Rojo: exterior · verde: cero · azul: interior (normal local)' if firmado else 'Desviación absoluta: verde cero, rojo máximo'
    dibujo.text((30, 758), leyenda, fill='#203040', font=fuente(18))
    dibujo.text((30, 788), f"Escala saturada en {limite:g} mm. Distancias sin recorte en el CSV. Registro rígido, escala 1.",
                 fill='#405060', font=fuente(16))
    return imagen


def generar_archivos(carpeta: Path, nominal, puntos: np.ndarray, desviaciones: np.ndarray,
                     resultado: dict, configuracion: dict) -> None:
    rgb = colores(desviaciones, resultado['mapa_limite_mm'], resultado['mapa_firmado'])
    crear_mapa(puntos, desviaciones, resultado).save(carpeta / 'mapa-desviacion.png', dpi=(300, 300))
    nube = trimesh.points.PointCloud(puntos, colors=rgb)
    (carpeta / 'escaneo-alineado-colores.ply').write_bytes(nube.export(file_type='ply'))
    with (carpeta / 'distancias.csv').open('w', newline='', encoding='utf-8-sig') as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(['x_mm', 'y_mm', 'z_mm', 'desviacion_mm', 'desviacion_absoluta_mm'])
        escritor.writerows([*p.tolist(), float(d), float(abs(d))] for p, d in zip(puntos, desviaciones))
    if configuracion.get('plan_cotas'):
        (carpeta / 'plan-cotas.json').write_text(json.dumps(configuracion['plan_cotas'], ensure_ascii=False, indent=2), encoding='utf-8')
        with (carpeta / 'cotas-automaticas.csv').open('w', newline='', encoding='utf-8-sig') as archivo:
            campos = ['codigo', 'nombre', 'tipo', 'nominal_mm', 'medido_mm', 'delta_mm', 'estado',
                      'n_puntos', 'residuo_ajuste_rmse_mm', 'cobertura_angular_grados', 'metodo', 'diagnostico']
            escritor = csv.DictWriter(archivo, fieldnames=campos, extrasaction='ignore')
            escritor.writeheader(); escritor.writerows(resultado.get('cotas_automaticas', []))
    # Vista ligera para Three.js; los datos de análisis completos siguen en distancias.csv.
    indices = np.linspace(0, len(puntos) - 1, min(12000, len(puntos)), dtype=int)
    (carpeta / 'vista.json').write_text(json.dumps({'puntos': puntos[indices].round(6).tolist(),
        'colores': rgb[indices].tolist(), 'limite_mm': resultado['mapa_limite_mm'],
        'firmado': resultado['mapa_firmado']}, allow_nan=False), encoding='utf-8')
    (carpeta / 'transformacion.json').write_text(json.dumps({
        'unidad_entrada': configuracion['unidad'], 'unidad_salida': 'mm', 'escala_ajuste': 1,
        'matriz': resultado['transformacion_escaneo_a_nominal'], 'registro': resultado['registro']}, indent=2), encoding='utf-8')
    (carpeta / 'resultado.json').write_text(json.dumps(resultado, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    # Render del nominal con el mismo encuadre por pieza para la matriz fotográfica.
    from evaluador.metrologia import muestrear, SEMILLA
    puntos_nominal = muestrear(nominal, 18000, SEMILLA)
    centro = (nominal.bounds[0] + nominal.bounds[1]) / 2
    escala = 420 / max(float(np.linalg.norm(nominal.extents)), 1e-6)
    panel_puntos(puntos_nominal, np.tile([110, 143, 175], (len(puntos_nominal), 1)), 600, 480,
                 (1, -1, 1), centro, escala).save(carpeta / 'modelo-virtual.png')
    if (carpeta / 'foto-original').is_file():
        from PIL import ImageOps
        with Image.open(carpeta / 'foto-original') as original:
            original = ImageOps.exif_transpose(original).convert('RGB')
            foto = ImageOps.contain(original, (600, 480))
        matriz = Image.new('RGB', (1200, 540), 'white')
        with Image.open(carpeta / 'modelo-virtual.png') as render:
            matriz.paste(render, (0, 45))
        matriz.paste(foto, (600 + (600 - foto.width) // 2, 45 + (480 - foto.height) // 2))
        dibujo = ImageDraw.Draw(matriz)
        dibujo.text((20, 10), 'Modelo virtual generado', fill='#203040', font=fuente(22))
        dibujo.text((620, 10), 'Pieza física · fotografía aportada', fill='#203040', font=fuente(22))
        matriz.save(carpeta / 'comparacion-fotografica.png', dpi=(300, 300))
