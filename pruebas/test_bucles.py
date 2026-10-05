"""El número de llamadas y la historia de éxito no dependen del resultado final."""

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aplicacion.base_datos import BaseDeclarativa, Ejecucion, IntentoGeneracion
from aplicacion.generacion import procesar_ejecucion


def respuesta(codigo):
    return {"texto": codigo, "modelo_informado": "simulado", "tokens_entrada": 100,
            "tokens_salida": 50, "finalizacion": "stop", "proveedor": "prueba",
            "perfil": {"temperatura": 0.2}}


class BuclesGeneracion(unittest.TestCase):
    def setUp(self):
        motor = create_engine("sqlite://", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)
        BaseDeclarativa.metadata.create_all(motor)
        self.sesiones = sessionmaker(bind=motor, expire_on_commit=False)
        self.motor = motor

    def tearDown(self):
        self.motor.dispose()

    def crear_ejecucion(self, identificador, modo):
        with self.sesiones() as sesion:
            sesion.add(Ejecucion(
                identificador=identificador, descripcion="Cubo de 20 mm de lado centrado",
                motor="cadquery", modelo="deepseek-flash", modo=modo,
                maximo_intentos=1 if modo == "open-loop" else 5,
                estado="pendiente", mensaje="Prueba",
            ))
            sesion.commit()

    def test_open_loop_termina_tras_un_fallo(self):
        self.crear_ejecucion("abierto", "open-loop")
        with patch("aplicacion.generacion.crear_sesion", self.sesiones), \
             patch("aplicacion.generacion.solicitar_codigo", return_value=respuesta("esto no es python !!!")) as proveedor:
            procesar_ejecucion("abierto")
        with self.sesiones() as sesion:
            ejecucion = sesion.get(Ejecucion, "abierto")
            self.assertEqual(ejecucion.estado, "fallida")
            self.assertEqual(ejecucion.numero_intentos, 1)
            self.assertIsNone(ejecucion.primer_exito_ejecucion)
            self.assertEqual(ejecucion.intentos[0].fase_error, "sintaxis")
        self.assertEqual(proveedor.call_count, 1)

    def test_closed_loop_conserva_exito_de_codigo_previo_a_cad(self):
        self.crear_ejecucion("cerrado", "closed-loop")
        codigo = "import cadquery as cq\nresultado = cq.Workplane('XY').box(20,20,20)"
        invalido = {"correcto": False, "sintaxis_valida": True,
                    "ejecucion_correcta": True, "cad_valido": False,
                    "exportacion_valida": None, "fase_error": "cad",
                    "diagnostico": "No se obtuvo sólido válido"}
        valido = {"correcto": True, "sintaxis_valida": True,
                  "ejecucion_correcta": True, "cad_valido": True,
                  "exportacion_valida": True, "archivos": {},
                  "volumen_mm3": 8000.0, "runtime_identificador": "prueba"}
        with patch("aplicacion.generacion.crear_sesion", self.sesiones), \
             patch("aplicacion.generacion.solicitar_codigo", side_effect=[respuesta(codigo), respuesta(codigo)]) as proveedor, \
             patch("aplicacion.generacion.solicitar_ejecucion_cad", side_effect=[invalido, valido]), \
             patch("aplicacion.generacion.guardar_archivos"), \
             patch("aplicacion.analisis.analizar_ejecucion"):
            procesar_ejecucion("cerrado")
        with self.sesiones() as sesion:
            ejecucion = sesion.get(Ejecucion, "cerrado")
            self.assertEqual(ejecucion.estado, "completada")
            self.assertEqual(ejecucion.numero_intentos, 2)
            self.assertEqual(ejecucion.primer_exito_ejecucion, 1)
            self.assertEqual(ejecucion.primer_exito_cad, 2)
            self.assertEqual(ejecucion.primer_exito_exportacion, 2)
            self.assertEqual([i.estado for i in ejecucion.intentos], ["invalido", "correcto"])
            self.assertIn("No se obtuvo sólido válido", ejecucion.intentos[1].solicitud_modelo["mensajes"][1]["content"])
        self.assertEqual(proveedor.call_count, 2)

    def test_cinco_fallos_acumulan_diagnosticos_en_cada_llamada_real(self):
        self.crear_ejecucion("repetido", "closed-loop")
        codigo = "import cadquery as cq\nresultado = cq.Workplane('XY').box(20,20,20).edges().fillet(99)"
        fallo = {"correcto": False, "sintaxis_valida": True, "ejecucion_correcta": False,
                 "fase_error": "ejecucion", "diagnostico": "StdFail_NotDone: BRep_API: command not done",
                 "linea_error": 2, "fragmento_codigo": "2: resultado = pieza.edges().fillet(99)",
                 "traza_error": "traza-original-del-runtime"}
        with patch("aplicacion.generacion.crear_sesion", self.sesiones), \
             patch("aplicacion.generacion.solicitar_codigo", return_value=respuesta(codigo)) as proveedor, \
             patch("aplicacion.generacion.solicitar_ejecucion_cad", return_value=fallo):
            procesar_ejecucion("repetido")
        self.assertEqual(proveedor.call_count, 5)
        for indice, llamada in enumerate(proveedor.call_args_list[1:], 1):
            contenido = llamada.args[1][1]["content"]
            self.assertIn(codigo, contenido)
            self.assertIn("traza-original-del-runtime", contenido)
            self.assertIn("Línea 2", contenido)
            for numero in range(1, indice + 1):
                self.assertIn(f"Intento {numero} · fase ejecucion", contenido)
        self.assertIn("Cambia la estrategia", proveedor.call_args_list[-1].args[1][1]["content"])
        with self.sesiones() as sesion:
            ejecucion = sesion.get(Ejecucion, "repetido")
            self.assertEqual(ejecucion.estado, "fallida")
            self.assertEqual(ejecucion.intentos[-1].solicitud_modelo["retroalimentacion"]["intentos_fuente"], [1, 2, 3, 4])

    def test_reanudar_recupera_feedback_persistido(self):
        self.crear_ejecucion("reanudar", "closed-loop")
        with self.sesiones() as sesion:
            sesion.get(Ejecucion, "reanudar").estado = "pausada"
            sesion.add(IntentoGeneracion(
                ejecucion_identificador="reanudar", numero=1, estado="invalido",
                codigo="resultado = pieza.edges().fillet(99)", diagnostico="falló fillet", fase_error="ejecucion",
                solicitud_modelo={"validacion_cad": {"linea_error": 1, "traza_error": "traza-guardada"}},
            ))
            sesion.commit()
        codigo = "import cadquery as cq\nresultado = cq.Workplane('XY').box(20,20,20)"
        valido = {"correcto": True, "sintaxis_valida": True, "ejecucion_correcta": True,
                  "cad_valido": True, "exportacion_valida": True, "archivos": {}, "volumen_mm3": 8000}
        with patch("aplicacion.generacion.crear_sesion", self.sesiones), \
             patch("aplicacion.generacion.solicitar_codigo", return_value=respuesta(codigo)) as proveedor, \
             patch("aplicacion.generacion.solicitar_ejecucion_cad", return_value=valido), \
             patch("aplicacion.generacion.guardar_archivos"), patch("aplicacion.analisis.analizar_ejecucion"):
            procesar_ejecucion("reanudar")
        self.assertIn("traza-guardada", proveedor.call_args.args[1][1]["content"])
        self.assertIn("falló fillet", proveedor.call_args.args[1][1]["content"])
        self.assertEqual(proveedor.call_count, 1)


if __name__ == "__main__":
    unittest.main()
