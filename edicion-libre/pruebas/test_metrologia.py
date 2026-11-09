"""Geometrías sintéticas conocidas: ninguna inferencia ni medida física inventada."""
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import trimesh
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from evaluador.metrologia import (calcular, cargar_geometria, procesar_carpeta, resumen_cotas,
                                 transformar, ajuste_rigido, VERSION)
from aplicacion import metrologia
from aplicacion.api import aplicacion
from aplicacion.base_datos import BaseDeclarativa, Ejecucion, ArchivoGenerado, ComparacionFisica


def configuracion(**cambios):
    return {'pieza': 'Pieza de ensayo sintética', 'unidad': 'mm', 'tolerancia_mm': .3,
            'umbral_icp_mm': 2, 'mapa_limite_mm': .5, 'muestras': 2000, 'alineacion': 'conservar',
            'cotas': [], 'calibracion_realizada': False, **cambios}


class GeometriaFisicaTests(unittest.TestCase):
    def test_identicas_tienen_distancia_cero_sin_piso_de_muestreo(self):
        nominal = trimesh.creation.box(extents=[40, 25, 12])
        resultado, _, _ = calcular(nominal, nominal.copy(), configuracion())
        self.assertLess(resultado['hausdorff_maximo_mm'], 1e-10)
        self.assertLess(resultado['chamfer_fisico_mm2'], 1e-15)
        self.assertEqual(resultado['dentro_tolerancia_pct'], 100)
        self.assertIsNone(resultado['error_dimensional']['delta_media_mm'])

    def test_icp_recupera_rotacion_y_traslacion_sin_escala(self):
        nominal = trimesh.creation.box(extents=[40, 25, 12])
        matriz = trimesh.transformations.euler_matrix(.35, -.6, .8)
        matriz[:3, 3] = [31, -18, 24]
        escaneo = nominal.copy()
        escaneo.apply_transform(matriz)
        resultado, _, _ = calcular(nominal, escaneo, configuracion(alineacion='automatica'))
        self.assertLess(resultado['hausdorff_maximo_mm'], .01)
        self.assertAlmostEqual(np.linalg.det(np.array(resultado['transformacion_escaneo_a_nominal'])[:3, :3]), 1, places=7)
        self.assertEqual(resultado['escala_ajuste'], 1)

    def test_contraccion_y_outliers_no_se_borran_de_las_metricas(self):
        nominal = trimesh.creation.box(extents=[40, 25, 12])
        escaneo = nominal.copy()
        escaneo.apply_scale(.98)
        resultado, _, _ = calcular(nominal, escaneo, configuracion(alineacion='automatica'))
        self.assertGreater(resultado['hausdorff_maximo_mm'], .35)
        self.assertGreater(resultado['chamfer_fisico_mm2'], .01)
        self.assertEqual(resultado['escala_ajuste'], 1)
        nube = trimesh.points.PointCloud(np.vstack([nominal.sample(2000), [[50, 0, 0]]]))
        resultado, _, _ = calcular(nominal, nube, configuracion(muestras=3000))
        self.assertGreater(resultado['hausdorff_maximo_mm'], 29)

    def test_refinamiento_no_sesga_contraccion_rotada_hacia_una_cara(self):
        nominal = trimesh.creation.box(extents=[40, 25, 12])
        escaneo = nominal.copy(); escaneo.apply_scale(.99)
        transformacion = trimesh.transformations.euler_matrix(.2, -.3, .4)
        transformacion[:3, 3] = [12, -25, 18]
        escaneo.apply_transform(transformacion)
        resultado, _, _ = calcular(nominal, escaneo, configuracion(muestras=20000, alineacion='automatica'))
        self.assertGreater(resultado['hausdorff_maximo_mm'], .18)
        self.assertLess(resultado['hausdorff_maximo_mm'], .3)
        self.assertLess(abs(resultado['envolvente_mm'][0]['delta_mm'] + .4), .03)

    def test_ajuste_por_puntos_rechaza_colineales_y_reflexion(self):
        puntos = np.array([[0, 0, 0], [1, 0, 0], [0, 2, 0], [0, 0, 3.]])
        matriz = ajuste_rigido(puntos, puntos * [-1, 1, 1])
        self.assertAlmostEqual(np.linalg.det(matriz[:3, :3]), 1)
        with self.assertRaises(ValueError):
            ajuste_rigido(np.zeros((3, 3)), np.zeros((3, 3)))

    def test_cotas_repetidas_no_confunden_dispersion_superficial(self):
        filas, resumen = resumen_cotas([{'nombre': 'Agujero', 'nominal_mm': 8, 'mediciones_mm': [8.1, 8.2, 8.3], 'metodo': 'Calibre'}])
        self.assertAlmostEqual(filas[0]['delta_media_mm'], .2)
        self.assertAlmostEqual(filas[0]['delta_desviacion_estandar_mm'], .1)
        self.assertEqual(resumen['n_mediciones'], 3)
        _, resumen = resumen_cotas([{'nombre': 'Largo', 'nominal_mm': 10, 'mediciones_mm': [10.1], 'metodo': 'Calibre'}])
        self.assertIsNone(resumen['delta_desviacion_estandar_mm'])

    def test_formatos_otter_ply_obj_stl_y_unidades_explicitas(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for extension in ('stl', 'obj', 'ply'):
                ruta = Path(carpeta) / ('scan.' + extension)
                trimesh.creation.box(extents=[4, 2.5, 1.2]).export(ruta)
                malla = cargar_geometria(ruta, 10)
                np.testing.assert_allclose(malla.extents, [40, 25, 12], atol=1e-5)
            ruta = Path(carpeta) / 'nube.ply'
            trimesh.points.PointCloud(np.random.default_rng(1).random((50, 3))).export(ruta)
            self.assertEqual(len(cargar_geometria(ruta).vertices), 50)
            ruta = Path(carpeta) / 'nube.pcd'
            ruta.write_text('FIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nPOINTS 30\nDATA ascii\n' + '\n'.join(f'{i} {i*i} 0' for i in range(30)))
            self.assertEqual(len(cargar_geometria(ruta).vertices), 30)
            ruta.write_text(ruta.read_text().replace('DATA ascii', 'DATA binary_compressed'))
            with self.assertRaisesRegex(ValueError, 'comprimir'):
                cargar_geometria(ruta)

    def test_rechaza_unidades_equivocadas_y_nubes_no_finitas(self):
        nominal = trimesh.creation.box(extents=[40, 25, 12])
        escaneo = nominal.copy()
        escaneo.apply_scale(1000)
        with self.assertRaisesRegex(ValueError, 'unidades'):
            calcular(nominal, escaneo, configuracion())

    def test_exportacion_real_con_hashes_mapas_y_foto(self):
        with tempfile.TemporaryDirectory() as carpeta:
            carpeta = Path(carpeta)
            nominal = trimesh.creation.box(extents=[40, 25, 12])
            nominal.export(carpeta / 'nominal.stl')
            scan = nominal.copy(); scan.apply_scale(.99); scan.export(carpeta / 'escaneo.ply')
            Image.new('RGB', (300, 200), '#bbbbbb').save(carpeta / 'foto-original', format='PNG')
            config = configuracion(extension='.ply', escaneo_sha256=hashlib.sha256((carpeta / 'escaneo.ply').read_bytes()).hexdigest(),
                nominal_sha256=hashlib.sha256((carpeta / 'nominal.stl').read_bytes()).hexdigest())
            (carpeta / 'configuracion.json').write_text(json.dumps(config))
            original = (carpeta / 'escaneo.ply').read_bytes()
            r = procesar_carpeta(carpeta)
            self.assertGreater(r['hausdorff_maximo_mm'], .1)
            for nombre in ('mapa-desviacion.png', 'comparacion-fotografica.png', 'modelo-virtual.png'):
                with Image.open(carpeta / nombre) as imagen:
                    imagen.verify()
            self.assertEqual((carpeta / 'escaneo.ply').read_bytes(), original)
            self.assertTrue((carpeta / 'distancias.csv').is_file())
            self.assertEqual(json.loads((carpeta / 'vista.json').read_text())['firmado'], True)
            (carpeta / 'escaneo.ply').write_bytes(b'cambio')
            with self.assertRaisesRegex(ValueError, 'cambió'):
                procesar_carpeta(carpeta)


class FlujoFisicoTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.carpeta = Path(self.temporal.name)
        self.motor = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(self.motor.dispose)
        BaseDeclarativa.metadata.create_all(self.motor)
        self.sesiones = sessionmaker(self.motor, expire_on_commit=False)
        for nombre, valor in [('crear_sesion', self.sesiones), ('DIRECTORIO_ARTEFACTOS', str(self.carpeta))]:
            parche = patch.object(metrologia, nombre, valor); parche.start(); self.addCleanup(parche.stop)
        from evaluador.cotas_automaticas import proponer_cotas
        parche = patch.object(metrologia, 'proponer_desde_copia', side_effect=lambda carpeta:
            proponer_cotas(cargar_geometria(carpeta / 'nominal.stl'), metrologia.huella_archivo(carpeta / 'nominal.stl')))
        parche.start(); self.addCleanup(parche.stop)
        self.cola = patch.object(metrologia.EJECUTOR, 'submit'); self.programar = self.cola.start(); self.addCleanup(self.cola.stop)
        self.ejecucion = str(uuid4())
        ruta = self.carpeta / 'pieza.stl'; trimesh.creation.box().export(ruta)
        with self.sesiones() as s:
            s.add(Ejecucion(identificador=self.ejecucion, descripcion='Caja', motor='cadquery', modelo='L01', estado='completada'))
            s.flush()
            s.add(ArchivoGenerado(ejecucion_identificador=self.ejecucion, nombre='pieza.stl', ruta=str(ruta),
                tamano_bytes=ruta.stat().st_size, sha256=hashlib.sha256(ruta.read_bytes()).hexdigest()))
            s.commit()
        self.cliente = TestClient(aplicacion)

    def crear(self, **cambios):
        r = self.cliente.post(f'/api/ejecuciones/{self.ejecucion}/comparaciones-fisicas', json={
            'pieza': 'Réplica 1', **cambios})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()['identificador']

    def test_carga_asincrona_preserva_nominal_y_rechaza_sobreescritura(self):
        identificador = self.crear()
        with (self.carpeta / 'pieza.stl').open('rb') as archivo:
            bruto = archivo.read()
        r = self.cliente.put(f'/api/comparaciones-fisicas/{identificador}/escaneo?nombre=scan.STL', content=bruto)
        self.assertEqual(r.status_code, 202, r.text)
        self.programar.assert_called_once()
        r = self.cliente.put(f'/api/comparaciones-fisicas/{identificador}/escaneo?nombre=scan.stl', content=b'otro')
        self.assertEqual(r.status_code, 409)
        self.assertEqual((self.carpeta / 'metrologia' / identificador / 'nominal.stl').read_bytes(), bruto)
        with self.sesiones() as s:
            self.assertEqual(s.get(Ejecucion, self.ejecucion).estado, 'completada')
        r = self.cliente.get(f'/api/ejecuciones/{self.ejecucion}/comparaciones-fisicas')
        self.assertEqual(r.json()[0]['estado'], 'pendiente')

    def test_errores_de_archivo_calibracion_y_no_exitosos(self):
        r = self.cliente.post(f'/api/ejecuciones/{self.ejecucion}/comparaciones-fisicas', json={'pieza': 'P', 'calibracion_realizada': True})
        self.assertEqual(r.status_code, 422)
        identificador = self.crear()
        for nombre in ('proyecto.creality', 'scan.exe'):
            self.assertEqual(self.cliente.put(f'/api/comparaciones-fisicas/{identificador}/escaneo?nombre={nombre}', content=b'a').status_code, 422)
        self.assertEqual(self.cliente.put(f'/api/comparaciones-fisicas/{identificador}/escaneo?nombre=a.stl', content=b'').status_code, 422)
        self.assertEqual(self.cliente.post(f'/api/comparaciones-fisicas/{identificador}/confirmar').status_code, 409)
        with self.sesiones() as s:
            s.get(Ejecucion, self.ejecucion).estado = 'fallida'; s.commit()
        self.assertEqual(self.cliente.post(f'/api/ejecuciones/{self.ejecucion}/comparaciones-fisicas', json={'pieza': 'P'}).status_code, 409)

    def test_recuperacion_y_confirmacion_no_repite_inferencia(self):
        identificador = self.crear()
        with self.sesiones() as s:
            r = s.get(ComparacionFisica, identificador); r.estado = 'procesando'; r.escaneo_sha256 = 'a' * 64; s.commit()
        metrologia.recuperar_interrumpidas()
        with self.sesiones() as s:
            self.assertEqual(s.get(ComparacionFisica, identificador).estado, 'fallida')
            r = s.get(ComparacionFisica, identificador); r.estado = 'completada'; r.resultado = {'protocolo': VERSION}; s.commit()
        self.assertEqual(self.cliente.post(f'/api/comparaciones-fisicas/{identificador}/confirmar').status_code, 200)
        with self.sesiones() as s:
            self.assertTrue(s.get(ComparacionFisica, identificador).alineacion_confirmada)
            self.assertEqual(s.get(Ejecucion, self.ejecucion).estado, 'completada')
        self.programar.assert_not_called()

    def test_zip_trazable_incluye_escaneo_y_no_fabrica_medidas(self):
        identificador = self.crear()
        r = self.cliente.get(f'/api/comparaciones-fisicas/{identificador}/entregables.zip')
        self.assertEqual(r.status_code, 200, r.text[:100])
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            self.assertIn('tabla_metrologica.csv', z.namelist())
            self.assertIn(f'comparaciones/{identificador}/nominal.stl', z.namelist())
            manifiesto = json.loads(z.read('manifiesto.json'))
            for archivo in manifiesto['archivos']:
                self.assertEqual(hashlib.sha256(z.read(archivo['archivo'])).hexdigest(), archivo['sha256'])
            self.assertNotIn('0.15', z.read('tabla_metrologica.csv').decode())


class ExportacionesYComparativaTests(unittest.TestCase):
    setUp = FlujoFisicoTests.setUp
    crear = FlujoFisicoTests.crear
    def preparar_campana(self):
        from aplicacion.base_datos import Campana, CasoDiseno, VersionConjunto
        self.campana = str(uuid4()); conjunto = str(uuid4()); caso = str(uuid4())
        with self.sesiones() as s:
            s.add(VersionConjunto(identificador=conjunto, nombre='Conjunto ensayo', version='1', finalidad='desarrollo', estado='congelado', huella_sha256='b' * 64))
            s.flush()
            s.add(CasoDiseno(identificador=caso, conjunto_identificador=conjunto, codigo='B01', nivel='basico', familia='Caja', fundamento='Ensayo', descripcion='Caja de ensayo', especificacion={'unidad': 'mm'}))
            s.add(Campana(identificador=self.campana, conjunto_identificador=conjunto, nombre='Selección de un caso', tipo='seleccion', estado='completada', semilla=1, repeticiones=1,
                total_ejecuciones=1, configuracion={'conjunto_sha256': 'b' * 64, 'modelos':['L01'], 'motores':['cadquery'], 'modos':['open-loop']}))
            s.flush()
            e = s.get(Ejecucion, self.ejecucion); e.campana_identificador = self.campana; e.caso_identificador = caso
            e.modo = 'open-loop'; e.primer_exito_ejecucion = 1; e.primer_exito_exportacion = 1
            s.commit()

    def test_manual_exporta_tamano_real_y_conserva_plantilla_rellenada(self):
        from aplicacion import archivado, metricas, campanas
        import nativo.exportaciones as exportaciones
        self.preparar_campana()
        with patch.object(campanas, 'crear_sesion', self.sesiones), patch.object(archivado, 'crear_sesion', self.sesiones), patch.object(metricas, 'crear_sesion', self.sesiones), \
             patch.object(exportaciones, 'crear_sesion', self.sesiones), patch.object(archivado, 'MODO_NATIVO', True), \
             patch.object(archivado, 'DIRECTORIO_RESULTADOS', str(self.carpeta / 'resultados')):
            archivado.guardar_ejecucion(self.ejecucion)
            archivado.guardar_resumen(self.campana)
            carpeta = self.carpeta / 'resultados' / ('Campana-' + self.campana)
            self.assertTrue((carpeta / 'manufacturabilidad.csv').exists())
            self.assertEqual(json.loads((carpeta / 'alcance_metricas.json').read_text())['n_prompts'], 1)
            self.assertNotIn('1.350', (carpeta / 'LEEME.txt').read_text())
            plantilla = carpeta / 'mediciones_fisicas.csv'; plantilla.write_text('medición del usuario')
            archivado.guardar_resumen(self.campana)
            self.assertEqual(plantilla.read_text(), 'medición del usuario')
            conjunto = json.loads((carpeta / 'protocolo/conjunto.json').read_text())
            self.assertEqual(conjunto['nombre'], 'Conjunto ensayo')
            self.assertEqual(len(list(carpeta.rglob('prompt.txt'))), 1)

    def test_resultados_externos_exigen_mismos_casos_y_no_derivan_compile_de_ir(self):
        from aplicacion import comparativa, metricas
        from aplicacion.resultados import filas_tabla_digital
        self.preparar_campana()
        with patch.object(comparativa, 'crear_sesion', self.sesiones), patch.object(metricas, 'crear_sesion', self.sesiones):
            plantilla = self.cliente.get(f'/api/campanas/{self.campana}/plantilla-resultados-externos.json').json()
            plantilla.update(metodo='Método externo de ensayo', fuente='Trazas de ensayo externo', condiciones='Mismos prompts; un intento; CadQuery')
            plantilla['casos'][0].update(ejecucion_correcta=True, cad_exportable=False)
            r = self.cliente.post(f'/api/campanas/{self.campana}/resultados-externos', json=plantilla)
            self.assertEqual(r.status_code, 201, r.text)
            filas = filas_tabla_digital(metricas.calcular_metricas_campana(self.campana))
            externa = next(f for f in filas if f['origen'] == 'ensayo_externo_aportado')
            self.assertEqual(externa['compile_rate_pct'], 100)
            self.assertEqual(externa['ir_cad_pct'], 100)
            plantilla['conjunto_sha256'] = 'c' * 64
            self.assertEqual(self.cliente.post(f'/api/campanas/{self.campana}/resultados-externos', json=plantilla).status_code, 422)

    def test_migracion_sqlite_06_crea_copia_y_preserva_resultado(self):
        import aplicacion.base_datos as base
        ruta = self.carpeta / 'historica.sqlite'
        motor = create_engine('sqlite:///' + str(ruta))
        self.addCleanup(motor.dispose)
        BaseDeclarativa.metadata.create_all(motor)
        with motor.begin() as conexion:
            conexion.exec_driver_sql('DROP TABLE comparaciones_fisicas')
            conexion.exec_driver_sql("INSERT INTO ejecuciones (identificador,descripcion,motor,modelo,estado,mensaje,numero_intentos,modo,repeticion,maximo_intentos,fecha_creacion,fecha_actualizacion) VALUES ('antigua','conservar','cadquery','L01','completada','terminada',1,'open-loop',1,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        with patch.object(base, 'motor_base_datos', motor):
            base.crear_tablas(); base.crear_tablas()
        self.assertEqual(len(list(self.carpeta.glob('historica.sqlite.antes-0.7.0-*.bak'))), 1)
        with motor.connect() as conexion:
            self.assertEqual(conexion.exec_driver_sql("SELECT estado FROM ejecuciones WHERE identificador='antigua'").scalar(), 'completada')
