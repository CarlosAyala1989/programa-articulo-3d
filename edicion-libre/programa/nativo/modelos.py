"""Registrar los cinco modelos existentes de Windows sin descargarlos ni inferir."""

import hashlib
import json
import re
from pathlib import Path

import httpx


def registrar_modelos(programa: Path, destino: Path) -> dict:
    perfiles = json.loads((programa / "datos/modelos_windows_nativos_v1.json").read_text(encoding="utf-8"))
    resultado = {"version": perfiles["version"], "estado": "completo", "modelos": {}}
    anterior = json.loads(destino.read_text(encoding="utf-8")) if destino.is_file() else None
    with httpx.Client(base_url="http://127.0.0.1:11434", timeout=30, trust_env=False) as cliente:
        respuesta = cliente.get("/api/tags")
        respuesta.raise_for_status()
        modelos = {m["name"]: m for m in respuesta.json()["models"]}
        for perfil in perfiles["modelos"]:
            etiqueta = perfil["etiqueta"]
            actual = modelos.get(etiqueta)
            if actual is None:
                raise RuntimeError(f"No está instalado {etiqueta} en Ollama Windows. No se descargará automáticamente.")
            cuantizacion = str((actual.get("details") or {}).get("quantization_level", "")).upper()
            if cuantizacion != perfil["cuantizacion"]:
                raise RuntimeError(f"{etiqueta}: se esperaba {perfil['cuantizacion']}, se encontró {cuantizacion}")
            digest = actual.get("digest", "")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise RuntimeError(f"Ollama no informa un digest completo para {etiqueta}")
            fijado = (anterior or {}).get("modelos", {}).get(perfil["codigo"])
            if fijado and (fijado["digest"] != digest or fijado["etiqueta"] != etiqueta):
                raise RuntimeError(f"Cambió el modelo {etiqueta}. Conserva el modelo anterior para reanudar; una versión distinta requiere otra carpeta de resultados.")
            detalle = cliente.post("/api/show", json={"model": etiqueta})
            detalle.raise_for_status()
            datos = detalle.json()
            blobs = re.findall(r"sha256[-:]([0-9a-f]{64})", datos.get("modelfile", ""))
            resultado["modelos"][perfil["codigo"]] = {
                **perfil, "digest": digest, "detalles": actual.get("details"), "tamano_bytes": actual.get("size"),
                "sha256": blobs[0] if blobs else None, "blobs_modelfile": blobs,
                "fuente": "Ollama instalado por el usuario en Windows; identidad fijada al iniciar",
                "plantilla_sha256": hashlib.sha256(datos.get("template", "").encode()).hexdigest(),
                "ollama_show": datos,
            }
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".tmp")
    temporal.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporal.replace(destino)
    return resultado
