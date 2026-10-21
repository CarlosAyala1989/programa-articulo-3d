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
from aplicacion.base_datos import (
    ArchivoGenerado, BaseDeclarativa, Ejecucion, InformeCalidad, IntentoGeneracion,
)
from aplicacion.calidad import flujo
from aplicacion.calidad.metricas import evaluar_quality_gate, preparar_metricas
from aplicacion.calidad.modelos import (
    CajaPlan, CoordenadaPlan, CriterioPlan, CriticaGeometrica, DimensionPlan, ErrorGeometrico,
    FeaturePlan, PlanGeometrico, RevisionCodigo, RevisionVisual, VectorPlan,
)
from aplicacion.calidad.nvidia import ErrorNvidia, ProveedorNvidia, RouterModelos
from aplicacion.calidad.planificador_local import construir_plan_local
from aplicacion.calidad.generador_local import generar_cadquery_de_casa
from aplicacion.calidad.prompts import instruccion_modeler, validar_plan_para_descripcion
from aplicacion.calidad.recipes import seleccionar_recipes, texto_recipes
from aplicacion.proveedores import solicitar_codigo
from aplicacion.proveedor_deepseek import ErrorProveedor
from aplicacion.configuracion import (
    MODELOS_NVIDIA_GENERADORES, NVIDIA_MODEL_CODE_REVIEWER, NVIDIA_MODEL_GENERATOR,
    NVIDIA_MODEL_CODE_REVIEWER_FALLBACK, NVIDIA_MODEL_PLANNER, NVIDIA_MODEL_PLANNER_FALLBACK,
    NVIDIA_MODEL_VISUAL_REVIEWER,
)
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
    def test_planificador_local_conserva_cotas_y_rasgos_del_prompt_de_casa(self):
        descripcion = (
            "Casa sencilla de 40 × 25 × 12 mm, con fachada rectangular, techo a dos aguas, "
            "una puerta centrada de 8 × 12 mm y dos ventanas cuadradas de 6 × 6 mm, "
            "una a cada lado de la puerta. Diseño simple, con paredes y techo sólidos, "
            "sin detalles adicionales, listo para impresión 3D."
        )
        plan = construir_plan_local(descripcion)
        validar_plan_para_descripcion(descripcion, plan)
        self.assertEqual(plan.clase_modelado, "MECHANICAL_PRECISE")
        self.assertEqual([plan.bounding_box_esperada.x.valor,
                          plan.bounding_box_esperada.y.valor,
                          plan.bounding_box_esperada.z.valor], [40, 25, 12])
        features = {feature.feature_id: feature for feature in plan.features}
        self.assertEqual(set(features), {
            "cuerpo_principal", "techo", "puerta", "ventana_izquierda", "ventana_derecha",
        })
        self.assertEqual(features["puerta"].dimensiones["ancho"].valor, 8)
        self.assertEqual(features["puerta"].dimensiones["alto"].valor, 12)
        self.assertEqual(features["ventana_izquierda"].dimensiones["ancho"].valor, 6)
        self.assertEqual(features["techo"].dimensiones, {})
        codigo = generar_cadquery_de_casa(plan)
        revisar_codigo(codigo, "cadquery")
        self.assertIn("resultado = paredes.union(perfil_techo)", codigo)
        self.assertIn("resultado = resultado.cut(cortador_puerta)", codigo)
        self.assertIn("cortador_ventana_1", codigo)
        self.assertIn("cortador_ventana_2", codigo)
        with self.assertRaisesRegex(ValueError, "categoría casa"):
            generar_cadquery_de_casa(plan_mecanico())

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

    def test_plan_semanticamente_invalido_usa_alternativo_una_sola_vez(self):
        plan_invalido = plan_mecanico()
        plan_invalido.dimensiones_globales["x"] = dimension(90)

        class RouterFalso:
            def __init__(self):
                self.proveedor = SimpleNamespace(llamadas=1)
                self.alternativas = 0

            def planificar_alternativo(self, descripcion):
                self.alternativas += 1
                self.proveedor.llamadas += 1
                return plan_mecanico(), respuesta(modelo="moonshotai/kimi-k3")

        router = RouterFalso()
        plan, llamada = flujo._validar_plan_con_respaldo(
            router, "Placa de 100 x 60 x 10 mm", plan_invalido,
            respuesta(modelo="nvidia/nemotron-3-super-120b-a12b"), True,
        )
        self.assertEqual(router.alternativas, 1)
        self.assertEqual(plan.bounding_box_esperada.x.valor, 100)
        self.assertEqual(llamada.modelo, "moonshotai/kimi-k3")

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
        organico_sin_loft = PlanGeometrico(clase_modelado="ORGANIC_FREEFORM", features=[
            FeaturePlan(feature_id="cuerpo", nombre="cuerpo", tipo="volumen orgánico")])
        ids_sin_loft = {r.identificador for r in seleccionar_recipes(organico_sin_loft, "cadquery")}
        self.assertNotIn("loft", ids_sin_loft)
        self.assertNotIn("asymmetric_loft", ids_sin_loft)

    def test_perfiles_mecanico_organico_e_hibrido_son_distintos(self):
        perfiles = {clase: instruccion_modeler(clase, "contrato") for clase in (
            "MECHANICAL_PRECISE", "ORGANIC_FREEFORM", "HYBRID")}
        self.assertEqual(len(set(perfiles.values())), 3)
        self.assertIn("cotas exactas", perfiles["MECHANICAL_PRECISE"])
        self.assertIn("secciones asimétricas", perfiles["ORGANIC_FREEFORM"])
        self.assertIn("separa regiones mecánicas", perfiles["HYBRID"])

    def test_quality_mode_no_inyecta_loft_en_placa_mecanica(self):
        plan = plan_mecanico()
        plan.operaciones = ["extrude"]
        mensajes, _ = flujo._mensajes_modelador(
            "Placa de 100 x 60 x 10 mm", plan.model_dump(mode="json"), "cadquery", None, 1
        )
        sistema = mensajes[0]["content"].casefold()
        self.assertIn("workplane.extrude", sistema)
        self.assertNotIn("patrón mínimo verificado de loft", sistema)
        self.assertNotIn(".loft(", sistema)
        self.assertIn("extrusion", texto_recipes(plan, "cadquery"))

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
    def test_revisor_recibe_version_exacta_del_motor(self):
        capturado = {}

        class ProveedorFalso:
            def generar_estructurado(self, modelo, sistema, solicitud, esquema, **kwargs):
                capturado.update({"modelo": modelo, "solicitud": solicitud})
                return RevisionCodigo(accepted=True, severity="none"), respuesta()

        RouterModelos(ProveedorFalso()).revisar_codigo(
            "build123d", plan_mecanico(), "from build123d import Box\nresultado = Box(1, 1, 1)"
        )
        self.assertEqual(capturado["modelo"], NVIDIA_MODEL_CODE_REVIEWER)
        self.assertIn("build123d 0.13.0", capturado["solicitud"])

    def test_revisor_usa_glm_si_nemotron_devuelve_respuesta_malformada(self):
        class ProveedorFalso:
            def __init__(self):
                self.modelos = []

            def generar_estructurado(self, modelo, sistema, solicitud, esquema, **kwargs):
                self.modelos.append(modelo)
                if len(self.modelos) == 1:
                    raise ErrorNvidia("JSON inválido", "malformed_response")
                return RevisionCodigo(accepted=True, severity="none"), respuesta("{}", modelo)

        proveedor = ProveedorFalso()
        router = RouterModelos(proveedor)
        revision, respuesta_revisor = router.revisar_codigo(
            "cadquery", plan_mecanico(), "import cadquery as cq\nresultado = cq.Workplane(\"XY\")"
        )
        self.assertEqual(proveedor.modelos, [
            NVIDIA_MODEL_CODE_REVIEWER, NVIDIA_MODEL_CODE_REVIEWER_FALLBACK,
        ])
        self.assertEqual(router.modelos_revisor_codigo, proveedor.modelos)
        self.assertEqual(respuesta_revisor.modelo, NVIDIA_MODEL_CODE_REVIEWER_FALLBACK)
        self.assertTrue(revision.accepted)

    def test_revisor_no_intenta_fallback_tras_timeout(self):
        class ProveedorFalso:
            def __init__(self):
                self.llamadas = 0

            def generar_estructurado(self, modelo, sistema, solicitud, esquema, **kwargs):
                self.llamadas += 1
                raise ErrorNvidia("Timeout NVIDIA", "timeout")

        proveedor = ProveedorFalso()
        with self.assertRaisesRegex(ErrorNvidia, "Timeout NVIDIA"):
            RouterModelos(proveedor).revisar_codigo(
                "cadquery", plan_mecanico(), "import cadquery as cq\nresultado = cq.Workplane(\"XY\")"
            )
        self.assertEqual(proveedor.llamadas, 1)

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

    def test_planificador_usa_alternativo_tras_json_invalido_completado(self):
        class ProveedorFalso:
            def __init__(self):
                self.modelos = []

            def generar_estructurado(self, modelo, sistema, solicitud, esquema, **kwargs):
                self.modelos.append(modelo)
                if len(self.modelos) == 1:
                    raise ErrorNvidia("Respuesta JSON NVIDIA no cumple el esquema requerido",
                                      "malformed_response")
                return plan_mecanico(), respuesta("{}", modelo)

        proveedor = ProveedorFalso()
        plan, respuesta_plan = RouterModelos(proveedor).planificar(
            "Placa de 100 x 60 x 10 mm", permitir_fallback=True
        )
        self.assertEqual(plan.clase_modelado, "MECHANICAL_PRECISE")
        self.assertEqual(proveedor.modelos, [NVIDIA_MODEL_PLANNER, NVIDIA_MODEL_PLANNER_FALLBACK])
        self.assertEqual(respuesta_plan.modelo, proveedor.modelos[1])
        self.assertNotEqual(proveedor.modelos[0], proveedor.modelos[1])


class NvidiaProviderTests(unittest.TestCase):
    def test_generadores_nvidia_responsivos_figuran_en_opciones(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "clave-prueba-no-real"}):
            opciones = consultar_opciones()
        self.assertEqual(opciones["quality_loop"]["modelo_nvidia_generador"], NVIDIA_MODEL_GENERATOR)
        self.assertIn("nvidia/nemotron-3-super-120b-a12b", opciones["modelos"])
        self.assertIn("moonshotai/kimi-k2.6", opciones["modelos"])
        self.assertNotIn("moonshotai/kimi-k3", opciones["modelos"])
        self.assertIn("google/gemma-4-31b-it", opciones["modelos"])
        self.assertIn("z-ai/glm-5.3", opciones["modelos"])
        self.assertNotIn("nvidia/nemotron-3-ultra-550b-a55b", opciones["modelos"])
        for modelo in MODELOS_NVIDIA_GENERADORES:
            self.assertIn(modelo, opciones["modelos"])
        if NVIDIA_MODEL_GENERATOR != "deepseek-ai/deepseek-v4.1-flash":
            self.assertNotIn("deepseek-ai/deepseek-v4.1-flash", opciones["modelos"])

    def test_fallos_de_infraestructura_tienen_categoria_distinta(self):
        self.assertEqual(flujo._clasificar_fallo_proveedor(
            ErrorNvidia("Timeout NVIDIA", "timeout")), "timeout")
        self.assertEqual(flujo._clasificar_fallo_proveedor(
            ErrorNvidia("JSON inválido", "malformed_response")), "malformed_response")
        self.assertEqual(flujo._clasificar_fallo_proveedor(
            ErrorNvidia("HTTP 503")), "provider_error")

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

    def test_nemotron_envia_esfuerzo_razonamiento_compatible_con_cada_modelo(self):
        for modelo, esfuerzo in (
            ("nvidia/nemotron-3-super-120b-a12b", "low"),
            ("nvidia/nemotron-3-ultra-550b-a55b", "medium"),
            ("moonshotai/kimi-k3", None),
        ):
            with self.subTest(modelo=modelo):
                proveedor = ProveedorNvidia(clave="clave-prueba-no-real")
                cliente = MagicMock()
                cliente.__enter__.return_value = cliente
                cliente.post.return_value.status_code = 200
                cliente.post.return_value.json.return_value = {
                    "model": modelo,
                    "choices": [{"message": {"content": plan_mecanico().model_dump_json()},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
                with patch("aplicacion.calidad.nvidia.httpx.Client", return_value=cliente):
                    proveedor.generar_estructurado(modelo, "sistema", "solicitud", PlanGeometrico)
                cuerpo = cliente.post.call_args.kwargs["json"]
                self.assertEqual(cuerpo.get("reasoning_effort"), esfuerzo)

    def test_generador_nvidia_usa_esfuerzo_bajo_o_medio_y_lo_registra(self):
        for modelo, esfuerzo in (
            ("nvidia/nemotron-3-super-120b-a12b", "low"),
            ("nvidia/nemotron-3-ultra-550b-a55b", "medium"),
            ("moonshotai/kimi-k3", None),
        ):
            with self.subTest(modelo=modelo), patch(
                "aplicacion.proveedores.ProveedorNvidia"
            ) as constructor:
                proveedor = constructor.return_value
                proveedor.generar.return_value = respuesta("import cadquery as cq", modelo)
                resultado = solicitar_codigo(modelo, [{"role": "user", "content": "Pieza"}])
                self.assertEqual(proveedor.generar.call_args.kwargs["esfuerzo_razonamiento"], esfuerzo)
                self.assertEqual(resultado["perfil"]["reasoning_effort"], esfuerzo)

    def test_timeout_kimi_cambia_a_nemotron_y_registra_el_respaldo(self):
        modelo_primario = "moonshotai/kimi-k3"
        modelo_respaldo = "nvidia/nemotron-3-super-120b-a12b"
        mensajes = [{"role": "user", "content": "Genera una casa simple"}]
        with patch("aplicacion.proveedores.ProveedorNvidia") as constructor:
            proveedor = constructor.return_value
            proveedor.generar.side_effect = [
                ErrorNvidia("Timeout NVIDIA", "timeout"),
                respuesta("import cadquery as cq", modelo_respaldo),
            ]
            resultado = solicitar_codigo(modelo_primario, mensajes)
        self.assertEqual(proveedor.generar.call_count, 2)
        self.assertEqual(proveedor.generar.call_args.args[0], modelo_respaldo)
        self.assertEqual(resultado["modelo_informado"], modelo_respaldo)
        self.assertEqual(resultado["perfil"]["fallback_automatico"], {
            "modelo_primario": modelo_primario,
            "modelo_respaldo": modelo_respaldo,
            "causa": "timeout",
        })

    def test_timeout_de_generadores_nuevos_alterna_gemma_y_glm(self):
        mensajes = [{"role": "user", "content": "Genera una pieza sencilla"}]
        for modelo_primario, modelo_respaldo in (
            ("google/gemma-4-31b-it", "z-ai/glm-5.3"),
            ("z-ai/glm-5.3", "google/gemma-4-31b-it"),
        ):
            with self.subTest(modelo=modelo_primario), patch(
                "aplicacion.proveedores.ProveedorNvidia"
            ) as constructor:
                constructor.return_value.generar.side_effect = [
                    ErrorNvidia("Timeout NVIDIA", "timeout"),
                    respuesta("resultado = 1", modelo_respaldo),
                ]
                resultado = solicitar_codigo(modelo_primario, mensajes)
            self.assertEqual(resultado["modelo_informado"], modelo_respaldo)
            self.assertEqual(resultado["perfil"]["fallback_automatico"], {
                "modelo_primario": modelo_primario,
                "modelo_respaldo": modelo_respaldo,
                "causa": "timeout",
            })

    def test_timeout_nemotron_cambia_a_deepseek_pro_con_maximo_publicado(self):
        mensajes = [{"role": "user", "content": "Genera una casa simple"}]
        with patch("aplicacion.proveedores.ProveedorNvidia") as constructor, patch(
            "aplicacion.proveedores.solicitar_deepseek", return_value={
                "texto": "resultado = 1", "modelo_informado": "deepseek-v4-pro",
                "tokens_entrada": 20, "tokens_salida": 12, "finalizacion": "stop",
            }
        ) as respaldo:
            constructor.return_value.generar.side_effect = ErrorNvidia("Timeout NVIDIA", "timeout")
            resultado = solicitar_codigo("nvidia/nemotron-3-super-120b-a12b", mensajes)
        self.assertEqual(respaldo.call_args.args[0], "deepseek-v4-pro")
        self.assertEqual(respaldo.call_args.args[2], "low")
        self.assertIsNone(respaldo.call_args.args[3])
        self.assertEqual(resultado["perfil"]["max_tokens"], 393216)
        self.assertEqual(resultado["proveedor"], "deepseek")
        self.assertEqual(resultado["perfil"]["fallback_automatico"]["causa"], "timeout")

    def test_revisor_visual_envia_imagen_y_esquema_estructurado(self):
        proveedor = ProveedorNvidia(clave="clave-prueba-no-real")
        cliente = MagicMock()
        cliente.__enter__.return_value = cliente
        cliente.post.return_value.status_code = 200
        revision = RevisionVisual(
            accepted=True, puntuacion_silueta=0.9,
            puntuacion_proporciones=0.9, puntuacion_features=0.9,
        )
        cliente.post.return_value.json.return_value = {
            "model": NVIDIA_MODEL_VISUAL_REVIEWER,
            "choices": [{"message": {"content": revision.model_dump_json()}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        imagen = b"\x89PNG\r\n\x1a\nimagen-prueba"
        with patch("aplicacion.calidad.nvidia.httpx.Client", return_value=cliente):
            resultado, _ = RouterModelos(proveedor).revisar_visual(
                "placa", plan_mecanico(), {}, imagen
            )
        cuerpo = cliente.post.call_args.kwargs["json"]
        usuario = cuerpo["messages"][1]["content"]
        self.assertTrue(resultado.accepted)
        self.assertEqual(cuerpo["model"], NVIDIA_MODEL_VISUAL_REVIEWER)
        self.assertEqual(usuario[1]["type"], "image_url")
        self.assertIn("puntuacion_silueta", usuario[0]["text"])

    def test_revision_acepta_alias_ingles_errors_y_normaliza_espanol(self):
        critica = CriticaGeometrica.model_validate({"accepted": False, "errors": []})
        visual = RevisionVisual.model_validate({
            "accepted": False, "puntuacion_silueta": 0.5,
            "puntuacion_proporciones": 0.5, "puntuacion_features": 0.5,
            "errors": [],
        })
        self.assertIn("errores", critica.model_dump())
        self.assertNotIn("errors", critica.model_dump())
        self.assertEqual(visual.errores, [])

    def test_modelo_nvidia_fuera_de_allowlist(self):
        with self.assertRaisesRegex(ErrorNvidia, "no permitido"):
            ProveedorNvidia(clave="clave-prueba-no-real").generar("modelo/arbitrario", [])


class QualityGateTests(unittest.TestCase):
    def test_fallo_tecnico_nunca_pasa_quality_gate(self):
        visual = RevisionVisual(accepted=True, puntuacion_silueta=1,
            puntuacion_proporciones=1, puntuacion_features=1)
        metricas = preparar_metricas(plan_mecanico(), {"technical_success": False}, visual)
        resultado = evaluar_quality_gate(metricas, False,
            RevisionCodigo(accepted=True, severity="none"), visual,
            CriticaGeometrica(accepted=True))
        self.assertFalse(resultado["technical_success"])
        self.assertFalse(resultado["quality_success"])

    def test_feature_no_medible_se_marca_unsupported_sin_inventar_medida(self):
        plan = PlanGeometrico(clase_modelado="ORGANIC_FREEFORM", features=[
            FeaturePlan(feature_id="pliegue", nombre="pliegue asimétrico", tipo="organic relief")
        ])
        metricas = preparar_metricas(plan, {"features": {"pliegue": {
            "estado": "unsupported", "verification_status": "unsupported"}}})
        detalle = metricas["puntuaciones"]["features"]["valor"]["detalle"][0]
        self.assertEqual(detalle["verification_status"], "unsupported")
        self.assertNotIn("observado", detalle)

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

    def test_gate_rechaza_agujeros_faltantes_aunque_revisores_aprueben(self):
        plan = plan_mecanico()
        plan.features[0].esencial = False
        plan.features.append(FeaturePlan(feature_id="agujeros", nombre="cuatro agujeros",
            tipo="hole pattern", dimensiones={"count": dimension(4), "diameter": dimension(8)}))
        visual = RevisionVisual(accepted=True, puntuacion_silueta=1,
            puntuacion_proporciones=1, puntuacion_features=1)
        observadas = {"technical_success": True, "brep_valido": True, "solidos": 1,
            "watertight": True, "dang_el": 0,
            "bounding_box_mm": {"x": 100, "y": 60, "z": 10},
            "features": {"agujeros": {"estado": "calculated", "cantidad": 2,
                "diametro_mm": 8, "diametros_observados_mm": [8, 8]}}}
        metricas = preparar_metricas(plan, observadas, visual)
        gate = evaluar_quality_gate(metricas, True,
            RevisionCodigo(accepted=True, severity="none"), visual,
            CriticaGeometrica(accepted=True))
        self.assertFalse(gate["quality_success"])
        self.assertEqual(gate["features_esenciales_incorrectas"], ["agujeros"])

    def test_gate_rechaza_cota_explicita_fuera_de_tolerancia(self):
        plan = plan_mecanico()
        visual = RevisionVisual(accepted=True, puntuacion_silueta=1,
            puntuacion_proporciones=1, puntuacion_features=1)
        observadas = {"technical_success": True, "brep_valido": True, "solidos": 1,
            "watertight": True, "dang_el": 0,
            "bounding_box_mm": {"x": 102, "y": 60, "z": 10}}
        metricas = preparar_metricas(plan, observadas, visual)
        gate = evaluar_quality_gate(metricas, True,
            RevisionCodigo(accepted=True, severity="none"), visual,
            CriticaGeometrica(accepted=True))
        self.assertFalse(gate["quality_success"])
        self.assertEqual(gate["cotas_explicitas_incorrectas"], ["x"])

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
    def test_fallo_de_cualquier_revisor_consume_intento_y_el_loop_continua(self):
        for rol_fallido in (
            "planner", "planner_validation", "generator", "code_reviewer",
            "visual_reviewer", "geometric_critic",
        ):
            with self.subTest(rol=rol_fallido):
                motor_db = create_engine("sqlite://", connect_args={"check_same_thread": False},
                                         poolclass=StaticPool)
                BaseDeclarativa.metadata.create_all(motor_db)
                Sesiones = sessionmaker(bind=motor_db, expire_on_commit=False)
                ejecucion_id = f"{len(rol_fallido):08d}-1111-4111-8111-111111111111"
                descripcion = (
                    "Casa sencilla de 40 × 25 × 12 mm, con fachada rectangular, techo a dos aguas, "
                    "una puerta centrada de 8 × 12 mm y dos ventanas cuadradas de 6 × 6 mm, "
                    "una a cada lado de la puerta. Diseño simple, con paredes y techo sólidos."
                    if rol_fallido == "generator" else "Placa de 100 x 60 x 10 mm"
                )
                with Sesiones() as sesion:
                    sesion.add(Ejecucion(
                        identificador=ejecucion_id,
                        descripcion=descripcion, motor="cadquery",
                        modelo="deepseek-v4-pro", modo="quality-loop", maximo_intentos=3,
                        estado="pendiente", mensaje="En cola",
                        configuracion_calidad={"best_of_n": False},
                    ))
                    sesion.commit()

                proveedor_fake = SimpleNamespace(llamadas=0)

                class RouterFalso:
                    def __init__(self, proveedor):
                        self.proveedor = proveedor

                    def _comprobar_fallo(self, rol):
                        self.proveedor.llamadas += 1
                        if rol == rol_fallido:
                            raise ErrorNvidia(f"Timeout simulado en {rol}", "timeout")
                        return respuesta(modelo="nvidia/nemotron-3-super-120b-a12b")

                    def planificar(self, descripcion, permitir_fallback=True):
                        self.proveedor.llamadas += 1
                        if rol_fallido == "planner":
                            raise ErrorNvidia("Timeout simulado en planner", "timeout")
                        if rol_fallido == "planner_validation":
                            plan = plan_mecanico().model_copy(update={"bounding_box_esperada": CajaPlan(
                                x=dimension(90), y=dimension(60), z=dimension(10))})
                            return plan, respuesta(modelo="nvidia/nemotron-3-super-120b-a12b")
                        if rol_fallido == "generator":
                            return construir_plan_local(descripcion), respuesta(
                                modelo="nvidia/nemotron-3-super-120b-a12b")
                        return plan_mecanico(), respuesta(modelo="nvidia/nemotron-3-ultra-550b-a55b")

                    def planificar_alternativo(self, descripcion):
                        self.proveedor.llamadas += 1
                        raise ErrorNvidia("Timeout simulado en planner alternativo", "timeout")

                    def revisar_codigo(self, motor, plan, codigo):
                        llamada = self._comprobar_fallo("code_reviewer")
                        return RevisionCodigo(accepted=True, severity="none"), llamada

                    def revisar_visual(self, descripcion, plan, metricas, imagen):
                        llamada = self._comprobar_fallo("visual_reviewer")
                        return (RevisionVisual(accepted=True, puntuacion_silueta=0.98,
                                puntuacion_proporciones=0.98, puntuacion_features=0.98), llamada)

                    def criticar(self, plan, evidencia):
                        llamada = self._comprobar_fallo("geometric_critic")
                        return CriticaGeometrica(accepted=True, preservar=["cuerpo"],
                            prioridad_reparacion=[]), llamada

                llamadas_generacion = []

                def generar(modelo, mensajes, esfuerzo, maximo_tokens=None):
                    llamadas_generacion.append(mensajes)
                    if rol_fallido == "generator":
                        raise ErrorProveedor("Timeout simulado del generador")
                    return {"texto": "import cadquery as cq\nresultado = cq.Workplane('XY').box(100, 60, 10)",
                        "modelo_informado": modelo, "tokens_entrada": 100, "tokens_salida": 40,
                        "finalizacion": "stop", "proveedor": "deepseek", "perfil": {"max_tokens": 1000}}

                png = base64.b64encode(b"\x89PNG\r\n\x1a\nmock").decode("ascii")
                inspeccion = {"technical_success": True, "geometric_metrics": {
                    "technical_success": True, "brep_valido": True, "solidos": 1,
                    "watertight": True, "dang_el": 0,
                    "bounding_box_mm": {"x": 100, "y": 60, "z": 10}, "features": {},
                    "symmetry": {"estado": "not_applicable", "valor": None}},
                    "reference_metrics": {"estado": "not_available"},
                    "multiview_png_base64": png}
                resultado_cad = {"correcto": True, "sintaxis_valida": True,
                    "ejecucion_correcta": True, "cad_valido": True, "exportacion_valida": True,
                    "runtime_identificador": "cadquery-test", "volumen_mm3": 60000,
                    "archivos": {"pieza.stl": "U1RMLW1vY2s=", "pieza.step": "U1RFUC1tb2Nr"}}

                with tempfile.TemporaryDirectory() as directorio:
                    with patch("aplicacion.calidad.flujo.crear_sesion", Sesiones), \
                         patch("aplicacion.calidad.flujo.ProveedorNvidia", return_value=proveedor_fake), \
                         patch("aplicacion.calidad.flujo.RouterModelos", RouterFalso), \
                         patch("aplicacion.calidad.flujo.solicitar_codigo", side_effect=generar), \
                         patch("aplicacion.calidad.flujo.solicitar_ejecucion_cad",
                               return_value=resultado_cad) as runtime, \
                         patch("aplicacion.calidad.flujo._consulta_evaluador",
                               return_value=inspeccion), \
                         patch("aplicacion.calidad.flujo.DIRECTORIO_ARTEFACTOS", directorio):
                        flujo.procesar_quality_loop(ejecucion_id)

                with Sesiones() as sesion:
                    ejecucion = sesion.get(Ejecucion, ejecucion_id)
                    intentos = list(sesion.scalars(select(IntentoGeneracion).where(
                        IntentoGeneracion.ejecucion_identificador == ejecucion_id
                    ).order_by(IntentoGeneracion.numero)))
                    informes = list(sesion.scalars(select(InformeCalidad).where(
                        InformeCalidad.ejecucion_identificador == ejecucion_id
                    ).order_by(InformeCalidad.iteracion)))
                    archivos_guardados = list(sesion.scalars(select(ArchivoGenerado).where(
                        ArchivoGenerado.ejecucion_identificador == ejecucion_id
                    )))
                    if rol_fallido in {"planner", "planner_validation"}:
                        self.assertIn(ejecucion.estado, {"completada", "fallida"})
                        self.assertEqual(ejecucion.configuracion_calidad["planner_fallback_local"]["causa"],
                                         "timeout")
                        self.assertTrue(ejecucion.configuracion_calidad["technical_success"])
                        self.assertTrue(archivos_guardados)
                        self.assertGreaterEqual(runtime.call_count, 1)
                    elif rol_fallido == "generator":
                        self.assertIn(ejecucion.estado, {"completada", "fallida"})
                        self.assertEqual(
                            ejecucion.configuracion_calidad["generador_fallback_local"]["modelo"],
                            "generador_local_cadquery_determinista_v1",
                        )
                        self.assertTrue(ejecucion.configuracion_calidad["technical_success"])
                        self.assertTrue(archivos_guardados)
                        self.assertEqual(runtime.call_count, 3)
                    elif rol_fallido == "code_reviewer":
                        self.assertEqual(ejecucion.estado, "fallida")
                        self.assertEqual(ejecucion.configuracion_calidad["estado_protocolo"],
                                         "quality_rejected")
                        self.assertTrue(ejecucion.configuracion_calidad["technical_success"])
                        self.assertTrue(all(i.solicitud_modelo["fallo_revisor"]["rol"] == rol_fallido
                                            for i in intentos))
                        self.assertTrue(archivos_guardados)
                        self.assertEqual(runtime.call_count, 3)
                    else:
                        self.assertEqual(ejecucion.estado, "fallida")
                        self.assertEqual(ejecucion.numero_intentos, 3)
                        self.assertEqual(ejecucion.configuracion_calidad["estado_protocolo"],
                                         "reviewer_attempts_exhausted")
                        self.assertEqual(len(llamadas_generacion), 3)
                        self.assertEqual(len(intentos), 3)
                        self.assertEqual(len(informes), 3)
                        self.assertTrue(all(i.estado == "error_proveedor" for i in intentos))
                        self.assertTrue(all(i.fase_error == "proveedor" for i in intentos))
                        self.assertTrue(all(i.solicitud_modelo["fallo_revisor"]["rol"] == rol_fallido
                                            for i in intentos))
                        self.assertTrue(all(i.resultado["resultado_clasificado"] == "reviewer_failed_attempt"
                                            for i in informes))
                        self.assertEqual(len(ejecucion.configuracion_calidad["errores_revisores"]), 3)
                        self.assertIn("3 intentos se perdieron", ejecucion.mensaje)
                        self.assertFalse(ejecucion.configuracion_calidad["quality_success"])
                        self.assertTrue(ejecucion.configuracion_calidad["technical_success"])
                        self.assertIn("pieza.stl", {archivo.nombre for archivo in archivos_guardados})
                        self.assertIsNotNone(ejecucion.primer_exito_cad)
                if rol_fallido in {"planner", "planner_validation", "generator", "code_reviewer"}:
                    self.assertGreaterEqual(runtime.call_count, 1)
                else:
                    self.assertEqual(runtime.call_count, 3)
                motor_db.dispose()

    def test_revision_codigo_negativa_no_omite_el_runtime_cad(self):
        motor_db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        BaseDeclarativa.metadata.create_all(motor_db)
        Sesiones = sessionmaker(bind=motor_db, expire_on_commit=False)
        ejecucion_id = "d1111111-1111-4111-8111-111111111111"
        with Sesiones() as sesion:
            sesion.add(Ejecucion(identificador=ejecucion_id,
                descripcion="Placa de 100 x 60 x 10 mm", motor="cadquery", modelo="deepseek-v4-pro",
                modo="quality-loop", maximo_intentos=3, estado="pendiente", mensaje="En cola",
                configuracion_calidad={"best_of_n": False}))
            sesion.commit()

        proveedor_fake = SimpleNamespace(llamadas=0)

        class RouterFalso:
            def __init__(self, proveedor):
                self.proveedor = proveedor

            def planificar(self, descripcion, permitir_fallback=True):
                self.proveedor.llamadas += 1
                return plan_mecanico(), respuesta(modelo="nvidia/nemotron-3-ultra-550b-a55b")

            def revisar_codigo(self, motor, plan, codigo):
                self.proveedor.llamadas += 1
                return (RevisionCodigo(accepted=False, severity="critical"),
                        respuesta(modelo="poolside/laguna-xs-2.1"))

        def generar(modelo, mensajes, esfuerzo, maximo_tokens=None):
            return {"texto": "import cadquery as cq\nresultado = cq.Workplane('XY').box(100, 60, 10)",
                    "modelo_informado": modelo, "tokens_entrada": 100, "tokens_salida": 50,
                    "finalizacion": "stop", "proveedor": "deepseek", "perfil": {"max_tokens": 1000}}

        with tempfile.TemporaryDirectory() as directorio:
            with patch("aplicacion.calidad.flujo.crear_sesion", Sesiones), \
                 patch("aplicacion.calidad.flujo.ProveedorNvidia", return_value=proveedor_fake), \
                 patch("aplicacion.calidad.flujo.RouterModelos", RouterFalso), \
                 patch("aplicacion.calidad.flujo.solicitar_codigo", side_effect=generar), \
                 patch("aplicacion.calidad.flujo.solicitar_ejecucion_cad", return_value={
                     "correcto": False, "fase_error": "cad", "diagnostico": "Rechazo CAD simulado",
                     "sintaxis_valida": True, "ejecucion_correcta": True,
                     "cad_valido": False, "exportacion_valida": None,
                 }) as runtime, \
                 patch("aplicacion.calidad.flujo.DIRECTORIO_ARTEFACTOS", directorio):
                flujo.procesar_quality_loop(ejecucion_id)
            self.assertEqual(runtime.call_count, 3)
        with Sesiones() as sesion:
            ejecucion = sesion.get(Ejecucion, ejecucion_id)
            informes = list(sesion.scalars(select(InformeCalidad).where(
                InformeCalidad.ejecucion_identificador == ejecucion_id)))
            self.assertEqual(ejecucion.estado, "fallida")
            self.assertEqual(ejecucion.configuracion_calidad["estado_protocolo"], "quality_rejected")
            self.assertFalse(ejecucion.configuracion_calidad["quality_success"])
            self.assertEqual(len(informes), 3)
            self.assertTrue(all(i.resultado["resultado_clasificado"] == "review_rejected"
                                for i in informes))

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
        with self.assertRaisesRegex(ValueError, "Acceso a archivo no permitido"):
            revisar_codigo("import cadquery as cq\nresultado = cq.importers.importStep('/tmp/ref.step')",
                           "cadquery")
        with self.assertRaisesRegex(ValueError, "importaciones relativas"):
            revisar_codigo("from .cadquery import Workplane", "cadquery")

    def test_ocp_restringido_a_simbolos_y_motores_permitidos(self):
        codigo = "from OCP.gp import gp_Pnt\nimport cadquery as cq\nresultado = cq.Workplane('XY').box(1, 1, 1)"
        revisar_codigo(codigo, "cadquery")
        with self.assertRaisesRegex(ValueError, "Módulo OCP no permitido"):
            revisar_codigo("from OCP.StlAPI import StlAPI_Writer", "cadquery")
        with self.assertRaisesRegex(ValueError, "Módulo OCP no permitido"):
            revisar_codigo("from OCP.gp import gp_Pnt", "freecad")
        with self.assertRaisesRegex(ValueError, "Símbolo OCP no permitido"):
            revisar_codigo("from OCP.gp import gp_XYZ", "cadquery")


if __name__ == "__main__":
    unittest.main()
