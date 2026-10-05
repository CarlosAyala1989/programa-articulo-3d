"""Configuración operativa leída del entorno de los contenedores."""

import os


URL_BASE_DATOS = os.environ.get(
    "URL_BASE_DATOS", "postgresql+psycopg://ciel:ciel_local@postgres:5432/ciel"
)
URL_REDIS = os.environ.get("URL_REDIS", "redis://redis:6379/0")
URL_SUPERVISOR = os.environ.get("URL_SUPERVISOR", "http://supervisor:8100")
URL_EVALUADOR = os.environ.get("URL_EVALUADOR", "http://evaluador:8200")
URL_DEEPSEEK = "https://api.deepseek.com"
URL_OLLAMA = os.environ.get("URL_OLLAMA", "http://host.docker.internal:11434")
DIRECTORIO_ARTEFACTOS = os.environ.get("DIRECTORIO_ARTEFACTOS", "/datos")
MODELOS_DISPONIBLES = {
    "deepseek-flash": "DeepSeek V4.1 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
}
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
VERSION_PLANTILLA = "v5-formas-organicas-avanzadas"
MAXIMO_TOKENS_SALIDA = 8000
MAXIMO_TOKENS_DEEPSEEK = 393216
TIEMPO_ESPERA_DEEPSEEK_SEGUNDOS = 10800
TOKENS_ENTRADA_PLANIFICACION = 65536
# El programa viaja como una variable base64 al contenedor. 90.000 bytes UTF-8
# mantienen ese argumento por debajo del límite individual del proceso Linux.
MAXIMO_BYTES_CODIGO = 90000
ESFUERZOS_DISPONIBLES = {"low": "Bajo", "high": "Alto", "max": "Máximo"}
ESFUERZO_PREDETERMINADO = "max"


def resolver_esfuerzo(modelo: str, esfuerzo_razonamiento: str | None = None) -> str | None:
    if modelo in MODELOS_LOCALES:
        if esfuerzo_razonamiento is not None:
            raise ValueError("El nivel de esfuerzo solo está disponible para DeepSeek Flash y Pro")
        return None
    if modelo not in MODELOS_DISPONIBLES:
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
    if modelo in MODELOS_LOCALES:
        if maximo_tokens is not None:
            raise ValueError("El límite DeepSeek no corresponde a un modelo local")
        return {"temperatura": 0.2, "top_p": 0.9, "repeat_penalty": 1.05,
                "num_predict": MAXIMO_TOKENS_SALIDA}
    if maximo_tokens is not None and (
        isinstance(maximo_tokens, bool) or not isinstance(maximo_tokens, int)
        or not 1 <= maximo_tokens <= MAXIMO_TOKENS_DEEPSEEK
    ):
        raise ValueError("Límite de salida DeepSeek fuera del rango admitido")
    return {"thinking": {"type": "enabled"}, "reasoning_effort": esfuerzo,
            "max_tokens": maximo_tokens if maximo_tokens is not None else MAXIMO_TOKENS_DEEPSEEK}
