"""Adaptadores de inferencia con identidad comprobada del modelo local."""

import os

import httpx

from aplicacion.configuracion import MAXIMO_TOKENS_SALIDA, MODELOS_DISPONIBLES, MODELOS_LOCALES, URL_OLLAMA, perfil_generacion
from aplicacion.proveedor_deepseek import ErrorProveedor, solicitar_codigo as solicitar_deepseek


def modelos_configurados() -> dict:
    resultado = dict(MODELOS_DISPONIBLES)
    for codigo, perfil in MODELOS_LOCALES.items():
        if os.environ.get(perfil["variable"], "").strip():
            resultado[codigo] = f'{perfil["nombre"]} — {perfil["cuantizacion"]} (Ollama)'
    return resultado


def verificar_modelo_local(codigo: str) -> dict:
    perfil = MODELOS_LOCALES[codigo]
    etiqueta = os.environ.get(perfil["variable"], "").strip()
    if not etiqueta:
        raise ErrorProveedor(f"{codigo} no tiene etiqueta Ollama configurada")
    try:
        with httpx.Client(timeout=12) as cliente:
            respuesta = cliente.get(f"{URL_OLLAMA}/api/tags")
            respuesta.raise_for_status()
            modelos = respuesta.json()["models"]
    except (httpx.HTTPError, ValueError, KeyError) as error:
        raise ErrorProveedor(f"Ollama no está disponible: {type(error).__name__}") from error
    encontrado = next((modelo for modelo in modelos if etiqueta in {modelo.get("name"), modelo.get("model")}), None)
    if encontrado is None:
        raise ErrorProveedor(f"El modelo {etiqueta} no está instalado en Ollama")
    cuantizacion = str((encontrado.get("details") or {}).get("quantization_level", ""))
    if cuantizacion.upper() != perfil["cuantizacion"]:
        raise ErrorProveedor(
            f"{codigo} exige {perfil['cuantizacion']} y Ollama informa {cuantizacion or 'desconocida'}"
        )
    digest = encontrado.get("digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ErrorProveedor(f"{codigo} no tiene digest verificable en Ollama")
    return {"etiqueta": etiqueta, "digest": digest, "cuantizacion": cuantizacion}


def solicitar_codigo(modelo: str, mensajes: list[dict[str, str]], esfuerzo_razonamiento: str | None = None) -> dict:
    perfil = perfil_generacion(modelo, esfuerzo_razonamiento)
    if modelo in MODELOS_DISPONIBLES:
        respuesta = solicitar_deepseek(modelo, mensajes, esfuerzo_razonamiento)
        respuesta["proveedor"] = "deepseek"
        respuesta["perfil"] = {"modelo": modelo, **perfil}
        return respuesta
    if modelo not in MODELOS_LOCALES:
        raise ErrorProveedor("El modelo solicitado no está habilitado")
    identidad = verificar_modelo_local(modelo)
    cuerpo = {
        "model": identidad["etiqueta"], "messages": mensajes, "stream": False,
        "options": {"temperature": 0.2, "top_p": 0.9,
                    "repeat_penalty": 1.05, "num_predict": MAXIMO_TOKENS_SALIDA},
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=12.0)) as cliente:
            respuesta_http = cliente.post(f"{URL_OLLAMA}/api/chat", json=cuerpo)
            respuesta_http.raise_for_status()
            datos = respuesta_http.json()
            contenido = datos["message"].get("content") or ""
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        raise ErrorProveedor(f"Ollama no respondió correctamente: {type(error).__name__}") from error
    return {
        "texto": contenido,
        "modelo_informado": datos.get("model", identidad["etiqueta"]),
        "tokens_entrada": datos.get("prompt_eval_count") or 0,
        "tokens_salida": datos.get("eval_count") or 0,
        "finalizacion": datos.get("done_reason") or "desconocida",
        "proveedor": "ollama",
        "perfil": {**identidad, "temperatura": 0.2, "top_p": 0.9,
                   "repeat_penalty": 1.05, "num_predict": MAXIMO_TOKENS_SALIDA},
    }
