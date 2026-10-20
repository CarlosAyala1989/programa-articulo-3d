"""Validación aislada de la edición Ollama: sin descargas de pesos ni inferencias."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aplicacion.api import SolicitudGeneracion, aplicacion, consultar_opciones
from aplicacion.base_datos import BaseDeclarativa, Ejecucion
from aplicacion.configuracion import MODELOS_LOCALES
from aplicacion.generacion import procesar_ejecucion
from aplicacion.proveedor_deepseek import ErrorProveedor
from aplicacion.proveedores import solicitar_codigo, verificar_modelo_local
import preparar_modelos


ETIQUETAS = {codigo: f"modelo-{codigo}:prueba" for codigo in MODELOS_LOCALES}
ENTORNO = {"OLLAMA_" + codigo: etiqueta for codigo, etiqueta in ETIQUETAS.items()}
FIJADOS = {"estado": "completo", "modelos": {codigo: {
    "etiqueta": etiqueta, "digest": "a" * 64} for codigo, etiqueta in ETIQUETAS.items()}}


class EdicionLibreTests(unittest.TestCase):
    def test_cinco_modelos_y_solo_dos_modos_aunque_existan_claves(self):
        with patch.dict(os.environ, {**ENTORNO, "NVIDIA_API_KEY": "no-real", "DEEPSEEK_API_KEY": "no-real"}):
            opciones = consultar_opciones()
        self.assertEqual(set(opciones["modelos"]), {"L01", "L02", "L03", "L04", "L05"})
        self.assertEqual(set(opciones["modos"]), {"open-loop", "closed-loop"})
        self.assertNotIn("quality_loop", opciones)
        self.assertFalse(any("nvidia" in ruta.path or "suscripcion" in ruta.path for ruta in aplicacion.routes))

    def test_api_rechaza_quality_best_of_n_y_revisores(self):
        base = {"descripcion": "Bloque de 20 mm de lado", "motor": "cadquery", "modelo": "L01"}
        for extra in ({"modo": "quality-loop"}, {"best_of_n": True}, {"proveedor_revisores": "codex-cli"}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                SolicitudGeneracion(**base, **extra)

    def test_no_hay_ruta_de_inferencia_para_modelos_pagados(self):
        with patch("aplicacion.proveedores.httpx.Client") as cliente:
            for modelo in ("deepseek-flash", "codex-cli", "nvidia/modelo"):
                with self.subTest(modelo=modelo), self.assertRaises(ErrorProveedor):
                    solicitar_codigo(modelo, [{"role": "user", "content": "pieza"}])
        cliente.assert_not_called()

    def test_ollama_verifica_quant_y_digest_y_libera_memoria(self):
        tags = {"models": [{"name": ETIQUETAS["L04"], "digest": "a" * 64,
                            "details": {"quantization_level": "Q6_K"}}]}
        cliente = MagicMock()
        cliente.get.return_value = httpx.Response(200, json=tags, request=httpx.Request("GET", "http://prueba/api/tags"))
        cliente.post.return_value = httpx.Response(200, json={"model": ETIQUETAS["L04"],
            "message": {"content": "resultado = caja"}, "done_reason": "stop"},
            request=httpx.Request("POST", "http://prueba/api/chat"))
        with patch.dict(os.environ, ENTORNO), \
             patch("aplicacion.proveedores.Path.read_text", return_value=json.dumps(FIJADOS)), \
             patch("aplicacion.proveedores.httpx.Client") as fabrica:
            fabrica.return_value.__enter__.return_value = cliente
            respuesta = solicitar_codigo("L04", [{"role": "user", "content": "pieza"}])
            self.assertEqual(respuesta["proveedor"], "ollama")
            cuerpo = cliente.post.call_args.kwargs["json"]
            self.assertEqual(cuerpo["keep_alive"], 0)
            self.assertEqual(cuerpo["options"]["num_ctx"], 16384)
            tags["models"][0]["digest"] = "b" * 64
            cliente.get.return_value = httpx.Response(200, json=tags, request=httpx.Request("GET", "http://prueba/api/tags"))
            with self.assertRaisesRegex(ErrorProveedor, "identidad"):
                verificar_modelo_local("L04")

    def test_open_y_closed_respetan_uno_y_cinco_intentos_para_los_cinco(self):
        motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        BaseDeclarativa.metadata.create_all(motor)
        sesiones = sessionmaker(bind=motor, expire_on_commit=False)
        try:
            for modelo in MODELOS_LOCALES:
                for modo, limite in (("open-loop", 1), ("closed-loop", 5)):
                    identificador = modelo + modo
                    with sesiones() as sesion:
                        sesion.add(Ejecucion(identificador=identificador, descripcion="Bloque de 20 mm de lado",
                            motor="cadquery", modelo=modelo, modo=modo, maximo_intentos=limite,
                            estado="pendiente", mensaje="Prueba aislada"))
                        sesion.commit()
                    respuesta = {"texto": "esto no es python !!!", "modelo_informado": modelo,
                        "tokens_entrada": 10, "tokens_salida": 10, "finalizacion": "stop",
                        "proveedor": "ollama", "perfil": {"digest": "a" * 64}}
                    with patch("aplicacion.generacion.crear_sesion", sesiones), \
                         patch("aplicacion.generacion.verificar_modelo_local", return_value={"digest": "a" * 64}), \
                         patch("aplicacion.generacion.solicitar_codigo", return_value=respuesta) as proveedor:
                        procesar_ejecucion(identificador)
                    self.assertEqual(proveedor.call_count, limite)
                    with sesiones() as sesion:
                        ejecucion = sesion.get(Ejecucion, identificador)
                        self.assertEqual(ejecucion.numero_intentos, limite)
                        self.assertEqual(ejecucion.estado, "fallida")
                        if limite == 5:
                            self.assertTrue(ejecucion.intentos[-1].solicitud_modelo["retroalimentacion"])
        finally:
            motor.dispose()

    def test_worker_bloquea_quality_sin_cargar_modulos_de_revision(self):
        motor = create_engine("sqlite://", poolclass=StaticPool)
        BaseDeclarativa.metadata.create_all(motor)
        sesiones = sessionmaker(bind=motor, expire_on_commit=False)
        with sesiones() as sesion:
            sesion.add(Ejecucion(identificador="prohibido", descripcion="pieza de prueba", motor="cadquery",
                modelo="L01", modo="quality-loop", estado="pendiente", mensaje="Prueba"))
            sesion.commit()
        with patch("aplicacion.generacion.crear_sesion", sesiones):
            procesar_ejecucion("prohibido")
        with sesiones() as sesion:
            self.assertEqual(sesion.get(Ejecucion, "prohibido").estado, "bloqueada")
        motor.dispose()


class PreparacionModelosTests(unittest.TestCase):
    def test_importacion_fallida_reanuda_sin_redescargar_modelos_terminados(self):
        with tempfile.TemporaryDirectory() as temporal:
            base = Path(temporal)
            activos = base / "datos/modelos_libres"
            activos.mkdir(parents=True)
            descargas = base / "descargas"
            descargas.mkdir()
            perfiles = []
            for codigo, modelo in MODELOS_LOCALES.items():
                (activos / (codigo + ".template")).write_text("plantilla")
                (activos / (codigo + ".license")).write_text("licencia")
                (descargas / (codigo + ".gguf")).write_bytes(b"GGUF")
                perfiles.append({"codigo": codigo, "nombre": modelo["nombre"], "etiqueta": codigo,
                    "cuantizacion": modelo["cuantizacion"], "sha256": hashlib.sha256(b"GGUF").hexdigest(),
                    "bytes": 4, "url": "https://ejemplo.invalid/peso", "plantilla": codigo + ".template",
                    "licencia_archivo": codigo + ".license", "plantilla_sha256": hashlib.sha256(b"plantilla").hexdigest(),
                    "licencia_sha256": hashlib.sha256(b"licencia").hexdigest()})
            (activos / "modelos.json").write_text(json.dumps({"version": "prueba", "contexto": 16384, "modelos": perfiles}))
            modelos = {}
            fallar = True
            creados = []
            def crear(argumentos, **_):
                nonlocal fallar
                self.assertEqual(argumentos[0], "ollama")
                codigo = argumentos[2]
                if codigo == "L03" and fallar:
                    fallar = False
                    raise RuntimeError("Interrupción simulada")
                creados.append(codigo)
                modelos[codigo] = {"name": codigo, "digest": codigo * 10,
                    "details": {"quantization_level": MODELOS_LOCALES[codigo]["cuantizacion"]}}
            with patch("preparar_modelos.consultar", side_effect=lambda _: {"models": list(modelos.values())}), \
                 patch("preparar_modelos.subprocess.run", side_effect=crear):
                with self.assertRaisesRegex(RuntimeError, "simulada"):
                    preparar_modelos.preparar(base, descargas)
                self.assertEqual(json.loads((base / "modelos_instalados.json").read_text())["estado"], "descargando")
                preparar_modelos.preparar(base, descargas)
                preparar_modelos.preparar(base, descargas, verificar=True)
            self.assertEqual(creados, list(MODELOS_LOCALES))
            self.assertEqual(len(json.loads((base / "modelos_instalados.json").read_text())["modelos"]), 5)

    def test_los_cinco_artifactos_tienen_hashes_y_plantillas_fijadas(self):
        base = Path(preparar_modelos.__file__).parent / "datos/modelos_libres"
        manifiesto = json.loads((base / "modelos.json").read_text())
        self.assertEqual([m["codigo"] for m in manifiesto["modelos"]], list(MODELOS_LOCALES))
        for modelo in manifiesto["modelos"]:
            self.assertEqual(modelo["cuantizacion"], MODELOS_LOCALES[modelo["codigo"]]["cuantizacion"])
            self.assertEqual(len(modelo["sha256"]), 64)
            self.assertEqual(preparar_modelos.huella(base / modelo["plantilla"]), modelo["plantilla_sha256"])
            self.assertEqual(preparar_modelos.huella(base / modelo["licencia_archivo"]), modelo["licencia_sha256"])


if __name__ == "__main__":
    unittest.main()
