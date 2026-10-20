"""Extraer FreeCAD con 7-Zip nativo: BCJ2 no está soportado por py7zr."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4


def sha256_archivo(ruta: Path) -> str:
    resumen = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def encontrar_binario(directorio: Path) -> Path:
    for ejecutable in sorted(directorio.rglob("FreeCAD.exe")):
        if (ejecutable.parent / "python.exe").is_file():
            return ejecutable.parent
    raise RuntimeError("El paquete extraído no contiene FreeCAD.exe y python.exe en su directorio bin")


def extraer(archivo: Path, destino: Path, extractor: Path,
            sha256_portable: str, sha256_extractor: str) -> Path:
    if sys.platform != "win32":
        raise RuntimeError("La preparación de FreeCAD se ejecuta solamente en Windows")
    for ruta, esperado in ((archivo, sha256_portable), (extractor, sha256_extractor)):
        if not ruta.is_file() or sha256_archivo(ruta) != esperado:
            raise RuntimeError(f"El archivo no coincide con su SHA-256 fijado: {ruta}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    marcador = destino / ".extraccion-completa.json"
    if marcador.is_file():
        try:
            datos = json.loads(marcador.read_text(encoding="utf-8"))
            if (datos.get("extraccion_completa") is True and datos.get("sha256_portable") == sha256_portable
                    and datos.get("sha256_extractor") == sha256_extractor):
                return encontrar_binario(destino)
        except (ValueError, OSError, RuntimeError):
            pass
    # El destino definitivo solo se reemplaza cuando el extractor completa el archivo.
    temporal = Path(tempfile.mkdtemp(prefix="freecad-preparacion-", dir=destino.parent))
    anterior = destino.with_name("freecad-anterior-" + uuid4().hex[:8])
    publicada = False
    try:
        print("Extrayendo FreeCAD con 7-Zip nativo (BCJ2). Se reutiliza el archivo portable descargado.", flush=True)
        resultado = subprocess.run([str(extractor), "x", "-y", "-bd", "-bb0", "-bsp0",
            "-o" + str(temporal), str(archivo)], stdin=subprocess.DEVNULL, timeout=1800)
        if resultado.returncode != 0:
            raise RuntimeError(f"7-Zip no completó la extracción de FreeCAD; código de salida {resultado.returncode}")
        encontrar_binario(temporal)
        (temporal / marcador.name).write_text(json.dumps({"version": "ciel-extraccion-freecad-v2",
            "sha256_portable": sha256_portable, "sha256_extractor": sha256_extractor,
            "extractor": "7-Zip 26.04; BCJ2", "extraccion_completa": True}, indent=2) + "\n", encoding="utf-8")
        if destino.exists():
            destino.replace(anterior)
        try:
            temporal.replace(destino)
            publicada = True
        except OSError:
            if anterior.exists() and not destino.exists():
                anterior.replace(destino)
            raise
        # Solo se limpia el paquete anterior de FreeCAD; datos y entornos viven fuera.
        if anterior.exists():
            try:
                shutil.rmtree(anterior)
            except OSError:
                print(f"FreeCAD preparado. La carpeta anterior permanece en {anterior}", flush=True)
        return encontrar_binario(destino)
    finally:
        if not publicada:
            shutil.rmtree(temporal, ignore_errors=True)


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("La preparación de FreeCAD se ejecuta solamente en Windows")
    parser = argparse.ArgumentParser()
    parser.add_argument("--archivo", type=Path, required=True)
    parser.add_argument("--destino", type=Path, required=True)
    parser.add_argument("--extractor", type=Path, required=True)
    parser.add_argument("--sha256-portable", required=True)
    parser.add_argument("--sha256-extractor", required=True)
    argumentos = parser.parse_args()
    binario = extraer(argumentos.archivo.resolve(), argumentos.destino.resolve(), argumentos.extractor.resolve(),
        argumentos.sha256_portable, argumentos.sha256_extractor)
    print(f"FreeCAD extraído completamente: {binario}", flush=True)


if __name__ == "__main__":
    main()
