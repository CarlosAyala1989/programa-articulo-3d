"""Regresiones de límites por endpoint; todas las inferencias son simuladas."""

import json
import unittest
from unittest.mock import patch

import httpx

from aplicacion.api import SolicitudGeneracion
from aplicacion.calidad.nvidia import ErrorNvidia, ProveedorNvidia
from aplicacion.configuracion import VERSION_PLANTILLA, perfil_generacion
from aplicacion.conjuntos import validar_documento
from aplicacion.limites_modelos import limites_modelo
from aplicacion.proveedores import solicitar_codigo


class LimitesOficiales(unittest.TestCase):
    def test_nvidia_envia_maximo_por_modelo_y_entrada_completa(self):
        descripcion = "Requisito geométrico con medidas precisas. " * 10000
        capturados = []

        def responder(peticion):
            capturados.append(json.loads(peticion.content))
            return httpx.Response(200, json={"choices": [{
                "message": {"content": "resultado = 1"}, "finish_reason": "stop"}]})

        cliente_real = httpx.Client
        with patch("aplicacion.calidad.nvidia.httpx.Client", side_effect=lambda **opciones:
                   cliente_real(transport=httpx.MockTransport(responder), **opciones)):
            for modelo, maximo in (("nvidia/nemotron-3-super-120b-a12b", 32768),
                                   ("moonshotai/kimi-k3", 65536),
                                   ("google/gemma-4-31b-it", 32768),
                                   ("z-ai/glm-5.3", 131072)):
                with self.subTest(modelo=modelo):
                    perfil = perfil_generacion(modelo)
                    self.assertEqual(perfil["max_tokens"], maximo)
                    proveedor = ProveedorNvidia(clave="clave-simulada")
                    proveedor.generar(modelo, [{"role": "user", "content": descripcion}])
                    self.assertEqual(capturados[-1]["max_tokens"], maximo)
                    self.assertEqual(capturados[-1]["messages"][0]["content"], descripcion)
                    with self.assertRaises(ErrorNvidia):
                        proveedor.generar(modelo, [], maximo_tokens=maximo + 1)
                    with self.assertRaises(ValueError):
                        perfil_generacion(modelo, maximo_tokens=maximo + 1)

    def test_limite_congelado_nvidia_se_conserva(self):
        self.assertEqual(perfil_generacion("moonshotai/kimi-k3", maximo_tokens=8192)["max_tokens"], 8192)
        with patch("aplicacion.proveedores.ProveedorNvidia") as constructor:
            constructor.return_value.generar.side_effect = ErrorNvidia("Timeout", "timeout")
            with patch("aplicacion.proveedores.solicitar_deepseek", return_value={"texto": "resultado = 1"}) as respaldo:
                solicitar_codigo("nvidia/nemotron-3-super-120b-a12b", [], maximo_tokens=8192)
        self.assertEqual(respaldo.call_args.args[3], 8192)

    def test_descripcion_e_importacion_extensas_no_tienen_tope_de_caracteres(self):
        descripcion = ("Cubo de 20 mm con los requisitos siguientes. " * 10000).strip()
        solicitud = SolicitudGeneracion(descripcion=descripcion, modelo="deepseek-flash", motor="cadquery")
        self.assertEqual(solicitud.descripcion, descripcion)
        documento = validar_documento({"nombre": "Largo", "version": "1", "finalidad": "desarrollo", "casos": [{
            "codigo": "L01", "nivel": "basico", "familia": "cubo", "fundamento": "Prueba de entrada extensa",
            "descripcion": descripcion,
        }]})
        self.assertEqual(documento["casos"][0]["descripcion"], descripcion)

    def test_referencias_cli_no_se_presentan_como_limites_efectivos(self):
        for modelo, entrada, salida in (("codex-cli::gpt-6.1-sol", 922000, 128000),
                                        ("antigravity-cli::gemini-3.8-flash-high", 1048576, 65536)):
            limites = limites_modelo(modelo)
            self.assertEqual(limites["entrada"], entrada)
            self.assertEqual(limites["salida"], salida)
            self.assertEqual(limites["gestion"], "cli")
            self.assertIsNone(limites["salida_configurada"])
            self.assertNotIn("max_tokens", perfil_generacion(modelo))
        self.assertNotIn("salida", limites_modelo("codex-cli::modelo-nuevo-no-documentado"))
        self.assertEqual(perfil_generacion("L01")["num_predict"], -1)
        self.assertTrue(VERSION_PLANTILLA.startswith("v7-"))


if __name__ == "__main__":
    unittest.main()
