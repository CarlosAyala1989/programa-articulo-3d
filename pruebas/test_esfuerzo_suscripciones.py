"""Esfuerzos anunciados, enviados y congelados sin generar turnos de cuentas reales."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aplicacion.api import aplicacion
from aplicacion.base_datos import BaseDeclarativa, CasoDiseno, Ejecucion, IntentoGeneracion, VersionConjunto
from aplicacion.catalogo_cli import _esfuerzo_antigravity, consultar_catalogo_cli
from aplicacion.cli_suscripcion import ErrorCLI, ejecutar_cli
from aplicacion.configuracion import perfil_generacion
from aplicacion.generacion import procesar_ejecucion


GPT = "codex-cli::gpt-6.1-sol"
GEMINI = "antigravity-cli::gemini-3.8-flash-high"
CLAUDE = "antigravity-cli::claude-sonnet-4-6"
NIVELES = {"low": "Bajo", "medium": "Medio", "high": "Alto", "xhigh": "Muy alto", "max": "Máximo"}
CATALOGOS = {
    "codex-cli": {"estado": "disponible", "modelos": {GPT: {
        "nombre": "GPT", "modalidades": ["text", "image"], "esfuerzos": NIVELES,
        "esfuerzo_predeterminado": "low", "esfuerzo_informado": "low"}}},
    "antigravity-cli": {"estado": "disponible", "modelos": {
        GEMINI: {"nombre": "Gemini High", "esfuerzos": {"low": "Bajo", "high": "Alto"},
                 "esfuerzo_predeterminado": "high", "esfuerzo_informado": "high",
                 "modelos_por_esfuerzo": {"low": GEMINI.replace("-high", "-low"), "high": GEMINI}},
        CLAUDE: {"nombre": "Claude Sonnet (Thinking)", "esfuerzos": {}, "esfuerzo_ajustable": False}}},
}
MENSAJES = [{"role": "user", "content": "Genera una caja de 20 mm"}]


class EsfuerzoSuscripcionesTests(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.motor.dispose)
        BaseDeclarativa.metadata.create_all(self.motor)
        self.sesiones = sessionmaker(bind=self.motor, expire_on_commit=False)
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        parches = [patch.dict(os.environ, {"CLI_PUENTE_SOCKET": "/inexistente.sock", "CLI_CATALOGO_DIRECTORIO": temporal.name}),
                   patch("aplicacion.proveedor_suscripcion.catalogos_cli", return_value=CATALOGOS),
                   patch("aplicacion.api.catalogos_cli", return_value=CATALOGOS),
                   patch("aplicacion.api.estado_puente", return_value={}),
                   patch("aplicacion.catalogo_cli._cache", {})]
        parches.extend(patch(f"aplicacion.{modulo}.crear_sesion", self.sesiones)
                       for modulo in ("api", "campanas", "conjuntos", "generacion"))
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)
        self.cliente = TestClient(aplicacion)
        self.addCleanup(self.cliente.close)

    def test_catalogo_codex_publica_predeterminado_y_niveles_sin_delegacion(self):
        with patch("aplicacion.catalogo_cli.ejecutable_cli", return_value="codex"), \
             patch("aplicacion.catalogo_cli._modelos_codex", return_value=[{
                 "model": "gpt-6.1-sol", "defaultReasoningEffort": "low",
                 "supportedReasoningEfforts": [{"reasoningEffort": n} for n in [*NIVELES, "ultra"]]}]):
            modelo = consultar_catalogo_cli("codex-cli")["modelos"][GPT]
        self.assertEqual(modelo["esfuerzos"], NIVELES)
        self.assertEqual(modelo["esfuerzo_predeterminado"], "low")

    def test_catalogo_gemini_conserva_identidades_por_esfuerzo(self):
        with patch("aplicacion.catalogo_cli.ejecutable_cli", return_value="agy"), \
             patch("aplicacion.catalogo_cli._ejecutar", return_value="\n".join(
                 f"gemini-3.8-flash-{n}\tGemini {n}" for n in ("low", "medium", "high"))), \
             patch("aplicacion.catalogo_cli._esfuerzo_antigravity", side_effect=lambda _, modelo, *args: {
                 "adjustable": True, "current": modelo.rsplit("-", 1)[-1], "available": ["low", "medium", "high"]}):
            modelo = consultar_catalogo_cli("antigravity-cli")["modelos"][GEMINI]
        self.assertEqual(modelo["esfuerzo_predeterminado"], "high")
        self.assertEqual(modelo["modelos_por_esfuerzo"]["low"], GEMINI.replace("-high", "-low"))

    def test_consulta_effort_solo_acepta_metadatos_de_cero_turnos(self):
        for turnos in (0, 1):
            datos = {"status": "SUCCESS", "num_turns": turnos,
                     "command": {"name": "effort", "data": {"adjustable": False}}}
            with patch("aplicacion.catalogo_cli._ejecutar", return_value=json.dumps(datos)) as ejecutar:
                resultado = _esfuerzo_antigravity("agy", "claude-sonnet-4-6", "/tmp", 5)
            self.assertEqual(resultado, {"adjustable": False} if turnos == 0 else {})
            self.assertEqual(ejecutar.call_args.args[0], ["agy", "--print", "/effort", "--model", "claude-sonnet-4-6", "--output-format", "json"])

    def test_esfuerzos_guardados_sobreviven_fallo_parcial_de_metadatos(self):
        with patch("aplicacion.catalogo_cli._cache", {}) as memoria, \
             patch("aplicacion.catalogo_cli.ejecutable_cli", return_value="agy"), \
             patch("aplicacion.catalogo_cli._ejecutar", return_value="gemini-3.8-flash-high\tGemini High"), \
             patch("aplicacion.catalogo_cli._esfuerzo_antigravity", return_value={
                 "adjustable": True, "current": "high", "available": ["high"]}) as metadatos:
            original = consultar_catalogo_cli("antigravity-cli")["modelos"][GEMINI]
            memoria.clear()
            metadatos.return_value = {}
            recuperado = consultar_catalogo_cli("antigravity-cli")["modelos"][GEMINI]
        self.assertEqual(recuperado["esfuerzos"], original["esfuerzos"])
        self.assertEqual(recuperado["esfuerzo_predeterminado"], "high")

    def test_no_presenta_como_fijo_un_esfuerzo_sin_consulta_verificada(self):
        with patch("aplicacion.catalogo_cli.ejecutable_cli", return_value="agy"), \
             patch("aplicacion.catalogo_cli._ejecutar", return_value="gpt-oss-120b-medium\tGPT-OSS Medium"), \
             patch("aplicacion.catalogo_cli._esfuerzo_antigravity", return_value={}):
            detalle = consultar_catalogo_cli("antigravity-cli")["modelos"]["antigravity-cli::gpt-oss-120b-medium"]
        self.assertIsNone(detalle["esfuerzo_informado"])
        self.assertIsNone(detalle["esfuerzo_ajustable"])

    def test_api_anuncia_niveles_y_predeterminados_por_modelo(self):
        respuesta = self.cliente.get("/api/opciones")
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertEqual(datos["esfuerzos_por_modelo"][GPT], NIVELES)
        self.assertEqual(datos["esfuerzos_predeterminados"][GPT], "low")
        self.assertNotIn(CLAUDE, datos["esfuerzos_por_modelo"])
        self.assertFalse(datos["detalles_esfuerzo"][CLAUDE]["esfuerzo_ajustable"])

    def test_codex_recibe_esfuerzo_explicito_y_lo_registra(self):
        with patch("aplicacion.cli_suscripcion.ejecutable_cli", return_value="codex"), \
             patch("aplicacion.catalogo_cli.consultar_catalogo_cli", return_value=CATALOGOS["codex-cli"]), \
             patch("aplicacion.cli_suscripcion.subprocess.run", return_value=SimpleNamespace(
                 returncode=0, stdout="Logged in using ChatGPT", stderr="")), \
             patch("aplicacion.cli_suscripcion._ejecutar", return_value='{"type":"item.completed","item":{"type":"agent_message","text":"Python"}}\n{"type":"turn.completed"}') as ejecutar:
            respuesta = ejecutar_cli(GPT, MENSAJES, esfuerzo_razonamiento="xhigh")
        self.assertIn('model_reasoning_effort="xhigh"', ejecutar.call_args.args[0])
        self.assertEqual(respuesta["perfil"]["reasoning_effort"], "xhigh")
        self.assertIn("features.multi_agent=false", ejecutar.call_args.args[0])

    def test_antigravity_recibe_effort_y_modelo_compatibles(self):
        salida = {"event": "result", "result": {"status": "SUCCESS", "response": "Python", "model": "gemini-3.8-flash-high"}}
        with patch("aplicacion.cli_suscripcion.ejecutable_cli", return_value="agy"), \
             patch("aplicacion.catalogo_cli.consultar_catalogo_cli", return_value=CATALOGOS["antigravity-cli"]), \
             patch("aplicacion.cli_suscripcion.Path.home", return_value=Path("/inexistente")), \
             patch("aplicacion.cli_suscripcion._ejecutar", return_value=json.dumps(salida)) as ejecutar:
            respuesta = ejecutar_cli(GEMINI, MENSAJES, esfuerzo_razonamiento="high")
        argumentos = ejecutar.call_args.args[0]
        self.assertEqual(argumentos[argumentos.index("--effort") + 1], "high")
        self.assertEqual(argumentos[argumentos.index("--model") + 1], "gemini-3.8-flash-high")
        self.assertEqual(respuesta["perfil"]["reasoning_effort"], "high")

    def test_esfuerzo_incompatible_no_inicia_inferencia(self):
        with patch("aplicacion.cli_suscripcion.ejecutable_cli", return_value="agy"), \
             patch("aplicacion.catalogo_cli.consultar_catalogo_cli", return_value=CATALOGOS["antigravity-cli"]), \
             patch("aplicacion.cli_suscripcion._ejecutar") as ejecutar:
            for modelo, esfuerzo in ((GEMINI, "low"), (CLAUDE, "high"), (GEMINI, "ultra")):
                with self.subTest(modelo=modelo, esfuerzo=esfuerzo), self.assertRaises(ErrorCLI):
                    ejecutar_cli(modelo, MENSAJES, esfuerzo_razonamiento=esfuerzo)
        ejecutar.assert_not_called()

    def test_api_congela_esfuerzo_en_los_cinco_intentos(self):
        with patch("aplicacion.api.tarea_generacion.apply_async"):
            respuesta = self.cliente.post("/api/ejecuciones", json={"descripcion": "Caja de 20 mm por lado",
                "motor": "cadquery", "modelo": GPT, "modo": "closed-loop", "esfuerzo_razonamiento": "high"})
        self.assertEqual(respuesta.status_code, 202, respuesta.text)
        identificador = respuesta.json()["identificador"]
        with patch("aplicacion.proveedores.solicitar_cli", return_value={"texto": "esto no es Python !!!",
                   "modelo_informado": "", "tokens_entrada": 0, "tokens_salida": 0,
                   "finalizacion": "stop", "perfil": {"reasoning_effort": "high"}}) as cli:
            procesar_ejecucion(identificador)
        self.assertEqual(cli.call_count, 5)
        self.assertTrue(all(llamada.kwargs["esfuerzo_razonamiento"] == "high" for llamada in cli.call_args_list))
        with self.sesiones() as sesion:
            ejecucion = sesion.get(Ejecucion, identificador)
            self.assertEqual(ejecucion.esfuerzo_razonamiento, "high")
            self.assertTrue(all(i.solicitud_modelo["perfil"]["reasoning_effort"] == "high" for i in ejecucion.intentos))

    def test_campana_congela_esfuerzos_distintos_y_rechaza_modelos_ajenos(self):
        with self.sesiones() as sesion:
            sesion.add(VersionConjunto(identificador="prueba", nombre="Prueba", version="1", finalidad="desarrollo", estado="congelado"))
            sesion.add(CasoDiseno(identificador="caso", conjunto_identificador="prueba", codigo="B01", nivel="basico",
                                  familia="caja", fundamento="Prueba", descripcion="Caja de 20 mm por lado", especificacion={"unidad": "mm"}))
            sesion.commit()
        solicitud = {"nombre": "Esfuerzos independientes", "conjunto_identificador": "prueba",
            "modelos": [GPT, "deepseek-flash"], "motores": ["cadquery"], "modos": ["open-loop"],
            "esfuerzos_por_modelo": {GPT: "medium", "deepseek-flash": "max"}}
        respuesta = self.cliente.post("/api/campanas", json=solicitud)
        self.assertEqual(respuesta.status_code, 201, respuesta.text)
        self.assertEqual(respuesta.json()["configuracion"]["esfuerzos_por_modelo"], solicitud["esfuerzos_por_modelo"])
        with self.sesiones() as sesion:
            self.assertEqual({e.modelo: e.esfuerzo_razonamiento for e in sesion.scalars(select(Ejecucion))},
                             solicitud["esfuerzos_por_modelo"])
        solicitud["esfuerzos_por_modelo"][CLAUDE] = "high"
        for ruta in ("/api/campanas", "/api/campanas/previsualizar"):
            self.assertEqual(self.cliente.post(ruta, json=solicitud).status_code, 422)

    def test_reanudacion_recupera_esfuerzo_cli_de_la_traza(self):
        with self.sesiones() as sesion:
            sesion.add(Ejecucion(identificador="reanudar", descripcion="Caja de 20 mm por lado", modelo=GPT,
                motor="cadquery", modo="closed-loop", maximo_intentos=5, estado="pausada"))
            sesion.add(IntentoGeneracion(ejecucion_identificador="reanudar", numero=1, estado="invalido",
                codigo="!", diagnostico="Error de sintaxis", fase_error="sintaxis",
                solicitud_modelo={"perfil": {"reasoning_effort": "high"}}))
            sesion.commit()
        with patch("aplicacion.proveedores.solicitar_cli", return_value={"texto": "esto no es Python !!!",
                   "modelo_informado": "", "tokens_entrada": 0, "tokens_salida": 0,
                   "finalizacion": "stop", "perfil": {"reasoning_effort": "high"}}) as cli:
            procesar_ejecucion("reanudar")
        self.assertEqual(cli.call_count, 4)
        self.assertTrue(all(llamada.kwargs["esfuerzo_razonamiento"] == "high" for llamada in cli.call_args_list))
        with self.sesiones() as sesion:
            self.assertEqual(sesion.get(Ejecucion, "reanudar").esfuerzo_razonamiento, "high")

    def test_historial_cli_sin_esfuerzo_no_se_reinterpreta(self):
        self.assertNotIn("reasoning_effort", perfil_generacion(GPT))


if __name__ == "__main__":
    unittest.main()
