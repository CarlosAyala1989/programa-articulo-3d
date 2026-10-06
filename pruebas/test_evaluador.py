"""Fixtures geométricos con resultados IoU, Chamfer y DangEL conocidos."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import cadquery as cq
    import trimesh
    from evaluador.api import (
        SolicitudAnalisis, _cilindros, _comparar_superficies, _simetrias,
        _verificar_agujeros, analizar, analizar_malla, comparar, leer_malla,
    )
    from evaluador.renderizado import renderizar_lamina
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

    def test_metricas_de_superficie_identica_y_render_multivista_determinista(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "cubo.stl"
            forma = cq.Workplane("XY").box(10, 10, 10).val()
            cq.exporters.export(forma, str(ruta), exportType="STL", tolerance=0.1,
                                angularTolerance=0.1)
            malla = leer_malla(ruta)
            metricas = _comparar_superficies(forma, forma, malla, malla)
            self.assertAlmostEqual(metricas["centroid_error_mm"], 0.0, places=8)
            self.assertEqual(metricas["bounding_box_error_mm"], {"x": 0.0, "y": 0.0, "z": 0.0})
            self.assertAlmostEqual(metricas["surface_area_error_relative"], 0.0, places=8)
            self.assertAlmostEqual(metricas["hausdorff_robusto_mm"]["p95"], 0.0, places=8)
            self.assertAlmostEqual(metricas["chamfer_digital_mm2"], 0.0, places=8)
            self.assertEqual(metricas["metadatos"]["hausdorff_robusto_mm"]["unidad"], "mm")
            self.assertEqual(metricas["metadatos"]["hausdorff_robusto_mm"]["semilla"], 20261004)
            self.assertEqual(metricas["metadatos"]["iou_brep"]["version"], "ciel-quality-metrics-v2")
            self.assertAlmostEqual(metricas["silhouette_iou"]["iou_medio"], 1.0, places=8)
            self.assertGreater(metricas["normal_consistency"], 0.99)
            simetria = _simetrias({"simetrias": [{"eje": "x"}],
                                  "sistema_coordenadas": {"origen": [0, 0, 0]}}, malla)
            self.assertAlmostEqual(simetria["valor"], 1.0, places=8)
            lamina_1, perfil_1 = renderizar_lamina(malla)
            lamina_2, perfil_2 = renderizar_lamina(malla)
            self.assertEqual(lamina_1, lamina_2)
            self.assertEqual(perfil_1, perfil_2)
            self.assertEqual(perfil_1["version"], "ciel-ortho-render-v2")

    def test_orientacion_de_frente_del_plan_controla_lamina(self):
        figura = trimesh.creation.box(extents=(10, 20, 30))
        primera, perfil_a = renderizar_lamina(figura, "+Y")
        segunda, perfil_b = renderizar_lamina(figura, "-Y")
        self.assertEqual(perfil_a["orientacion_frente"], "+Y")
        self.assertEqual(perfil_b["orientacion_frente"], "-Y")
        self.assertNotEqual(primera, segunda)

    def test_agujeros_no_cuentan_pared_cilindrica_exterior(self):
        placa = (cq.Workplane("XY").box(100, 60, 10)
                 .faces(">Z").workplane().pushPoints([(-30, -15), (30, -15)]).hole(8).val())
        cilindro_macizo = cq.Workplane("XY").cylinder(10, 4).val()
        self.assertEqual(len(_cilindros(placa)), 2)
        self.assertEqual(len(_cilindros(cilindro_macizo)), 0)
        plan = {"features": [{"feature_id": "agujeros", "tipo": "hole pattern",
                  "dimensiones": {"count": {"valor": 4}, "diameter": {"valor": 8}}},
                 {"feature_id": "relieve", "tipo": "organic relief"}],
                "criterios_verificables": [{"identificador": "cantidad_agujeros",
                  "feature_id": "agujeros", "medicion": "hole_count", "esperado": 4}]}
        observadas = _verificar_agujeros(plan, _cilindros(placa))
        self.assertEqual(observadas["agujeros"]["cantidad"], 2)
        self.assertEqual(observadas["agujeros"]["diametro_mm"], 8)
        self.assertEqual(observadas["relieve"]["verification_status"], "unsupported")

    def test_pieza_escalada_revela_error_de_caja(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            base = cq.Workplane("XY").box(10, 10, 10).val()
            escala = cq.Workplane("XY").box(12, 10, 10).val()
            for nombre, figura in (("base", base), ("escala", escala)):
                cq.exporters.export(figura, str(raiz / f"{nombre}.stl"), exportType="STL")
            metricas = _comparar_superficies(escala, base,
                leer_malla(raiz / "escala.stl"), leer_malla(raiz / "base.stl"))
            self.assertAlmostEqual(metricas["bounding_box_error_mm"]["x"], 2.0)
            self.assertAlmostEqual(metricas["bounding_box_error_mm"]["y"], 0.0)

    def test_error_de_centroide_y_cotas_detectan_traslacion(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            base = cq.Workplane("XY").box(10, 10, 10).val()
            corrida = base.translate((5, 0, 0))
            for nombre, forma in (("base", base), ("corrida", corrida)):
                cq.exporters.export(forma, str(raiz / f"{nombre}.stl"), exportType="STL",
                                    tolerance=0.1, angularTolerance=0.1)
            metricas = _comparar_superficies(base, corrida,
                leer_malla(raiz / "base.stl"), leer_malla(raiz / "corrida.stl"))
            self.assertAlmostEqual(metricas["centroid_error_mm"], 5.0, places=3)
            for error in metricas["bounding_box_error_mm"].values():
                self.assertAlmostEqual(error, 0.0, places=8)
            self.assertGreater(metricas["hausdorff_robusto_mm"]["p95"], 0)


if __name__ == "__main__":
    unittest.main()
