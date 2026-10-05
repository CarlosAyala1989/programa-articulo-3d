"""Fixtures geométricos con resultados IoU, Chamfer y DangEL conocidos."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import cadquery as cq
    import trimesh
    from evaluador.api import SolicitudAnalisis, analizar, analizar_malla, comparar, leer_malla
except ImportError:
    cq = None


@unittest.skipIf(cq is None, "Requiere la imagen del evaluador CAD")
class GeometriaDigital(unittest.TestCase):
    def test_solidos_identicos_y_disjuntos(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal)
            primero = cq.Workplane("XY").box(10, 10, 10).val()
            igual = cq.Workplane("XY").box(10, 10, 10).val()
            separado = cq.Workplane("XY").box(10, 10, 10).translate((30, 0, 0)).val()
            for nombre, forma in (("primero", primero), ("igual", igual), ("separado", separado)):
                cq.exporters.export(forma, str(ruta / f"{nombre}.stl"), exportType="STL")
            malla_primera = leer_malla(ruta / "primero.stl")
            identidad = comparar(primero, igual, malla_primera, leer_malla(ruta / "igual.stl"))
            desplazado = comparar(primero, separado, malla_primera, leer_malla(ruta / "separado.stl"))
            self.assertAlmostEqual(identidad["iou_brep"], 1.0, places=8)
            self.assertAlmostEqual(identidad["chamfer_digital_mm2"], 0.0, places=8)
            self.assertAlmostEqual(desplazado["iou_brep"], 0.0, places=8)
            self.assertGreater(desplazado["chamfer_digital_mm2"], 0)

    def test_malla_abierta_tiene_aristas_colgantes(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "abierta.stl"
            cubo = trimesh.creation.box(extents=(10, 10, 10))
            cubo.update_faces(list(range(len(cubo.faces) - 1)))
            cubo.export(ruta)
            informe = analizar_malla(ruta)
            self.assertFalse(informe["watertight"])
            self.assertGreater(informe["dang_el"], 0)
            self.assertGreater(informe["aristas_abiertas"], 0)

    def test_referencia_invalida_no_borra_topologia_valida(self):
        ejecucion = "11111111-1111-4111-8111-111111111111"
        caso = "22222222-2222-4222-8222-222222222222"
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            carpeta = raiz / "ejecuciones" / ejecucion
            carpeta.mkdir(parents=True)
            pieza = cq.Workplane("XY").box(10, 10, 10)
            cq.exporters.export(pieza, str(carpeta / "pieza.step"), exportType="STEP")
            cq.exporters.export(pieza, str(carpeta / "pieza.stl"), exportType="STL")
            referencia = raiz / "referencias" / caso
            referencia.mkdir(parents=True)
            (referencia / "referencia.step").write_bytes(b"no es STEP")
            with patch("evaluador.api.RAIZ", raiz):
                resultado = analizar(SolicitudAnalisis(
                    ejecucion_identificador=ejecucion, caso_identificador=caso
                ))
            self.assertEqual(resultado["nativa"]["estado"], "analizada")
            self.assertEqual(resultado["comun"]["estado"], "analizada")
            self.assertEqual(resultado["comparacion"]["estado"], "no_calculable")


if __name__ == "__main__":
    unittest.main()
