"""Concurrencia de campañas y suscripciones sin consultar modelos reales."""

import os
import socketserver
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx

from aplicacion.iniciar_trabajador import argumentos_trabajador
from aplicacion.proveedor_suscripcion import solicitar_cli
from aplicacion.puente_cli import ManejadorCLI


class CampanasParalelas(unittest.TestCase):
    def test_trabajador_acepta_dos_campanas_y_configuracion_explicita(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIn('--concurrency=2', argumentos_trabajador())
        with patch.dict(os.environ, {'CIEL_CONCURRENCIA': '3'}):
            self.assertIn('--concurrency=3', argumentos_trabajador())
        for valor in ('0', '-1', 'dos'):
            with self.subTest(valor=valor), patch.dict(os.environ, {'CIEL_CONCURRENCIA': valor}):
                with self.assertRaisesRegex(ValueError, 'entero positivo'):
                    argumentos_trabajador()

    def test_antigravity_y_codex_generan_a_la_vez_y_no_duplican_proveedor(self):
        barrera = threading.Barrier(2)
        def generar(modelo, *_):
            barrera.wait(timeout=3)
            return {'texto': modelo}
        with tempfile.TemporaryDirectory() as directorio:
            ruta = str(Path(directorio) / 'cli.sock')
            with socketserver.ThreadingUnixStreamServer(ruta, ManejadorCLI) as servidor:
                servidor.turnos = {p: threading.Lock() for p in ('codex-cli', 'antigravity-cli')}
                hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
                hilo.start()
                def pedir(modelo):
                    with httpx.Client(transport=httpx.HTTPTransport(uds=ruta), timeout=5) as cliente:
                        return cliente.post('http://localhost/generar', json={'modelo': modelo, 'mensajes': []})
                try:
                    with patch('aplicacion.puente_cli.ejecutar_cli', side_effect=generar) as ejecutar:
                        with ThreadPoolExecutor(max_workers=2) as grupo:
                            solicitudes = [grupo.submit(pedir, p) for p in servidor.turnos]
                            self.assertEqual([f.result().status_code for f in solicitudes], [200, 200])
                        self.assertEqual(ejecutar.call_count, 2)
                        servidor.turnos['antigravity-cli'].acquire()
                        try:
                            respuesta = pedir('antigravity-cli')
                            self.assertEqual(respuesta.status_code, 409)
                            self.assertEqual(respuesta.json()['codigo'], 'busy')
                            self.assertEqual(ejecutar.call_count, 2)
                        finally:
                            servidor.turnos['antigravity-cli'].release()
                finally:
                    servidor.shutdown()
                    hilo.join()

    def test_esperar_turno_no_consume_otro_intento_ni_reintenta_errores_inciertos(self):
        for estado, datos, llamadas in ((200, {'texto': 'programa'}, 2),
                (503, {'error': 'Error del proveedor', 'codigo': 'provider_error'}, 1)):
            with self.subTest(estado=estado), \
                 patch.dict(os.environ, {'CLI_PUENTE_SOCKET': '/puente/cli.sock'}), \
                 patch('aplicacion.proveedor_suscripcion.modelos_cli_configurados', return_value={'codex-cli': 'GPT'}), \
                 patch('aplicacion.proveedor_suscripcion.time.sleep') as esperar, \
                 patch('aplicacion.proveedor_suscripcion.httpx.Client') as cliente:
                respuestas = [httpx.Response(estado, json=datos)]
                if estado == 200:
                    respuestas.insert(0, httpx.Response(409, json={'codigo': 'busy'}))
                enviar = cliente.return_value.__enter__.return_value.post
                enviar.side_effect = respuestas
                if estado == 200:
                    self.assertEqual(solicitar_cli('codex-cli', []), {'texto': 'programa'})
                    esperar.assert_called_once_with(1)
                else:
                    from aplicacion.cli_suscripcion import ErrorCLI
                    with self.assertRaises(ErrorCLI):
                        solicitar_cli('codex-cli', [])
                    esperar.assert_not_called()
                self.assertEqual(enviar.call_count, llamadas)

    def test_campanas_gpt_nvidia_y_antigravity_se_envian_a_colas_independientes(self):
        from types import SimpleNamespace
        from aplicacion.api import _cambiar_campana
        from aplicacion.configuracion import VERSION_REINTENTOS_NVIDIA
        for modelo, perfil, cola in (
                ('codex-cli::gpt-5.6-luna', {'reasoning_effort': 'low'}, 'codex'),
                ('moonshotai/kimi-k2.6', {'protocolo_reintentos': VERSION_REINTENTOS_NVIDIA}, 'nvidia'),
                ('antigravity-cli::gemini-3.8-flash-high', {'reasoning_effort': 'high'}, 'celery')):
            with self.subTest(modelo=modelo), patch('aplicacion.api.cambiar_estado', return_value=SimpleNamespace(
                    configuracion={'perfiles_generacion': {modelo: perfil}})), \
                 patch('aplicacion.api.resumen_campana', return_value={}), \
                 patch('aplicacion.api.tarea_campana.apply_async') as separada, \
                 patch('aplicacion.api.tarea_campana.delay') as normal:
                _cambiar_campana('campana', 'iniciar')
                if cola == 'celery':
                    normal.assert_called_once_with('campana')
                    separada.assert_not_called()
                else:
                    separada.assert_called_once_with(args=['campana'], queue=cola)
                    normal.assert_not_called()
