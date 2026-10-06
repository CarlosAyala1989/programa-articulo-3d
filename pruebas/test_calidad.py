"""Pruebas deterministas del protocolo Quality Loop; ningún test invoca proveedores reales."""

import base64
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aplicacion.api import consultar_opciones
from aplicacion.base_datos import BaseDeclarativa, Ejecucion, InformeCalidad, IntentoGeneracion
from aplicacion.calidad import flujo
from aplicacion.calidad.metricas import evaluar_quality_gate, preparar_metricas
from aplicacion.calidad.modelos import (
    CajaPlan, CoordenadaPlan, CriterioPlan, CriticaGeometrica, DimensionPlan, ErrorGeometrico,
    FeaturePlan, PlanGeometrico, RevisionCodigo, RevisionVisual, VectorPlan,
)
from aplicacion.calidad.nvidia import ErrorNvidia, ProveedorNvidia, RouterModelos
from aplicacion.calidad.prompts import validar_plan_para_descripcion
from aplicacion.calidad.recipes import seleccionar_recipes
from aplicacion.generacion import revisar_codigo


def dimension(valor, procedencia="specified", tolerancia=None):
    return DimensionPlan(valor=valor, procedencia=procedencia, tolerancia=tolerancia)


def plan_mecanico():
    return PlanGeometrico(
        clase_modelado="MECHANICAL_PRECISE", categoria="placa",
        bounding_box_esperada=CajaPlan(x=dimension(100), y=dimension(60), z=dimension(10)),
        features=[FeaturePlan(feature_id="cuerpo", nombre="cuerpo principal", tipo="placa")],
    )


def respuesta(texto="{}", modelo="fake/model"):
    return SimpleNamespace(texto=texto, modelo=modelo, proveedor="nvidia_nim",
        tokens_entrada=12, tokens_salida=8, finalizacion="stop",
        latencia_segundos=0.01, request_id="req-test")


class GeometricPlanTests(unittest.TestCase):
    def test_dimensiones_explicitas_y_coordenadas_negativas(self):
        plan = plan_mecanico()
        validar_plan_para_descripcion("Placa de 100 x 60 x 10 mm", plan)
        plan.centroide_esperado = VectorPlan(
            x=CoordenadaPlan(valor=-25, procedencia="specified"),
            y=CoordenadaPlan(valor=0, procedencia="inferred"),
            z=CoordenadaPlan(valor=0, procedencia="inferred"),
        )
        validar_plan_para_descripcion("Placa 100 x 60 x 10 mm con centro x=-25 mm", plan)

    def test_rechaza_cota_especificada_inventada(self):
        plan = plan_mecanico()
        plan.dimensiones_globales["x"] = dimension(90)
        with self.assertRaisesRegex(ValueError, "alteró o inventó"):
            validar_plan_para_descripcion("Placa de 100 x 60 x 10 mm", plan)

    def test_conserva_cantidad_especificada_escrita_con_palabras(self):
        plan = plan_mecanico()
        plan.features.append(FeaturePlan(feature_id="agujeros", nombre="cuatro agujeros",
            tipo="hole pattern", dimensiones={"count": DimensionPlan(
                valor=4, procedencia="specified", unidad="unitless")}))
        plan.criterios_verificables.append(CriterioPlan(
            identificador="cantidad_agujeros", feature_id="agujeros",
            medicion="hole_count", esperado=4, unidad="unitless"))
        validar_plan_para_descripcion(
            "Placa de 100 x 60 x 10 mm con cuatro agujeros de 8 mm", plan)

    def test_plan_rechaza_referencias_rotas_y_dimensiones_negativas(self):
        with self.assertRaises(ValueError):
            PlanGeometrico(clase_modelado="HYBRID", features=[
                FeaturePlan(feature_id="borde", nombre="borde", tipo="fillet", padre_id="ausente")])
        with self.assertRaises(ValueError):
            dimension(-3)

    def test_recipes_cambian_segun_geometria(self):
        mecanico = plan_mecanico()
        mecanico.agujeros = ["agujero central"]
        ids = {r.identificador for r in seleccionar_recipes(mecanico, "cadquery")}
        self.assertIn("hole", ids)
        organico = PlanGeometrico(clase_modelado="ORGANIC_FREEFORM", features=[
            FeaturePlan(feature_id="relieve", nombre="relieve", tipo="organic relief")])
        ids_organicos = {r.identificador for r in seleccionar_recipes(organico, "build123d")}
        self.assertIn("organic_relief", ids_organicos)

    def test_candidatos_best_of_n_comparten_plan_y_no_reciben_referencias(self):
        plan = plan_mecanico().model_dump(mode="json")
        primero = flujo._mensajes_modelador("Placa de 100 x 60 x 10 mm", plan, "cadquery", None, 1)
        segundo = flujo._mensajes_modelador("Placa de 100 x 60 x 10 mm", plan, "cadquery", None, 2)
        self.assertEqual(primero[0], segundo[0])
        mensaje = primero[0][1]["content"].casefold()
        self.assertNotIn("ground truth", mensaje)
        self.assertNotIn("referencia.step", mensaje)

    def test_planner_no_recibe_identificador_ni_archivos_de_referencia(self):
        capturados = {}

        class ProveedorFalso:
            def generar_estructurado(self, modelo, sistema, solicitud, esquema):
                capturados.update({"modelo": modelo, "sistema": sistema, "solicitud": solicitud})
                return plan_mecanico(), respuesta("{}", modelo)

        RouterModelos(ProveedorFalso()).planificar("Placa de 100 x 60 x 10 mm")
        self.assertIn("100 x 60 x 10", capturados["solicitud"])
        self.assertNotIn("referencia.step", capturados["solicitud"])
        self.assertNotIn("caso_identificador", capturados["solicitud"])


class RouterModelTests(unittest.TestCase):
    def test_planificador_usa_fallback_solo_tras_rechazo_http_explicito(self):
        class ProveedorFalso:
            def __init__(self):
                self.modelos = []

            def generar_estructurado(self, modelo, sistema, solicitud, esquema, **kwargs):
                self.modelos.append(modelo)
                if len(self.modelos) == 1:
                    raise ErrorNvidia("NVIDIA respondió HTTP 404")
                return plan_mecanico(), respuesta("{}", modelo)

        proveedor = ProveedorFalso()
        plan, _ = RouterModelos(proveedor).planificar("Placa de 100 x 60 x 10 mm")
        self.assertEqual(plan.clase_modelado, "MECHANICAL_PRECISE")
        self.assertEqual(len(proveedor.modelos), 2)
        self.assertNotEqual(proveedor.modelos[0], proveedor.modelos[1])

    def test_planificador_no_reintenta_timeout_ni_resultado_incierto(self):
        class ProveedorFalso:
            def __init__(self):
                self.llamadas = 0

            def generar_estructurado(self, modelo, sistema, solicitud, esquema, **kwargs):
                self.llamadas += 1
                raise ErrorNvidia("Timeout NVIDIA; revisar la llamada antes de reintentar")

        proveedor = ProveedorFalso()
        with self.assertRaisesRegex(ErrorNvidia, "Timeout NVIDIA"):
            RouterModelos(proveedor).planificar("Placa de 100 x 60 x 10 mm")
        self.assertEqual(proveedor.llamadas, 1)


class NvidiaProviderTests(unittest.TestCase):
    def test_nvidia_es_opcional_y_no_desactiva_los_modos_historicos(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
            opciones = consultar_opciones()
        self.assertFalse(opciones["quality_loop"]["disponible"])
        self.assertIn("open-loop", opciones["modos"])
        self.assertIn("closed-loop", opciones["modos"])
        self.assertNotIn("deepseek-ai/deepseek-v4.1-flash", opciones["modelos"])

    def test_key_ausente_no_envia_solicitud(self):
        proveedor = ProveedorNvidia(clave="")
        with self.assertRaisesRegex(ErrorNvidia, "no está configurada"):
            proveedor.generar("poolside/laguna-xs-2.1", [])

    def test_timeout_no_reintenta_y_no_revela_secreto(self):
        proveedor = ProveedorNvidia(clave="clave-prueba-no-real", timeout=0.01)
        cliente = MagicMock()
        cliente.__enter__.return_value = cliente
        cliente.post.side_effect = httpx.ReadTimeout("timeout")
        with patch("aplicacion.calidad.nvidia.httpx.Client", return_value=cliente):
            with self.assertRaises(ErrorNvidia) as contexto:
                proveedor.generar("poolside/laguna-xs-2.1", [{"role": "user", "content": "x"}])
        self.assertEqual(cliente.post.call_count, 1)
        self.assertNotIn("clave-prueba-no-real", str(contexto.exception))

    def test_respuesta_malformada_no_se_acepta(self):
        proveedor = ProveedorNvidia(clave="clave-prueba-no-real")
        cliente = MagicMock()
        cliente.__enter__.return_value = cliente
        cliente.post.return_value.status_code = 200
        cliente.post.return_value.json.return_value = {"choices": []}
        with patch("aplicacion.calidad.nvidia.httpx.Client", return_value=cliente):
            with self.assertRaisesRegex(ErrorNvidia, "malformada"):
                proveedor.generar("poolside/laguna-xs-2.1", [{"role": "user", "content": "x"}])

    def test_modelo_nvidia_fuera_de_allowlist(self):
        with self.assertRaisesRegex(ErrorNvidia, "no permitido"):
            ProveedorNvidia(clave="clave-prueba-no-real").generar("modelo/arbitrario", [])


class QualityGateTests(unittest.TestCase):
    def test_pieza_tecnica_y_geometricamente_correcta_se_acepta(self):
        plan = plan_mecanico()
        visual = RevisionVisual(accepted=True, puntuacion_silueta=0.98,
            puntuacion_proporciones=0.98, puntuacion_features=0.98)
        geometria = {"technical_success": True, "brep_valido": True, "solidos": 1,
            "watertight": True, "dang_el": 0,
            "bounding_box_mm": {"x": 100, "y": 60, "z": 10},
            "features": {}, "symmetry": {"estado": "not_applicable", "valor": None}}
        metricas = preparar_metricas(plan, geometria, visual)
        codigo = RevisionCodigo(accepted=True, severity="none")
        critica = CriticaGeometrica(accepted=True)
        gate = evaluar_quality_gate(metricas, True, codigo, visual, critica)
        self.assertTrue(gate["technical_success"])
        self.assertTrue(gate["quality_success"])
        self.assertEqual(metricas["puntuaciones"]["dimensional"]["valor"]["errores_mm"],
                         {"x": 0.0, "y": 0.0, "z": 0.0})

    def test_validez_tecnica_no_oculta_agujeros_faltantes(self):
        plan = plan_mecanico()
        plan.features.append(FeaturePlan(feature_id="agujeros", nombre="cuatro agujeros", tipo="hole pattern"))
        plan.criterios_verificables.append(CriterioPlan(identificador="conteo_agujeros",
            feature_id="agujeros", medicion="hole_count", esperado=4, unidad="unitless"))
        visual = RevisionVisual(accepted=False, puntuacion_silueta=0.9,
            puntuacion_proporciones=0.9, puntuacion_features=0.3)
        geometria = {"technical_success": True, "brep_valido": True, "solidos": 1,
            "watertight": True, "dang_el": 0,
            "bounding_box_mm": {"x": 100, "y": 60, "z": 10},
            "features": {"agujeros": {"estado": "calculated", "cantidad": 2}},
            "symmetry": {"estado": "not_applicable", "valor": None}}
        metricas = preparar_metricas(plan, geometria, visual)
        codigo = RevisionCodigo(accepted=True, severity="none")
        critica = CriticaGeometrica(accepted=False, errores=[ErrorGeometrico(
            feature_id="agujeros", severidad="high", causa_probable="faltan dos",
            estrategia_reparacion="añadir agujeros sin cambiar la placa")], preservar=["cuerpo"])
        gate = evaluar_quality_gate(metricas, True, codigo, visual, critica)
        self.assertTrue(gate["technical_success"])
        self.assertFalse(gate["quality_success"])
        self.assertLess(metricas["puntuaciones"]["features"]["valor"]["score"], 1)

    def test_feature_de_agujero_compara_diametro_y_cantidad_en_sus_unidades(self):
        plan = plan_mecanico()
        plan.features[0].esencial = False
        plan.features.append(FeaturePlan(feature_id="patron_agujeros", nombre="patrón",
            tipo="hole pattern", dimensiones={"count": dimension(4), "diameter": dimension(8)}))
        correcto = preparar_metricas(plan, {"features": {"patron_agujeros": {
            "estado": "calculated", "cantidad": 4, "diametro_mm": 8.0}}})
        incorrecto = preparar_metricas(plan, {"features": {"patron_agujeros": {
            "estado": "calculated", "cantidad": 2, "diametro_mm": 8.0}}})
        self.assertEqual(correcto["puntuaciones"]["features"]["valor"]["score"], 1.0)
        self.assertLess(incorrecto["puntuaciones"]["features"]["valor"]["score"], 1.0)

    def test_organico_simple_con_baja_silueta_se_rechaza(self):
        plan = PlanGeometrico(clase_modelado="ORGANIC_FREEFORM", features=[
            FeaturePlan(feature_id="cabeza", nombre="masa principal", tipo="forma orgánica")])
        visual = RevisionVisual(accepted=False, puntuacion_silueta=0.2,
            puntuacion_proporciones=0.3, puntuacion_features=0.2)
        geometria = {"technical_success": True, "brep_valido": True, "solidos": 1,
            "watertight": True, "dang_el": 0,
            "bounding_box_mm": {"x": 50, "y": 50, "z": 70},
            "features": {}, "symmetry": {"estado": "not_applicable", "valor": None}}
        metricas = preparar_metricas(plan, geometria, visual)
        codigo = RevisionCodigo(accepted=True, severity="none")
        critica = CriticaGeometrica(accepted=False)
        gate = evaluar_quality_gate(metricas, True, codigo, visual, critica)
        self.assertTrue(gate["technical_success"])
        self.assertFalse(gate["accepted"])

    def test_code_reviewer_rechazado_no_se_sobrepasa_por_metricas_altas(self):
        plan = plan_mecanico()
        visual = RevisionVisual(accepted=True, puntuacion_silueta=1,
            puntuacion_proporciones=1, puntuacion_features=1)
        metricas = preparar_metricas(plan, {"technical_success": True, "brep_valido": True,
            "solidos": 1, "watertight": True, "dang_el": 0,
            "bounding_box_mm": {"x": 100, "y": 60, "z": 10}, "features": {}}, visual)
        codigo = RevisionCodigo(accepted=False, severity="critical")
        self.assertFalse(evaluar_quality_gate(metricas, True, codigo, visual,
            CriticaGeometrica(accepted=True))["quality_success"])

    def test_best_of_n_conserva_todos_y_ordena_por_gate_y_score(self):
        resultados = [(1, {"candidate_id": "a", "quality_success": False,
                           "technical_success": True, "quality_score": 0.99}),
                      (2, {"candidate_id": "b", "quality_success": True,
                           "technical_success": True, "quality_score": 0.86}),
                      (3, {"candidate_id": "c", "quality_success": True,
                           "technical_success": True, "quality_score": 0.92})]
        ordenados = flujo._ordenar_candidatos(resultados)
        self.assertEqual([c["candidate_id"] for _, c in ordenados], ["c", "b", "a"])
        self.assertEqual(len(ordenados), 3)

    def test_estados_no_disponibles_no_se_convierten_en_cero(self):
        metricas = preparar_metricas(plan_mecanico(), {"technical_success": False})
        self.assertEqual(metricas["puntuaciones"]["dimensional"]["estado"], "not_available")
        self.assertIsNone(metricas["puntuaciones"]["dimensional"]["valor"])


class QualityLoopIntegrationTests(unittest.TestCase):
    def test_cad_rechazado_se_repara_preservando_features_y_acepta_ganador(self):
        motor_db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        BaseDeclarativa.metadata.create_all(motor_db)
        Sesiones = sessionmaker(bind=motor_db, expire_on_commit=False)
        ejecucion_id = "f1111111-1111-4111-8111-111111111111"
        with Sesiones() as sesion:
            sesion.add(Ejecucion(identificador=ejecucion_id,
                descripcion="Placa de 100 x 60 x 10 mm", motor="cadquery", modelo="deepseek-v4-pro",
                modo="quality-loop", maximo_intentos=3, estado="pendiente", mensaje="En cola",
                configuracion_calidad={"best_of_n": False}))
            sesion.commit()

        plan = plan_mecanico()
        modelo_fake = respuesta(modelo="nvidia/nemotron-3-ultra-550b-a55b")
        proveedor_fake = SimpleNamespace(llamadas=0)

        class RouterFalso:
            def __init__(self, proveedor):
                self.proveedor = proveedor
                self.ciclo_critica = 0

            def planificar(self, descripcion, permitir_fallback=True):
                self.proveedor.llamadas += 1
                return plan, modelo_fake

            def revisar_codigo(self, motor, plan_actual, codigo):
                self.proveedor.llamadas += 1
                return RevisionCodigo(accepted=True, severity="none"), respuesta("{}", "poolside/laguna-xs-2.1")

            def revisar_visual(self, descripcion, plan_actual, metricas, imagen):
                self.proveedor.llamadas += 1
                aceptado = self.ciclo_critica > 0
                return RevisionVisual(accepted=aceptado,
                    puntuacion_silueta=0.98 if aceptado else 0.55,
                    puntuacion_proporciones=0.98 if aceptado else 0.6,
                    puntuacion_features=0.98 if aceptado else 0.6), respuesta("{}", "moonshotai/kimi-k3")

            def criticar(self, plan_actual, evidencia):
                self.proveedor.llamadas += 1
                auto = self.ciclo_critica > 0
                self.ciclo_critica += 1
                return CriticaGeometrica(accepted=auto, preservar=["cuerpo_base"],
                    prioridad_reparacion=[] if auto else ["corregir proporciones sin reconstruir el cuerpo"]), response_critic

        response_critic = respuesta("{}", "z-ai/glm-5.3")
        codigo_generado = []

        def generar(modelo, mensajes, esfuerzo, maximo_tokens=None):
            codigo_generado.append(mensajes)
            return {"texto": "import cadquery as cq\nresultado = cq.Workplane('XY')",
                "modelo_informado": modelo, "tokens_entrada": 100, "tokens_salida": 30,
                "finalizacion": "stop", "proveedor": "deepseek", "perfil": {"max_tokens": 1000}}

        respuestas_evaluador = [
            {"technical_success": True, "geometric_metrics": {"technical_success": True,
                "brep_valido": True, "solidos": 1, "watertight": True, "dang_el": 0,
                "bounding_box_mm": {"x": 75, "y": 60, "z": 10}, "features": {},
                "symmetry": {"estado": "not_applicable", "valor": None}},
             "reference_metrics": {"estado": "not_available"},
             "multiview_png_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nmock").decode("ascii")},
            {"technical_success": True, "geometric_metrics": {"technical_success": True,
                "brep_valido": True, "solidos": 1, "watertight": True, "dang_el": 0,
                "bounding_box_mm": {"x": 100, "y": 60, "z": 10}, "features": {},
                "symmetry": {"estado": "not_applicable", "valor": None}},
             "reference_metrics": {"estado": "not_available"},
             "multiview_png_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nmock").decode("ascii")},
        ]
        archivos = {"pieza.stl": base64.b64encode(b"STL-candidato").decode("ascii"),
                    "pieza.step": base64.b64encode(b"STEP-candidato").decode("ascii")}
        resultado_cad = {"correcto": True, "sintaxis_valida": True,
            "ejecucion_correcta": True, "cad_valido": True, "exportacion_valida": True,
            "runtime_identificador": "cadquery-test", "volumen_mm3": 1000,
            "archivos": archivos}
        with tempfile.TemporaryDirectory() as directorio:
            with patch("aplicacion.calidad.flujo.crear_sesion", Sesiones), \
                 patch("aplicacion.calidad.flujo.ProveedorNvidia", return_value=proveedor_fake), \
                 patch("aplicacion.calidad.flujo.RouterModelos", RouterFalso), \
                 patch("aplicacion.calidad.flujo.solicitar_codigo", side_effect=generar), \
                 patch("aplicacion.calidad.flujo.solicitar_ejecucion_cad", return_value=resultado_cad), \
                 patch("aplicacion.calidad.flujo._consulta_evaluador", side_effect=respuestas_evaluador), \
                 patch("aplicacion.calidad.flujo.DIRECTORIO_ARTEFACTOS", directorio), \
                 patch("aplicacion.calidad.flujo.MAXIMO_LLAMADAS_QUALITY_LOOP", 40):
                flujo.procesar_quality_loop(ejecucion_id)

            with Sesiones() as sesion:
                ejecucion = sesion.get(Ejecucion, ejecucion_id)
                informes = list(sesion.scalars(select(InformeCalidad).where(
                    InformeCalidad.ejecucion_identificador == ejecucion_id).order_by(InformeCalidad.iteracion)))
                intentos = list(sesion.scalars(select(IntentoGeneracion).where(
                    IntentoGeneracion.ejecucion_identificador == ejecucion_id).order_by(IntentoGeneracion.numero)))
                self.assertEqual(ejecucion.estado, "completada")
                self.assertTrue(ejecucion.configuracion_calidad["technical_success"])
                self.assertTrue(ejecucion.configuracion_calidad["quality_success"])
                self.assertEqual(ejecucion.configuracion_calidad["ganador_iteracion"], 2)
                self.assertEqual(len(informes), 2)
                self.assertFalse(informes[0].resultado["quality_success"])
                self.assertTrue(informes[1].resultado["quality_success"])
                self.assertEqual(len(intentos), 2)
                self.assertIn("cuerpo_base", codigo_generado[1][1]["content"])
                self.assertIn("Código CAD completo", codigo_generado[1][1]["content"])

    def test_politica_estatica_bloquea_importaciones_fuera_de_allowlist(self):
        with self.assertRaisesRegex(ValueError, "Importación no permitida"):
            revisar_codigo("import os", "cadquery")


if __name__ == "__main__":
    unittest.main()
