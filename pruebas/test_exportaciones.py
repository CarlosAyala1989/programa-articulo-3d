"""Exportaciones parciales y finales sin inferencias ni modificaciones de campañas."""

import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aplicacion.api import aplicacion
from aplicacion.base_datos import (
    ArchivoGenerado, BaseDeclarativa, Campana, CasoDiseno, Ejecucion, IntentoGeneracion, VersionConjunto,
)
from aplicacion.resultados import convertir_csv, paquete_resultados


class ExportacionesDigitales(unittest.TestCase):
    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.raiz = Path(self.directorio.name)
        self.motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        BaseDeclarativa.metadata.create_all(self.motor)
        self.sesiones = sessionmaker(bind=self.motor, expire_on_commit=False)
        self.pieza = b"STEP-de-prueba-completo\n"
        carpeta = self.raiz / "ejecuciones" / "terminada"
        carpeta.mkdir(parents=True)
        (carpeta / "pieza.step").write_bytes(self.pieza)
        with self.sesiones() as sesion:
            sesion.add(VersionConjunto(identificador="conjunto", nombre="Exportación de prueba", version="1",
                finalidad="desarrollo", estado="congelado", huella_sha256="a" * 64))
            sesion.add(CasoDiseno(identificador="caso", conjunto_identificador="conjunto", codigo="B01",
                nivel="basico", familia="cubo", fundamento="Exportación", descripcion="Cubo de veinte milímetros"))
            sesion.add(Campana(identificador="campana", conjunto_identificador="conjunto", nombre="Campaña parcial",
                semilla=1, estado="en_curso", total_ejecuciones=3))
            for identificador, estado, orden in (("bloqueada", "bloqueada", 1), ("activa", "generando", 2), ("terminada", "completada", 3)):
                sesion.add(Ejecucion(identificador=identificador, campana_identificador="campana", caso_identificador="caso",
                    descripcion="Cubo de veinte milímetros", motor="cadquery", modelo="deepseek-flash",
                    modo="closed-loop", estado=estado, orden_campana=orden,
                    numero_intentos=2 if identificador == "terminada" else 1,
                    primer_exito_ejecucion=1 if identificador == "terminada" else None,
                    primer_exito_cad=2 if identificador == "terminada" else None,
                    primer_exito_exportacion=2 if identificador == "terminada" else None))
            sesion.add(IntentoGeneracion(ejecucion_identificador="activa", numero=1, estado="consultando_ia",
                solicitud_modelo={"mensajes": [{"role": "user", "content": "Cubo completo"}]}))
            sesion.add(IntentoGeneracion(ejecucion_identificador="terminada", numero=1, estado="invalido",
                codigo="resultado = 1", respuesta_modelo="Respuesta íntegra del primer intento", sintaxis_valida=True,
                solicitud_modelo={"perfil": {"max_tokens": 393216, "reasoning_effort": "max"}}))
            sesion.add(IntentoGeneracion(ejecucion_identificador="terminada", numero=2, estado="correcto",
                codigo="resultado = pieza", respuesta_modelo="Respuesta final íntegra"))
            sesion.add(ArchivoGenerado(ejecucion_identificador="terminada", nombre="pieza.step", rol="nativo",
                ruta=str(carpeta / "pieza.step"), tamano_bytes=len(self.pieza), sha256=hashlib.sha256(self.pieza).hexdigest()))
            sesion.commit()
        self.parches = ExitStack()
        for modulo in ("api", "campanas", "metricas", "conjuntos"):
            self.parches.enter_context(patch(f"aplicacion.{modulo}.crear_sesion", self.sesiones))
        self.parches.enter_context(patch("aplicacion.api.DIRECTORIO_ARTEFACTOS", str(self.raiz)))
        self.cliente = TestClient(aplicacion)

    def tearDown(self):
        self.cliente.close()
        self.parches.close()
        self.motor.dispose()
        self.directorio.cleanup()

    def test_seguimiento_prioriza_generacion_y_muestra_siguiente_en_cola(self):
        self.assertEqual(self.cliente.get("/api/campanas/campana").json()["ejecucion_actual"]["identificador"], "activa")
        with self.sesiones() as sesion:
            sesion.get(Ejecucion, "activa").estado = "pendiente"
            sesion.commit()
        actual = self.cliente.get("/api/campanas/campana").json()["ejecucion_actual"]
        self.assertEqual(actual["estado"], "pendiente")
        self.assertEqual(actual["caso"], "B01")

    def test_figuras_png_svg_pdf_y_validacion_de_filtros(self):
        for tipo, texto in (("codigo", "Compile Rate"), ("cad", "Éxito CAD exportable")):
            for formato, mime in (("svg", "image/svg+xml"), ("png", "image/png"), ("pdf", "application/pdf")):
                with self.subTest(tipo=tipo, formato=formato):
                    respuesta = self.cliente.get(f"/api/campanas/campana/figura.{formato}?tipo={tipo}&nivel=basico")
                    self.assertEqual(respuesta.status_code, 200, respuesta.text[:100])
                    self.assertTrue(respuesta.headers["content-type"].startswith(mime))
                    if formato == "svg":
                        self.assertEqual(ElementTree.fromstring(respuesta.content).tag, "{http://www.w3.org/2000/svg}svg")
                        self.assertIn(texto, respuesta.text)
                        self.assertIn("Provisional", respuesta.text)
                    elif formato == "png":
                        self.assertTrue(respuesta.content.startswith(b"\x89PNG\r\n\x1a\n"))
                    else:
                        self.assertTrue(respuesta.content.startswith(b"%PDF-"))
        for sufijo in ("figura.exe", "figura.svg?nivel=inexistente", "figura.png?tipo=otro"):
            self.assertEqual(self.cliente.get(f"/api/campanas/campana/{sufijo}").status_code, 422)
        self.assertEqual(self.cliente.get("/api/campanas/no-existe/figura.svg").status_code, 404)

    def test_tabla_distingue_exito_codigo_cad_y_denominadores(self):
        respuesta = self.cliente.get("/api/campanas/campana/tabla-digital.csv")
        filas = list(csv.DictReader(io.StringIO(respuesta.text)))
        fila = filas[0]
        self.assertEqual(fila["n_evaluable"], "1")
        self.assertEqual(fila["n_planificado"], "3")
        self.assertEqual(fila["ir_codigo_pct"], "0.0")
        self.assertEqual(fila["referencia_iou_brep_medio"], "")
        literatura = [f for f in filas if f["origen"] == "literatura"]
        self.assertTrue(literatura)
        self.assertTrue(all(f["comparacion_directa"] == "False" and f["fuente"] for f in literatura))
        self.assertTrue(all(f["compile_rate_pct"] == "" for f in literatura))
        with self.sesiones() as sesion:
            sesion.get(Ejecucion, "terminada").estado = "bloqueada"
            sesion.commit()
        fila = list(csv.DictReader(io.StringIO(self.cliente.get("/api/campanas/campana/tabla-digital.csv").text)))[0]
        self.assertEqual(fila["ir_codigo_pct"], "")
        self.assertEqual(fila["ir_cad_pct"], "")
        self.assertEqual(self.cliente.get("/api/campanas/campana/figura.svg?nivel=complejo").status_code, 200)

    def test_zip_campana_incluye_trazas_cad_y_huellas_y_limpia_temporal(self):
        crear_temporal = tempfile.mkstemp
        temporales = []

        def crear(**opciones):
            descriptor, ruta = crear_temporal(dir=self.raiz, **opciones)
            temporales.append(Path(ruta))
            return descriptor, ruta

        with patch("aplicacion.api.tempfile.mkstemp", side_effect=crear):
            respuesta = self.cliente.get("/api/campanas/campana/entregables.zip")
        self.assertEqual(respuesta.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as paquete:
            self.assertIsNone(paquete.testzip())
            datos = json.loads(paquete.read("datos_y_trazas.json"))
            self.assertTrue(datos["provisional"])
            self.assertEqual(datos["conjunto"]["casos"][0]["codigo"], "B01")
            self.assertEqual(paquete.read("ejecuciones/terminada/archivos/pieza.step"), self.pieza)
            self.assertEqual(paquete.read("ejecuciones/terminada/intento-1/respuesta.txt").decode(), "Respuesta íntegra del primer intento")
            for archivo in ("figuras/codigo-todos.png", "figuras/cad-basico.svg", "figuras/codigo-todos.pdf", "intentos.csv", "geometria.csv"):
                self.assertIn(archivo, paquete.namelist())
            for registro in json.loads(paquete.read("huellas_archivos.json")):
                self.assertEqual(hashlib.sha256(paquete.read(registro["archivo"])).hexdigest(), registro["sha256"])
        self.assertTrue(temporales)
        self.assertTrue(all(not ruta.exists() for ruta in temporales))

    def test_exportacion_individual_disponible_durante_generacion(self):
        datos = self.cliente.get("/api/ejecuciones/activa/datos.json").json()
        self.assertTrue(datos["provisional"])
        respuesta = self.cliente.get("/api/ejecuciones/activa/entregables.zip")
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as paquete:
            self.assertIn("ejecuciones/activa/intento-1/solicitud.json", paquete.namelist())
        datos = self.cliente.get("/api/ejecuciones/terminada/datos.json").json()
        self.assertFalse(datos["provisional"])
        self.assertEqual(datos["ejecuciones"][0]["intentos"][1]["respuesta_modelo"], "Respuesta final íntegra")
        for tipo in ("ejecuciones", "intentos", "geometria"):
            self.assertEqual(self.cliente.get(f"/api/campanas/campana/registros/{tipo}.csv").status_code, 200)
        self.assertEqual(self.cliente.get("/api/ejecuciones/activa/intentos.csv").status_code, 200)

    def test_zip_disponible_desde_la_cola_sin_intentos_ni_archivos(self):
        with self.sesiones() as sesion:
            sesion.execute(delete(IntentoGeneracion).where(IntentoGeneracion.ejecucion_identificador == "activa"))
            sesion.get(Ejecucion, "activa").estado = "pendiente"
            sesion.commit()
        respuesta = self.cliente.get("/api/ejecuciones/activa/entregables.zip")
        self.assertEqual(respuesta.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as paquete:
            datos = json.loads(paquete.read("datos_y_trazas.json"))
            self.assertTrue(datos["provisional"])
            self.assertEqual(datos["ejecuciones"][0]["intentos"], [])
            self.assertEqual(datos["ejecuciones"][0]["archivos"], [])
            self.assertEqual(json.loads(paquete.read("archivos_ausentes.json")), [])

    def test_campanas_historicas_exportan_sin_migrar_protocolo_ni_datos(self):
        configuracion = {"plantilla": "v1-historica", "perfiles_generacion": {
            "deepseek-flash": {"max_tokens": 8000}}}
        with self.sesiones() as sesion:
            campana = sesion.get(Campana, "campana")
            campana.configuracion = configuracion
            campana.estado = "completada"
            ejecucion = sesion.get(Ejecucion, "activa")
            ejecucion.estado = "fallida"
            ejecucion.esfuerzo_razonamiento = None
            ejecucion.intentos[0].solicitud_modelo = None
            sesion.commit()
            fecha = campana.fecha_creacion
        for ruta in ("metricas.csv", "datos.json", "tabla-digital.csv", "figura.png", "entregables.zip"):
            with self.subTest(ruta=ruta):
                respuesta = self.cliente.get(f"/api/campanas/campana/{ruta}")
                self.assertEqual(respuesta.status_code, 200)
        with self.sesiones() as sesion:
            campana = sesion.get(Campana, "campana")
            self.assertEqual(campana.configuracion, configuracion)
            self.assertEqual(campana.fecha_creacion, fecha)
            self.assertEqual(campana.estado, "completada")
            self.assertEqual(sesion.get(Ejecucion, "activa").estado, "fallida")
            self.assertIsNone(sesion.get(Ejecucion, "activa").intentos[0].solicitud_modelo)

    def test_zip_no_incluye_rutas_externas_symlinks_ni_archivos_alterados(self):
        datos = self.cliente.get("/api/ejecuciones/terminada/datos.json").json()
        ejecucion = datos["ejecuciones"][0]
        carpeta = self.raiz / "ejecuciones" / "terminada"
        (self.raiz / "externo.txt").write_text("No incluir")
        (carpeta / "enlace.txt").symlink_to(self.raiz / "externo.txt")
        ejecucion["archivos"] += [{"nombre": nombre, "sha256": "0" * 64} for nombre in (
            "../../externo.txt", "enlace.txt", "pieza-alterada.step")]
        (carpeta / "pieza-alterada.step").write_text("alterado")
        destino = self.raiz / "resultado.zip"
        paquete_resultados(datos, str(self.raiz), destino)
        with zipfile.ZipFile(destino) as paquete:
            incidencias = json.loads(paquete.read("archivos_ausentes.json"))
            self.assertEqual(len(incidencias), 3)
            self.assertFalse(any("enlace.txt" in nombre or "externo.txt" in nombre for nombre in paquete.namelist()))

    def test_csv_neutraliza_formulas_sin_cambiar_valores_numericos(self):
        datos = list(csv.DictReader(io.StringIO(convertir_csv([{"texto": "=1+1", "numero": -1.25}]))))[0]
        self.assertEqual(datos["texto"], "'=1+1")
        self.assertEqual(datos["numero"], "-1.25")


if __name__ == "__main__":
    unittest.main()
