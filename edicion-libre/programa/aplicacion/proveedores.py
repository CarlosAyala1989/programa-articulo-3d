"""Edición libre: inferencia exclusivamente en los modelos de Ollama local."""

import os
import json
from pathlib import Path
import httpx

from aplicacion.configuracion import MODELOS_LOCALES, TIMEOUT_OLLAMA_SEGUNDOS, URL_OLLAMA, perfil_generacion, MODO_NATIVO
from aplicacion.proveedor_deepseek import ErrorProveedor


def modelos_configurados() -> dict:
    return {codigo: f'{perfil["nombre"]} · {perfil["cuantizacion"]} · local'
            for codigo, perfil in MODELOS_LOCALES.items()
            if os.environ.get(perfil["variable"], "").strip()}


def verificar_modelo_local(codigo: str) -> dict:
    perfil = MODELOS_LOCALES[codigo]
    etiqueta = os.environ.get(perfil["variable"], "").strip()
    if not etiqueta:
        raise ErrorProveedor(f"{codigo} no tiene etiqueta Ollama configurada")
    try:
        with httpx.Client(timeout=12, trust_env=not MODO_NATIVO) as cliente:
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
    archivo = Path(os.environ.get("CIEL_REGISTRO_MODELOS", str(Path(__file__).resolve().parents[1] / "modelos_instalados.json")))
    try:
        manifiesto = json.loads(archivo.read_text(encoding="utf-8"))
        fijado = manifiesto.get("modelos", {}).get(codigo, {})
    except (OSError, ValueError, TypeError):
        raise ErrorProveedor("No se pudo leer el registro de los modelos instalados") from None
    if manifiesto.get("estado") != "completo":
        raise ErrorProveedor("La instalación automática de modelos no está completa")
    if fijado.get("digest") != digest or fijado.get("etiqueta") != etiqueta:
        raise ErrorProveedor("La identidad del modelo cambió respecto a la instalación fijada")
    return {"etiqueta": etiqueta, "digest": digest, "cuantizacion": cuantizacion,
            "sha256_gguf": fijado.get("sha256"), "fuente": fijado.get("fuente"),
            "revision": fijado.get("revision"), "licencia": fijado.get("licencia")}


def solicitar_codigo(
    modelo: str, mensajes: list[dict[str, str]], esfuerzo_razonamiento: str | None = None,
    maximo_tokens: int | None = None,
) -> dict:
    if modelo not in MODELOS_LOCALES:
        raise ErrorProveedor("La edición libre solo permite los modelos locales instalados")
    perfil = perfil_generacion(modelo, esfuerzo_razonamiento, maximo_tokens)
    identidad = verificar_modelo_local(modelo)
    cuerpo = {
        "model": identidad["etiqueta"], "messages": mensajes, "stream": False,
        "keep_alive": perfil["keep_alive"],
        "options": {"num_ctx": perfil["num_ctx"], "temperature": perfil["temperatura"],
                    "top_p": perfil["top_p"], "repeat_penalty": perfil["repeat_penalty"],
                    "num_predict": perfil["num_predict"]},
    }
    muestreador = None
    telemetria = None
    if MODO_NATIVO:
        from nativo.telemetria import Muestreador
        muestreador = Muestreador(identidad["etiqueta"])
        muestreador.iniciar()
    try:
        with httpx.Client(timeout=httpx.Timeout(TIMEOUT_OLLAMA_SEGUNDOS, connect=12.0), trust_env=not MODO_NATIVO) as cliente:
            respuesta_http = cliente.post(f"{URL_OLLAMA}/api/chat", json=cuerpo)
            respuesta_http.raise_for_status()
            datos = respuesta_http.json()
            contenido = datos["message"].get("content") or ""
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        raise ErrorProveedor(f"Ollama no respondió correctamente: {type(error).__name__}") from error
    finally:
        if muestreador:
            telemetria = muestreador.finalizar()
    return {
        "texto": contenido,
        "modelo_informado": datos.get("model", identidad["etiqueta"]),
        "tokens_entrada": datos.get("prompt_eval_count") or 0,
        "tokens_salida": datos.get("eval_count") or 0,
        "finalizacion": datos.get("done_reason") or "desconocida",
        "proveedor": "ollama",
        **({"metadatos_ollama": {k: v for k, v in datos.items() if k != "message"},
            "razonamiento_ollama": datos["message"].get("thinking"), "telemetria_ollama": telemetria} if MODO_NATIVO else {}),
        "perfil": {**identidad, **perfil, "contexto": perfil["num_ctx"]},
    }
