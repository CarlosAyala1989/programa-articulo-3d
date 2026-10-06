"""El esfuerzo elegido llega a HTTP, queda registrado y sobrevive a los bucles."""

import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aplicacion.api import aplicacion
from aplicacion.base_datos import (
    BaseDeclarativa, Campana, CasoDiseno, CondicionExperimental, Ejecucion,
    IntentoGeneracion, VersionConjunto,
)
from aplicacion.configuracion import MAXIMO_TOKENS_DEEPSEEK, VERSION_PLANTILLA
from aplicacion.costos import costo_maximo_planificacion
from aplicacion.generacion import procesar_ejecucion
from aplicacion.proveedores import solicitar_codigo


class EsfuerzoDeepSeek(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        BaseDeclarativa.metadata.create_all(self.motor)
        self.sesiones = sessionmaker(bind=self.motor, expire_on_commit=False)
        self.cliente = TestClient(aplicacion)

    def tearDown(self):
        self.cliente.close()
        self.motor.dispose()

    def test_los_tres_niveles_se_envian_a_ambos_modelos(self):
        capturados = []

        def responder(peticion):
            capturados.append(json.loads(peticion.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": "resultado = 1"}, "finish_reason": "stop"}]})

        cliente_real = httpx.Client
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "clave-simulada"}), patch(
            "aplicacion.proveedor_deepseek.httpx.Client",
            side_effect=lambda **opciones: cliente_real(transport=httpx.MockTransport(responder), **opciones),
        ):
            for modelo in ["deepseek-flash", "deepseek-v4-pro"]:
                for esfuerzo in ["low", "high", "max"]:
                    with self.subTest(modelo=modelo, esfuerzo=esfuerzo):
                        respuesta = solicitar_codigo(modelo, [{"role": "user", "content": "Pieza curva"}], esfuerzo)
                        self.assertEqual(capturados[-1]["model"], modelo)
                        self.assertEqual(capturados[-1]["reasoning_effort"], esfuerzo)
                        self.assertEqual(capturados[-1]["thinking"], {"type": "enabled"})
                        self.assertEqual(capturados[-1]["max_tokens"], 393216)
                        self.assertEqual(respuesta["perfil"]["reasoning_effort"], esfuerzo)
                        self.assertEqual(respuesta["perfil"]["max_tokens"], 393216)

    def test_campana_anterior_mantiene_limite_congelado(self):
        with self.sesiones() as sesion:
            sesion.add(VersionConjunto(identificador="conjunto-anterior", nombre="Prueba", version="1",
                finalidad="evaluacion", estado="congelado", huella_sha256="a" * 64))
            sesion.add(Campana(identificador="campana-anterior", conjunto_identificador="conjunto-anterior",
                nombre="Campaña con límite histórico", semilla=1,
                presupuesto_usd=(costo_maximo_planificacion("deepseek-flash", 131072)
                                 + costo_maximo_planificacion("deepseek-flash")) / 2,
                configuracion={
                    "plantilla": VERSION_PLANTILLA,
                    "perfiles_generacion": {"deepseek-flash": {"max_tokens": 131072}},
                }))
            sesion.add(Ejecucion(identificador="ejecucion-anterior", descripcion="Pieza curva",
                motor="cadquery", modelo="deepseek-flash", modo="open-loop",
                campana_identificador="campana-anterior"))
            sesion.commit()
        respuesta = {"texto": "!", "modelo_informado": "deepseek-flash",
                    "tokens_entrada": 1, "tokens_salida": 1, "finalizacion": "stop",
                    "perfil": {"max_tokens": 131072}}
        with patch("aplicacion.generacion.crear_sesion", self.sesiones), patch(
            "aplicacion.generacion.solicitar_codigo", return_value=respuesta
        ) as proveedor:
            procesar_ejecucion("ejecucion-anterior")
        self.assertEqual(proveedor.call_args.args[3], 131072)
        with self.sesiones() as sesion:
            intento = sesion.get(Ejecucion, "ejecucion-anterior").intentos[0]
            self.assertEqual(intento.solicitud_modelo["perfil"]["max_tokens"], 131072)
        self.assertEqual(MAXIMO_TOKENS_DEEPSEEK, 393216)
        self.assertLess(costo_maximo_planificacion("deepseek-flash", 131072),
                        costo_maximo_planificacion("deepseek-flash"))

    def test_campana_v5_no_se_reinterpreta_bajo_plantilla_v6(self):
        with self.sesiones() as sesion:
            sesion.add(VersionConjunto(identificador="conjunto-v5", nombre="Prueba v5", version="1",
                finalidad="evaluacion", estado="congelado", huella_sha256="b" * 64))
            sesion.add(Campana(identificador="campana-v5", conjunto_identificador="conjunto-v5",
                nombre="Campaña histórica", semilla=1, presupuesto_usd=None,
                configuracion={"plantilla": "v5-formas-organicas-avanzadas"}))
            sesion.add(Ejecucion(identificador="ejecucion-v5", descripcion="Bloque de prueba",
                motor="cadquery", modelo="deepseek-flash", modo="open-loop",
                campana_identificador="campana-v5", estado="pendiente"))
            sesion.commit()
        with patch("aplicacion.generacion.crear_sesion", self.sesiones), patch(
            "aplicacion.generacion.solicitar_codigo"
        ) as proveedor:
            procesar_ejecucion("ejecucion-v5")
        proveedor.assert_not_called()
        with self.sesiones() as sesion:
            campana = sesion.get(Campana, "campana-v5")
            ejecucion = sesion.get(Ejecucion, "ejecucion-v5")
            self.assertEqual(campana.estado, "bloqueada")
            self.assertEqual(ejecucion.estado, "bloqueada")
            self.assertIn("nueva", campana.mensaje)

    def test_respuesta_extensa_se_guarda_completa(self):
        with self.sesiones() as sesion:
            sesion.add(Ejecucion(identificador="respuesta-extensa", descripcion="Pieza curva",
                motor="cadquery", modelo="deepseek-flash", modo="open-loop"))
            sesion.commit()
        texto_extenso = "!" * 600001
        respuesta = {"texto": texto_extenso, "modelo_informado": "deepseek-flash",
                    "tokens_entrada": 1, "tokens_salida": 1, "finalizacion": "stop",
                    "perfil": {"max_tokens": 393216}}
        with patch("aplicacion.generacion.crear_sesion", self.sesiones), patch(
            "aplicacion.generacion.solicitar_codigo", return_value=respuesta
        ):
            procesar_ejecucion("respuesta-extensa")
        with self.sesiones() as sesion:
            intento = sesion.get(Ejecucion, "respuesta-extensa").intentos[0]
            self.assertEqual(intento.respuesta_modelo, texto_extenso)

    def test_api_persiste_seleccion_y_conserva_compatibilidad(self):
        with patch("aplicacion.api.crear_sesion", self.sesiones), patch("aplicacion.api.tarea_generacion.delay") as cola:
            for esfuerzo in ["low", "high", "max", None]:
                cuerpo = {"descripcion": "Cubo de 20 mm de lado", "motor": "cadquery", "modelo": "deepseek-flash"}
                if esfuerzo is not None:
                    cuerpo["esfuerzo_razonamiento"] = esfuerzo
                respuesta = self.cliente.post("/api/ejecuciones", json=cuerpo)
                self.assertEqual(respuesta.status_code, 202, respuesta.text)
                identificador = respuesta.json()["identificador"]
                datos = self.cliente.get(f"/api/ejecuciones/{identificador}").json()
                self.assertEqual(datos["esfuerzo_razonamiento"], esfuerzo or "max")
                with self.sesiones() as sesion:
                    self.assertEqual(sesion.get(Ejecucion, identificador).esfuerzo_razonamiento, esfuerzo or "max")
            self.assertEqual(cola.call_count, 4)

    def test_api_rechaza_esfuerzo_invalido_y_esfuerzo_local(self):
        with patch.dict(os.environ, {"OLLAMA_L01": "modelo-prueba"}), patch("aplicacion.api.tarea_generacion.delay") as cola:
            for modelo, esfuerzo in [("deepseek-v4-pro", "medium"), ("L01", "low"), ("", "max")]:
                respuesta = self.cliente.post("/api/ejecuciones", json={
                    "descripcion": "Cubo de 20 mm de lado", "motor": "cadquery",
                    "modelo": modelo, "esfuerzo_razonamiento": esfuerzo,
                })
                self.assertEqual(respuesta.status_code, 422)
            cola.assert_not_called()

    def test_cinco_intentos_conservan_el_esfuerzo_y_su_traza(self):
        with self.sesiones() as sesion:
            sesion.add(Ejecucion(identificador="bucle", descripcion="Pieza con curvas complejas",
                motor="cadquery", modelo="deepseek-v4-pro", esfuerzo_razonamiento="low", modo="closed-loop"))
            sesion.commit()
        respuesta = {"texto": "esto no es python !!!", "modelo_informado": "deepseek-v4-pro",
                     "tokens_entrada": 1, "tokens_salida": 1, "finalizacion": "stop",
                     "proveedor": "prueba", "perfil": {"reasoning_effort": "low"}}
        with patch("aplicacion.generacion.crear_sesion", self.sesiones), patch(
            "aplicacion.generacion.solicitar_codigo", return_value=respuesta
        ) as proveedor:
            procesar_ejecucion("bucle")
        self.assertEqual(proveedor.call_count, 5)
        self.assertTrue(all(llamada.args[2] == "low" for llamada in proveedor.call_args_list))
        with self.sesiones() as sesion:
            ejecucion = sesion.get(Ejecucion, "bucle")
            self.assertEqual(ejecucion.estado, "fallida")
            self.assertTrue(all(intento.solicitud_modelo["perfil"]["reasoning_effort"] == "low" for intento in ejecucion.intentos))

    def test_reanudacion_recupera_el_esfuerzo_historico(self):
        with self.sesiones() as sesion:
            sesion.add(Ejecucion(identificador="antigua", descripcion="Pieza curva de prueba",
                motor="cadquery", modelo="deepseek-flash", estado="pausada", modo="closed-loop"))
            sesion.add(IntentoGeneracion(ejecucion_identificador="antigua", numero=1, estado="invalido",
                fase_error="sintaxis", diagnostico="SyntaxError", codigo="!",
                solicitud_modelo={"perfil": {"reasoning_effort": "high"}}))
            sesion.commit()
        respuesta = {"texto": "!", "modelo_informado": "deepseek-flash", "tokens_entrada": 1,
                     "tokens_salida": 1, "finalizacion": "stop", "perfil": {"reasoning_effort": "high"}}
        with patch("aplicacion.generacion.crear_sesion", self.sesiones), patch(
            "aplicacion.generacion.solicitar_codigo", return_value=respuesta
        ) as proveedor:
            procesar_ejecucion("antigua")
        self.assertEqual(proveedor.call_count, 4)
        self.assertTrue(all(llamada.args[2] == "high" for llamada in proveedor.call_args_list))
        with self.sesiones() as sesion:
            self.assertEqual(sesion.get(Ejecucion, "antigua").esfuerzo_razonamiento, "high")

    def test_campana_congela_esfuerzo_en_condiciones_y_ejecuciones(self):
        with self.sesiones() as sesion:
            sesion.add(VersionConjunto(identificador="conjunto", nombre="Prueba", version="1",
                finalidad="evaluacion", estado="congelado", huella_sha256="a" * 64))
            sesion.add(CasoDiseno(identificador="caso", conjunto_identificador="conjunto", codigo="B01",
                nivel="basico", familia="cubo", fundamento="Prueba", descripcion="Cubo de 20 mm de lado"))
            sesion.commit()
        with patch("aplicacion.api.crear_sesion", self.sesiones), patch("aplicacion.campanas.crear_sesion", self.sesiones), \
             patch("aplicacion.metricas.crear_sesion", self.sesiones):
            respuesta = self.cliente.post("/api/campanas", json={
                "nombre": "Campaña alto", "conjunto_identificador": "conjunto",
                "modelos": ["deepseek-flash", "deepseek-v4-pro"], "motores": ["cadquery"],
                "modos": ["open-loop", "closed-loop"], "codigos_caso": ["B01"], "esfuerzo_razonamiento": "high",
            })
            self.assertEqual(respuesta.status_code, 201, respuesta.text)
            datos = respuesta.json()
            self.assertEqual(datos["configuracion"]["esfuerzo_razonamiento"], "high")
            self.assertTrue(all(perfil["reasoning_effort"] == "high" for perfil in datos["configuracion"]["perfiles_generacion"].values()))
            with self.sesiones() as sesion:
                ejecuciones = list(sesion.scalars(select(Ejecucion)))
                condiciones = list(sesion.scalars(select(CondicionExperimental)))
                self.assertEqual(len(ejecuciones), 4)
                self.assertTrue(all(ejecucion.esfuerzo_razonamiento == "high" for ejecucion in ejecuciones))
                self.assertTrue(all(condicion.configuracion["reasoning_effort"] == "high" for condicion in condiciones))
            identificador = datos["identificador"]
            metricas = self.cliente.get(f"/api/campanas/{identificador}/metricas").json()
            self.assertTrue(all(fila["esfuerzo_razonamiento"] == "high" for fila in metricas["filas"]))
            csv = self.cliente.get(f"/api/campanas/{identificador}/metricas.csv")
            self.assertEqual(csv.status_code, 200)
            self.assertIn("modelo,esfuerzo_razonamiento,", csv.text)
            self.assertIn("deepseek-flash,high,", csv.text)
            exportacion = self.cliente.get(f"/api/campanas/{identificador}/datos.json")
            self.assertEqual(exportacion.status_code, 200, exportacion.text)
            self.assertIn('"esfuerzo_razonamiento": "high"', exportacion.text)


if __name__ == "__main__":
    unittest.main()
