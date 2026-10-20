"""Empaqueta y compila NSIS; nunca inicia la aplicación ni los motores CAD."""

import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path


BASE = Path(__file__).resolve().parent
VERSION = (BASE / "VERSION").read_text(encoding="utf-8").strip()


def construir(compilar: bool = True) -> Path:
    programa = BASE / "programa"
    destino = BASE / "dist-nativo"
    destino.mkdir(exist_ok=True)
    archivos = []
    for archivo in sorted(programa.rglob("*")):
        if not archivo.is_file():
            continue
        partes = archivo.relative_to(programa).parts
        if partes[0] not in {"aplicacion", "evaluador", "motores", "nativo", "datos", "interfaz"}:
            continue
        if set(partes) & {"__pycache__", "node_modules", "modelos_libres"}:
            continue
        if partes[0] == "interfaz" and partes[1] != "dist":
            continue
        if archivo.name == "Dockerfile" or archivo.suffix in {".pyc", ".env", ".log", ".sqlite", ".db"}:
            continue
        if archivo.name == "requirements.txt" or (partes[0] == "aplicacion" and archivo.name == "tareas.py"):
            continue
        archivos.append(archivo)
    if not (programa / "interfaz/dist/index.html").is_file():
        raise RuntimeError("Falta la interfaz compilada; el empaquetador no inicia ni construye la aplicación")
    dependencias = json.loads((BASE / "nativo/dependencias.json").read_text(encoding="utf-8"))
    extractor = BASE / "nativo" / dependencias["extractor_7zip"]["archivo"]
    if hashlib.sha256(extractor.read_bytes()).hexdigest() != dependencias["extractor_7zip"]["sha256"]:
        raise RuntimeError("El extractor 7-Zip incluido no coincide con su SHA-256")
    codigo = hashlib.sha256()
    for archivo in archivos:
        codigo.update(archivo.relative_to(programa).as_posix().encode() + b"\0" + archivo.read_bytes())
    perfil = json.loads((programa / "datos/perfiles_generacion_nativos_v2.json").read_text(encoding="utf-8"))
    origen = {"version": perfil["version"], "version_instalador": VERSION,
        "codigo_sha256": codigo.hexdigest(), "protocolo": perfil["protocolo_lote"],
        "n_ejecuciones": 1350, "ejecucion": "solo Windows; Ollama existente; SQLite local",
        "validacion": "inspección estática y compilación del instalador; sin ejecutar aplicación o benchmark en Ubuntu"}
    paquete = destino / "programa.zip"
    with zipfile.ZipFile(paquete, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as salida:
        for archivo in archivos:
            info = zipfile.ZipInfo(archivo.relative_to(programa).as_posix(), (2026, 10, 13, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            salida.writestr(info, archivo.read_bytes())
        info = zipfile.ZipInfo("origen.json", (2026, 10, 13, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        salida.writestr(info, json.dumps(origen, ensure_ascii=False, indent=2) + "\n")
    (destino / "paquete.json").write_text(json.dumps({"version": VERSION,
        "sha256_programa": hashlib.sha256(paquete.read_bytes()).hexdigest(),
        "bytes_programa": paquete.stat().st_size, "origen": origen}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not compilar:
        return paquete
    # Reutiliza exclusivamente el compilador NSIS existente. No construye imágenes CAD.
    subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", str(os.getuid()),
        "-v", f"{BASE}:/paquete", "ciel-libre-compilador:nsis", "-V2", "nativo/instalador.nsi"], check=True)
    ejecutable = destino / f"Agente-Ciel-Nativo-{VERSION}-Setup.exe"
    if ejecutable.read_bytes()[:2] != b"MZ":
        raise RuntimeError("El compilador no produjo un ejecutable Windows")
    nombres = [ejecutable, paquete, destino / "paquete.json"]
    (destino / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in nombres), encoding="utf-8")
    print(f"Instalador generado: {ejecutable}")
    return ejecutable


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Empaquetar Agente Ciel Nativo para Windows")
    parser.add_argument("--solo-paquete", action="store_true")
    argumentos = parser.parse_args()
    construir(not argumentos.solo_paquete)
