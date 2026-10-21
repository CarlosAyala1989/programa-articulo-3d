"""Ejecutar en la imagen del supervisor para verificar su transporte Docker."""

import json
import unittest
from unittest.mock import MagicMock, patch

try:
    from supervisor.api import SolicitudEjecucion, ejecutar_codigo
except ModuleNotFoundError:
    SolicitudEjecucion = None


@unittest.skipIf(SolicitudEjecucion is None, "Requiere dependencias de la imagen del supervisor")
class TransporteCodigo(unittest.TestCase):
    def test_codigo_extenso_llega_integro_sin_argumento_de_entorno(self):
        codigo = "# detalle ñ\n" * 50000 + "resultado = 1\n"
        solicitud = SolicitudEjecucion(motor="cadquery", codigo=codigo)
        cliente = MagicMock()
        contenedor = cliente.containers.create.return_value
        entrada = contenedor.attach_socket.return_value.__enter__.return_value
        enviados = []

        entrada._sock.sendall.side_effect = enviados.append
        contenedor.wait.return_value = {"StatusCode": 0}
        contenedor.logs.return_value = ("SALIDA_CAD:" + json.dumps({"correcto": False, "fase_error": "cad"})).encode()
        contenedor.image.id = "sha256:imagen-simulada"
        with patch("supervisor.api.docker.from_env", return_value=cliente):
            ejecutar_codigo(solicitud)
        parametros = cliente.containers.create.call_args.kwargs
        self.assertNotIn("CODIGO_BASE64", parametros["environment"])
        self.assertTrue(parametros["network_disabled"])
        self.assertTrue(parametros["read_only"])
        self.assertTrue(parametros["stdin_open"])
        self.assertEqual(parametros["cap_drop"], ["ALL"])
        self.assertEqual(json.loads(b"".join(enviados))["codigo"], codigo)
        contenedor.remove.assert_called_once_with(force=True)


@unittest.skipIf(SolicitudEjecucion is None, "Requiere dependencias de la imagen del supervisor")
class TimeoutCad(unittest.TestCase):
    def test_timeout_envuelto_se_registra_como_tiempo_cad_y_libera_contenedor(self):
        from requests.exceptions import ConnectionError
        from urllib3.exceptions import ReadTimeoutError
        cliente = MagicMock()
        contenedor = cliente.containers.create.return_value
        contenedor.image.id = 'sha256:imagen-congelada'
        contenedor.wait.side_effect = ConnectionError(ReadTimeoutError(None, None, 'Read timed out'))
        with patch('supervisor.api.docker.from_env', return_value=cliente):
            resultado = ejecutar_codigo(SolicitudEjecucion(motor='freecad', codigo='resultado = 1'))
        self.assertFalse(resultado['correcto'])
        self.assertEqual(resultado['fase_error'], 'tiempo')
        self.assertEqual(resultado['runtime_identificador'], 'sha256:imagen-congelada')
        contenedor.kill.assert_called_once()
        contenedor.remove.assert_called_once_with(force=True)

    def test_conexion_rota_no_se_convierte_en_fallo_del_programa(self):
        from fastapi import HTTPException
        from requests.exceptions import ConnectionError
        cliente = MagicMock()
        contenedor = cliente.containers.create.return_value
        contenedor.wait.side_effect = ConnectionError('socket desconectado')
        with patch('supervisor.api.docker.from_env', return_value=cliente):
            with self.assertRaises(HTTPException) as contexto:
                ejecutar_codigo(SolicitudEjecucion(motor='freecad', codigo='resultado = 1'))
        self.assertEqual(contexto.exception.status_code, 503)
        contenedor.kill.assert_not_called()
        contenedor.remove.assert_called_once_with(force=True)


if __name__ == "__main__":
    unittest.main()
