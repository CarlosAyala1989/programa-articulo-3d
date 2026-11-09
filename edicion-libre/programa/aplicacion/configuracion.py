"""Configuración operativa leída del entorno de los contenedores."""

import os
import json
from pathlib import Path



URL_BASE_DATOS = os.environ.get(
    "URL_BASE_DATOS", "postgresql+psycopg://ciel:ciel_local@postgres:5432/ciel"
)
URL_REDIS = os.environ.get("URL_REDIS", "redis://redis:6379/0")
URL_SUPERVISOR = os.environ.get("URL_SUPERVISOR", "http://supervisor:8100")
URL_EVALUADOR = os.environ.get("URL_EVALUADOR", "http://evaluador:8200")
URL_OLLAMA = os.environ.get("URL_OLLAMA", "http://host.docker.internal:11434")
DIRECTORIO_ARTEFACTOS = os.environ.get("DIRECTORIO_ARTEFACTOS", "/datos")
DIRECTORIO_RESULTADOS = os.environ.get("DIRECTORIO_RESULTADOS", "/salida")
MODELOS_LOCALES = {
    "L01": {"nombre": "Qwen 3.5 0.8B", "cuantizacion": "Q8_0", "variable": "OLLAMA_L01"},
    "L02": {"nombre": "Qwen 3.5 2B", "cuantizacion": "Q8_0", "variable": "OLLAMA_L02"},
    "L03": {"nombre": "Gemma 3 4B IT", "cuantizacion": "Q5_K_M", "variable": "OLLAMA_L03"},
    "L04": {"nombre": "Ministral 3 3B Instruct", "cuantizacion": "Q6_K", "variable": "OLLAMA_L04"},
    "L05": {"nombre": "SmolLM3 3B", "cuantizacion": "Q6_K", "variable": "OLLAMA_L05"},
}
MODO_NATIVO = os.environ.get("CIEL_MODO_NATIVO") == "1"
PERFIL_NATIVO = None
if MODO_NATIVO:
    _directorio_datos = Path(__file__).resolve().parents[1] / "datos"
    _perfiles_windows = json.loads((_directorio_datos /
        "modelos_windows_nativos_v1.json").read_text(encoding="utf-8"))
    PERFIL_NATIVO = json.loads((_directorio_datos /
        "perfiles_generacion_nativos_v2.json").read_text(encoding="utf-8"))
    MODELOS_LOCALES = {m["codigo"]: {"nombre": m["nombre"], "cuantizacion": m["cuantizacion"],
        "variable": "OLLAMA_" + m["codigo"]} for m in _perfiles_windows["modelos"]}
    _registro = Path(os.environ["CIEL_REGISTRO_MODELOS"]) if os.environ.get("CIEL_REGISTRO_MODELOS") else None
    if _registro and _registro.is_file():
        _inventario = json.loads(_registro.read_text(encoding="utf-8"))
        # Mantener los códigos históricos para poder consultar resultados antiguos.
        for _codigo, _modelo in _inventario.get("modelos", {}).items():
            MODELOS_LOCALES[_codigo] = {"nombre": _modelo["nombre"], "cuantizacion": _modelo["cuantizacion"],
                                      "variable": "OLLAMA_" + _codigo}
        for _codigo, _perfil in MODELOS_LOCALES.items():
            os.environ[_perfil["variable"]] = _inventario.get("modelos", {}).get(_codigo, {}).get("etiqueta", "")
MOTORES_DISPONIBLES = {
    "cadquery": "CadQuery",
    "build123d": "build123d",
    "freecad": "FreeCAD Python API",
}
MAXIMO_INTENTOS = 5
VERSION_PLANTILLA = "v1-edicion-libre-open-closed"
if MODO_NATIVO:
    VERSION_PLANTILLA = "ciel-nativo-windows-open-closed-v2"
PROTOCOLO_LOTE = PERFIL_NATIVO["protocolo_lote"] if MODO_NATIVO else "ciel-lote-45-v3"
MAXIMO_TOKENS_SALIDA = PERFIL_NATIVO["num_predict"] if MODO_NATIVO else 8000
TIMEOUT_OLLAMA_SEGUNDOS = PERFIL_NATIVO["timeout_ollama_segundos"] if MODO_NATIVO else 10800
# El programa viaja como una variable base64 al contenedor. 90.000 bytes UTF-8
# mantienen ese argumento por debajo del límite individual del proceso Linux.
MAXIMO_BYTES_CODIGO = PERFIL_NATIVO["maximo_bytes_codigo"] if MODO_NATIVO else 90000


def resolver_esfuerzo(modelo: str, esfuerzo_razonamiento: str | None = None) -> None:
    if modelo not in MODELOS_LOCALES:
        raise ValueError("Selecciona un modelo local de Ollama disponible")
    if esfuerzo_razonamiento is not None:
        raise ValueError("Los perfiles locales tienen parámetros fijados; no admiten niveles de esfuerzo")
    return None


def perfil_generacion(modelo: str, esfuerzo_razonamiento: str | None = None,
                      maximo_tokens: int | None = None) -> dict:
    resolver_esfuerzo(modelo, esfuerzo_razonamiento)
    if maximo_tokens is not None:
        raise ValueError("Esta edición usa el perfil local fijado")
    return {"version": PERFIL_NATIVO["version"] if MODO_NATIVO else "ciel-libre-v1", "temperatura": 0.2, "top_p": 0.9,
            "repeat_penalty": 1.05, "num_predict": MAXIMO_TOKENS_SALIDA,
            "num_ctx": PERFIL_NATIVO["contextos"].get(modelo, 16384) if MODO_NATIVO else 16384, "keep_alive": 0}
