"""Tablas y figuras del PDF a partir de mediciones reales, con manifiesto verificable."""

import base64
import hashlib
import html
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from aplicacion.resultados import convertir_csv

COLUMNAS = ['comparacion', 'ejecucion', 'pieza', 'estado', 'alineacion_confirmada', 'calibracion_realizada',
    'fecha_calibracion', 'escaner', 'software', 'unidad_entrada', 'hausdorff_maximo_mm', 'hausdorff_p95_mm',
    'chamfer_fisico_mm2', 'desviacion_absoluta_media_mm', 'desviacion_estandar_superficie_mm',
    'delta_media_mm', 'delta_absoluto_medio_mm', 'delta_desviacion_estandar_mm', 'n_mediciones',
    'dentro_tolerancia_pct', 'tolerancia_mm', 'cobertura_nominal_pct', 'muestras_nominal', 'muestras_escaneo',
    'nominal_sha256', 'escaneo_sha256', 'protocolo', 'hausdorff_alcance',
    'hausdorff_superficie_muestreado_mm', 'puntos_hausdorff_nominal', 'puntos_hausdorff_escaneo',
    'cotas_planificadas', 'cotas_medidas', 'completo', 'origen', 'alcance_desviacion']


def filas_metrologia(registros: list[dict]) -> list[dict]:
    filas = []
    for registro in registros:
        configuracion, resultado = registro['configuracion'], registro.get('resultado') or {}
        filas.append({
            'comparacion': registro['identificador'], 'ejecucion': registro['ejecucion_identificador'],
            'pieza': configuracion['pieza'], 'estado': registro['estado'],
            'alineacion_confirmada': registro['alineacion_confirmada'],
            **{k: configuracion.get(k) for k in ('calibracion_realizada', 'fecha_calibracion', 'escaner', 'software')},
            'unidad_entrada': configuracion['unidad'], 'nominal_sha256': registro['nominal_sha256'],
            'escaneo_sha256': registro.get('escaneo_sha256'), **{k: resultado.get(k) for k in COLUMNAS if k in resultado},
            **resultado.get('error_dimensional', {}),
        })
    return filas


def tabla_cotas(registros: list[dict]) -> str:
    filas = []
    for r in registros:
        for cota in (r.get('resultado') or {}).get('cotas_criticas', []):
            filas.append({'comparacion': r['identificador'], 'pieza': r['configuracion']['pieza'], **cota})
        for cota in (r.get('resultado') or {}).get('cotas_automaticas', []):
            filas.append({'comparacion': r['identificador'], 'pieza': r['configuracion']['pieza'], **cota,
                'medido_media_mm': cota.get('medido_mm'), 'delta_media_mm': cota.get('delta_mm'),
                'n': 1 if cota['estado'] == 'medida' else 0})
    return convertir_csv(filas, ['comparacion', 'pieza', 'nombre', 'metodo', 'nominal_mm', 'mediciones_mm',
                               'n', 'medido_media_mm', 'delta_media_mm', 'delta_desviacion_estandar_mm', 'codigo', 'tipo', 'estado',
                               'diagnostico', 'n_puntos', 'residuo_ajuste_rmse_mm', 'cobertura_angular_grados'])


def componer_figuras(registros: list[dict], nombre: str) -> list[tuple[str, bytes]]:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    from aplicacion.metrologia import carpeta_comparacion
    disponibles = [r for r in registros if r['estado'] == 'completada' and
                   (carpeta_comparacion(r['identificador']) / nombre).is_file()]
    figuras = []
    from evaluador.fuentes import fuente
    tipografia = fuente(20)
    for inicio in range(0, len(disponibles), 4):
        grupo = disponibles[inicio:inicio + 4]
        imagen = Image.new('RGB', (1600, 680 * ((len(grupo) + 1) // 2)), 'white')
        dibujo = ImageDraw.Draw(imagen)
        for i, registro in enumerate(grupo):
            x, y = i % 2 * 800, i // 2 * 680
            with Image.open(carpeta_comparacion(registro['identificador']) / nombre) as original:
                miniatura = ImageOps.contain(original.convert('RGB'), (780, 600))
            imagen.paste(miniatura, (x + (800 - miniatura.width) // 2, y + 70))
            pieza = registro['configuracion']['pieza'][:55]
            dibujo.text((x + 15, y + 8), pieza, fill='#203040', font=tipografia)
            estado = 'Alineación confirmada' if registro['alineacion_confirmada'] else 'Alineación pendiente de revisión'
            dibujo.text((x + 15, y + 36), estado + ' · ' + registro['identificador'][:8], fill='#405060', font=tipografia)
        salida = io.BytesIO()
        imagen.save(salida, format='PNG', dpi=(300, 300))
        prefijo = 'heatmaps' if nombre.startswith('mapa') else 'matriz-fotografica'
        figuras.append((f'figuras/{prefijo}-{inicio // 4 + 1:02}.png', salida.getvalue()))
    return figuras


def crear_zip(registros: list[dict]) -> Path:
    from aplicacion.metrologia import carpeta_comparacion, huella_archivo
    descriptor, nombre = tempfile.mkstemp(prefix='ciel-metrologia-', suffix='.zip')
    os.close(descriptor)
    ruta = Path(nombre)
    huellas = []
    try:
        with zipfile.ZipFile(ruta, 'w', zipfile.ZIP_DEFLATED) as paquete:
            def agregar(nombre_archivo, contenido):
                bruto = contenido.encode('utf-8') if isinstance(contenido, str) else contenido
                paquete.writestr(nombre_archivo, bruto)
                huellas.append({'archivo': nombre_archivo, 'sha256': hashlib.sha256(bruto).hexdigest()})
            filas = filas_metrologia(registros)
            agregar('tabla_metrologica.csv', convertir_csv(filas, COLUMNAS))
            agregar('cotas_criticas.csv', tabla_cotas(registros))
            agregar('comparaciones.json', json.dumps(registros, ensure_ascii=False, indent=2, default=str))
            figuras = componer_figuras(registros, 'mapa-desviacion.png') + componer_figuras(registros, 'comparacion-fotografica.png')
            for nombre_figura, contenido in figuras:
                agregar(nombre_figura, contenido)
            for registro in registros:
                carpeta = carpeta_comparacion(registro['identificador'])
                for archivo in sorted(carpeta.iterdir()):
                    if not archivo.is_file() or archivo.is_symlink() or archivo.name.endswith('.tmp'):
                        continue
                    destino = f"comparaciones/{registro['identificador']}/{archivo.name}"
                    paquete.write(archivo, destino)
                    huellas.append({'archivo': destino, 'sha256': huella_archivo(archivo)})
            imagenes = ''.join(f'<figure><img src="data:image/png;base64,{base64.b64encode(b).decode()}" '
                               f'alt="{html.escape(n)}"><figcaption>{html.escape(n)}</figcaption></figure>' for n, b in figuras)
            cabeceras = ['pieza', 'estado', 'alineacion_confirmada', 'hausdorff_maximo_mm', 'chamfer_fisico_mm2',
                         'delta_media_mm', 'delta_desviacion_estandar_mm']
            filas_html = ''.join('<tr>' + ''.join('<td>' + html.escape(str(f.get(c) if f.get(c) is not None else 'No medido'))
                                                 + '</td>' for c in cabeceras) + '</tr>' for f in filas)
            texto = ('Protocolo ciel-metrologia-otter-v1. Impresión manual y escaneos aportados por el usuario. '
                     'Registro rígido sin ajuste de escala. Hausdorff/Chamfer estimados por muestreo de superficies; '
                     'el CSV registra tamaños de muestra. Chamfer cuadrático bidireccional en mm². '
                     'Delta dimensional: medida declarada menos nominal, en mm; desviación estándar muestral, '
                     'vacía con una sola medida. No confundir la dispersión superficial con la de las cotas críticas. '
                     'Revisar alineación, cobertura y calibración antes de usar una fila en el artículo. '
                     'Las comparaciones son independientes del éxito técnico y de las métricas digitales. '
                     'Las cotas automáticas registran cobertura y residuo del ajuste. La desviación entre cotas no estima repetibilidad del escáner. El alcance de Hausdorff se conserva en JSON y CSV; v2 usa todos los puntos/vértices para el máximo discreto. Las fotos y cotas ausentes no se reconstruyen. Cada mapa conserva su escala en mm.')
            agregar('LEEME.txt', texto + '\n')
            agregar('informe.html', '<!doctype html><html lang="es"><meta charset="utf-8"><title>Resultados metrológicos</title>'
                '<style>body{font:16px/1.6 Arial,sans-serif;margin:32px;color:#203040}table{border-collapse:collapse;display:block;overflow:auto}'
                'th,td{padding:10px;border:1px solid #ccd4db;text-align:left}img{max-width:100%;height:auto}figure{margin:30px 0}'
                '@media print{figure{break-inside:avoid}body{margin:10mm}}</style><h1>Resultados metrológicos</h1><p>' + html.escape(texto) +
                '</p><table><thead><tr>' + ''.join('<th>' + html.escape(c) + '</th>' for c in cabeceras) +
                '</tr></thead><tbody>' + filas_html + '</tbody></table>' + imagenes + '</html>')
            paquete.writestr('manifiesto.json', json.dumps({'protocolo': 'ciel-metrologia-otter-v1',
                'archivos': huellas}, ensure_ascii=False, indent=2))
        return ruta
    except Exception:
        ruta.unlink(missing_ok=True)
        raise


def respuesta_zip(ruta: Path, nombre: str) -> FileResponse:
    return FileResponse(ruta, media_type='application/zip', filename=nombre, background=BackgroundTask(ruta.unlink, missing_ok=True))
