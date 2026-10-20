"""Ejecución local de CLI oficiales; no lee ni copia credenciales de suscripción."""

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path


MODELOS_SUSCRIPCION = {
    "codex-cli": "Codex · suscripción ChatGPT",
    "antigravity-cli": "Antigravity · suscripción Google",
}
VERSION_CLI = "ciel-cli-subscription-v3"
# Ultra activa delegación automática; este adaptador conserva un turno sin subagentes.
ESFUERZOS_CLI = {"low": "Bajo", "medium": "Medio", "high": "Alto",
                 "xhigh": "Muy alto", "max": "Máximo"}


def proveedor_cli(modelo: str) -> str | None:
    if not isinstance(modelo, str):
        return None
    proveedor, separador, identificador = modelo.partition("::")
    if proveedor not in MODELOS_SUSCRIPCION:
        return None
    if separador and (len(modelo) > 60 or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]*", identificador)):
        return None
    return proveedor


class ErrorCLI(Exception):
    def __init__(self, mensaje: str, codigo: str = "provider_error"):
        super().__init__(mensaje)
        self.codigo = codigo


def tiempo_espera_cli() -> int:
    try:
        return max(30, min(10800, int(os.environ.get("CLI_TIMEOUT_SEGUNDOS", "900"))))
    except ValueError:
        return 900


def validar_esfuerzo_cli(modelo: str, esfuerzo: str | None, detalle: dict) -> str | None:
    if esfuerzo is None:
        return None  # Conservar el comportamiento de las ejecuciones históricas sin selección.
    if esfuerzo not in ESFUERZOS_CLI or esfuerzo not in detalle.get("esfuerzos", {}):
        raise ValueError("El modelo no admite ese esfuerzo; consulta los niveles de su catálogo")
    destino = detalle.get("modelos_por_esfuerzo", {}).get(esfuerzo)
    if destino and destino != modelo:
        raise ValueError("El esfuerzo corresponde a otra variante; selecciona ese modelo concreto")
    return esfuerzo


def perfil_cli(modelo: str, esfuerzo_razonamiento: str | None = None) -> dict:
    prefijo = "CODEX" if proveedor_cli(modelo) == "codex-cli" else "ANTIGRAVITY"
    return {"version": VERSION_CLI, "autenticacion": "sesion_cli",
            "modelo_configurado": modelo.partition("::")[2] or os.environ.get(f"{prefijo}_CLI_MODELO", "").strip() or None,
            "timeout_segundos": tiempo_espera_cli(),
            "limite_tokens_aplicable": False,
            **({"reasoning_effort": esfuerzo_razonamiento} if esfuerzo_razonamiento is not None else {})}


def ejecutable_cli(modelo: str) -> str | None:
    proveedor = proveedor_cli(modelo)
    if proveedor is None:
        return None
    variable, nombre = (("CODEX_CLI_BIN", "codex") if proveedor == "codex-cli"
                        else ("ANTIGRAVITY_CLI_BIN", "agy"))
    return shutil.which(os.environ.get(variable, nombre))


def _entorno_cli() -> dict:
    entorno = dict(os.environ)
    # Una clave heredada nunca debe convertir esta ruta en consumo de API pagada.
    for nombre in ("OPENAI_API_KEY", "CODEX_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                   "DEEPSEEK_API_KEY", "NVIDIA_API_KEY", "CODEX_ACCESS_TOKEN"):
        entorno.pop(nombre, None)
    return entorno


def _terminar(proceso: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(proceso.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        proceso.kill()
    proceso.communicate()


def _ejecutar(argumentos: list[str], entrada: str, directorio: str, timeout: int) -> str:
    try:
        proceso = subprocess.Popen(
            argumentos, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", cwd=directorio, env=_entorno_cli(),
            start_new_session=os.name == "posix",
        )
    except OSError:
        raise ErrorCLI("No se pudo iniciar el CLI de suscripción; revisa su instalación") from None
    try:
        salida, _ = proceso.communicate(entrada, timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminar(proceso)
        raise ErrorCLI("Timeout del CLI; la llamada no se reenvía automáticamente", "timeout") from None
    except BaseException:
        _terminar(proceso)
        raise
    if proceso.returncode:
        # stdout/stderr pueden contener datos de sesión. No se publican ni registran.
        raise ErrorCLI(
            f"El CLI terminó con código {proceso.returncode}; revisa inicio de sesión, "
            "cuota, modelo y permisos en el terminal"
        )
    return salida


def ejecutar_cli(modelo: str, mensajes: list[dict], imagenes_png: list[bytes] | None = None,
                 esfuerzo_razonamiento: str | None = None) -> dict:
    proveedor = proveedor_cli(modelo)
    ejecutable = ejecutable_cli(modelo)
    if not ejecutable:
        raise ErrorCLI("CLI no instalado: se requiere codex o el CLI agy (no el lanzador del IDE)")
    if imagenes_png and proveedor != "codex-cli":
        raise ErrorCLI("Antigravity headless no admite adjuntos de imagen en este adaptador; usa NVIDIA o Codex")
    if esfuerzo_razonamiento is not None:
        from aplicacion.catalogo_cli import consultar_catalogo_cli
        detalle = consultar_catalogo_cli(proveedor)["modelos"].get(modelo, {})
        try:
            validar_esfuerzo_cli(modelo, esfuerzo_razonamiento, detalle)
        except ValueError as error:
            raise ErrorCLI(str(error), "invalid_effort") from None
    if not mensajes or any(m.get("role") not in {"system", "user", "assistant"}
                           or not isinstance(m.get("content"), str) for m in mensajes):
        raise ErrorCLI("Mensajes CLI inválidos")
    prompt = (
        "Resuelve exclusivamente la solicitud siguiente. Devuelve solo la respuesta final exigida "
        "(programa Python completo o JSON). No ejecutes el programa CAD, no consultes archivos "
        "externos ni uses herramientas de terminal, red, MCP o subagentes. "
        "Las imágenes adjuntas, si existen, son evidencia visual de la pieza generada.\n\n"
        + json.dumps(mensajes, ensure_ascii=False)
    )
    perfil = perfil_cli(modelo, esfuerzo_razonamiento)
    inicio = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ciel-cli-") as directorio:
        if proveedor == "codex-cli":
            # login status suele escribir en stderr: no se publica su contenido.
            try:
                comprobacion = subprocess.run(
                    [ejecutable, "login", "status"], capture_output=True, text=True,
                    env=_entorno_cli(), timeout=15, cwd=directorio,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise ErrorCLI("No se pudo comprobar la sesión de Codex") from None
            if comprobacion.returncode or "chatgpt" not in (comprobacion.stdout + comprobacion.stderr).casefold():
                raise ErrorCLI("Codex requiere iniciar sesión con ChatGPT mediante codex login")
            argumentos = [ejecutable, "exec", "--json", "--ephemeral", "--ignore-user-config",
                          "--skip-git-repo-check", "--sandbox", "read-only",
                          "-c", "approval_policy=\"never\"", "-c", "cli_auth_credentials_store=\"auto\"",
                          "-c", "features.shell_tool=false", "-c", "web_search=\"disabled\"",
                          "-c", "features.multi_agent=false"]
            for indice, imagen in enumerate(imagenes_png or []):
                ruta = Path(directorio) / f"vista_{indice}.png"
                ruta.write_bytes(imagen)
                argumentos.extend(["--image", str(ruta)])
            if perfil["modelo_configurado"]:
                argumentos.extend(["--model", perfil["modelo_configurado"]])
            if esfuerzo_razonamiento is not None:
                argumentos.extend(["-c", f'model_reasoning_effort="{esfuerzo_razonamiento}"'])
            argumentos.append("-")
            salida = _ejecutar(argumentos, prompt, directorio, perfil["timeout_segundos"])
            try:
                eventos = [json.loads(linea) for linea in salida.splitlines() if linea.strip()]
                if any(e.get("type") in {"error", "turn.failed"} for e in eventos):
                    raise ValueError
                final = next(e for e in reversed(eventos) if e.get("type") == "turn.completed")
                texto = next(e["item"]["text"] for e in reversed(eventos)
                             if e.get("type") == "item.completed"
                             and e.get("item", {}).get("type") == "agent_message")
                uso = final.get("usage") or {}
                modelo_informado = ""  # El stream exec no certifica el modelo efectivo.
                identificador = next((e.get("thread_id") for e in eventos
                                      if e.get("type") == "thread.started"), None)
            except (ValueError, KeyError, TypeError, StopIteration):
                raise ErrorCLI("Codex no devolvió un turno completo válido", "malformed_response") from None
        else:
            # Impide una configuración explícita de Gemini API; el keyring lo gestiona agy.
            ajustes = Path.home() / ".gemini/antigravity-cli/settings.json"
            try:
                if ajustes.exists() and json.loads(ajustes.read_text()).get("modelProvider") == "gemini":
                    raise ErrorCLI("Antigravity está configurado para Gemini API; selecciona la autenticación de cuenta")
            except (OSError, ValueError, AttributeError):
                raise ErrorCLI("No se pudo comprobar el proveedor de Antigravity") from None
            argumentos = [ejecutable, "--input-format", "stream-json",
                          "--output-format", "stream-json", "--mode", "plan",
                          "--disable-slash-commands", "--sandbox",
                          "--print-timeout", f"{perfil['timeout_segundos']}s"]
            if perfil["modelo_configurado"]:
                argumentos.extend(["--model", perfil["modelo_configurado"]])
            if esfuerzo_razonamiento is not None:
                argumentos.extend(["--effort", esfuerzo_razonamiento])
            entrada = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"
            salida = _ejecutar(argumentos, entrada, directorio, perfil["timeout_segundos"])
            try:
                eventos = [json.loads(linea) for linea in salida.splitlines() if linea.strip()]
                final = next(e["result"] for e in reversed(eventos) if e.get("event") == "result")
                if final.get("status") != "SUCCESS":
                    raise ValueError
                texto = final["response"]
                uso = final.get("usage") or {}
                modelo_informado = final.get("model") or ""
                identificador = final.get("conversation_id")
            except (ValueError, KeyError, TypeError, AttributeError, StopIteration):
                raise ErrorCLI("Antigravity no devolvió un resultado SUCCESS válido", "malformed_response") from None
        if not isinstance(texto, str) or not texto.strip():
            raise ErrorCLI("El CLI devolvió una respuesta vacía", "malformed_response")
        try:
            tokens_entrada = max(0, int(uso.get("input_tokens") or 0))
            tokens_salida = max(0, int(uso.get("output_tokens") or 0))
        except (ValueError, TypeError, AttributeError):
            raise ErrorCLI("El CLI devolvió un consumo malformado", "malformed_response") from None
        return {"texto": texto, "modelo_informado": modelo_informado,
                "tokens_entrada": tokens_entrada,
                "tokens_salida": tokens_salida, "finalizacion": "stop",
                "proveedor": proveedor, "perfil": {**perfil,
                    "latencia_segundos": time.monotonic() - inicio, "request_id": identificador,
                    "tokens_razonamiento": uso.get("thinking_tokens") or uso.get("reasoning_output_tokens"),
                    "consumo_desconocido": not bool(uso),
                    "modelo_verificado": bool(modelo_informado)}}
