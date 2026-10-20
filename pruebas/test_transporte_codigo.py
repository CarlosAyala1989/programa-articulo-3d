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


if __name__ == "__main__":
    unittest.main()
