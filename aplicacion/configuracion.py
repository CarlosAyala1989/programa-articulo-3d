"""Configuración operativa leída del entorno de los contenedores."""

import os
import re

from aplicacion.cli_suscripcion import proveedor_cli, perfil_cli, validar_esfuerzo_cli


URL_BASE_DATOS = os.environ.get(
    "URL_BASE_DATOS", "postgresql+psycopg://ciel:ciel_local@postgres:5432/ciel"
)
URL_REDIS = os.environ.get("URL_REDIS", "redis://redis:6379/0")
URL_SUPERVISOR = os.environ.get("URL_SUPERVISOR", "http://supervisor:8100")
URL_EVALUADOR = os.environ.get("URL_EVALUADOR", "http://evaluador:8200")
URL_DEEPSEEK = "https://api.deepseek.com"
NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
URL_OLLAMA = os.environ.get("URL_OLLAMA", "http://host.docker.internal:11434")
DIRECTORIO_ARTEFACTOS = os.environ.get("DIRECTORIO_ARTEFACTOS", "/datos")
MODELOS_DISPONIBLES = {
    "deepseek-flash": "DeepSeek V4.1 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
}
MODELOS_NVIDIA_CATALOGO = {
    "nvidia/nemotron-3-ultra-550b-a55b": "Nemotron 3 Ultra 550B · Planner",
    "nvidia/nemotron-3-super-120b-a12b": "Nemotron 3 Super 120B · Planner/Judge",
    "poolside/laguna-xs-2.1": "Laguna XS 2.1 · Revisor de código experimental",
    "moonshotai/kimi-k3": "Kimi K3 · Revisor visual",
    "deepseek-ai/deepseek-v4.1-flash": "DeepSeek V4.1 Flash · Endpoint NVIDIA experimental",
    "z-ai/glm-5.3": "GLM 5.3 · Juez textual",
    "google/gemma-4-31b-it": "Gemma 4 31B · Generación CAD",
}
MODELOS_NVIDIA_GENERADORES = {
    "nvidia/nemotron-3-super-120b-a12b": "NVIDIA NIM · Nemotron 3 Super (código)",
    "moonshotai/kimi-k3": "NVIDIA NIM · Kimi K3 (código alternativo)",
    "google/gemma-4-31b-it": "NVIDIA NIM · Gemma 4 31B (código)",
    "z-ai/glm-5.3": "NVIDIA NIM · GLM 5.3 (código)",
}
ESFUERZOS_RAZONAMIENTO_GENERACION_NVIDIA = {
    "nvidia/nemotron-3-super-120b-a12b": "low",
    "nvidia/nemotron-3-ultra-550b-a55b": "medium",
}
MODELOS_RESPALDO_GENERACION_NVIDIA = {
    "nvidia/nemotron-3-super-120b-a12b": "deepseek-v4-pro",
    "moonshotai/kimi-k3": "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3-ultra-550b-a55b": "nvidia/nemotron-3-super-120b-a12b",
    "google/gemma-4-31b-it": "z-ai/glm-5.3",
    "z-ai/glm-5.3": "google/gemma-4-31b-it",
}
try:
    NVIDIA_GENERACION_TIMEOUT_SEGUNDOS = max(30, min(300,
        int(os.environ.get("NVIDIA_GENERACION_TIMEOUT_SEGUNDOS", "90"))))
except ValueError:
    NVIDIA_GENERACION_TIMEOUT_SEGUNDOS = 90
MODELO_COSMOS_EXPERIMENTAL = os.environ.get("NVIDIA_MODEL_VISUAL_REASONER", "").strip()
QUALITY_ALLOW_REFERENCE_METRICS = os.environ.get("QUALITY_ALLOW_REFERENCE_METRICS", "0") == "1"
try:
    MAXIMO_LLAMADAS_QUALITY_LOOP = max(1, min(100, int(os.environ.get("MAXIMO_LLAMADAS_QUALITY_LOOP", "40"))))
except ValueError:
    MAXIMO_LLAMADAS_QUALITY_LOOP = 40
try:
    MAXIMO_TOKENS_QUALITY_LOOP = max(1, min(5_000_000,
        int(os.environ.get("MAXIMO_TOKENS_QUALITY_LOOP", "800000"))))
except ValueError:
    MAXIMO_TOKENS_QUALITY_LOOP = 800000
try:
    MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR = max(4096, min(131072,
        int(os.environ.get("MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR", "32768"))))
except ValueError:
    MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR = 32768
MAXIMO_ITERACIONES_QUALITY_LOOP = 3
NVIDIA_MODEL_PLANNER = os.environ.get(
    "NVIDIA_MODEL_PLANNER", "nvidia/nemotron-3-super-120b-a12b"
)
NVIDIA_MODEL_PLANNER_FALLBACK = os.environ.get(
    "NVIDIA_MODEL_PLANNER_FALLBACK", "moonshotai/kimi-k3"
)
NVIDIA_MODEL_CODE_REVIEWER = os.environ.get("NVIDIA_MODEL_CODE_REVIEWER", "nvidia/nemotron-3-super-120b-a12b")
NVIDIA_MODEL_CODE_REVIEWER_FALLBACK = os.environ.get(
    "NVIDIA_MODEL_CODE_REVIEWER_FALLBACK", "z-ai/glm-5.3"
)
NVIDIA_MODEL_VISUAL_REVIEWER = os.environ.get("NVIDIA_MODEL_VISUAL_REVIEWER", "moonshotai/kimi-k3")
NVIDIA_MODEL_GENERATOR = os.environ.get("NVIDIA_MODEL_GENERATOR", "nvidia/nemotron-3-super-120b-a12b")
NVIDIA_MODEL_TEXT_JUDGE = os.environ.get("NVIDIA_MODEL_TEXT_JUDGE", "nvidia/nemotron-3-super-120b-a12b")
_MODELOS_NVIDIA_CONFIGURADOS = {
    NVIDIA_MODEL_PLANNER, NVIDIA_MODEL_PLANNER_FALLBACK, NVIDIA_MODEL_CODE_REVIEWER,
    NVIDIA_MODEL_CODE_REVIEWER_FALLBACK,
    NVIDIA_MODEL_VISUAL_REVIEWER, NVIDIA_MODEL_GENERATOR, NVIDIA_MODEL_TEXT_JUDGE,
}
if MODELO_COSMOS_EXPERIMENTAL:
    _MODELOS_NVIDIA_CONFIGURADOS.add(MODELO_COSMOS_EXPERIMENTAL)
MODELOS_NVIDIA_REGISTRADOS = frozenset(MODELOS_NVIDIA_CATALOGO) | frozenset(
    modelo for modelo in _MODELOS_NVIDIA_CONFIGURADOS
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*", modelo)
)
MODELOS_LOCALES = {
    "L01": {"nombre": "Qwen 3.5 0.8B", "cuantizacion": "Q8_0", "variable": "OLLAMA_L01"},
    "L02": {"nombre": "Qwen 3.5 2B", "cuantizacion": "Q8_0", "variable": "OLLAMA_L02"},
    "L03": {"nombre": "Gemma 3 4B", "cuantizacion": "Q5_K_M", "variable": "OLLAMA_L03"},
    "L04": {"nombre": "Ministral 3 3B", "cuantizacion": "Q6_K", "variable": "OLLAMA_L04"},
    "L05": {"nombre": "SmolLM3 3B", "cuantizacion": "Q6_K", "variable": "OLLAMA_L05"},
}
MOTORES_DISPONIBLES = {
    "cadquery": "CadQuery",
    "build123d": "build123d",
    "freecad": "FreeCAD Python API",
}
MAXIMO_INTENTOS = 5
VERSION_PLANTILLA = "v6-quality-loop-geometric-plan"
MAXIMO_TOKENS_SALIDA = 8000
MAXIMO_TOKENS_NVIDIA = 8192
MAXIMO_TOKENS_DEEPSEEK = 393216
TIEMPO_ESPERA_DEEPSEEK_SEGUNDOS = 10800
TOKENS_ENTRADA_PLANIFICACION = 65536
# El programa viaja como una variable base64 al contenedor. 90.000 bytes UTF-8
# mantienen ese argumento por debajo del límite individual del proceso Linux.
MAXIMO_BYTES_CODIGO = 90000
ESFUERZOS_DISPONIBLES = {"low": "Bajo", "high": "Alto", "max": "Máximo"}
ESFUERZO_PREDETERMINADO = "max"


def resolver_esfuerzo(modelo: str, esfuerzo_razonamiento: str | None = None) -> str | None:
    if proveedor_cli(modelo):
        if esfuerzo_razonamiento is None:
            return None
        from aplicacion.proveedor_suscripcion import catalogos_cli
        detalle = catalogos_cli().get(proveedor_cli(modelo), {}).get("modelos", {}).get(modelo, {})
        return validar_esfuerzo_cli(modelo, esfuerzo_razonamiento, detalle)
    if modelo in MODELOS_LOCALES:
        if esfuerzo_razonamiento is not None:
            raise ValueError("El nivel de esfuerzo solo está disponible para DeepSeek Flash y Pro")
        return None
    if modelo not in MODELOS_DISPONIBLES:
        if modelo in MODELOS_NVIDIA_REGISTRADOS:
            if esfuerzo_razonamiento is not None:
                raise ValueError("El esfuerzo configurable se ofrece solo para los modelos DeepSeek directos")
            return None
        raise ValueError("Modelo de IA no reconocido")
    esfuerzo = esfuerzo_razonamiento if esfuerzo_razonamiento is not None else ESFUERZO_PREDETERMINADO
    if esfuerzo not in ESFUERZOS_DISPONIBLES:
        raise ValueError("Nivel de esfuerzo no reconocido; usa low, high o max")
    return esfuerzo


def perfil_generacion(
    modelo: str, esfuerzo_razonamiento: str | None = None,
    maximo_tokens: int | None = None,
) -> dict:
    esfuerzo = resolver_esfuerzo(modelo, esfuerzo_razonamiento)
    if proveedor_cli(modelo):
        if maximo_tokens is not None:
            raise ValueError("Los CLI de suscripción no admiten el límite de tokens DeepSeek")
        return perfil_cli(modelo, esfuerzo)
    if modelo in MODELOS_LOCALES:
        if maximo_tokens is not None:
            raise ValueError("El límite DeepSeek no corresponde a un modelo local")
        return {"temperatura": 0.2, "top_p": 0.9, "repeat_penalty": 1.05,
                "num_predict": MAXIMO_TOKENS_SALIDA}
    if modelo in MODELOS_NVIDIA_REGISTRADOS:
        if maximo_tokens is not None:
            raise ValueError("El límite DeepSeek no corresponde al endpoint NVIDIA NIM")
        return {"max_tokens": MAXIMO_TOKENS_NVIDIA, "temperature": 0.1,
                "reasoning_effort": ESFUERZOS_RAZONAMIENTO_GENERACION_NVIDIA.get(modelo)}
    if maximo_tokens is not None and (
        isinstance(maximo_tokens, bool) or not isinstance(maximo_tokens, int)
        or not 1 <= maximo_tokens <= MAXIMO_TOKENS_DEEPSEEK
    ):
        raise ValueError("Límite de salida DeepSeek fuera del rango admitido")
    return {"thinking": {"type": "enabled"}, "reasoning_effort": esfuerzo,
            "max_tokens": maximo_tokens if maximo_tokens is not None else MAXIMO_TOKENS_DEEPSEEK}
