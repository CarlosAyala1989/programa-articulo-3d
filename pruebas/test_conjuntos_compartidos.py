"""Los 45 prompts compartidos conviven con los 60 históricos sin consumir proveedores."""

import hashlib
import json
import unittest
from collections import Counter
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aplicacion.api import aplicacion, preparar_base_datos
from aplicacion.base_datos import BaseDeclarativa, CasoDiseno, Ejecucion, VersionConjunto
from aplicacion.conjuntos import RUTA_CONJUNTO_45, validar_documento


class ConjuntosCompartidosTests(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.motor.dispose)
        BaseDeclarativa.metadata.create_all(self.motor)
        self.sesiones = sessionmaker(bind=self.motor, expire_on_commit=False)
        for modulo in ("api", "conjuntos", "campanas"):
            parche = patch(f"aplicacion.{modulo}.crear_sesion", self.sesiones)
            parche.start()
            self.addCleanup(parche.stop)
        tablas = patch("aplicacion.api.crear_tablas")
        tablas.start()
        self.addCleanup(tablas.stop)
        preparar_base_datos()
        self.cliente = TestClient(aplicacion)
        self.addCleanup(self.cliente.close)
        self.conjuntos = {c["nombre"]: c for c in self.cliente.get("/api/conjuntos").json()}

    def test_documento_45_conserva_textos_codigos_y_distribucion_originales(self):
        self.assertEqual(hashlib.sha256(RUTA_CONJUNTO_45.read_bytes()).hexdigest(),
                         "6c0ad0f44cdca1c2ab2d8befd582acc6f1cf27634e5b08707d7f76684e78b9b0")
        documento = validar_documento(json.loads(RUTA_CONJUNTO_45.read_text(encoding="utf-8")))
        self.assertEqual(Counter(c["nivel"] for c in documento["casos"]),
                         {"basico": 15, "intermedio": 15, "complejo": 15})
        self.assertEqual({c["codigo"] for c in documento["casos"]},
                         {f"{prefijo}{numero:02d}" for prefijo in "BMC" for numero in range(1, 16)})

    def test_protocolo_45_rechaza_conjunto_incompleto(self):
        documento = json.loads(RUTA_CONJUNTO_45.read_text(encoding="utf-8"))
        documento["casos"].pop()
        with self.assertRaisesRegex(ValueError, "exactamente 45"):
            validar_documento(documento)

    def test_reinicio_conserva_identidades_y_conjunto_historico(self):
        preparar_base_datos()
        despues = {c["nombre"]: c for c in self.cliente.get("/api/conjuntos").json()}
        self.assertEqual(despues, self.conjuntos)
        self.assertEqual(despues["CAD-LLMIA-60"]["total"], 60)
        self.assertEqual(despues["CAD-LLMIA-45"]["total"], 45)
        self.assertTrue(all(c["estado"] == "congelado" for c in despues.values()))
        with self.sesiones() as sesion:
            self.assertEqual(len(list(sesion.scalars(select(CasoDiseno)))), 105)

    def test_todos_los_prompts_45_se_guardan_con_sus_textos_y_limites_por_modo(self):
        identificador = self.conjuntos["CAD-LLMIA-45"]["identificador"]
        casos = self.cliente.get(f"/api/conjuntos/{identificador}").json()["casos"]
        solicitud = {"nombre": "Piloto de los 45 prompts", "conjunto_identificador": identificador,
                     "modelos": ["deepseek-flash"], "motores": ["cadquery"],
                     "modos": ["open-loop", "closed-loop"],
                     "codigos_caso": [c["codigo"] for c in casos]}
        vista = self.cliente.post("/api/campanas/previsualizar", json=solicitud)
        self.assertEqual(vista.status_code, 200, vista.text)
        self.assertEqual(vista.json()["ejecuciones"], 90)
        self.assertEqual(vista.json()["maximo_generaciones"], 270)
        respuesta = self.cliente.post("/api/campanas", json=solicitud)
        self.assertEqual(respuesta.status_code, 201, respuesta.text)
        datos = respuesta.json()
        self.assertEqual(datos["configuracion"]["codigos_caso"], sorted(c["codigo"] for c in casos))
        por_identificador = {c["identificador"]: c for c in casos}
        with self.sesiones() as sesion:
            ejecuciones = list(sesion.scalars(select(Ejecucion).where(
                Ejecucion.campana_identificador == datos["identificador"])))
            self.assertEqual(len(ejecuciones), 90)
            for ejecucion in ejecuciones:
                self.assertEqual(ejecucion.descripcion, por_identificador[ejecucion.caso_identificador]["descripcion"])
                self.assertEqual(ejecucion.maximo_intentos, 1 if ejecucion.modo == "open-loop" else 5)

    def test_casos_con_mismo_codigo_se_mantienen_en_sus_conjuntos(self):
        casos = []
        for nombre in ("CAD-LLMIA-45", "CAD-LLMIA-60"):
            identificador = self.conjuntos[nombre]["identificador"]
            documento = self.cliente.get(f"/api/conjuntos/{identificador}").json()
            casos.append(next(c for c in documento["casos"] if c["codigo"] == "B01"))
        self.assertNotEqual(casos[0]["identificador"], casos[1]["identificador"])
        self.assertNotEqual(casos[0]["descripcion"], casos[1]["descripcion"])

    def test_campana_principal_sigue_exigiendo_los_60_casos(self):
        solicitud = {"nombre": "Principal histórica", "tipo": "principal",
                     "modelos": ["deepseek-flash"], "motores": ["cadquery", "build123d", "freecad"],
                     "modos": ["open-loop", "closed-loop"]}
        for nombre, estado in (("CAD-LLMIA-45", 422), ("CAD-LLMIA-60", 200)):
            with self.subTest(conjunto=nombre):
                solicitud["conjunto_identificador"] = self.conjuntos[nombre]["identificador"]
                respuesta = self.cliente.post("/api/campanas/previsualizar", json=solicitud)
                self.assertEqual(respuesta.status_code, estado, respuesta.text)


if __name__ == "__main__":
    unittest.main()
