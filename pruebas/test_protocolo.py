"""Pruebas del conjunto, diseño experimental y denominadores científicos."""

import json
import unittest
from collections import Counter
from pathlib import Path

from aplicacion.base_datos import Ejecucion, InformeTopologia, IntentoGeneracion
from aplicacion.campanas import previsualizar
from aplicacion.conjuntos import validar_documento
from aplicacion.metricas import resumen_grupo


class ProtocoloDigital(unittest.TestCase):
    def test_conjunto_principal_equilibrado(self):
        ruta = Path(__file__).resolve().parent.parent / "datos" / "prompts_60_v1.json"
        datos = validar_documento(json.loads(ruta.read_text(encoding="utf-8")))
        self.assertEqual(len(datos["casos"]), 60)
        self.assertEqual(Counter(c["nivel"] for c in datos["casos"]),
                         {"basico": 20, "intermedio": 20, "complejo": 20})
        self.assertEqual(len({c["codigo"] for c in datos["casos"]}), 60)

    def test_matriz_completa_dos_modelos(self):
        vista = previsualizar(60, ["deepseek-flash", "deepseek-v4-pro"],
                             ["cadquery", "build123d", "freecad"],
                             ["open-loop", "closed-loop"], 1)
        self.assertEqual(vista["ejecuciones"], 720)
        self.assertEqual(vista["maximo_generaciones"], 2160)

    def test_compilacion_y_cad_tienen_curvas_distintas(self):
        primera = Ejecucion(identificador="uno", descripcion="pieza uno", motor="cadquery",
                           modelo="deepseek-flash", modo="closed-loop", estado="completada",
                           numero_intentos=3, primer_exito_ejecucion=2,
                           primer_exito_cad=3, primer_exito_exportacion=3)
        primera.intentos = [IntentoGeneracion(numero=k, estado="invalido") for k in range(1, 4)]
        segunda = Ejecucion(identificador="dos", descripcion="pieza dos", motor="cadquery",
                           modelo="deepseek-flash", modo="closed-loop", estado="fallida",
                           numero_intentos=5)
        segunda.intentos = [IntentoGeneracion(numero=k, estado="invalido") for k in range(1, 6)]
        tercera = Ejecucion(identificador="tres", descripcion="pieza tres", motor="cadquery",
                           modelo="deepseek-flash", modo="closed-loop", estado="bloqueada")
        tercera.intentos = []
        topologia = InformeTopologia(ejecucion_identificador="uno", rol_malla="nativa",
                                     sha256_malla="abc", estado="analizada",
                                     watertight=True, dang_el=0)
        datos = resumen_grupo([primera, segunda, tercera], {"uno": topologia}, {}, "closed-loop")
        self.assertEqual(datos["n_planificado"], 3)
        self.assertEqual(datos["n_evaluable"], 2)
        self.assertEqual(datos["primer_exito_ejecucion"], [0, 1, 0, 0, 0])
        self.assertEqual(datos["primer_exito_cad_exportable"], [0, 0, 1, 0, 0])
        self.assertEqual(datos["compile_rate_acumulado_pct"][-1], 50.0)
        self.assertEqual(datos["ir_cad_pct"], 50.0)
        self.assertEqual(datos["topologia"]["cobertura_stl_pct"], 50.0)
        self.assertFalse(datos["final"])

    def test_denominador_cero_no_es_tasa_cero(self):
        pendiente = Ejecucion(identificador="p", descripcion="pendiente", motor="cadquery",
                              modelo="deepseek-flash", modo="open-loop", estado="pendiente")
        pendiente.intentos = []
        datos = resumen_grupo([pendiente], {}, {}, "open-loop")
        self.assertIsNone(datos["ir_cad_pct"])
        self.assertEqual(datos["compile_rate_acumulado_pct"], [None])
        self.assertIsNone(datos["topologia"]["watertight_pct_condicional"])


if __name__ == "__main__":
    unittest.main()
