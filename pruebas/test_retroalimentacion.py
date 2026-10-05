"""Evidencia de que el feedback completo llega a la llamada y resiste repeticiones."""

import base64
import json
import os
import unittest
from unittest.mock import patch

import httpx

from aplicacion.generacion import instrucciones_sistema, revisar_codigo
from aplicacion.proveedor_deepseek import ErrorProveedor, solicitar_codigo
from aplicacion.retroalimentacion import construir_solicitud, huella_codigo
from motores.ejecutar import ejecutar


class RetroalimentacionCompleta(unittest.TestCase):
    def test_programa_largo_no_pierde_importaciones_ni_final(self):
        codigo = "import cadquery as cq\n" + "# detalle del objeto\n" * 3000 + "resultado = cq.Workplane('XY').box(20,20,20)"
        revisar_codigo(codigo, "cadquery")
        solicitud, datos = construir_solicitud("Cubo de 20 mm", "cadquery", [
            {"numero": 1, "codigo": codigo, "diagnostico": "error geométrico", "fase_error": "cad"}
        ])
        self.assertIn(codigo, solicitud)
        self.assertTrue(datos["codigo_anterior_completo"])

    def test_limite_utf8_impide_un_argumento_de_contenedor_excesivo(self):
        with self.assertRaisesRegex(ValueError, "bytes UTF-8"):
            revisar_codigo("resultado = 1\n#" + "ñ" * 45000, "cadquery")

    def test_historial_causa_y_linea_antes_de_cambiar_estrategia(self):
        codigo = "resultado = pieza.edges().fillet(2)"
        contexto = {"linea_error": 1, "fragmento_codigo": codigo,
                    "traza_error": "Traza real de BRepFilletAPI"}
        historial = [{"numero": 1, "codigo": "resultado = pieza.scale(1,2,3)",
                      "diagnostico": "AttributeError: Workplane has no attribute scale", "fase_error": "ejecucion"}]
        historial += [{"numero": numero, "codigo": codigo, "diagnostico": "StdFail_NotDone: BRep_API: command not done",
                       "fase_error": "ejecucion", "contexto": contexto} for numero in (2, 3, 4)]
        solicitud, datos = construir_solicitud("Cabeza con relieves", "cadquery", historial)
        self.assertEqual(datos["intentos_fuente"], [1, 2, 3, 4])
        self.assertEqual(datos["repeticiones_codigo"], 3)
        self.assertEqual(datos["repeticiones_error"], 3)
        for fragmento in ("no tiene scale", "Línea 1", "Traza real", "No apliques fillet", "Cambia la estrategia"):
            self.assertIn(fragmento, solicitud)

    def test_cambios_cosmeticos_no_ocultan_repeticion(self):
        self.assertEqual(huella_codigo("resultado = 1"), huella_codigo("# cambio\nresultado=1\n"))
        self.assertNotEqual(huella_codigo("resultado = 1"), huella_codigo("resultado = 2"))

    def test_la_misma_excepcion_en_otra_linea_se_detecta_como_repetida(self):
        historial = [{"numero": n, "codigo": f"resultado = pieza_{n}.loft()",
                      "diagnostico": f"ValueError: Nothing to loft\nLínea {n + 20}\nContexto {n}",
                      "fase_error": "ejecucion"} for n in (1, 2, 3)]
        solicitud, datos = construir_solicitud("Cabeza", "cadquery", historial)
        self.assertEqual(datos["repeticiones_codigo"], 1)
        self.assertEqual(datos["repeticiones_error"], 3)
        self.assertIn("Cambia la estrategia", solicitud)

    def test_loft_y_cortes_reciben_causa_especifica_al_final_del_mensaje(self):
        codigo = "resultado = cuerpo.add(perfil).loft()"
        solicitud, datos = construir_solicitud("Cabeza", "cadquery", [{
            "numero": 1, "codigo": codigo, "diagnostico": "ValueError: Nothing to loft",
            "contexto": {"fragmento_codigo": codigo}, "fase_error": "ejecucion",
        }])
        self.assertIn("toPending", solicitud)
        self.assertIn("desplazamientos son incrementales", solicitud)
        self.assertTrue(datos["orientaciones"])
        self.assertLess(solicitud.index(codigo), solicitud.index("Nothing to loft"))
        self.assertTrue(solicitud.endswith("No reproduzcas la operación que ya falló."))

    def test_rasgos_organicos_no_modifican_casos_mecanicos(self):
        artistico, _ = construir_solicitud("Quiero una cabeza clava de la cultura Chavín", "cadquery", [])
        mecanico, _ = construir_solicitud("Cubo de 20 mm", "cadquery", [])
        self.assertIn("espiga posterior", artistico)
        self.assertIn("pupilas", artistico)
        self.assertIn("colmillos", artistico)
        self.assertNotIn("Guía de interpretación", mecanico)
        self.assertIn("No sustituyas", instrucciones_sistema("cadquery"))

    def test_feedback_se_envia_en_el_cuerpo_http_de_deepseek(self):
        solicitud, _ = construir_solicitud("Cabeza", "build123d", [{
            "numero": 1, "codigo": "resultado = Cone(radius_bottom=4, radius_top=0, height=10)",
            "diagnostico": "TypeError: Cone got an unexpected keyword argument radius_bottom", "fase_error": "ejecucion",
        }])
        mensajes = [{"role": "system", "content": instrucciones_sistema("build123d")},
                    {"role": "user", "content": solicitud}]
        capturados = []
        def responder(peticion):
            capturados.append(json.loads(peticion.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": "resultado = 1"}, "finish_reason": "stop"}]})
        cliente_real = httpx.Client
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "clave-simulada"}), \
             patch("aplicacion.proveedor_deepseek.httpx.Client", side_effect=lambda **opciones: cliente_real(
                 transport=httpx.MockTransport(responder), **opciones)):
            solicitar_codigo("deepseek-v4-pro", mensajes)
        self.assertEqual(capturados[0]["messages"], mensajes)
        self.assertEqual(capturados[0]["max_tokens"], 393216)
        self.assertEqual(capturados[0]["thinking"], {"type": "enabled"})
        self.assertEqual(capturados[0]["reasoning_effort"], "max")
        self.assertNotIn("temperature", capturados[0])
        self.assertIn("Cone(bottom_radius", capturados[0]["messages"][1]["content"])

    def test_runtime_informa_linea_fuente_y_traza(self):
        codigo = "valor = 2\nresultado = 1 / 0"
        with patch.dict(os.environ, {"CODIGO_BASE64": base64.b64encode(codigo.encode()).decode(), "MOTOR_CAD": "cadquery"}):
            datos = ejecutar()
        self.assertFalse(datos["correcto"])
        self.assertEqual(datos["linea_error"], 2)
        self.assertIn("resultado = 1 / 0", datos["fragmento_codigo"])
        self.assertIn("ZeroDivisionError", datos["traza_error"])
        self.assertEqual(datos["fase_error"], "ejecucion")

    def test_timeout_de_generacion_larga_no_duplica_la_peticion(self):
        llamadas = []
        def responder(peticion):
            llamadas.append(peticion)
            raise httpx.ReadTimeout("sin desenlace conocido", request=peticion)
        cliente_real = httpx.Client
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "clave-simulada"}), \
             patch("aplicacion.proveedor_deepseek.httpx.Client", side_effect=lambda **opciones: cliente_real(
                 transport=httpx.MockTransport(responder), **opciones)):
            with self.assertRaises(ErrorProveedor):
                solicitar_codigo("deepseek-v4-pro", [{"role": "user", "content": "Figura curva"}])
        self.assertEqual(len(llamadas), 1)


if __name__ == "__main__":
    unittest.main()
