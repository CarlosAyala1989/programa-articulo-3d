"""Descarga e importa cinco GGUF fijados; no ejecuta inferencias durante la instalación."""

import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


URL_OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")


def huella(ruta: Path) -> str:
    resumen = hashlib.sha256()
    with ruta.open("rb") as entrada:
        for fragmento in iter(lambda: entrada.read(8 * 1024 * 1024), b""):
            resumen.update(fragmento)
    return resumen.hexdigest()


def consultar(ruta: str, datos: dict | None = None) -> dict:
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    solicitud = urllib.request.Request(URL_OLLAMA + ruta, data=cuerpo,
                                      headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(solicitud, timeout=120) as respuesta:
        return json.load(respuesta)


def verificar_modelos(manifiesto: dict, instalados: dict) -> None:
    actuales = {m["name"]: m for m in consultar("/api/tags")["models"]}
    for modelo in manifiesto["modelos"]:
        anterior = instalados.get("modelos", {}).get(modelo["codigo"], {})
        actual = actuales.get(modelo["etiqueta"], {})
        if not anterior.get("digest") or actual.get("digest") != anterior["digest"]:
            raise RuntimeError(f"Falta el modelo fijado {modelo['nombre']}; vuelve a abrir el instalador para repararlo")
        if (actual.get("details") or {}).get("quantization_level") != modelo["cuantizacion"]:
            raise RuntimeError(f"Cuantización incorrecta en {modelo['nombre']}")


def preparar(base: Path, descargas: Path, verificar: bool = False) -> None:
    activos = base / "datos/modelos_libres"
    manifiesto = json.loads((activos / "modelos.json").read_text(encoding="utf-8"))
    if len(manifiesto["modelos"]) != 5:
        raise RuntimeError("Esta versión necesita exactamente cinco modelos")
    destino = base / "modelos_instalados.json"
    instalado = json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {}
    if instalado.get("estado") == "completo":
        try:
            verificar_modelos(manifiesto, instalado)
            print("Los cinco modelos conservan su identidad", flush=True)
            return
        except RuntimeError:
            if verificar:
                raise
    if verificar:
        raise RuntimeError("La descarga inicial de modelos no terminó")
    descargas.mkdir(parents=True, exist_ok=True)
    resultado = {"version": manifiesto["version"], "estado": "descargando",
                 "contexto": manifiesto["contexto"], "modelos": {}}
    for modelo in manifiesto["modelos"]:
        print(f"Preparando {modelo['nombre']} · {modelo['cuantizacion']}", flush=True)
        anterior = instalado.get("modelos", {}).get(modelo["codigo"], {})
        actuales = {m["name"]: m for m in consultar("/api/tags")["models"]}
        actual_anterior = actuales.get(modelo["etiqueta"], {})
        if (anterior.get("sha256") == modelo["sha256"] and anterior.get("digest")
                and actual_anterior.get("digest") == anterior["digest"]
                and (actual_anterior.get("details") or {}).get("quantization_level") == modelo["cuantizacion"]):
            resultado["modelos"][modelo["codigo"]] = anterior
            continue
        plantilla = activos / modelo["plantilla"]
        licencia = activos / modelo["licencia_archivo"]
        for ruta, esperado in ((plantilla, modelo["plantilla_sha256"]), (licencia, modelo["licencia_sha256"])):
            if huella(ruta) != esperado:
                raise RuntimeError("La plantilla o licencia del modelo no coincide con el paquete")
        peso = descargas / (modelo["codigo"] + ".gguf")
        if not peso.exists() or huella(peso) != modelo["sha256"]:
            parcial = peso.with_suffix(".gguf.parcial")
            # curl puede reanudar un archivo parcial; un archivo completo incorrecto no se reutiliza.
            subprocess.run(["curl", "--fail", "--location", "--retry", "5", "--retry-delay", "3",
                            "--connect-timeout", "30", "--continue-at", "-",
                            "--output", str(parcial), modelo["url"]], check=True)
            if parcial.stat().st_size != modelo["bytes"] or huella(parcial) != modelo["sha256"]:
                parcial.unlink(missing_ok=True)
                raise RuntimeError(f"SHA-256 incorrecto en {modelo['nombre']}; la descarga no se importa")
            with parcial.open("rb") as entrada:
                if entrada.read(4) != b"GGUF":
                    raise RuntimeError("El archivo descargado no es GGUF")
            parcial.replace(peso)
        texto = (f'FROM "{peso}"\nTEMPLATE """{plantilla.read_text(encoding="utf-8")}"""\n'
                 f'LICENSE """{licencia.read_text(encoding="utf-8")}"""\n'
                 f'PARAMETER num_ctx {manifiesto["contexto"]}\nPARAMETER temperature 0.2\n'
                 'PARAMETER top_p 0.9\nPARAMETER repeat_penalty 1.05\n')
        for parada in modelo.get("paradas", []):
            texto += "PARAMETER stop " + json.dumps(parada, ensure_ascii=False) + "\n"
        archivo_modelo = descargas / (modelo["codigo"] + ".Modelfile")
        archivo_modelo.write_text(texto, encoding="utf-8")
        subprocess.run(["ollama", "create", modelo["etiqueta"], "-f", str(archivo_modelo)], check=True)
        actual = next((m for m in consultar("/api/tags")["models"]
                       if m["name"] == modelo["etiqueta"]), None)
        if actual is None or (actual.get("details") or {}).get("quantization_level") != modelo["cuantizacion"]:
            raise RuntimeError(f"Ollama no confirmó la cuantización de {modelo['nombre']}")
        resultado["modelos"][modelo["codigo"]] = {**modelo, "digest": actual["digest"],
            "detalles": actual["details"], "fecha_instalacion": int(time.time())}
        temporal = destino.with_suffix(".json.tmp")
        temporal.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporal.replace(destino)
        # Ollama ya conserva el blob: evitar otra copia de varios GB en la carpeta de descarga.
        peso.unlink()
    resultado["estado"] = "completo"
    temporal = destino.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporal.replace(destino)
    verificar_modelos(manifiesto, resultado)


if __name__ == "__main__":
    argumentos = argparse.ArgumentParser(description="Preparar modelos fijados de Agente Ciel Libre")
    argumentos.add_argument("--base", type=Path, default=Path(__file__).resolve().parent)
    argumentos.add_argument("--descargas", type=Path, default=Path("/var/lib/agente-ciel/descargas"))
    argumentos.add_argument("--verificar", action="store_true")
    opciones = argumentos.parse_args()
    preparar(opciones.base, opciones.descargas, opciones.verificar)
