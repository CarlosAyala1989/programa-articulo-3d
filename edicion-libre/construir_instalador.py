"""Genera el instalador Windows desde Linux con un compilador NSIS aislado."""

import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path


BASE = Path(__file__).resolve().parent
VERSION = "0.3.0"


def construir(compilar: bool = True) -> Path:
    programa = BASE / "programa"
    destino = BASE / "dist"
    destino.mkdir(exist_ok=True)
    archivos = sorted(p for p in programa.rglob("*") if p.is_file()
                      and not set(p.relative_to(programa).parts) & {"node_modules", "dist", "__pycache__"}
                      and p.suffix not in {".pyc", ".env", ".log"}
                      and p.name != "modelos_instalados.json")
    codigo = hashlib.sha256()
    for archivo in archivos:
        relativo = archivo.relative_to(programa).as_posix()
        if relativo not in {"origen.json", "modelos_instalados.json"}:
            codigo.update(relativo.encode() + b"\0" + archivo.read_bytes())
    origen = json.loads((programa / "origen.json").read_text(encoding="utf-8"))
    origen["codigo_sha256"] = codigo.hexdigest()
    (programa / "origen.json").write_text(json.dumps(origen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paquete = destino / "programa.zip"
    with zipfile.ZipFile(paquete, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as salida:
        for archivo in archivos:
            informacion = zipfile.ZipInfo(archivo.relative_to(programa).as_posix(), (2026, 10, 13, 0, 0, 0))
            informacion.compress_type = zipfile.ZIP_DEFLATED
            salida.writestr(informacion, archivo.read_bytes())
    huella = hashlib.sha256(paquete.read_bytes()).hexdigest()
    (destino / "paquete.json").write_text(json.dumps({"version": "ciel-instalador-libre-v2-windows",
        "sha256_programa": huella, "bytes_programa": paquete.stat().st_size,
        "origen": origen}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if compilar:
        subprocess.run(["docker", "build", "-t", "ciel-libre-compilador:nsis", "-f",
                        str(BASE / "instalador/Dockerfile.compilador"), str(BASE / "instalador")], check=True)
        subprocess.run(["docker", "run", "--rm", "--user", str(os.getuid()),
                        "-v", f"{BASE}:/paquete", "ciel-libre-compilador:nsis", "-V2",
                        "instalador/instalador.nsi"], check=True)
        ejecutable = destino / f"Agente-Ciel-Libre-{VERSION}-Setup.exe"
        with ejecutable.open("rb") as entrada:
            if entrada.read(2) != b"MZ":
                raise RuntimeError("NSIS no generó un ejecutable Windows válido")
        resumen = hashlib.sha256(ejecutable.read_bytes()).hexdigest()
        (destino / "SHA256SUMS.txt").write_text(f"{resumen}  {ejecutable.name}\n", encoding="utf-8")
        print(f"Instalador generado: {ejecutable}")
        return ejecutable
    return paquete


if __name__ == "__main__":
    parametros = argparse.ArgumentParser(description="Construir Agente Ciel Libre Setup.exe")
    parametros.add_argument("--solo-paquete", action="store_true")
    opciones = parametros.parse_args()
    construir(not opciones.solo_paquete)
