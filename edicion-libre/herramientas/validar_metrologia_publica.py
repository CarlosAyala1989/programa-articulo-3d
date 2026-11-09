"""Ensayo offline reproducible con STL público: nunca escribe campañas del usuario.

Ejecutar desde programa, con PYTHONPATH apuntando a programa y las dependencias
de metrología instaladas. El directorio de salida debe ser nuevo.
"""
import argparse
import copy
import hashlib
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from evaluador.metrologia import cargar_geometria, procesar_carpeta, VERSION_ACTUAL
from evaluador.cotas_automaticas import proponer_cotas
from evaluador.protocolo_cotas import huella_plan
from evaluador.fuentes import fuente


def validar(destino: Path) -> dict:
    destino.mkdir(parents=True, exist_ok=False)
    origen = Path(__file__).resolve().parents[1] / 'pruebas/datos/placa_publica'
    metadatos = json.loads((origen / 'origen.json').read_text())
    ruta = origen / 'placa_agujeros.stl'
    assert hashlib.sha256(ruta.read_bytes()).hexdigest() == metadatos['archivos'][ruta.name]['sha256']
    nominal = cargar_geometria(ruta)
    nominal.apply_translation(-nominal.bounds.mean(0)); nominal.apply_scale(.25)
    casos = []
    for codigo, nombre in [('identica', 'Malla idéntica'), ('contraccion', 'Contracción uniforme del 1 %'),
                           ('espesor', 'Espesor aumentado 0,2 mm'), ('agujero', 'Diámetro aumentado 0,2 mm')]:
        carpeta = destino / codigo; carpeta.mkdir(); nominal.export(carpeta / 'nominal.stl')
        nominal = cargar_geometria(carpeta / 'nominal.stl')
        nominal_sha = hashlib.sha256((carpeta / 'nominal.stl').read_bytes()).hexdigest()
        plan = proponer_cotas(nominal, nominal_sha)
        escaneo = nominal.copy(); esperado = {c['codigo']: 0. for c in plan['cotas']}
        if codigo == 'contraccion':
            escaneo.apply_scale(.99)
            esperado = {c['codigo']: -.01 * c['nominal_mm'] for c in plan['cotas']}
        elif codigo == 'espesor':
            vertices = np.array(escaneo.vertices)
            vertices[:, 2] += np.sign(vertices[:, 2]) * .1; escaneo.vertices = vertices
            for c in plan['cotas']:
                if c['tipo'] == 'distancia_planos' and abs(c['nominal_mm'] - 3.175) < .001:
                    esperado[c['codigo']] = .2
        elif codigo == 'agujero':
            cota = next(c for c in plan['cotas'] if c['tipo'] == 'diametro')
            base = np.array(cota['base']); locales = escaneo.vertices @ base
            radial = locales[:, :2] - cota['centro_xy']; radios = np.linalg.norm(radial, axis=1)
            mascara = abs(radios - cota['nominal_mm'] / 2) < .0001
            locales[mascara, :2] += radial[mascara] / radios[mascara, None] * .1
            escaneo.vertices = locales @ base.T; esperado[cota['codigo']] = .2
        escaneo.export(carpeta / 'escaneo.ply')
        configuracion = {'protocolo': VERSION_ACTUAL, 'pieza': 'CONTROL SINTÉTICO · ' + nombre,
            'unidad': 'mm', 'alineacion': 'conservar', 'muestras': 20000, 'umbral_icp_mm': 2,
            'tolerancia_mm': .3, 'mapa_limite_mm': .5, 'banda_cotas_mm': .5,
            'cotas': [], 'plan_cotas': plan, 'plan_cotas_sha256': huella_plan(plan),
            'extension': '.ply', 'nominal_sha256': nominal_sha,
            'escaneo_sha256': hashlib.sha256((carpeta / 'escaneo.ply').read_bytes()).hexdigest()}
        (carpeta / 'configuracion.json').write_text(json.dumps(configuracion, ensure_ascii=False, indent=2))
        resultado = procesar_carpeta(carpeta)
        for c in resultado['cotas_automaticas']:
            assert c['estado'] == 'medida', (codigo, c)
            assert abs(c['delta_mm'] - esperado[c['codigo']]) < .003, (codigo, c, esperado)
        casos.append({'codigo': codigo, 'nombre': nombre, 'esperado_delta_mm': esperado,
                      'resultado': resultado})
    documento = {'version_aplicacion': '0.8.0', 'tipo': 'Validación sintética, sin impresión ni escáner físico',
        'fuente': metadatos, 'transformacion_fuente': 'Centrado y escala 0.25; unidades declaradas mm',
        'tolerancia_verificacion_cotas_mm': .003, 'casos': casos}
    (destino / 'validacion.json').write_text(json.dumps(documento, ensure_ascii=False, indent=2))
    matriz = Image.new('RGB', (1600, 1320), 'white'); dibujo = ImageDraw.Draw(matriz)
    for i, caso in enumerate(casos):
        x, y = i % 2 * 800, i // 2 * 660
        dibujo.text((x + 15, y + 10), 'CONTROL SINTÉTICO · ' + caso['nombre'], fill='#203040', font=fuente(20))
        with Image.open(destino / caso['codigo'] / 'mapa-desviacion.png') as mapa:
            mapa.thumbnail((790, 610)); matriz.paste(mapa, (x + 5, y + 45))
    matriz.save(destino / 'figura-controles.png', dpi=(300, 300))
    tablas = []
    for caso in casos:
        filas = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(v))}</td>' for v in
            [c['nombre'], round(c['nominal_mm'], 6), round(caso['esperado_delta_mm'][c['codigo']], 6),
             round(c['delta_mm'], 6), c['estado']]) + '</tr>' for c in caso['resultado']['cotas_automaticas'])
        tablas.append(f'<h2>{html.escape(caso["nombre"])}</h2><table><tr><th>Cota</th><th>Nominal mm</th><th>Δ esperado mm</th><th>Δ medido mm</th><th>Estado</th></tr>{filas}</table>')
    (destino / 'informe.html').write_text('''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Validación de metrología 0.8.0</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px;color:#203040}table{border-collapse:collapse;width:100%}th,td{padding:10px;border-bottom:1px solid #ccd4df;text-align:left}img{max-width:100%}</style><h1>Validación de metrología 0.8.0</h1><p>Controles sintéticos sobre una placa pública. No son impresiones ni escaneos del Otter. Cuatro controles, nueve cotas por control; tolerancia de verificación 0,003 mm.</p><p>Fuente: <a href="https://github.com/mikedh/trimesh/blob/main/models/plate_holes.STL">Trimesh plate_holes.STL</a>. Commit y hashes en validacion.json. Copia centrada y escalada a 1:4.</p><img src="figura-controles.png" alt="Cuatro mapas de desviación de los controles sintéticos">''' + ''.join(tablas) + '</html>', encoding='utf-8')
    resumen = {'controles': len(casos), 'cotas_verificadas': sum(len(c['resultado']['cotas_automaticas']) for c in casos),
               'maximo_error_cota_mm': max(abs(cota['delta_mm'] - c['esperado_delta_mm'][cota['codigo']]) for c in casos for cota in c['resultado']['cotas_automaticas'])}
    print(json.dumps(resumen, ensure_ascii=False)); return resumen


if __name__ == '__main__':
    analizador = argparse.ArgumentParser(); analizador.add_argument('destino', type=Path)
    validar(analizador.parse_args().destino)
