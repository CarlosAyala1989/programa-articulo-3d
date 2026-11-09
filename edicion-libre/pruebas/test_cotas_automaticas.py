"""Regresiones de metrología v2 con STL público y controles analíticos independientes."""
import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import trimesh
from scipy.spatial.distance import directed_hausdorff

from evaluador.cotas_automaticas import proponer_cotas, medir_cotas
from evaluador.protocolo_cotas import huella_plan
from evaluador.metrologia import cargar_geometria, calcular, hausdorff_discreto, VERSION_ACTUAL
from test_metrologia import configuracion
import test_metrologia as anteriores
from aplicacion import metrologia
from aplicacion.base_datos import ComparacionFisica, PlanCotas

RAIZ_MODELO = Path(__file__).parent / 'datos/placa_publica'


def placa():
    malla = cargar_geometria(RAIZ_MODELO / 'placa_agujeros.stl')
    malla.apply_translation(-malla.bounds.mean(0))
    malla.apply_scale(.25)
    return malla


class CotasAutomaticasTests(unittest.TestCase):
    def test_fuente_publica_conserva_sha_y_licencia(self):
        origen = json.loads((RAIZ_MODELO / 'origen.json').read_text())
        for nombre, datos in origen['archivos'].items():
            self.assertEqual(hashlib.sha256((RAIZ_MODELO / nombre).read_bytes()).hexdigest(), datos['sha256'])
        self.assertIn('MIT', (RAIZ_MODELO / 'LICENCIA-MIT.txt').read_text())

    def test_detecta_seis_agujeros_y_dimensiones_de_placa(self):
        plan = proponer_cotas(placa(), 'nominal')
        diametros = sorted(c['nominal_mm'] for c in plan['cotas'] if c['tipo'] == 'diametro')
        self.assertEqual(len(diametros), 6)
        np.testing.assert_allclose(diametros, [1.6891] * 5 + [2.778125], atol=.00001)
        planos = sorted(c['nominal_mm'] for c in plan['cotas'] if c['tipo'] == 'distancia_planos')
        np.testing.assert_allclose(planos, [3.175, 50.8, 76.2], atol=.00001)

    def test_placa_identica_no_inventa_error_en_los_agujeros(self):
        nominal = placa(); plan = proponer_cotas(nominal, 'nominal')
        filas = medir_cotas(nominal, plan, .5, 7)
        self.assertTrue(all(c['estado'] == 'medida' for c in filas), filas)
        self.assertLess(max(abs(c['delta_mm']) for c in filas), .0001)

    def test_contraccion_conocida_mide_diametros_y_espesor(self):
        nominal = placa(); plan = proponer_cotas(nominal, 'nominal')
        escaneo = nominal.copy(); escaneo.apply_scale(.99)
        filas = medir_cotas(escaneo, plan, .5, 8)
        self.assertTrue(all(c['estado'] == 'medida' for c in filas), filas)
        for cota in filas:
            self.assertAlmostEqual(cota['delta_mm'], -.01 * cota['nominal_mm'], delta=.002)

    def test_circulo_analitico_con_ruido_y_error_de_diametro(self):
        nominal = placa(); plan = proponer_cotas(nominal, 'nominal')
        cota = next(c for c in plan['cotas'] if c['tipo'] == 'diametro')
        base = np.array(cota['base']); centro = np.array(cota['centro_xy'])
        azar = np.random.default_rng(9); angulos = np.linspace(0, 2 * np.pi, 3000, endpoint=False)
        radio = cota['nominal_mm'] / 2 + .1
        xy = centro + np.column_stack([np.cos(angulos), np.sin(angulos)]) * radio
        z0, z1 = cota['limites_z']; z = azar.uniform(z0, z1, len(xy))
        puntos = np.column_stack([xy, z]) @ base.T + azar.normal(0, .003, (len(xy), 3))
        fila = medir_cotas(trimesh.points.PointCloud(puntos), {**plan, 'cotas': [cota]}, .4, 9)[0]
        self.assertEqual(fila['estado'], 'medida', fila)
        self.assertAlmostEqual(fila['delta_mm'], .2, delta=.002)
        self.assertLess(fila['residuo_ajuste_rmse_mm'], .005)
        # Ocultar la mitad del cilindro debe invalidar la medida, sin sustituirla por un bbox.
        fila = medir_cotas(trimesh.points.PointCloud(puntos[:1500]), {**plan, 'cotas': [cota]}, .4, 9)[0]
        self.assertEqual(fila['estado'], 'sin_cobertura')
        self.assertIsNone(fila['medido_mm'])

    def test_un_solo_plano_no_produce_espesor(self):
        nominal = trimesh.creation.box([40, 25, 12]); plan = proponer_cotas(nominal, 'nominal')
        cota = next(c for c in plan['cotas'] if abs(c['nominal_mm'] - 12) < .001)
        azar = np.random.default_rng(10)
        nube = trimesh.points.PointCloud(np.column_stack([azar.uniform(-19, 19, 1000), azar.uniform(-11, 11, 1000), np.full(1000, 6.)]))
        fila = medir_cotas(nube, {**plan, 'cotas': [cota]}, .5, 10)[0]
        self.assertEqual(fila['estado'], 'sin_cobertura'); self.assertIsNone(fila['delta_mm'])

    def test_hausdorff_exhaustivo_coincide_con_scipy_y_conserva_outlier(self):
        azar = np.random.default_rng(11); a = azar.random((1200, 3)); b = azar.random((1900, 3))
        b = np.vstack([b, [50, 30, 20]])
        referencia = max(directed_hausdorff(a, b)[0], directed_hausdorff(b, a)[0])
        self.assertAlmostEqual(hausdorff_discreto(a, b), referencia, places=10)
        self.assertGreater(hausdorff_discreto(a, b), 50)

    def test_ply_con_vertice_aislado_se_conserva_en_maximo_discreto(self):
        import tempfile
        nominal = trimesh.creation.box([40, 25, 12])
        malla = trimesh.Trimesh(vertices=np.vstack([nominal.vertices, [[50, 0, 0]]]),
                                faces=nominal.faces, process=False)
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / 'escaneo.ply'; malla.export(ruta)
            escaneo = cargar_geometria(ruta)
            # El punto no pertenece a la superficie de ningún triángulo.
            self.assertEqual(len(escaneo.vertices), 8)
            r, _, _ = calcular(nominal, escaneo, configuracion(protocolo=VERSION_ACTUAL))
            self.assertEqual(r['puntos_hausdorff_escaneo'], 9)
            self.assertGreater(r['hausdorff_maximo_mm'], 29)
            self.assertLess(r['hausdorff_superficie_muestreado_mm'], 1e-8)

    def test_v2_separa_discreto_superficie_y_dispersion_entre_cotas(self):
        nominal = placa(); plan = proponer_cotas(nominal, 'nominal')
        escaneo = nominal.copy(); escaneo.apply_scale(.999)
        r, _, _ = calcular(nominal, escaneo, configuracion(protocolo=VERSION_ACTUAL, plan_cotas=plan, banda_cotas_mm=.5))
        self.assertEqual(r['protocolo'], VERSION_ACTUAL)
        self.assertEqual(r['puntos_hausdorff_escaneo'], len(escaneo.vertices))
        self.assertTrue(r['error_dimensional']['completo'])
        self.assertEqual(r['error_dimensional']['cotas_medidas'], 9)
        self.assertIn('no repetibilidad', r['error_dimensional']['alcance_desviacion'])
        self.assertAlmostEqual(r['hausdorff_maximo_mm'], hausdorff_discreto(nominal.vertices, escaneo.vertices))
        self.assertIn('hausdorff_superficie_muestreado_mm', r)

    def test_cilindros_coaxiales_vecinos_no_contaminan_cota_seleccionada(self):
        nominal = placa(); plan = proponer_cotas(nominal, 'nominal')
        mayor = next(c for c in plan['cotas'] if c['tipo'] == 'diametro')
        menor = next(c for c in plan['cotas'] if c['tipo'] == 'diametro' and
                     c['nominal_mm'] < mayor['nominal_mm'] and
                     np.linalg.norm(np.array(c['centro_xy']) - mayor['centro_xy']) < .001)
        escaneo = nominal.copy(); escaneo.apply_scale(.99); escaneo.apply_translation([.08, .03, 0])
        # Aunque se mida solo el diámetro menor, el escalón vecino sigue siendo una región de exclusión.
        fila = medir_cotas(escaneo, {**plan, 'cotas': [menor]}, .5, 12)[0]
        self.assertEqual(fila['estado'], 'medida', fila)
        self.assertAlmostEqual(fila['delta_mm'], -.01 * menor['nominal_mm'], delta=.002)

    def test_rechaza_plan_de_otro_nominal_o_modificado(self):
        import tempfile
        from evaluador.metrologia import procesar_carpeta
        with tempfile.TemporaryDirectory() as temporal:
            carpeta = Path(temporal); nominal = placa()
            nominal.export(carpeta / 'nominal.stl'); nominal.export(carpeta / 'escaneo.ply')
            sha = hashlib.sha256((carpeta / 'nominal.stl').read_bytes()).hexdigest()
            plan = proponer_cotas(nominal, 'otro-nominal')
            config = configuracion(protocolo=VERSION_ACTUAL, extension='.ply', nominal_sha256=sha,
                escaneo_sha256=hashlib.sha256((carpeta / 'escaneo.ply').read_bytes()).hexdigest(),
                plan_cotas=plan, plan_cotas_sha256=huella_plan(plan))
            (carpeta / 'configuracion.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'plan de cotas'):
                procesar_carpeta(carpeta)
            plan['nominal_sha256'] = sha
            (carpeta / 'configuracion.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'plan de cotas'):
                procesar_carpeta(carpeta)

    def test_v1_sigue_siendo_muestreado_al_reintentar(self):
        nominal = trimesh.creation.box([40, 25, 12])
        r, _, _ = calcular(nominal, nominal.copy(), configuracion(protocolo='ciel-metrologia-otter-v1'))
        self.assertEqual(r['protocolo'], 'ciel-metrologia-otter-v1')
        self.assertNotIn('hausdorff_alcance', r)
        self.assertNotIn('cotas_automaticas', r)


class ConfiguracionReutilizableTests(unittest.TestCase):
    setUp = anteriores.FlujoFisicoTests.setUp
    def test_perfil_no_reutiliza_calibracion_y_no_mutan_comparaciones(self):
        perfil = self.cliente.post('/api/metrologia/perfiles', json={'nombre': 'PLA + Otter', 'configuracion': {'material': 'PLA', 'banda_cotas_mm': .4}})
        self.assertEqual(perfil.status_code, 201, perfil.text)
        p = perfil.json()
        self.assertNotIn('fecha_calibracion', p['configuracion'])
        self.assertEqual(self.cliente.post('/api/metrologia/perfiles', json={'nombre': 'Inválido', 'configuracion': {'calibracion_realizada': True}}).status_code, 422)
        # La instantánea usa el perfil aun si otro cliente solo envía su identificador.
        respuesta = self.cliente.post(f'/api/ejecuciones/{self.ejecucion}/comparaciones-fisicas', json={'pieza': 'Réplica 1', 'perfil_identificador': p['identificador']})
        self.assertEqual(respuesta.status_code, 201, respuesta.text)
        self.assertEqual(respuesta.json()['configuracion']['material'], 'PLA')
        nuevo = self.cliente.post('/api/metrologia/perfiles', json={'nombre': 'PETG', 'configuracion': {'material': 'PETG'}})
        self.assertEqual(nuevo.status_code, 201)
        with self.sesiones() as sesion:
            guardada = sesion.get(ComparacionFisica, respuesta.json()['identificador'])
            self.assertEqual(guardada.configuracion['material'], 'PLA')
            self.assertFalse(guardada.configuracion['calibracion_realizada'])

    def test_plan_versionado_y_seleccion_no_alteran_comparacion_anterior(self):
        propuesta = self.cliente.post(f'/api/ejecuciones/{self.ejecucion}/plan-cotas/proponer')
        self.assertEqual(propuesta.status_code, 200, propuesta.text)
        origen = propuesta.json()
        creada = self.cliente.post(f'/api/ejecuciones/{self.ejecucion}/comparaciones-fisicas', json={'pieza': 'Réplica 1'}).json()
        codigo = origen['documento']['cotas'][0]['codigo']
        seleccion = self.cliente.post(f'/api/ejecuciones/{self.ejecucion}/plan-cotas', json={'origen_identificador': origen['identificador'], 'codigos': [codigo]})
        self.assertEqual(seleccion.status_code, 200, seleccion.text)
        self.assertNotEqual(seleccion.json()['identificador'], origen['identificador'])
        with self.sesiones() as sesion:
            anterior = sesion.get(ComparacionFisica, creada['identificador'])
            self.assertGreater(len(anterior.configuracion['plan_cotas']['cotas']), 1)
            self.assertEqual(anterior.configuracion['plan_cotas_sha256'], origen['sha256'])
        self.assertEqual(self.cliente.post(f'/api/ejecuciones/{self.ejecucion}/plan-cotas', json={'origen_identificador': origen['identificador'], 'codigos': ['falsa']}).status_code, 422)

    def test_migracion_08_respalda_sin_reescribir_comparaciones(self):
        import tempfile
        from sqlalchemy import create_engine, inspect
        from aplicacion import base_datos
        from aplicacion.base_datos import BaseDeclarativa
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / 'historica.sqlite'
            motor = create_engine('sqlite:///' + str(ruta))
            BaseDeclarativa.metadata.create_all(motor)
            with motor.begin() as conexion:
                conexion.exec_driver_sql('DROP TABLE planes_cotas')
                conexion.exec_driver_sql('DROP TABLE perfiles_metrologia')
            with patch.object(base_datos, 'motor_base_datos', motor):
                base_datos.crear_tablas()
                self.assertIn('planes_cotas', inspect(motor).get_table_names())
                base_datos.crear_tablas()
            motor.dispose()
            self.assertEqual(len(list(Path(temporal).glob('*.antes-0.8.0-*.bak'))), 1)
