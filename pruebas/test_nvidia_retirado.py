"""Endpoints retirados y sustitución explícita sin modificar campañas históricas."""

import unittest
from unittest.mock import patch

import httpx

from aplicacion.configuracion import perfil_generacion
from aplicacion.limites_modelos import limites_modelo
from aplicacion.proveedor_deepseek import ErrorProveedor
from aplicacion.proveedores import modelos_configurados, solicitar_codigo


class EndpointsRetirados(unittest.TestCase):
    def test_410_no_se_reintenta_ni_cambia_silenciosamente_de_modelo(self):
        llamadas = []
        cliente_real = httpx.Client
        def responder(peticion):
            llamadas.append(peticion)
            return httpx.Response(410, headers={'x-request-id': 'retirada-prueba'})
        with patch.dict('os.environ', {'NVIDIA_API_KEY': 'clave-simulada'}), \
             patch('aplicacion.calidad.nvidia.httpx.Client', side_effect=lambda **opciones:
                cliente_real(transport=httpx.MockTransport(responder), **opciones)), \
             patch('aplicacion.reintentos_nvidia.time.sleep') as dormir, \
             patch('aplicacion.proveedores.solicitar_deepseek') as respaldo:
            with self.assertRaises(ErrorProveedor) as contexto:
                solicitar_codigo('moonshotai/kimi-k3', [], reintentos_nvidia=True)
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(contexto.exception.codigo, 'endpoint_retirado')
        self.assertIn('HTTP 410', str(contexto.exception))
        self.assertIn('campaña original se conserva', str(contexto.exception))
        dormir.assert_not_called()
        respaldo.assert_not_called()

    def test_selector_ofrece_k2_6_y_conserva_k3_solo_para_historia(self):
        with patch.dict('os.environ', {'NVIDIA_API_KEY': 'clave-simulada'}), \
             patch('aplicacion.proveedores.NVIDIA_MODEL_GENERATOR', 'moonshotai/kimi-k3'), \
             patch('aplicacion.proveedores.modelos_cli_configurados', return_value={}):
            modelos = modelos_configurados()
        self.assertIn('moonshotai/kimi-k2.6', modelos)
        self.assertNotIn('moonshotai/kimi-k3', modelos)
        self.assertEqual(limites_modelo('moonshotai/kimi-k3')['salida'], 65536)
        self.assertEqual(perfil_generacion('moonshotai/kimi-k3')['max_tokens'], 65536)

    def test_k2_6_usa_el_maximo_publicado_y_no_reescribe_el_perfil_k3(self):
        anterior = limites_modelo('moonshotai/kimi-k3')
        nuevo = limites_modelo('moonshotai/kimi-k2.6')
        self.assertEqual(nuevo['contexto'], 262144)
        self.assertEqual(nuevo['salida'], 65536)
        self.assertEqual(perfil_generacion('moonshotai/kimi-k2.6')['max_tokens'], 65536)
        self.assertEqual(anterior['contexto'], 1048576)
        self.assertNotEqual(anterior['version'], nuevo['version'])
        self.assertEqual(limites_modelo('moonshotai/kimi-k3'), anterior)

    def test_404_de_cuenta_no_se_confunde_con_timeout_ni_expone_identificadores(self):
        cliente_real = httpx.Client
        with patch.dict('os.environ', {'NVIDIA_API_KEY': 'clave-simulada'}), \
             patch('aplicacion.calidad.nvidia.httpx.Client', side_effect=lambda **opciones:
                cliente_real(transport=httpx.MockTransport(lambda p: httpx.Response(404, json={
                    'detail': "Function 'funcion-privada': Not found for account 'cuenta-privada'"})), **opciones)), \
             patch('aplicacion.reintentos_nvidia.time.sleep') as dormir:
            with self.assertRaises(ErrorProveedor) as contexto:
                solicitar_codigo('moonshotai/kimi-k2.6', [], reintentos_nvidia=True)
        self.assertEqual(contexto.exception.codigo, 'endpoint_no_habilitado')
        self.assertNotIn('cuenta-privada', str(contexto.exception))
        self.assertNotIn('funcion-privada', str(contexto.exception))
        dormir.assert_not_called()
