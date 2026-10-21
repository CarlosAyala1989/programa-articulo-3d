"""Los bloqueos operativos se recuperan sin borrar historia ni repetir IA recibida."""

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aplicacion.base_datos import BaseDeclarativa, Ejecucion, IntentoGeneracion
from aplicacion.generacion import procesar_ejecucion
from aplicacion.proveedor_deepseek import ErrorProveedor


CODIGO = "import cadquery as cq\nresultado = cq.Workplane('XY').box(20,20,20)"
MODELO = 'codex-cli::gpt-5.6-luna'


class Recuperacion(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine('sqlite://')
        BaseDeclarativa.metadata.create_all(self.motor)
        self.sesiones = sessionmaker(bind=self.motor, expire_on_commit=False)
        self.addCleanup(self.motor.dispose)
        catalogo = patch('aplicacion.proveedor_suscripcion.catalogos_cli', return_value={
            'codex-cli': {'modelos': {MODELO: {'esfuerzos': {'low': 'Bajo'}}}}})
        catalogo.start()
        self.addCleanup(catalogo.stop)
        self.solicitud = {'mensajes': [{'role': 'user', 'content': 'Solicitud congelada'}],
                         'perfil': {'reasoning_effort': 'low', 'max_tokens': None}}
        with self.sesiones() as sesion:
            sesion.add(Ejecucion(identificador='e', descripcion='Cubo de veinte milímetros',
                modelo=MODELO, esfuerzo_razonamiento='low', motor='cadquery', modo='closed-loop',
                maximo_intentos=5, numero_intentos=2, estado='bloqueada'))
            sesion.add(IntentoGeneracion(identificador=1, ejecucion_identificador='e', numero=1,
                estado='invalido', codigo='anterior', diagnostico='sólido inválido'))
            sesion.add(IntentoGeneracion(identificador=2, ejecucion_identificador='e', numero=2,
                estado='error_supervisor', fase_error='infraestructura', diagnostico='HTTP 503',
                codigo=CODIGO, respuesta_modelo=CODIGO, modelo_informado=MODELO,
                tokens_entrada=100, tokens_salida=30, duracion_ia_segundos=17,
                solicitud_modelo=self.solicitud))
            sesion.commit()

    def ejecutar(self, **opciones):
        with patch('aplicacion.generacion.crear_sesion', self.sesiones), \
             patch('aplicacion.generacion.solicitar_ejecucion_cad', return_value={
                 'correcto': True, 'ejecucion_correcta': True, 'cad_valido': True,
                 'exportacion_valida': True, 'archivos': {}}), \
             patch('aplicacion.generacion.guardar_archivos'), \
             patch('aplicacion.analisis.analizar_ejecucion'):
            procesar_ejecucion('e', **opciones)

    def test_reutiliza_codigo_sin_nueva_llamada_y_conserva_intentos(self):
        with patch('aplicacion.generacion.solicitar_codigo') as proveedor:
            self.ejecutar(recuperar_interrumpido=True)
        proveedor.assert_not_called()
        with self.sesiones() as sesion:
            e = sesion.get(Ejecucion, 'e')
            self.assertEqual(e.estado, 'completada')
            self.assertEqual(e.numero_intentos, 2)
            self.assertEqual(len(e.intentos), 2)
            self.assertEqual(sesion.get(IntentoGeneracion, 1).diagnostico, 'sólido inválido')
            i = sesion.get(IntentoGeneracion, 2)
            self.assertEqual(i.duracion_ia_segundos, 17)
            self.assertEqual(i.tokens_entrada, 100)
            self.assertEqual(i.solicitud_modelo['recuperaciones_operativas'][0]['diagnostico'], 'HTTP 503')

    def test_repite_solo_llamada_autorizada_con_solicitud_y_esfuerzo_congelados(self):
        with self.sesiones() as sesion:
            i = sesion.get(IntentoGeneracion, 2)
            i.estado, i.codigo, i.respuesta_modelo = 'error_proveedor', '', ''
            sesion.commit()
        respuesta = {'texto': CODIGO, 'modelo_informado': MODELO, 'tokens_entrada': 100,
                     'tokens_salida': 30, 'finalizacion': 'stop', 'perfil': self.solicitud['perfil']}
        with patch('aplicacion.generacion.solicitar_codigo', return_value=respuesta) as proveedor:
            with self.assertRaises(ValueError):
                self.ejecutar(recuperar_interrumpido=True)
            proveedor.assert_not_called()
            self.ejecutar(recuperar_interrumpido=True, repetir_proveedor=True)
        proveedor.assert_called_once_with(MODELO, self.solicitud['mensajes'], 'low', None)
        with self.sesiones() as sesion:
            self.assertEqual(len(sesion.get(Ejecucion, 'e').intentos), 2)
            incidencia = sesion.get(IntentoGeneracion, 2).solicitud_modelo['recuperaciones_operativas'][0]
            self.assertTrue(incidencia['consumo_previo_desconocido'])

    def test_no_toca_una_ejecucion_ya_completada(self):
        with self.sesiones() as sesion:
            sesion.get(Ejecucion, 'e').estado = 'completada'
            sesion.commit()
        with patch('aplicacion.generacion.solicitar_codigo') as proveedor:
            self.ejecutar(recuperar_interrumpido=True)
        proveedor.assert_not_called()
        with self.sesiones() as sesion:
            self.assertEqual(sesion.get(IntentoGeneracion, 2).estado, 'error_supervisor')

    def test_otro_error_proveedor_conserva_el_mismo_intento_y_la_incidencia(self):
        with self.sesiones() as sesion:
            i = sesion.get(IntentoGeneracion, 2)
            i.estado, i.codigo, i.respuesta_modelo = 'error_proveedor', '', ''
            sesion.commit()
        with patch('aplicacion.generacion.solicitar_codigo', side_effect=ErrorProveedor('Sin respuesta')):
            self.ejecutar(recuperar_interrumpido=True, repetir_proveedor=True)
        with self.sesiones() as sesion:
            e = sesion.get(Ejecucion, 'e')
            self.assertEqual(e.estado, 'bloqueada')
            self.assertEqual(len(e.intentos), 2)
            i = sesion.get(IntentoGeneracion, 2)
            self.assertEqual(i.estado, 'error_proveedor')
            self.assertEqual(i.diagnostico, 'Sin respuesta')
            self.assertEqual(i.solicitud_modelo['recuperaciones_operativas'][0]['estado_anterior'], 'error_proveedor')
