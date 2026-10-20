"""Entrada de un proceso CAD independiente. La autorización precede al código generado."""

import json
import os
import sys
import time
from pathlib import Path


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Esta entrada solo funciona en Windows; no ejecuta experimentos en Ubuntu")
    carpeta = Path(sys.argv[1]).resolve()
    for _ in range(300):
        if (carpeta / "autorizado").is_file():
            break
        time.sleep(0.1)
    else:
        raise SystemExit("El supervisor no autorizó el proceso")
    solicitud = json.loads((carpeta / "solicitud.json").read_text(encoding="utf-8"))
    programa = Path(solicitud["programa"])
    sys.path.insert(0, str(programa))
    os.environ["MOTOR_CAD"] = solicitud["motor"]
    os.environ["CIEL_DIRECTORIO_TEMP"] = str(carpeta / "archivos")
    directorios_dll = []
    if solicitud["motor"] == "freecad":
        binario = Path(solicitud["freecad_bin"])
        sys.path.insert(0, str(binario))
        for ruta in (binario, binario.parent / "lib"):
            if ruta.is_dir():
                directorios_dll.append(os.add_dll_directory(str(ruta)))
        # Inicialización necesaria antes de importar Part en FreeCAD Windows.
        import FreeCAD
    from motores.ejecutar import ejecutar
    respuesta = ejecutar(codigo=solicitud["codigo"])
    (carpeta / "respuesta.json").write_text(json.dumps(respuesta, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
