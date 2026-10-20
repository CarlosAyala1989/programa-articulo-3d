"""Identificar bibliotecas nativas instaladas; no genera piezas ni consulta modelos."""

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("La sonda de runtimes se usa únicamente en Windows")
    motor = sys.argv[1]
    datos = {"motor": motor, "python": sys.version, "arquitectura": platform.machine(), "plataforma": platform.platform()}
    handles = []
    if motor == "freecad":
        binario = Path(sys.argv[2])
        sys.path.insert(0, str(binario))
        handles.append(os.add_dll_directory(str(binario)))
        import FreeCAD
        import Part
        datos.update({"version": ".".join(FreeCAD.Version()[:3]),
            "biblioteca_sha256": hashlib.sha256(Path(FreeCAD.__file__).read_bytes()).hexdigest()})
    else:
        if motor == "cadquery":
            import cadquery
            version = importlib.metadata.version("cadquery")
        else:
            import build123d
            version = importlib.metadata.version("build123d")
        datos.update({"version": version,
            "paquetes": sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())})
    print("SONDA_NATIVA:" + json.dumps(datos, ensure_ascii=False))


if __name__ == "__main__":
    main()
