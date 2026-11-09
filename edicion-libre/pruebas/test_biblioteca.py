"""Regresiones de biblioteca y compatibilidad, sin inferencias ni motores CAD."""
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aplicacion import biblioteca
from aplicacion.base_datos import BaseDeclarativa, Ejecucion, IntentoGeneracion, ArchivoGenerado


class BibliotecaTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.carpeta = Path(self.temporal.name)
        self.motor = create_engine('sqlite://', poolclass=StaticPool)
        self.addCleanup(self.motor.dispose)
        BaseDeclarativa.metadata.create_all(self.motor)
        self.sesiones = sessionmaker(self.motor, expire_on_commit=False)
        for nombre, valor in [('crear_sesion', self.sesiones), ('DIRECTORIO_ARTEFACTOS', self.temporal.name)]:
            parche = patch.object(biblioteca, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)
        with self.sesiones() as s:
            e = Ejecucion(identificador='aaaaaaaa-0000-0000-0000-000000000001', descripcion='Bloque con agujero',
                          motor='cadquery', modelo='L01', estado='completada', primer_exito_exportacion=2)
            s.add(e)
            s.flush()
            s.add_all([IntentoGeneracion(ejecucion_identificador=e.identificador, numero=1, estado='invalido', diagnostico='Error geométrico'),
                       IntentoGeneracion(ejecucion_identificador=e.identificador, numero=2, estado='correcto', codigo='resultado = caja()',
                                         cad_valido=True, exportacion_valida=True)])
            s.commit()
            self.identificador = e.identificador
            self.intento = e.intentos[-1].identificador

    def test_historial_y_busqueda_sin_ollama(self):
        self.assertEqual(biblioteca.historial(busqueda='agujero', desplazamiento=0)['total'], 1)
        self.assertEqual(biblioteca.historial(busqueda='no existe', desplazamiento=0)['total'], 0)
        self.assertEqual(biblioteca.historial(motor='freecad', desplazamiento=0)['total'], 0)
        self.assertEqual(biblioteca.historial(desplazamiento=24)['ejecuciones'], [])

    def test_exportacion_antigua_con_fallos_y_archivo_ausente(self):
        with self.sesiones() as s:
            s.add(ArchivoGenerado(ejecucion_identificador=self.identificador, nombre='pieza.stl', ruta=str(self.carpeta/'ausente.stl'), tamano_bytes=1, sha256='a'*64))
            s.commit()
        destino = self.carpeta/'salida.zip'
        nombre = biblioteca.crear_paquete([self.identificador], destino)
        self.assertIn('LIBRE-aaaaaaaa__CadQuery__EXITO-TECNICO', nombre)
        with zipfile.ZipFile(destino) as z:
            self.assertIn(nombre+'/intentos/intento-01__FALLIDO/diagnostico.json', z.namelist())
            self.assertIn(nombre+'/intentos/intento-02__EXITO-TECNICO/codigo.py', z.namelist())
            self.assertIn('No registrado', z.read(nombre+'/LEEME.txt').decode())
            manifiesto = json.loads(z.read('manifiesto.json'))
            self.assertEqual(manifiesto['archivos_ausentes'][0]['estado'], 'ausente')
            for archivo in manifiesto['archivos']:
                self.assertEqual(hashlib.sha256(z.read(archivo['archivo'])).hexdigest(), archivo['sha256'])

    def test_variante_copia_codigo_sin_modificar_origen(self):
        solicitud = biblioteca.SolicitudVariante(intento_identificador=self.intento, modificacion='Añade un agujero', modelo='L01')
        with patch('aplicacion.proveedores.modelos_configurados', return_value={'L01': 'Modelo'}), patch('aplicacion.tareas.tarea_generacion.delay') as cola:
            resultado = biblioteca.crear_variante(self.identificador, solicitud)
            cola.assert_called_once_with(resultado['identificador'])
        with self.sesiones() as s:
            variante = s.get(Ejecucion, resultado['identificador'])
            self.assertEqual(variante.contexto_variante['codigo'], 'resultado = caja()')
            self.assertEqual(variante.origen_identificador, self.identificador)
            self.assertIsNone(variante.campana_identificador)
            self.assertEqual(s.get(Ejecucion, self.identificador).estado, 'completada')
            self.assertIn('Añade un agujero', biblioteca.solicitud_variante(variante.contexto_variante))

    def test_variante_rechaza_intento_fallido_y_modelo_ausente(self):
        with patch('aplicacion.proveedores.modelos_configurados', return_value={'L01': 'Modelo'}):
            with self.assertRaises(HTTPException) as error:
                biblioteca.crear_variante(self.identificador, biblioteca.SolicitudVariante(intento_identificador=self.intento-1, modificacion='Cambio', modelo='L01'))
            self.assertEqual(error.exception.status_code, 409)
        with patch('aplicacion.proveedores.modelos_configurados', return_value={}):
            with self.assertRaises(HTTPException) as error:
                biblioteca.crear_variante(self.identificador, biblioteca.SolicitudVariante(intento_identificador=self.intento, modificacion='Cambio', modelo='L01'))
            self.assertEqual(error.exception.status_code, 422)

    def test_nombres_windows_y_colisiones(self):
        datos = {'codigo_prompt': 'B01:<>?/*', 'motor': 'freecad', 'resultado': 'BLOQUEADA', 'modo': 'open-loop', 'identificador': self.identificador}
        nombre = biblioteca.nombre_carpeta(datos)
        self.assertFalse(any(c in nombre for c in ':<>?/*'))
        self.assertIn('__FreeCAD__BLOQUEADA__', nombre)
        with self.sesiones() as s:
            s.add(Ejecucion(identificador='aaaaaaaa-1111-0000-0000-000000000002', descripcion='Otro bloque', motor='cadquery', modelo='L01', estado='completada', primer_exito_exportacion=1))
            s.commit()
        destino = self.carpeta/'colisiones.zip'
        biblioteca.crear_paquete([self.identificador, 'aaaaaaaa-1111-0000-0000-000000000002'], destino)
        with zipfile.ZipFile(destino) as z:
            self.assertEqual(len(z.namelist()), len(set(z.namelist())))

    def test_vistas_reintentables_sin_duplicar_archivos(self):
        bruto = b'STL simulado'
        ruta = self.carpeta/'pieza.stl'
        ruta.write_bytes(bruto)
        with self.sesiones() as s:
            s.add(ArchivoGenerado(ejecucion_identificador=self.identificador, nombre='pieza.stl', ruta=str(ruta), tamano_bytes=len(bruto), sha256=hashlib.sha256(bruto).hexdigest(), intento_identificador=self.intento))
            s.commit()
        with patch('aplicacion.biblioteca.httpx.Client') as cliente:
            cliente.return_value.__enter__.return_value.post.return_value.json.return_value = {'archivos': {'vista-frontal.png': 'UE5H'}, 'perfil': {'version': 'prueba'}}
            biblioteca.generar_vistas(self.identificador)
            biblioteca.generar_vistas(self.identificador)
        with self.sesiones() as s:
            archivos = list(s.scalars(select(ArchivoGenerado).where(ArchivoGenerado.nombre == 'vista-frontal.png')))
            self.assertEqual(len(archivos), 1)
            self.assertEqual(archivos[0].intento_identificador, self.intento)

    def test_migracion_antigua_con_copia_consistente(self):
        from aplicacion import base_datos
        ruta = self.carpeta/'antigua.sqlite'
        motor = create_engine('sqlite:///' + str(ruta))
        BaseDeclarativa.metadata.create_all(motor)
        with motor.begin() as c:
            c.exec_driver_sql('DROP INDEX ix_ejecuciones_origen_identificador')
            c.exec_driver_sql('ALTER TABLE ejecuciones DROP COLUMN contexto_variante')
            c.exec_driver_sql('ALTER TABLE ejecuciones DROP COLUMN origen_identificador')
            c.exec_driver_sql("INSERT INTO ejecuciones (identificador,descripcion,motor,modelo,estado,mensaje,numero_intentos,modo,repeticion,maximo_intentos,fecha_creacion,fecha_actualizacion) VALUES ('historica','pieza antigua','freecad','L01','fallida','falló',1,'open-loop',1,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
        with patch.object(base_datos, 'motor_base_datos', motor):
            base_datos.crear_tablas()
            base_datos.crear_tablas()
        with motor.connect() as c:
            self.assertEqual(c.exec_driver_sql('SELECT descripcion FROM ejecuciones').scalar(), 'pieza antigua')
        self.assertEqual(len(list(self.carpeta.glob('*.bak'))), 1)
        motor.dispose()

    def test_reutilizar_anterior_sin_banderas_con_evidencia(self):
        with self.sesiones() as s:
            e = s.get(Ejecucion, self.identificador)
            i = e.intentos[-1]
            i.cad_valido = None
            i.exportacion_valida = None
            self.assertTrue(biblioteca.intento_reutilizable(e, i))
            e.primer_exito_exportacion = None
            self.assertFalse(biblioteca.intento_reutilizable(e, i))
            i.exportacion_valida = False
            e.primer_exito_exportacion = i.numero
            self.assertFalse(biblioteca.intento_reutilizable(e, i))

    def test_worker_conserva_contexto_en_las_cinco_correcciones(self):
        from aplicacion.generacion import procesar_ejecucion
        contexto = {'descripcion': 'Bloque original', 'codigo': 'resultado = caja()', 'modificacion': 'Añade un agujero de 5 mm'}
        with self.sesiones() as s:
            s.add(Ejecucion(identificador='variante', descripcion='Bloque original', motor='cadquery', modelo='L01',
                            modo='closed-loop', contexto_variante=contexto, origen_identificador=self.identificador))
            s.commit()
        respuesta = {'texto': 'no es python !!!', 'modelo_informado': 'L01', 'tokens_entrada': 10,
                     'tokens_salida': 10, 'finalizacion': 'stop', 'proveedor': 'ollama', 'perfil': {'digest': 'a'*64}}
        with patch('aplicacion.generacion.crear_sesion', self.sesiones), \
             patch('aplicacion.generacion.verificar_modelo_local', return_value={'digest': 'a'*64}), \
             patch('aplicacion.generacion.solicitar_codigo', return_value=respuesta) as proveedor:
            procesar_ejecucion('variante')
        self.assertEqual(proveedor.call_count, 5)
        with self.sesiones() as s:
            for i in s.get(Ejecucion, 'variante').intentos:
                solicitud = i.solicitud_modelo
                self.assertEqual(solicitud['plantilla'], 'ciel-variantes-v1')
                texto = solicitud['mensajes'][1]['content']
                self.assertIn(contexto['codigo'], texto)
                self.assertIn(contexto['modificacion'], texto)
