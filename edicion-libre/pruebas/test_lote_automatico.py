"""Lote de 1.350 celdas y recuperación local: proveedores y CAD simulados."""

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
import httpx
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aplicacion.base_datos import BaseDeclarativa, Campana, Ejecucion, IntentoGeneracion
from aplicacion.automatico import asegurar_lote, procesar_paso
from aplicacion.archivado import carpeta_ejecucion
from aplicacion.conjuntos import validar_documento
from aplicacion.generacion import procesar_ejecucion
from aplicacion.iniciar_trabajador import preparar_reinicio
from aplicacion.metricas import calcular_metricas_campana
from aplicacion.proveedor_deepseek import ErrorProveedor
from aplicacion.resultados import csv_tabla_digital, figura_compilacion, paquete_resultados
import aplicacion.automatico
import aplicacion.conjuntos


class LoteAutomaticoTests(unittest.TestCase):
    def setUp(self):
        self.motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        BaseDeclarativa.metadata.create_all(self.motor)
        self.sesiones = sessionmaker(bind=self.motor, expire_on_commit=False)
        self.contexto = ExitStack()
        self.temporal = self.contexto.enter_context(tempfile.TemporaryDirectory())
        self.contexto.enter_context(patch.dict(os.environ, {**{f"OLLAMA_L0{n}": f"modelo{n}:prueba" for n in range(1,6)}, "CIEL_AUTOMATICO": "0"}))
        for modulo in ("automatico", "archivado", "campanas", "conjuntos", "generacion", "metricas", "iniciar_trabajador", "api", "analisis"):
            self.contexto.enter_context(patch(f"aplicacion.{modulo}.crear_sesion", self.sesiones))
        self.contexto.enter_context(patch("aplicacion.iniciar_trabajador.crear_tablas"))
        self.contexto.enter_context(patch("aplicacion.archivado.DIRECTORIO_RESULTADOS", self.temporal))
        self.contexto.enter_context(patch("aplicacion.generacion.DIRECTORIO_ARTEFACTOS", self.temporal))
        self.contexto.enter_context(patch("aplicacion.generacion.verificar_modelo_local", return_value={"digest": "a" * 64}))
        self.identificador = asegurar_lote()

    def tearDown(self):
        self.contexto.close()
        self.motor.dispose()

    def activar(self):
        with self.sesiones() as sesion:
            campana = sesion.get(Campana, self.identificador)
            campana.estado = "en_curso"
            sesion.commit()

    def primera(self):
        with self.sesiones() as sesion:
            return sesion.scalar(select(Ejecucion).where(Ejecucion.campana_identificador == self.identificador).order_by(Ejecucion.orden_campana))

    def test_matriz_1350_unica_y_45_por_celda_sin_duplicar_al_reabrir(self):
        self.assertEqual(asegurar_lote(), self.identificador)
        with self.sesiones() as sesion:
            campana = sesion.get(Campana, self.identificador)
            filas = list(sesion.scalars(select(Ejecucion).order_by(Ejecucion.orden_campana)))
            self.assertEqual(campana.total_ejecuciones, 1350)
            self.assertEqual(campana.maximo_generaciones, 4050)
            self.assertEqual(len(filas), 1350)
            self.assertEqual(len({(e.modelo,e.motor,e.modo,e.caso_identificador) for e in filas}), 1350)
            self.assertEqual(set(Counter((e.modelo,e.motor,e.modo) for e in filas).values()), {45})
            self.assertTrue(all(e.modo == "open-loop" for e in filas[:45]))
            self.assertTrue(all(e.modo == "closed-loop" for e in filas[45:90]))
            self.assertEqual({e.maximo_intentos for e in filas[:45]}, {1})
            self.assertEqual({e.maximo_intentos for e in filas[45:90]}, {5})

    def test_45_prompts_exactos_y_no_acepta_44_ni_46(self):
        base = Path(aplicacion.conjuntos.__file__).parents[1] / "datos"
        documento = json.loads((base / "prompts_45_v1.json").read_text())
        origen = json.loads((base / "origen_prompts45.json").read_text())
        self.assertEqual(hashlib.sha256((base / "45_prompts_Agente_Ciel.md").read_bytes()).hexdigest(), origen["sha256_markdown"])
        for caso in documento["casos"]:
            self.assertEqual(hashlib.sha256(caso["descripcion"].encode()).hexdigest(), origen["prompts"][caso["codigo"]])
        self.assertEqual(Counter(c["nivel"] for c in documento["casos"]), {"basico":15,"intermedio":15,"complejo":15})
        for casos in (documento["casos"][:-1], documento["casos"] + [documento["casos"][0]]):
            with self.assertRaisesRegex(ValueError, "45"):
                validar_documento({**documento, "casos":casos})

    def test_reinicio_preserva_terminados_y_checkpoint_de_respuesta(self):
        self.activar()
        with self.sesiones() as sesion:
            filas = list(sesion.scalars(select(Ejecucion).order_by(Ejecucion.orden_campana).limit(2)))
            filas[0].estado = "completada"
            filas[1].estado = "generando"
            sesion.add(IntentoGeneracion(ejecucion_identificador=filas[1].identificador, numero=1,
                estado="respuesta_recibida", respuesta_modelo="resultado = caja", codigo="resultado = caja", modelo_informado="L01"))
            sesion.commit()
            ids = [e.identificador for e in filas]
        preparar_reinicio(programar=False)
        with self.sesiones() as sesion:
            self.assertEqual(sesion.get(Ejecucion,ids[0]).estado,"completada")
            self.assertEqual(sesion.get(Ejecucion,ids[1]).estado,"pendiente")
            self.assertEqual(sesion.get(Ejecucion,ids[1]).intentos[0].respuesta_modelo,"resultado = caja")
            self.assertEqual(sesion.get(Campana,self.identificador).estado,"en_curso")

    def test_respuesta_persistida_se_reutiliza_sin_otra_llamada_ni_otro_intento(self):
        self.activar()
        ejecucion = self.primera()
        with self.sesiones() as sesion:
            sesion.add(IntentoGeneracion(ejecucion_identificador=ejecucion.identificador, numero=1,
                estado="respuesta_recibida", respuesta_modelo="resultado = caja", codigo="resultado = caja", modelo_informado="L01",
                solicitud_modelo={"finalizacion":"stop", "perfil":{"digest":"a"*64}}))
            sesion.commit()
        with patch("aplicacion.generacion.solicitar_codigo") as proveedor, patch("aplicacion.generacion.solicitar_ejecucion_cad", return_value={
                "correcto":False,"diagnostico":"Error CAD simulado","ejecucion_correcta":False,"runtime_identificador":None}):
            procesar_ejecucion(ejecucion.identificador)
        proveedor.assert_not_called()
        with self.sesiones() as sesion:
            e=sesion.get(Ejecucion,ejecucion.identificador)
            self.assertEqual(len(e.intentos),1)
            self.assertEqual(e.estado,"fallida")
            self.assertEqual(e.numero_intentos,1)
            self.assertTrue(e.intentos[0].solicitud_modelo["recuperaciones_operativas"][0]["respuesta_persistida"])

    def test_recuperacion_operativa_repite_mismo_numero_y_continua_la_cola(self):
        self.activar()
        e = self.primera()
        with patch("aplicacion.generacion.solicitar_codigo", side_effect=ErrorProveedor("Ollama temporalmente apagado")):
            espera = procesar_paso(self.identificador)
        self.assertEqual(espera,10)
        with self.sesiones() as sesion:
            self.assertEqual(len(sesion.get(Ejecucion,e.identificador).intentos),1)
        def reactivar(*_):
            self.activar()
        respuesta={"texto":"esto no es python !!!","modelo_informado":"L01","tokens_entrada":10,"tokens_salida":5,
                   "finalizacion":"stop","perfil":{"digest":"a"*64},"proveedor":"ollama"}
        with patch("aplicacion.automatico.cambiar_estado",side_effect=reactivar), patch("aplicacion.generacion.solicitar_codigo",return_value=respuesta) as proveedor:
            self.assertEqual(procesar_paso(self.identificador),1)
        self.assertEqual(proveedor.call_count,1)
        with self.sesiones() as sesion:
            actual=sesion.get(Ejecucion,e.identificador)
            self.assertEqual(actual.estado,"fallida")
            self.assertEqual(len(actual.intentos),1)
            self.assertEqual(actual.numero_intentos,1)

    def test_carpetas_y_metricas_no_inventan_iou(self):
        self.activar()
        e = self.primera()
        respuesta={"texto":"invalido !!!","modelo_informado":"L01","tokens_entrada":1,"tokens_salida":2,
                   "finalizacion":"stop","perfil":{"digest":"a"*64},"proveedor":"ollama"}
        with patch("aplicacion.generacion.solicitar_codigo",return_value=respuesta):
            procesar_ejecucion(e.identificador)
        with self.sesiones() as sesion:
            e=sesion.get(Ejecucion,e.identificador)
            from aplicacion.base_datos import CasoDiseno
            carpeta=carpeta_ejecucion(sesion.get(Campana,self.identificador),sesion.get(CasoDiseno,e.caso_identificador),e)
        self.assertTrue((carpeta/"prompt.txt").exists())
        self.assertTrue((carpeta/"intentos/01/registro.json").exists())
        self.assertEqual(json.loads((carpeta/"resultado.json").read_text())["estado"],"fallida")
        metricas=calcular_metricas_campana(self.identificador)
        fila=next(f for f in metricas["filas"] if f["n_evaluable"])
        self.assertEqual(fila["n_evaluable"],1)
        self.assertEqual(fila["ir_codigo_pct"],100)
        self.assertEqual(fila["compile_rate_incremental_pct"],[0])
        self.assertIsNone(fila["referencias"]["iou_brep_medio"])
        self.assertIn("Text2CAD",csv_tabla_digital(metricas))

    def test_figura_y_zip_de_trazas_sin_generacion_real(self):
        metricas=calcular_metricas_campana(self.identificador)
        self.assertIn(b"<svg",figura_compilacion(metricas,"svg"))
        self.assertTrue(figura_compilacion(metricas,"png").startswith(b"\x89PNG"))
        with patch("aplicacion.resultados.figura_compilacion",return_value=b"<svg/>"):
            ruta=paquete_resultados({"metricas":metricas,"conjunto":{},"ejecuciones":[]},self.temporal,Path(self.temporal)/"paquete.zip")
        with zipfile.ZipFile(ruta) as paquete:
            self.assertIn("tabla_digital.csv",paquete.namelist())
            self.assertIn("figuras/compile-rate-todos.svg",paquete.namelist())
            for archivo in json.loads(paquete.read("huellas_archivos.json")):
                self.assertEqual(hashlib.sha256(paquete.read(archivo["archivo"])).hexdigest(),archivo["sha256"])

    def test_siguiente_prompt_no_repite_terminados_y_pausa_manual_se_respeta(self):
        self.activar()
        with self.sesiones() as sesion:
            filas=list(sesion.scalars(select(Ejecucion).order_by(Ejecucion.orden_campana).limit(3)))
            filas[0].estado="completada"
            filas[1].estado="fallida"
            siguiente=filas[2].identificador
            sesion.commit()
        def terminar(identificador):
            self.assertEqual(identificador,siguiente)
            with self.sesiones() as sesion:
                sesion.get(Ejecucion,identificador).estado="fallida"
                sesion.commit()
        with patch("aplicacion.generacion.procesar_ejecucion",side_effect=terminar) as generador:
            self.assertEqual(procesar_paso(self.identificador),1)
            generador.assert_called_once_with(siguiente)
        with self.sesiones() as sesion:
            sesion.get(Campana,self.identificador).estado="pausada"
            sesion.commit()
        with patch("aplicacion.generacion.procesar_ejecucion") as generador:
            self.assertIsNone(procesar_paso(self.identificador))
            generador.assert_not_called()

    def test_iou_requiere_activacion_explicita_de_referencia(self):
        from aplicacion.analisis import analizar_ejecucion
        e=self.primera()
        cliente=unittest.mock.MagicMock()
        cliente.post.return_value=httpx.Response(200,json={"nativa":{"estado":"no_calculable"},
            "comun":{"estado":"no_calculable"},"comparacion":{"estado":"sin_referencia"}},request=httpx.Request("POST","http://simulado/analizar"))
        with self.sesiones() as sesion:
            sesion.get(Ejecucion,e.identificador).estado="completada"
            sesion.commit()
        with patch("aplicacion.analisis.httpx.Client") as fabrica:
            fabrica.return_value.__enter__.return_value=cliente
            analizar_ejecucion(e.identificador)
            self.assertIsNone(cliente.post.call_args.kwargs["json"]["caso_identificador"])
            with self.sesiones() as sesion:
                campana=sesion.get(Campana,self.identificador)
                campana.configuracion={**campana.configuracion,"usar_referencias":True}
                sesion.commit()
            analizar_ejecucion(e.identificador)
            self.assertEqual(cliente.post.call_args.kwargs["json"]["caso_identificador"],e.caso_identificador)

    def test_exports_api_incluyen_tiempos_prompts_y_condiciones_fijadas(self):
        from aplicacion.api import descargar_datos, descargar_entregables
        datos=json.loads(descargar_datos(self.identificador).body)
        self.assertEqual(len(datos["ejecuciones"]),1350)
        self.assertEqual(len(datos["condiciones"]),30)
        self.assertEqual(len(datos["conjunto"]["casos"]),45)
        self.assertIn("fecha_inicio",datos["ejecuciones"][0])
        self.assertIn("descripcion",datos["ejecuciones"][0])
        with patch("aplicacion.resultados.figura_compilacion",return_value=b"<svg/>"):
            respuesta=descargar_entregables(self.identificador)
        self.assertTrue(Path(respuesta.path).is_file())
        Path(respuesta.path).unlink()

    def test_tarea_se_reprograma_si_la_base_de_datos_se_desconecta(self):
        from aplicacion.tareas import tarea_campana
        self.assertIsNone(tarea_campana.max_retries)
        with patch("aplicacion.tareas.crear_sesion",side_effect=RuntimeError("DB temporalmente caída")), \
             patch.object(tarea_campana,"retry",side_effect=RuntimeError("Reintento programado")) as reintento:
            with self.assertRaisesRegex(RuntimeError,"Reintento programado"):
                tarea_campana.run(self.identificador)
        self.assertEqual(reintento.call_args.kwargs["countdown"],30)
        self.assertIsNone(reintento.call_args.kwargs["max_retries"])


if __name__ == "__main__":
    unittest.main()
