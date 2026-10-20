"""Regresiones del transporte CLI; nunca consumen cuotas de cuentas reales."""

import json
import os
import socket
import subprocess
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx

from aplicacion.cli_suscripcion import ErrorCLI, _ejecutar, ejecutar_cli, perfil_cli, proveedor_cli
from aplicacion.catalogo_cli import consultar_catalogo_cli
from aplicacion.configuracion import perfil_generacion
from aplicacion.proveedores import solicitar_codigo
from aplicacion.calidad.modelos import RevisionCodigo
from aplicacion.calidad.nvidia import RouterModelos
from aplicacion.calidad.suscripcion import ProveedorRolesSuscripcion, rutas_revision, validar_revisores
from aplicacion.puente_cli import ManejadorCLI, _retirar_socket_obsoleto
from aplicacion.proveedor_suscripcion import catalogos_cli, modelos_cli_configurados, solicitar_cli


MENSAJES = [{"role": "system", "content": "Devuelve Python"},
            {"role": "user", "content": "Bloque de 40 × 25 × 12 mm"}]


class SuscripcionesTests(unittest.TestCase):
    def setUp(self):
        directorio = tempfile.TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        for parche in (patch.dict(os.environ, {"CLI_CATALOGO_DIRECTORIO": directorio.name}),
                       patch("aplicacion.catalogo_cli._cache", {}),
                       patch("aplicacion.catalogo_cli._esfuerzo_antigravity", return_value={}),
                       patch("aplicacion.proveedor_suscripcion._catalogos", None)):
            parche.start()
            self.addCleanup(parche.stop)

    def test_socket_abandonado_se_retira_tras_apagado(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "cli.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conexion:
                conexion.bind(str(ruta))
            self.assertTrue(ruta.exists())
            _retirar_socket_obsoleto(ruta)
            self.assertFalse(ruta.exists())
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conexion:
                conexion.bind(str(ruta))

    def test_socket_activo_no_se_retira(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "cli.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conexion:
                conexion.bind(str(ruta))
                conexion.listen(1)
                with self.assertRaisesRegex(SystemExit, "ya está en ejecución"):
                    _retirar_socket_obsoleto(ruta)
                self.assertTrue(ruta.exists())

    def test_ruta_ajena_al_socket_no_se_elimina(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "cli.sock"
            ruta.write_text("conservar", encoding="utf-8")
            with self.assertRaises(SystemExit):
                _retirar_socket_obsoleto(ruta)
            self.assertEqual(ruta.read_text(), "conservar")
            enlace = Path(directorio) / "enlace.sock"
            enlace.symlink_to(ruta)
            with self.assertRaises(SystemExit):
                _retirar_socket_obsoleto(enlace)
            self.assertTrue(enlace.is_symlink())

    def test_catalogos_sobreviven_reinicio_y_se_actualizan_al_recuperarse(self):
        for proveedor, identificador in (("codex-cli", "gpt-6.1-sol"),
                                         ("antigravity-cli", "gemini-3.1-pro-high")):
            clave = f"{proveedor}::{identificador}"
            with self.subTest(proveedor=proveedor), \
                 patch("aplicacion.catalogo_cli._cache", {}) as memoria, \
                 patch("aplicacion.catalogo_cli.time.monotonic", return_value=0) as reloj, \
                 patch("aplicacion.catalogo_cli.ejecutable_cli", return_value="cli"), \
                 patch("aplicacion.catalogo_cli._modelos_codex", return_value=[{
                     "model": identificador, "inputModalities": ["text", "image"]}]) as codex, \
                 patch("aplicacion.catalogo_cli._ejecutar", return_value=f"{identificador}\tModelo") as agy:
                original = consultar_catalogo_cli(proveedor)
                self.assertEqual(original["estado"], "disponible")
                archivo = Path(os.environ["CLI_CATALOGO_DIRECTORIO"]) / f"{proveedor}.json"
                self.assertEqual(archivo.stat().st_mode & 0o777, 0o600)
                memoria.clear()  # Simular otro proceso sin caché en memoria.
                consulta = codex if proveedor == "codex-cli" else agy
                consulta.side_effect = ErrorCLI("Sin conexión")
                guardado = consultar_catalogo_cli(proveedor)
                self.assertEqual(guardado["estado"], "guardado")
                self.assertEqual(guardado["modelos"], original["modelos"])
                self.assertIn(clave, guardado["modelos"])
                self.assertFalse(guardado["acceso_verificado"])
                consulta.side_effect = None
                nuevo = identificador + "-nuevo"
                codex.return_value = [{"model": nuevo, "inputModalities": ["text", "image"]}]
                agy.return_value = f"{nuevo}\tModelo nuevo"
                reloj.return_value = 11
                actualizado = consultar_catalogo_cli(proveedor)
                self.assertEqual(actualizado["estado"], "disponible")
                self.assertEqual(list(actualizado["modelos"]), [f"{proveedor}::{nuevo}"])
                memoria.clear()
                consulta.side_effect = ErrorCLI("Sin conexión")
                self.assertEqual(consultar_catalogo_cli(proveedor)["modelos"], actualizado["modelos"])
                self.assertEqual(consulta.call_count, 4)

    def test_catalogo_corrupto_no_bloquea_consulta(self):
        archivo = Path(os.environ["CLI_CATALOGO_DIRECTORIO"]) / "codex-cli.json"
        archivo.write_text("{incompleto", encoding="utf-8")
        with patch("aplicacion.catalogo_cli.ejecutable_cli", return_value=None):
            catalogo = consultar_catalogo_cli("codex-cli")
        self.assertEqual(catalogo["estado"], "no_disponible")
        self.assertEqual(catalogo["modelos"], {})

    def test_backend_recupera_catalogos_sin_esperar_cinco_minutos(self):
        catalogo = {"codex-cli": {"estado": "disponible", "modelos": {
            "codex-cli::gpt-6.1-sol": {"nombre": "GPT"}}}}
        respuesta = MagicMock()
        respuesta.json.return_value = catalogo
        with patch.dict(os.environ, {"CLI_PUENTE_SOCKET": "/puente/cli.sock"}), \
             patch("aplicacion.proveedor_suscripcion.time.monotonic", return_value=0) as reloj, \
             patch("aplicacion.proveedor_suscripcion.httpx.Client") as cliente:
            obtener = cliente.return_value.__enter__.return_value.get
            obtener.side_effect = [httpx.ConnectError("Arrancando"), respuesta,
                                   httpx.ConnectError("Reiniciando"), respuesta]
            self.assertEqual(catalogos_cli(), {})
            reloj.return_value = 11
            self.assertEqual(catalogos_cli(), catalogo)
            reloj.return_value = 312
            guardado = catalogos_cli()
            self.assertEqual(guardado["codex-cli"]["estado"], "guardado")
            self.assertEqual(guardado["codex-cli"]["modelos"], catalogo["codex-cli"]["modelos"])
            reloj.return_value = 323
            self.assertEqual(catalogos_cli(), catalogo)

    def test_selector_muestra_identificador_exacto_aunque_nombre_sea_generico(self):
        with patch.dict(os.environ, {"CLI_PUENTE_SOCKET": "/puente/cli.sock"}), \
             patch("aplicacion.proveedor_suscripcion.catalogos_cli", return_value={
                 "codex-cli": {"modelos": {"codex-cli::gpt-6.1-sol": {"nombre": "GPT"}}}}):
            self.assertIn("gpt-6.1-sol", modelos_cli_configurados()["codex-cli::gpt-6.1-sol"])

    def test_modelo_concreto_prevalece_sobre_variable_y_viaja_al_cli(self):
        for modelo, variable in (("codex-cli::gpt-6.1-sol", "CODEX_CLI_MODELO"),
                                 ("antigravity-cli::gemini-3.1-pro-high", "ANTIGRAVITY_CLI_MODELO")):
            with self.subTest(modelo=modelo), patch.dict(os.environ, {variable: "otro-modelo"}):
                self.assertEqual(perfil_cli(modelo)["modelo_configurado"], modelo.split("::")[1])
                self.assertEqual(perfil_generacion(modelo)["modelo_configurado"], modelo.split("::")[1])
        with patch("aplicacion.cli_suscripcion.ejecutable_cli", return_value="codex"), \
             patch("aplicacion.cli_suscripcion.subprocess.run", return_value=SimpleNamespace(
                 returncode=0, stdout="Logged in using ChatGPT", stderr="")), \
             patch("aplicacion.cli_suscripcion._ejecutar", return_value='{"type":"item.completed","item":{"type":"agent_message","text":"programa"}}\n{"type":"turn.completed"}') as ejecutar:
            respuesta = ejecutar_cli("codex-cli::gpt-6.1-sol", MENSAJES)
        argumentos = ejecutar.call_args.args[0]
        self.assertEqual(argumentos[argumentos.index("--model") + 1], "gpt-6.1-sol")
        self.assertEqual(respuesta["proveedor"], "codex-cli")

    def test_catalogo_antigravity_descarta_cabeceras_y_no_genera_turnos(self):
        with patch("aplicacion.catalogo_cli._cache", {}), \
             patch("aplicacion.catalogo_cli.ejecutable_cli", return_value="agy"), \
             patch("aplicacion.catalogo_cli._ejecutar", return_value="Fetching available models...\ngemini-3.1-pro-high\tGemini 3.1 Pro (High)\nclaude-sonnet-4-6\tClaude Sonnet 4.6\n") as ejecutar:
            catalogo = consultar_catalogo_cli("antigravity-cli")
            consultar_catalogo_cli("antigravity-cli")
        self.assertEqual(len(catalogo["modelos"]), 2)
        self.assertFalse(catalogo["acceso_verificado"])
        ejecutar.assert_called_once()
        self.assertEqual(ejecutar.call_args.args[0], ["agy", "models"])

    def test_catalogo_codex_conserva_modelos_y_modalidades(self):
        with patch("aplicacion.catalogo_cli._cache", {}), \
             patch("aplicacion.catalogo_cli.ejecutable_cli", return_value="codex"), \
             patch("aplicacion.catalogo_cli._modelos_codex", return_value=[{
                 "model": "gpt-6.1-sol", "displayName": "GPT-6.1-Sol",
                 "inputModalities": ["text", "image"], "isDefault": True}]):
            catalogo = consultar_catalogo_cli("codex-cli")
        self.assertEqual(catalogo["modelos"]["codex-cli::gpt-6.1-sol"]["modalidades"], ["text", "image"])
        self.assertFalse(catalogo["acceso_verificado"])

    def test_modelos_y_revisores_concretos_se_validan_por_catalogo(self):
        elegido = "codex-cli::gpt-6.1-sol"
        with patch("aplicacion.calidad.suscripcion.modelos_cli_configurados", return_value={elegido: "Codex"}), \
             patch("aplicacion.proveedor_suscripcion.catalogos_cli", return_value={"codex-cli": {"modelos": {elegido: {"modalidades": ["text", "image"]}}}}):
            validar_revisores(elegido, False)
        self.assertEqual(rutas_revision(elegido)["revisor_visual"]["modelo"], elegido)
        self.assertIsNone(proveedor_cli("codex-cli::--opcion"))
        self.assertIsNone(proveedor_cli("antigravity-cli::modelo con espacios"))

    def test_codex_recibe_mensajes_completos_y_solo_respuesta_final(self):
        eventos = [
            {"type": "thread.started", "thread_id": "prueba"},
            {"type": "item.completed", "item": {"type": "reasoning", "text": "privado"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "resultado = caja"}},
            {"type": "turn.completed", "usage": {"input_tokens": 22, "output_tokens": 11}},
        ]
        with patch("aplicacion.cli_suscripcion.ejecutable_cli", return_value="codex"), \
             patch("aplicacion.cli_suscripcion.subprocess.run", return_value=SimpleNamespace(
                 returncode=0, stdout="", stderr="Logged in using ChatGPT")), \
             patch("aplicacion.cli_suscripcion._ejecutar", return_value="\n".join(map(json.dumps, eventos))) as ejecutar:
            respuesta = ejecutar_cli("codex-cli", MENSAJES, [b"\x89PNG\r\n\x1a\nprueba"])
        self.assertEqual(respuesta["texto"], "resultado = caja")
        self.assertEqual(respuesta["modelo_informado"], "")
        self.assertEqual(respuesta["tokens_salida"], 11)
        argumentos, entrada, *_ = ejecutar.call_args.args
        self.assertIn("--ignore-user-config", argumentos)
        self.assertIn("read-only", argumentos)
        self.assertIn("--image", argumentos)
        for mensaje in MENSAJES:
            self.assertIn(mensaje["content"], entrada)

    def test_antigravity_envia_un_turno_por_stdin_y_exige_success(self):
        with patch("aplicacion.cli_suscripcion.ejecutable_cli", return_value="agy"), \
             patch("aplicacion.cli_suscripcion.Path.home", return_value=Path("/inexistente")), \
             patch("aplicacion.cli_suscripcion._ejecutar", return_value=json.dumps({
                 "event": "result", "result": {"status": "SUCCESS", "response": "resultado = caja"}
             })) as ejecutar:
            respuesta = ejecutar_cli("antigravity-cli::gemini-3.1-pro-high", MENSAJES)
        self.assertEqual(respuesta["texto"], "resultado = caja")
        self.assertTrue(respuesta["perfil"]["consumo_desconocido"])
        entrada = json.loads(ejecutar.call_args.args[1])
        self.assertEqual(entrada["event"], "user")
        self.assertIn(MENSAJES[1]["content"], entrada["message"]["content"])
        argumentos = ejecutar.call_args.args[0]
        self.assertEqual(argumentos[argumentos.index("--model") + 1], "gemini-3.1-pro-high")

    def test_codex_rechaza_login_de_api_sin_consumir_modelo(self):
        with patch("aplicacion.cli_suscripcion.ejecutable_cli", return_value="codex"), \
             patch("aplicacion.cli_suscripcion.subprocess.run", return_value=SimpleNamespace(
                 returncode=0, stdout="Logged in using API key", stderr="")), \
             patch("aplicacion.cli_suscripcion._ejecutar") as ejecutar:
            with self.assertRaisesRegex(ErrorCLI, "ChatGPT"):
                ejecutar_cli("codex-cli", MENSAJES)
        ejecutar.assert_not_called()

    def test_timeout_termina_grupo_y_no_reintenta_ni_expone_stderr(self):
        proceso = MagicMock(pid=123)
        proceso.communicate.side_effect = [subprocess.TimeoutExpired("codex", 30), ("", "secreto")]
        with patch("aplicacion.cli_suscripcion.subprocess.Popen", return_value=proceso) as iniciar, \
             patch("aplicacion.cli_suscripcion.os.killpg") as terminar, \
             patch.dict(os.environ, {"NVIDIA_API_KEY": "no-real", "OPENAI_API_KEY": "no-real"}):
            with self.assertRaisesRegex(ErrorCLI, "Timeout"):
                _ejecutar(["codex"], "prompt", "/tmp", 30)
        iniciar.assert_called_once()
        terminar.assert_called_once()
        self.assertNotIn("NVIDIA_API_KEY", iniciar.call_args.kwargs["env"])
        self.assertNotIn("OPENAI_API_KEY", iniciar.call_args.kwargs["env"])

    def test_proveedor_se_integra_sin_limite_de_tokens_ficticio(self):
        with patch("aplicacion.proveedores.solicitar_cli", return_value={"texto": "programa"}) as cli:
            self.assertEqual(solicitar_codigo("codex-cli", MENSAJES)["texto"], "programa")
        cli.assert_called_once_with("codex-cli", MENSAJES)
        self.assertFalse(perfil_generacion("codex-cli")["limite_tokens_aplicable"])
        with self.assertRaises(ValueError):
            perfil_generacion("codex-cli", maximo_tokens=4096)

    def test_router_codex_valida_json_y_no_usa_nvidia(self):
        salida = {"texto": '{"accepted": true, "severity": "none", "issues": []}',
                  "modelo_informado": None, "tokens_entrada": 1, "tokens_salida": 2,
                  "finalizacion": "stop", "perfil": {"latencia_segundos": 0.1}}
        with patch("aplicacion.calidad.suscripcion.solicitar_cli", return_value=salida), \
             patch("aplicacion.calidad.suscripcion.ProveedorNvidia") as nvidia:
            proveedor = ProveedorRolesSuscripcion()
            revision, respuesta = proveedor.generar_estructurado(
                "codex-cli", "revisa", "programa", RevisionCodigo)
        self.assertTrue(revision.accepted)
        self.assertEqual(respuesta.proveedor, "codex-cli")
        self.assertEqual(respuesta.modelo, "")
        self.assertEqual(respuesta.modelo_solicitado, "codex-cli")
        self.assertEqual(proveedor.llamadas, 1)
        nvidia.return_value.generar_estructurado.assert_not_called()

    def test_revisores_antigravity_conservan_imagenes_en_nvidia(self):
        rutas = rutas_revision("antigravity-cli")
        self.assertEqual(rutas["planificador"]["modelo"], "antigravity-cli")
        self.assertNotEqual(rutas["revisor_visual"]["modelo"], "antigravity-cli")
        with patch("aplicacion.calidad.suscripcion.modelos_cli_configurados", return_value={"antigravity-cli": "agy"}):
            with self.assertRaisesRegex(ValueError, "NVIDIA"):
                validar_revisores("antigravity-cli", False)
            validar_revisores("antigravity-cli", True)

    def test_cli_invalido_no_activa_fallback_nvidia(self):
        from aplicacion.calidad.nvidia import ErrorNvidia
        proveedor = MagicMock()
        proveedor.generar_estructurado.side_effect = ErrorNvidia("JSON inválido", "malformed_response")
        router = RouterModelos(proveedor, rutas_revision("codex-cli"))
        with self.assertRaises(ErrorNvidia):
            router.planificar("Bloque rectangular")
        proveedor.generar_estructurado.assert_called_once()

    def test_antigravity_rechaza_imagenes_en_headless(self):
        with patch("aplicacion.cli_suscripcion.ejecutable_cli", return_value="agy"):
            with self.assertRaisesRegex(ErrorCLI, "adjuntos"):
                ejecutar_cli("antigravity-cli", MENSAJES, [b"png"])

    def test_turno_incompleto_no_se_presenta_como_respuesta_exitosa(self):
        with patch("aplicacion.cli_suscripcion.ejecutable_cli", return_value="codex"), \
             patch("aplicacion.cli_suscripcion.subprocess.run", return_value=SimpleNamespace(
                 returncode=0, stdout="Logged in using ChatGPT", stderr="")), \
             patch("aplicacion.cli_suscripcion._ejecutar", return_value=json.dumps({
                 "type": "item.completed", "item": {"type": "agent_message", "text": "incompleto"}})):
            with self.assertRaisesRegex(ErrorCLI, "turno completo"):
                ejecutar_cli("codex-cli", MENSAJES)

    def test_socket_conecta_backend_y_cli_sin_claves_ni_red_publica(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = str(Path(directorio) / "cli.sock")
            with socketserver.ThreadingUnixStreamServer(ruta, ManejadorCLI) as servidor:
                servidor.turno = threading.Lock()
                hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
                hilo.start()
                try:
                    elegido = "codex-cli::gpt-6.1-sol"
                    catalogo = {"modelos": {elegido: {"nombre": "GPT-6.1-Sol", "modalidades": ["text", "image"],
                                                      "esfuerzos": {"high": "Alto"}}}}
                    with patch.dict(os.environ, {"CLI_PUENTE_SOCKET": ruta}), \
                         patch("aplicacion.puente_cli.consultar_catalogo_cli", return_value=catalogo), \
                         patch("aplicacion.puente_cli.ejecutar_cli", return_value={"texto": "Python"}) as cli:
                        self.assertEqual(solicitar_cli(elegido, MENSAJES), {"texto": "Python"})
                        cli.assert_called_once_with(elegido, MENSAJES, [])
                        cli.reset_mock()
                        self.assertEqual(solicitar_cli(elegido, MENSAJES, esfuerzo_razonamiento="high"), {"texto": "Python"})
                        cli.assert_called_once_with(elegido, MENSAJES, [], esfuerzo_razonamiento="high")
                    with httpx.Client(transport=httpx.HTTPTransport(uds=ruta)) as cliente:
                        servidor.turno.acquire()
                        try:
                            respuesta = cliente.post("http://localhost/generar", json={
                                "modelo": "codex-cli", "mensajes": MENSAJES})
                            self.assertEqual(respuesta.status_code, 409)
                        finally:
                            servidor.turno.release()
                        self.assertEqual(cliente.get("http://localhost/salud").status_code, 200)
                finally:
                    servidor.shutdown()
                    hilo.join()
