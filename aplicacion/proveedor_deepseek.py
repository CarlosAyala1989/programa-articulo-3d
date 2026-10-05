"""Cliente de DeepSeek: solo el trabajador conoce la clave API."""

import os
import time

import httpx

from aplicacion.configuracion import MODELOS_DISPONIBLES, URL_DEEPSEEK, perfil_generacion


class ErrorProveedor(Exception):
    """Fallo operativo externo que no consume otro intento científico."""


def solicitar_codigo(modelo: str, mensajes: list[dict[str, str]], esfuerzo_razonamiento: str | None = None) -> dict:
    if modelo not in MODELOS_DISPONIBLES:
        raise ErrorProveedor("El modelo solicitado no está habilitado")
    clave = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not clave:
        raise ErrorProveedor("Falta configurar la clave de DeepSeek en el trabajador")

    cuerpo = {
        "model": modelo,
        "messages": mensajes,
        "stream": False,
        **perfil_generacion(modelo, esfuerzo_razonamiento),
    }
    encabezados = {"Authorization": f"Bearer {clave}"}
    # Los reintentos de transporte nunca se cuentan como otra generación CAD.
    with httpx.Client(timeout=httpx.Timeout(1800.0, connect=12.0)) as cliente:
        for numero_transporte in range(2):
            try:
                respuesta = cliente.post(
                    f"{URL_DEEPSEEK}/chat/completions", json=cuerpo, headers=encabezados
                )
            except httpx.ReadTimeout as error:
                # La petición ya pudo ser facturada. No duplicar una generación
                # larga cuyo desenlace no conocemos.
                raise ErrorProveedor("DeepSeek excedió el tiempo de espera; revisar la llamada antes de repetirla") from error
            except httpx.HTTPError as error:
                if numero_transporte == 0:
                    time.sleep(2)
                    continue
                raise ErrorProveedor(f"No se pudo contactar DeepSeek: {type(error).__name__}") from error
            if respuesta.status_code in (429, 502, 503, 504) and numero_transporte == 0:
                time.sleep(2)
                continue
            if respuesta.status_code != 200:
                raise ErrorProveedor(f"DeepSeek respondió HTTP {respuesta.status_code}")
            try:
                datos = respuesta.json()
                eleccion = datos["choices"][0]
                contenido = eleccion["message"].get("content") or ""
                consumo = datos.get("usage") or {}
            except (ValueError, KeyError, IndexError, TypeError) as error:
                raise ErrorProveedor("La respuesta de DeepSeek no tiene el formato esperado") from error
            return {
                "texto": contenido,
                "modelo_informado": datos.get("model", modelo),
                "tokens_entrada": consumo.get("prompt_tokens") or 0,
                "tokens_salida": consumo.get("completion_tokens") or 0,
                "finalizacion": eleccion.get("finish_reason") or "desconocida",
            }
    raise ErrorProveedor("No se obtuvo una respuesta de DeepSeek")
