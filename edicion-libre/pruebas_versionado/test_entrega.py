"""Inspecciona la entrega publicada sin ejecutar instaladores ni código Windows."""

import ast
import hashlib
import json
import re
import unittest
import zipfile
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]


class EntregaLibre(unittest.TestCase):
    def test_version_independiente_coincide_con_instalador_y_manifiesto(self):
        version = (BASE / 'VERSION').read_text().strip()
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')
        nsis = (BASE / 'nativo/instalador.nsi').read_text()
        self.assertIn(f'VIProductVersion "{version}.0"', nsis)
        self.assertIn(f'VIAddVersionKey "FileVersion" "{version}"', nsis)
        self.assertEqual(json.loads((BASE / 'nativo/dependencias.json').read_text())['version_instalador'], version)
        self.assertIn(version, (BASE / 'CHANGELOG.md').read_text())
        constructor = (BASE / 'construir_nativo.py').read_text()
        ast.parse(constructor)
        self.assertIn('(BASE / "VERSION").read_text', constructor)

    def test_instalador_y_paquete_publicados_tienen_hashes_verificables(self):
        version = (BASE / 'VERSION').read_text().strip()
        entrega = BASE / 'entregas' / version
        for linea in (entrega / 'SHA256SUMS.txt').read_text().splitlines():
            huella, nombre = linea.split('  ', 1)
            self.assertEqual(Path(nombre).name, nombre)
            self.assertEqual(hashlib.sha256((entrega / nombre).read_bytes()).hexdigest(), huella, nombre)
        self.assertEqual((entrega / f'Agente-Ciel-Nativo-{version}-Setup.exe').read_bytes()[:2], b'MZ')
        paquete = json.loads((entrega / 'paquete.json').read_text())
        self.assertEqual(paquete['version'], version)
        self.assertEqual(paquete['sha256_programa'], hashlib.sha256((entrega / 'programa.zip').read_bytes()).hexdigest())
        with zipfile.ZipFile(entrega / 'programa.zip') as archivo:
            self.assertIsNone(archivo.testzip())
            origen = json.loads(archivo.read('origen.json'))
            self.assertEqual(origen['version_instalador'], version)
            codigo = hashlib.sha256()
            for nombre in sorted(n for n in archivo.namelist() if n != 'origen.json'):
                codigo.update(nombre.encode() + b'\0' + archivo.read(nombre))
                if nombre.endswith('.py'):
                    ast.parse(archivo.read(nombre).decode(), filename=nombre)
            self.assertEqual(codigo.hexdigest(), origen['codigo_sha256'])
            for nombre in archivo.namelist():
                self.assertFalse(re.search(r'(^|/)(node_modules|__pycache__)(/|$)|\.(env|sqlite|db|gguf)$', nombre), nombre)

    def test_extractor_incluido_conserva_huella_y_licencias(self):
        perfil = json.loads((BASE / 'nativo/dependencias.json').read_text())['extractor_7zip']
        self.assertEqual(hashlib.sha256((BASE / 'nativo' / perfil['archivo']).read_bytes()).hexdigest(), perfil['sha256'])
        for nombre in ('7zip-LICENSE.txt', '7zip-LGPL.txt', 'ORIGEN.txt'):
            self.assertTrue((BASE / 'nativo/herramientas' / nombre).is_file())


if __name__ == '__main__':
    unittest.main()
