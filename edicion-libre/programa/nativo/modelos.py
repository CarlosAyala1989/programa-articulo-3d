"""Inventario local de Ollama; descubrir modelos no descarga pesos ni infiere."""

import hashlib
import json
import re
from pathlib import Path

import httpx


def registrar_modelos(programa: Path, destino: Path) -> dict:
    perfiles = json.loads((programa / "datos/modelos_windows_nativos_v1.json").read_text(encoding="utf-8"))
    conocidos = {p["etiqueta"].casefold(): p for p in perfiles["modelos"]}
    resultado = {"version": "ciel-inventario-ollama-v2", "estado": "completo", "modelos": {}, "avisos": []}
    # El inventario puede cambiar. Cada campaña conserva y verifica su propio digest.
    with httpx.Client(base_url="http://127.0.0.1:11434", timeout=30, trust_env=False) as cliente:
        try:
            respuesta = cliente.get("/api/tags")
            respuesta.raise_for_status()
            modelos = respuesta.json()["models"]
        except (httpx.HTTPError, ValueError, KeyError) as error:
            modelos = []
            resultado["avisos"].append(f"Ollama no está disponible ({type(error).__name__}). Abre Ollama y vuelve a abrir la aplicación.")
        for actual in sorted(modelos, key=lambda m: m.get("name", m.get("model", ""))):
            etiqueta = actual.get("name") or actual.get("model")
            if not etiqueta:
                continue
            digest = actual.get("digest", "")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                resultado["avisos"].append(f"{etiqueta}: Ollama no informa un digest completo; no se puede seleccionar.")
                continue
            cuantizacion = str((actual.get("details") or {}).get("quantization_level") or "DESCONOCIDA").upper()
            conocido = conocidos.get(etiqueta.casefold())
            # Una variante conserva una identidad independiente del protocolo histórico.
            if conocido and cuantizacion == conocido["cuantizacion"]:
                perfil = conocido
            else:
                perfil = {"codigo": "O" + hashlib.sha256(etiqueta.encode()).hexdigest()[:16],
                          "nombre": etiqueta, "cuantizacion": cuantizacion}
            datos = {}
            try:
                detalle = cliente.post("/api/show", json={"model": etiqueta})
                detalle.raise_for_status()
                datos = detalle.json()
            except (httpx.HTTPError, ValueError) as error:
                resultado["avisos"].append(f"No se pudo consultar el detalle de {etiqueta}: {type(error).__name__}")
            blobs = re.findall(r"sha256[-:]([0-9a-f]{64})", datos.get("modelfile", ""))
            resultado["modelos"][perfil["codigo"]] = {
                **perfil, "etiqueta": etiqueta, "digest": digest,
                "detalles": actual.get("details"), "tamano_bytes": actual.get("size"),
                "sha256": blobs[0] if blobs else None, "blobs_modelfile": blobs,
                "fuente": "Ollama local del usuario; identidad verificada al iniciar cada campaña",
                "plantilla_sha256": hashlib.sha256(datos.get("template", "").encode()).hexdigest(),
                "ollama_show": datos,
            }
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".tmp")
    temporal.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporal.replace(destino)
    return resultado
