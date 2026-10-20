"""Crear un manifiesto de runtimes de Windows para congelar cada campaña."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def resolver_binario_freecad(carpeta: Path) -> Path:
    """Aceptar bin o la carpeta portable, comprobando los dos ejecutables."""
    for candidato in (carpeta, carpeta / "bin"):
        if (candidato / "FreeCAD.exe").is_file() and (candidato / "python.exe").is_file():
            return candidato.resolve()
    if carpeta.is_dir():
        for ejecutable in sorted(carpeta.rglob("FreeCAD.exe")):
            if (ejecutable.parent / "python.exe").is_file():
                return ejecutable.parent.resolve()
    raise RuntimeError(f"No se encontró una carpeta bin de FreeCAD con FreeCAD.exe y python.exe dentro de: {carpeta}")


def fijar(raiz: Path, freecad_bin: Path) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("La preparación de runtimes solo se permite en Windows")
    freecad_bin = resolver_binario_freecad(freecad_bin)
    print(f"Directorio bin de FreeCAD verificado: {freecad_bin}", flush=True)
    programa = Path(__file__).resolve().parents[1]
    interpretes = {
        "cadquery": raiz / "entornos/cadquery/Scripts/python.exe",
        "build123d": raiz / "entornos/build123d/Scripts/python.exe",
        "freecad": freecad_bin / "python.exe",
    }
    versiones = {"cadquery": "2.6.1", "build123d": "0.13.0", "freecad": "1.1.3"}
    resultado = {"version": "ciel-runtimes-windows-v1", "motores": {}, "freecad_bin": str(freecad_bin),
        "temporales": str(raiz / "temporales"), "limite_cad_s": 100, "limite_cad_bytes": 4 * 1024 ** 3}
    (raiz / "temporales").mkdir(exist_ok=True)
    hash_ejecutor = hashlib.sha256((programa / "motores/ejecutar.py").read_bytes() +
        (programa / "nativo/ejecutar_cad.py").read_bytes() + (programa / "nativo/procesos_windows.py").read_bytes()).hexdigest()
    for motor, python in interpretes.items():
        if not python.is_file():
            raise RuntimeError(f"Falta el intérprete nativo de {motor}: {python}")
        respuesta = subprocess.run([str(python), "-I", str(programa / "nativo/sonda_runtime.py"), motor, str(freecad_bin)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", QT_QPA_PLATFORM="offscreen"),
            cwd=freecad_bin if motor == "freecad" else raiz, creationflags=subprocess.CREATE_NO_WINDOW)
        lineas = [l[len("SONDA_NATIVA:"):] for l in respuesta.stdout.splitlines() if l.startswith("SONDA_NATIVA:")]
        if respuesta.returncode != 0 or not lineas:
            raise RuntimeError(f"No se pudo cargar {motor}: {respuesta.stderr[-2000:]} {respuesta.stdout[-2000:]}")
        datos = json.loads(lineas[-1])
        if datos["version"] != versiones[motor]:
            raise RuntimeError(f"{motor}: versión inesperada {datos['version']}; se requiere {versiones[motor]}")
        huella = hashlib.sha256(json.dumps(datos, sort_keys=True).encode() + hash_ejecutor.encode()).hexdigest()
        resultado["motores"][motor] = {"python": str(python), "identificador": "win-" + motor + "-" + huella,
            "metadatos": datos, "ejecutor_sha256": hash_ejecutor}
    destino = raiz / "runtimes_nativos.json"
    temporal = destino.with_suffix(".tmp")
    temporal.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(destino)
    return resultado


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raiz", type=Path, required=True)
    parser.add_argument("--freecad-bin", type=Path, required=True)
    argumentos = parser.parse_args()
    fijar(argumentos.raiz.resolve(), argumentos.freecad_bin.resolve())
