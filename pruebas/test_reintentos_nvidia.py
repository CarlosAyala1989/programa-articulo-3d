"""NVIDIA recupera incidencias de red sin gastar iteraciones científicas ni cuotas reales."""

import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aplicacion.api import aplicacion, _cambiar_campana
from aplicacion.base_datos import BaseDeclarativa, Campana, Ejecucion, VersionConjunto
from aplicacion.calidad.nvidia import ErrorNvidia
from aplicacion.configuracion import VERSION_PLANTILLA, VERSION_REINTENTOS_NVIDIA, perfil_generacion
from aplicacion.generacion import procesar_ejecucion, _reintentos_nvidia_ejecucion
from aplicacion.metricas import resumen_grupo
from aplicacion.proveedores import solicitar_codigo
from aplicacion.reintentos_nvidia import reintentar_nvidia


MODELO = 'nvidia/nemotron-3-super-120b-a12b'
CODIGO = "import cadquery as cq\nresultado = cq.Workplane('XY').box(20, 20, 20)"


def respuesta_correcta():
    return httpx.Response(200, json={'model': MODELO, 'id': 'respuesta-simulada',
        'choices': [{'message': {'content': CODIGO}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 20, 'completion_tokens': 30}})


class ReintentosNvidia(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        BaseDeclarativa.metadata.create_all(self.motor)
        self.sesiones = sessionmaker(bind=self.motor, expire_on_commit=False)
        self.contexto = ExitStack()
        self.addCleanup(self.contexto.close)
        self.addCleanup(self.motor.dispose)
        for modulo in ('generacion', 'api'):
            self.contexto.enter_context(patch(f'aplicacion.{modulo}.crear_sesion', self.sesiones))
        self.contexto.enter_context(patch.dict('os.environ', {'NVIDIA_API_KEY': 'clave-simulada'}))
        self.dormir = self.contexto.enter_context(patch('aplicacion.reintentos_nvidia.time.sleep'))
        self.respaldo = self.contexto.enter_context(patch('aplicacion.proveedores.solicitar_deepseek'))
        self.cliente_real = httpx.Client
        with self.sesiones() as sesion:
            sesion.add(VersionConjunto(identificador='conjunto', nombre='Prueba', version='1', finalidad='desarrollo', estado='congelado'))
            sesion.add(Campana(identificador='campana', nombre='NVIDIA', conjunto_identificador='conjunto',
                estado='en_curso', semilla=1, configuracion={'plantilla': VERSION_PLANTILLA,
                'perfiles_generacion': {MODELO: perfil_generacion(MODELO)}}))
            sesion.add(Ejecucion(identificador='ejecucion', descripcion='Cubo de veinte milímetros de lado',
                modelo=MODELO, motor='cadquery', modo='open-loop', maximo_intentos=1,
                campana_identificador='campana', estado='pendiente'))
            sesion.commit()

    def transporte(self, responder):
        return patch('aplicacion.calidad.nvidia.httpx.Client', side_effect=lambda **opciones:
            self.cliente_real(transport=httpx.MockTransport(responder), **opciones))

    def test_timeout_y_respuesta_vacia_recuperan_el_mismo_modelo_y_un_solo_intento(self):
        llamadas = []
        def responder(peticion):
            llamadas.append(json.loads(peticion.content))
            if len(llamadas) == 1:
                raise httpx.ReadTimeout('sin respuesta', request=peticion)
            if len(llamadas) == 2:
                with self.sesiones() as sesion:
                    e = sesion.get(Ejecucion, 'ejecucion')
                    self.assertEqual(e.estado, 'generando')
                    self.assertEqual(e.numero_intentos, 1)
                    self.assertEqual(e.intentos[0].estado, 'esperando_proveedor')
                    self.assertIsNone(e.intentos[0].sintaxis_valida)
                    self.assertEqual(resumen_grupo([e], {}, {}, 'open-loop')['n_evaluable'], 0)
                return httpx.Response(200, json={'choices': []})
            return respuesta_correcta()
        with self.transporte(responder), patch('aplicacion.generacion.solicitar_ejecucion_cad', return_value={
                'correcto': True, 'ejecucion_correcta': True, 'cad_valido': True, 'exportacion_valida': True, 'archivos': []}), \
             patch('aplicacion.generacion.guardar_archivos'), patch('aplicacion.analisis.analizar_ejecucion'):
            procesar_ejecucion('ejecucion')
        self.assertEqual(len(llamadas), 3)
        self.assertTrue(all(p == llamadas[0] for p in llamadas))
        self.respaldo.assert_not_called()
        with self.sesiones() as sesion:
            e = sesion.get(Ejecucion, 'ejecucion')
            self.assertEqual(e.estado, 'completada')
            self.assertEqual(len(e.intentos), 1)
            self.assertEqual(e.primer_exito_ejecucion, 1)
            incidencias = e.intentos[0].solicitud_modelo['reintentos_operativos']
            self.assertEqual([i['codigo'] for i in incidencias], ['timeout', 'malformed_response'])
            self.assertEqual([i['espera_segundos'] for i in incidencias], [5, 10])
            self.assertEqual([i['timeout_segundos'] for i in incidencias], [90, 180])
            self.assertEqual(e.intentos[0].solicitud_modelo['perfil']['timeout_ultima_llamada_segundos'], 360)
            self.assertTrue(all(i['consumo_desconocido'] for i in incidencias))
            self.assertIsNone(e.intentos[0].fase_error)

    def test_transporte_408_429_y_errores_temporales_se_recuperan(self):
        for incidencia in ('conexion', 'escritura', 408, 429, 500, 502, 503, 504):
            with self.subTest(incidencia=incidencia):
                llamadas = []
                def responder(peticion):
                    llamadas.append(peticion)
                    if len(llamadas) == 1:
                        if incidencia == 'conexion':
                            raise httpx.ConnectError('red', request=peticion)
                        if incidencia == 'escritura':
                            raise httpx.WriteTimeout('red', request=peticion)
                        return httpx.Response(incidencia, headers={'Retry-After': '75', 'x-request-id': 'req-simulado'})
                    return respuesta_correcta()
                with self.transporte(responder):
                    resultado = solicitar_codigo(MODELO, [], reintentos_nvidia=True)
                self.assertEqual(len(llamadas), 2)
                if isinstance(incidencia, int):
                    self.assertEqual(resultado['perfil']['reintentos_operativos'][0]['espera_segundos'], 75)
                self.assertEqual(resultado['modelo_informado'], MODELO)
                self.respaldo.assert_not_called()

    def test_espera_se_estabiliza_sin_agotar_los_cinco_intentos_cad(self):
        operacion = Mock(side_effect=[*[ErrorNvidia('Timeout', 'timeout') for _ in range(8)], 'respuesta'])
        respuesta, incidencias = reintentar_nvidia(operacion, MODELO)
        self.assertEqual(respuesta, 'respuesta')
        self.assertEqual([i['espera_segundos'] for i in incidencias], [5, 10, 20, 40, 60, 60, 60, 60])
        self.assertEqual(operacion.call_count, 9)

    def test_error_de_credenciales_no_se_reintenta_ni_se_cuenta_como_cad_fallido(self):
        llamadas = []
        def responder(peticion):
            llamadas.append(peticion)
            return httpx.Response(401)
        with self.transporte(responder):
            procesar_ejecucion('ejecucion')
        self.assertEqual(len(llamadas), 1)
        self.dormir.assert_not_called()
        self.respaldo.assert_not_called()
        with self.sesiones() as sesion:
            e = sesion.get(Ejecucion, 'ejecucion')
            self.assertEqual(e.estado, 'bloqueada')
            self.assertEqual(e.intentos[0].fase_error, 'proveedor')
            self.assertIsNone(e.intentos[0].sintaxis_valida)
            self.assertEqual(resumen_grupo([e], {}, {}, 'open-loop')['n_evaluable'], 0)

    def test_cancelar_durante_espera_detiene_otra_llamada_sin_fallo_cad(self):
        llamadas = []
        def responder(peticion):
            llamadas.append(peticion)
            raise httpx.ReadTimeout('sin respuesta', request=peticion)
        def cancelar(_):
            with self.sesiones() as sesion:
                sesion.get(Campana, 'campana').estado = 'cancelada'
                sesion.commit()
        self.dormir.side_effect = cancelar
        with self.transporte(responder):
            procesar_ejecucion('ejecucion')
        self.assertEqual(len(llamadas), 1)
        with self.sesiones() as sesion:
            e = sesion.get(Ejecucion, 'ejecucion')
            self.assertEqual(e.estado, 'cancelada')
            self.assertEqual(e.intentos[0].estado, 'cancelado')
            self.assertIsNone(e.intentos[0].sintaxis_valida)

    def test_campana_historica_no_adopta_politica_nueva(self):
        with self.sesiones() as sesion:
            c = sesion.get(Campana, 'campana')
            c.configuracion = {'plantilla': VERSION_PLANTILLA,
                'perfiles_generacion': {MODELO: {'max_tokens': 8192}}}
            sesion.commit()
            self.assertFalse(_reintentos_nvidia_ejecucion(sesion, sesion.get(Ejecucion, 'ejecucion')))
            self.assertEqual(c.configuracion['perfiles_generacion'][MODELO], {'max_tokens': 8192})

    def test_api_separa_la_cola_nvidia_sin_reprogramar_campanas_cli(self):
        cliente = TestClient(aplicacion)
        self.addCleanup(cliente.close)
        with patch('aplicacion.api.preparar_base_datos'), \
             patch('aplicacion.api.modelos_configurados', return_value={MODELO: 'NVIDIA'}), \
             patch('aplicacion.api.tarea_generacion.apply_async') as programar:
            respuesta = cliente.post('/api/ejecuciones', json={'descripcion': 'Cubo de veinte milímetros',
                'motor': 'cadquery', 'modelo': MODELO, 'modo': 'open-loop'})
            self.assertEqual(respuesta.status_code, 202, respuesta.text)
            self.assertEqual(programar.call_args.kwargs['queue'], 'nvidia')
        for perfil, cola in ((perfil_generacion(MODELO), 'nvidia'), ({'max_tokens': 8192}, 'celery')):
            with patch('aplicacion.api.cambiar_estado', return_value=SimpleNamespace(configuracion={'perfiles_generacion': {MODELO: perfil}})), \
                 patch('aplicacion.api.resumen_campana', return_value={}), \
                 patch('aplicacion.api.tarea_campana.apply_async') as nueva, patch('aplicacion.api.tarea_campana.delay') as antigua:
                _cambiar_campana('campana', 'iniciar')
                if cola == 'nvidia':
                    self.assertEqual(nueva.call_args.kwargs['queue'], cola)
                    antigua.assert_not_called()
                else:
                    nueva.assert_not_called()
                    antigua.assert_called_once_with('campana')
