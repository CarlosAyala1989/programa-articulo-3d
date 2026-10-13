"""Router de roles Quality Loop con CLI de suscripción y NVIDIA opcional."""

import json
from types import SimpleNamespace

from pydantic import ValidationError

from aplicacion.calidad.nvidia import ErrorNvidia, ProveedorNvidia, _contenido_json, catalogo_roles
from aplicacion.cli_suscripcion import ErrorCLI, proveedor_cli
from aplicacion.proveedor_suscripcion import modelos_cli_configurados, solicitar_cli


def rutas_revision(proveedor: str) -> dict:
    rutas = catalogo_roles()
    if proveedor == "nvidia":
        return rutas
    for rol in ("planificador", "revisor_codigo", "juez_textual", "revisor_visual"):
        if rol == "revisor_visual" and proveedor_cli(proveedor) == "antigravity-cli":
            continue
        rutas[rol] = {"modelo": proveedor}
        if rol in {"planificador", "revisor_codigo"}:
            rutas[rol]["alternativo"] = proveedor
    return rutas


def validar_revisores(proveedor: str, nvidia_disponible: bool) -> None:
    origen = proveedor_cli(proveedor)
    if proveedor != "nvidia" and origen is None:
        raise ValueError("Proveedor de revisores no reconocido")
    if proveedor != "nvidia" and proveedor not in modelos_cli_configurados():
        raise ValueError("El CLI seleccionado para los revisores no está habilitado")
    if (proveedor == "nvidia" or origen == "antigravity-cli") and not nvidia_disponible:
        raise ValueError("Esta configuración requiere NVIDIA para la revisión visual")
    if origen == "codex-cli" and "::" in proveedor:
        from aplicacion.proveedor_suscripcion import catalogos_cli
        detalle = catalogos_cli().get(origen, {}).get("modelos", {}).get(proveedor, {})
        if "image" not in detalle.get("modalidades", []):
            raise ValueError("El modelo revisor Codex seleccionado no anuncia entrada de imágenes")


class ProveedorRolesSuscripcion:
    def __init__(self):
        self.nvidia = ProveedorNvidia()
        self.llamadas = 0

    def generar_estructurado(self, modelo, sistema, solicitud, esquema,
                             maximo_tokens=8192, imagenes_png=None):
        self.llamadas += 1
        if not proveedor_cli(modelo):
            return self.nvidia.generar_estructurado(
                modelo, sistema, solicitud, esquema, maximo_tokens, imagenes_png
            )
        mensajes = [{"role": "system", "content": sistema},
                    {"role": "user", "content": solicitud + "\n\nESQUEMA JSON:\n"
                     + json.dumps(esquema.model_json_schema(), ensure_ascii=False)}]
        try:
            respuesta = solicitar_cli(modelo, mensajes, imagenes_png)
            validada = esquema.model_validate(_contenido_json(respuesta["texto"]))
        except ErrorCLI as error:
            raise ErrorNvidia(str(error), error.codigo) from None
        except (ValidationError, ErrorNvidia, TypeError, ValueError):
            raise ErrorNvidia("El CLI no devolvió JSON conforme al esquema del rol", "malformed_response") from None
        perfil = respuesta["perfil"]
        return validada, SimpleNamespace(
            texto=respuesta["texto"], modelo=respuesta["modelo_informado"] or "",
            modelo_solicitado=modelo,
            proveedor=proveedor_cli(modelo), tokens_entrada=respuesta["tokens_entrada"],
            tokens_salida=respuesta["tokens_salida"], finalizacion=respuesta["finalizacion"],
            latencia_segundos=perfil["latencia_segundos"], request_id=perfil.get("request_id"),
            perfil=perfil,
        )
