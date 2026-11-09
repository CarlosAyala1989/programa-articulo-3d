"""Regresiones del inventario nativo y campañas manuales, sin inferencia ni CAD."""

import json
import os
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from nativo.modelos import registrar_modelos
from aplicacion.base_datos import BaseDeclarativa, Campana, Ejecucion
from aplicacion.campanas import crear_campana, cambiar_estado
from aplicacion.conjuntos import importar_documento
from aplicacion.iniciar_trabajador import preparar_reinicio

PROGRAMA = Path(__file__).resolve().parents[1] / 'programa'


class InventarioTests(unittest.TestCase):
    def registrar(self, modelos, fallo=False):
        cliente = MagicMock()
        if fallo:
            cliente.get.side_effect = httpx.ConnectError('Ollama cerrado')
        else:
            cliente.get.return_value = httpx.Response(200, json={'models': modelos},
                request=httpx.Request('GET', 'http://prueba/api/tags'))
        cliente.post.return_value = httpx.Response(200, json={'template': 'plantilla'},
            request=httpx.Request('POST', 'http://prueba/api/show'))
        with tempfile.TemporaryDirectory() as carpeta, patch('nativo.modelos.httpx.Client') as fabrica:
            fabrica.return_value.__enter__.return_value = cliente
            destino = Path(carpeta) / 'modelos.json'
            resultado = registrar_modelos(PROGRAMA, destino)
            self.assertEqual(json.loads(destino.read_text()), resultado)
        return resultado, cliente

    def test_etiquetas_distintas_y_mas_de_cinco_sin_exigir_los_originales(self):
        modelos = [{'name': f'usuario/modelo:{n}', 'digest': str(n) * 64,
                    'details': {'quantization_level': 'Q4_K_M'}} for n in range(1, 8)]
        resultado, cliente = self.registrar(modelos)
        self.assertEqual(len(resultado['modelos']), 7)
        self.assertEqual({m['etiqueta'] for m in resultado['modelos'].values()}, {m['name'] for m in modelos})
        otro, _ = self.registrar(list(reversed(modelos)))
        self.assertEqual(resultado, otro)
        self.assertTrue(all(c.kwargs['json'].keys() == {'model'} for c in cliente.post.call_args_list))

    def test_configuracion_e_inferencia_admiten_modelo_adicional(self):
        inventario, _ = self.registrar([{'name': 'usuario/extra:latest', 'digest': 'a' * 64,
            'details': {'quantization_level': 'Q4_K_M'}}])
        codigo = next(iter(inventario['modelos']))
        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / 'inventario.json'
            archivo.write_text(json.dumps(inventario))
            codigo_prueba = """
import json, os
from unittest.mock import MagicMock, patch
import httpx
from aplicacion.configuracion import MODELOS_LOCALES, perfil_generacion
from aplicacion.proveedores import modelos_configurados, verificar_modelo_local
codigo = os.environ['CODIGO_PRUEBA']
assert list(modelos_configurados()) == [codigo]
assert perfil_generacion(codigo)['num_ctx'] == 16384
cliente = MagicMock()
cliente.get.return_value = httpx.Response(200, json={'models':[{'name':'usuario/extra:latest',
    'digest':'a'*64,'details':{'quantization_level':'Q4_K_M'}}]},
    request=httpx.Request('GET','http://prueba/api/tags'))
with patch('aplicacion.proveedores.httpx.Client') as fabrica:
    fabrica.return_value.__enter__.return_value = cliente
    assert verificar_modelo_local(codigo)['etiqueta'] == 'usuario/extra:latest'
"""
            proceso = subprocess.run([sys.executable, '-c', codigo_prueba], capture_output=True, text=True,
                env={**os.environ, 'CIEL_MODO_NATIVO': '1', 'CIEL_REGISTRO_MODELOS': str(archivo),
                     'CODIGO_PRUEBA': codigo})
            self.assertEqual(proceso.returncode, 0, proceso.stderr)

    def test_perfil_original_y_variante_separados(self):
        originales = json.loads((PROGRAMA / 'datos/modelos_windows_nativos_v1.json').read_text())['modelos']
        modelos = [{'name': m['etiqueta'], 'digest': 'a' * 64,
                    'details': {'quantization_level': m['cuantizacion']}} for m in originales]
        resultado, _ = self.registrar(modelos)
        self.assertEqual(set(resultado['modelos']), {'L01', 'L02', 'L03', 'L04', 'L05'})
        modelos[0]['details']['quantization_level'] = 'Q4_K_M'
        resultado, _ = self.registrar(modelos)
        self.assertNotIn('L01', resultado['modelos'])
        self.assertEqual(len(resultado['modelos']), 5)

    def test_sin_ollama_o_sin_modelos_se_puede_abrir(self):
        resultado, _ = self.registrar([], fallo=True)
        self.assertEqual(resultado['modelos'], {})
        self.assertTrue(resultado['avisos'])
        resultado, _ = self.registrar([])
        self.assertEqual(resultado['modelos'], {})


class CampanaManualTests(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine('sqlite://')
        BaseDeclarativa.metadata.create_all(self.motor)
        self.sesiones = sessionmaker(bind=self.motor, expire_on_commit=False)
        self.addCleanup(self.motor.dispose)
        for modulo in ('campanas', 'conjuntos', 'iniciar_trabajador'):
            parche = patch(f'aplicacion.{modulo}.crear_sesion', self.sesiones)
            parche.start()
            self.addCleanup(parche.stop)

    def test_guardar_solo_seleccion_no_inicia_y_reinicio_no_programa(self):
        documento = json.loads((PROGRAMA / 'datos/prompts_45_v1.json').read_text())
        conjunto = importar_documento(documento, congelar=True)
        with patch.dict(os.environ, {'OLLAMA_L01': 'mi-modelo', 'CIEL_AUTOMATICO': '0'}):
            campana = crear_campana('Manual', conjunto.identificador, ['L01'], ['cadquery'],
                ['closed-loop'], 1, 7, 'seleccion', [documento['casos'][0]['codigo']])
            self.assertEqual(campana.estado, 'borrador')
            self.assertEqual(campana.total_ejecuciones, 1)
            self.assertEqual(campana.maximo_generaciones, 5)
            self.assertEqual(campana.configuracion['protocolo_campana'], 'ciel-campana-manual-v1')
            with self.sesiones() as sesion:
                registro = sesion.get(Campana, campana.identificador)
                registro.estado = 'en_curso'
                registro.configuracion = {**registro.configuracion, 'automatico': True}
                sesion.commit()
            with patch('aplicacion.iniciar_trabajador.MODO_NATIVO', True), \
                 patch('aplicacion.iniciar_trabajador.crear_tablas'), \
                 patch('aplicacion.tareas_nativas.tarea_campana.delay') as programar, \
                 patch('aplicacion.automatico.asegurar_lote') as automatico:
                preparar_reinicio()
                programar.assert_not_called()
                automatico.assert_not_called()
            with self.sesiones() as sesion:
                self.assertEqual(sesion.get(Campana, campana.identificador).estado, 'pausada')
                self.assertEqual(len(list(sesion.scalars(select(Ejecucion)))), 1)

    def test_cambio_de_digest_se_rechaza_al_reanudar(self):
        documento = json.loads((PROGRAMA / 'datos/prompts_45_v1.json').read_text())
        conjunto = importar_documento(documento, congelar=True)
        with patch.dict(os.environ, {'OLLAMA_L01': 'mi-modelo'}):
            campana = crear_campana('Manual', conjunto.identificador, ['L01'], ['cadquery'],
                ['open-loop'], 1, 7, 'seleccion', [documento['casos'][0]['codigo']])
        cliente = MagicMock()
        cliente.get.return_value.json.return_value = {'cadquery': 'runtime-fijo'}
        with patch('aplicacion.campanas.httpx.Client') as fabrica, \
             patch('aplicacion.campanas.verificar_modelo_local', return_value={'digest': 'a' * 64}):
            fabrica.return_value.__enter__.return_value = cliente
            cambiar_estado(campana.identificador, 'iniciar')
            cambiar_estado(campana.identificador, 'pausar')
            with patch('aplicacion.campanas.verificar_modelo_local', return_value={'digest': 'b' * 64}):
                with self.assertRaisesRegex(ValueError, 'digest'):
                    cambiar_estado(campana.identificador, 'iniciar')
