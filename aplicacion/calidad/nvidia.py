"""Cliente NIM de NVIDIA y router de roles; nunca reintenta inferencias inciertas."""

import base64
import json
import os
import time
from dataclasses import asdict, dataclass

import httpx
from pydantic import BaseModel, ValidationError

from aplicacion.calidad.modelos import (
    CriticaGeometrica, PlanGeometrico, RevisionCodigo, RevisionVisual,
)
from aplicacion.calidad.prompts import (
    PROMPT_CRITICO, PROMPT_PLANIFICADOR, PROMPT_REVISOR_CODIGO, PROMPT_REVISOR_VISUAL,
)
from aplicacion.calidad.recipes import CONTRATOS_MOTOR
from aplicacion.configuracion import (
    NVIDIA_BASE_URL, NVIDIA_MODEL_CODE_REVIEWER, NVIDIA_MODEL_CODE_REVIEWER_FALLBACK,
    NVIDIA_MODEL_PLANNER,
    NVIDIA_MODEL_PLANNER_FALLBACK, NVIDIA_MODEL_TEXT_JUDGE, NVIDIA_MODEL_VISUAL_REVIEWER,
    MODELO_COSMOS_EXPERIMENTAL, MODELOS_NVIDIA_CATALOGO, MODELOS_NVIDIA_REGISTRADOS,
)


class ErrorNvidia(Exception):
    """Error operativo sin datos de autenticación o reintentos implícitos."""

    def __init__(self, mensaje: str, codigo: str = "provider_error"):
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass
class RespuestaNvidia:
    texto: str
    modelo: str
    proveedor: str
    tokens_entrada: int
    tokens_salida: int
    finalizacion: str
    latencia_segundos: float
    request_id: str | None = None

    def serializar(self) -> dict:
        return asdict(self)


def _contenido_json(texto: str) -> dict:
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        resultado = json.loads(texto)
        if not isinstance(resultado, dict):
            raise ValueError
        return resultado
    except (json.JSONDecodeError, ValueError, TypeError):
        # Admite texto breve antes/después del objeto, sin convertir JSON inválido en aceptación.
        inicio, fin = texto.find("{"), texto.rfind("}")
        if inicio < 0 or fin <= inicio:
            raise ErrorNvidia("Respuesta NVIDIA no contiene un objeto JSON válido") from None
        try:
            resultado = json.loads(texto[inicio:fin + 1])
            if not isinstance(resultado, dict):
                raise ValueError
            return resultado
        except (json.JSONDecodeError, ValueError, TypeError):
            raise ErrorNvidia("Respuesta NVIDIA no contiene un objeto JSON válido") from None


class ProveedorNvidia:
    def __init__(self, clave: str | None = None, base_url: str | None = None, timeout: float = 120):
        self._clave = (clave if clave is not None else os.environ.get("NVIDIA_API_KEY", "")).strip()
        self.base_url = (base_url or NVIDIA_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.llamadas = 0

    def generar(self, modelo: str, mensajes: list[dict], maximo_tokens: int = 8192,
                temperatura: float = 0.1, imagenes_png: list[bytes] | None = None,
                esfuerzo_razonamiento: str | None = None) -> RespuestaNvidia:
        if not self._clave:
            raise ErrorNvidia("NVIDIA_API_KEY no está configurada en el backend")
        if modelo not in MODELOS_NVIDIA_REGISTRADOS:
            raise ErrorNvidia("Modelo NVIDIA no permitido por la configuración")
        if not 1 <= maximo_tokens <= 32768 or not 0 <= temperatura <= 2:
            raise ErrorNvidia("Parámetros de inferencia NVIDIA fuera de rango")
        mensajes_solicitud = [dict(mensaje) for mensaje in mensajes]
        if imagenes_png:
            indice_usuario = next((i for i in range(len(mensajes_solicitud) - 1, -1, -1)
                                   if mensajes_solicitud[i].get("role") == "user"), None)
            if indice_usuario is None:
                raise ErrorNvidia("La revisión visual requiere un mensaje user")
            contenido = [{"type": "text", "text": mensajes_solicitud[indice_usuario].get("content", "")}]
            for imagen in imagenes_png:
                codificada = base64.b64encode(imagen).decode("ascii")
                contenido.append({"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{codificada}"
                }})
            mensajes_solicitud[indice_usuario]["content"] = contenido
        cuerpo = {"model": modelo, "messages": mensajes_solicitud, "stream": False,
                  "max_tokens": maximo_tokens, "temperature": temperatura}
        if esfuerzo_razonamiento:
            cuerpo["reasoning_effort"] = esfuerzo_razonamiento
        inicio = time.monotonic()
        self.llamadas += 1
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=15.0)) as cliente:
                respuesta = cliente.post(
                    f"{self.base_url}/chat/completions", json=cuerpo,
                    headers={"Authorization": f"Bearer {self._clave}", "Accept": "application/json"},
                )
        except httpx.ReadTimeout:
            raise ErrorNvidia("Timeout NVIDIA; revisar la llamada antes de reintentar", "timeout") from None
        except httpx.HTTPError as error:
            raise ErrorNvidia(
                f"Error de transporte NVIDIA: {type(error).__name__}", "transport_error"
            ) from None
        if respuesta.status_code != 200:
            codigo = ("rate_limited" if respuesta.status_code == 429
                      else "service_unavailable" if respuesta.status_code == 503
                      else "server_error" if respuesta.status_code >= 500
                      else f"http_{respuesta.status_code}")
            raise ErrorNvidia(f"NVIDIA respondió HTTP {respuesta.status_code}", codigo)
        try:
            datos = respuesta.json()
            eleccion = datos["choices"][0]
            contenido = eleccion["message"].get("content")
            if isinstance(contenido, list):
                contenido = "".join(parte.get("text", "") for parte in contenido if isinstance(parte, dict))
            if not isinstance(contenido, str) or not contenido.strip():
                raise ValueError("contenido vacío")
            uso = datos.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            raise ErrorNvidia("Respuesta NVIDIA vacía o malformada", "malformed_response") from None
        return RespuestaNvidia(
            texto=contenido, modelo=str(datos.get("model") or modelo), proveedor="nvidia_nim",
            tokens_entrada=int(uso.get("prompt_tokens") or uso.get("input_tokens") or 0),
            tokens_salida=int(uso.get("completion_tokens") or uso.get("output_tokens") or 0),
            finalizacion=str(eleccion.get("finish_reason") or "desconocida"),
            latencia_segundos=time.monotonic() - inicio,
            request_id=str(datos.get("id")) if datos.get("id") else None,
        )

    def generar_estructurado(self, modelo: str, sistema: str, solicitud: str,
                             esquema: type[BaseModel], maximo_tokens: int = 8192,
                             imagenes_png: list[bytes] | None = None):
        mensajes = [{"role": "system", "content": sistema},
                    {"role": "user", "content": solicitud + "\n\nESQUEMA JSON:\n" + json.dumps(esquema.model_json_schema(), ensure_ascii=False)}]
        esfuerzo_razonamiento = {
            "nvidia/nemotron-3-super-120b-a12b": "low",
            "nvidia/nemotron-3-ultra-550b-a55b": "medium",
        }.get(modelo)
        respuesta = self.generar(modelo, mensajes, maximo_tokens=maximo_tokens,
                                 temperatura=0, imagenes_png=imagenes_png,
                                 esfuerzo_razonamiento=esfuerzo_razonamiento)
        if respuesta.finalizacion == "length":
            raise ErrorNvidia(
                f"Respuesta estructurada truncada por límite de tokens (modelo={modelo}, "
                f"tokens_salida={respuesta.tokens_salida})", "malformed_response"
            )
        try:
            contenido = _contenido_json(respuesta.texto)
        except ErrorNvidia:
            raise ErrorNvidia(
                f"Respuesta NVIDIA no contiene JSON válido (modelo={modelo}, "
                f"finish_reason={respuesta.finalizacion}, tokens_salida={respuesta.tokens_salida})",
                "malformed_response",
            ) from None
        try:
            valido = esquema.model_validate(contenido)
        except ValidationError as error:
            ubicaciones = [
                ".".join(str(parte) for parte in incidencia.get("loc", ())) or "raíz"
                for incidencia in error.errors()[:5]
            ]
            resumen = ", ".join(ubicaciones)
            raise ErrorNvidia(
                f"Respuesta JSON NVIDIA no cumple el esquema (modelo={modelo}, "
                f"finish_reason={respuesta.finalizacion}, campos={resumen or 'desconocidos'})",
                "malformed_response",
            ) from None
        except TypeError:
            raise ErrorNvidia(
                f"Respuesta JSON NVIDIA no cumple el esquema (modelo={modelo}, "
                f"finish_reason={respuesta.finalizacion})", "malformed_response"
            ) from None
        return valido, respuesta

    def listar_modelos(self) -> list[dict]:
        if not self._clave:
            raise ErrorNvidia("NVIDIA_API_KEY no está configurada en el backend")
        try:
            with httpx.Client(timeout=httpx.Timeout(25.0, connect=10.0)) as cliente:
                respuesta = cliente.get(f"{self.base_url}/models", headers={
                    "Authorization": f"Bearer {self._clave}", "Accept": "application/json",
                })
        except httpx.HTTPError as error:
            raise ErrorNvidia(f"Error al consultar catálogo NVIDIA: {type(error).__name__}") from None
        if respuesta.status_code != 200:
            raise ErrorNvidia(f"El catálogo NVIDIA respondió HTTP {respuesta.status_code}")
        try:
            modelos = respuesta.json().get("data", [])
            if not isinstance(modelos, list):
                raise ValueError
            return [{"id": modelo.get("id"), "object": modelo.get("object"),
                     "created": modelo.get("created")} for modelo in modelos
                    if isinstance(modelo, dict) and isinstance(modelo.get("id"), str)]
        except (ValueError, TypeError):
            raise ErrorNvidia("Catálogo NVIDIA malformado") from None


class RouterModelos:
    """Rutas por rol configurables mediante entorno."""

    def __init__(self, proveedor: ProveedorNvidia | None = None, rutas: dict | None = None):
        self.proveedor = proveedor or ProveedorNvidia()
        self.rutas = rutas or catalogo_roles()
        self.modelos_planificador: list[str] = []
        self.modelos_revisor_codigo: list[str] = []

    @staticmethod
    def _solicitud_plan(descripcion: str) -> str:
        return (f"Descripción original, única fuente para cotas especificadas:\n{descripcion}"
                "\nNo hay CAD de referencia ni resultados del benchmark adjuntos.")

    def planificar(self, descripcion: str, permitir_fallback: bool = True):
        solicitud = self._solicitud_plan(descripcion)
        principal = self.rutas["planificador"]["modelo"]
        alternativo = self.rutas["planificador"]["alternativo"]
        self.modelos_planificador = [principal]
        try:
            return self.proveedor.generar_estructurado(
                principal, PROMPT_PLANIFICADOR, solicitud, PlanGeometrico
            )
        except ErrorNvidia as error:
            # Fallback tras respuesta definitivamente rechazada o malformada;
            # nunca ante timeout o transporte con facturación incierta.
            if (not permitir_fallback or principal == alternativo
                    or not (error.codigo == "malformed_response"
                        or any(codigo in str(error) for codigo in ("HTTP 400", "HTTP 404", "HTTP 422")))):
                raise
            self.modelos_planificador.append(alternativo)
            return self.proveedor.generar_estructurado(
                alternativo, PROMPT_PLANIFICADOR, solicitud, PlanGeometrico
            )

    def planificar_alternativo(self, descripcion: str):
        """Consulta el modelo alternativo tras una respuesta completa con cotas inválidas."""
        alternativo = self.rutas["planificador"]["alternativo"]
        if (not self.modelos_planificador
                or self.modelos_planificador[-1] != alternativo):
            self.modelos_planificador.append(alternativo)
        return self.proveedor.generar_estructurado(
            alternativo, PROMPT_PLANIFICADOR,
            self._solicitud_plan(descripcion), PlanGeometrico,
        )

    def revisar_codigo(self, motor: str, plan: PlanGeometrico, codigo: str):
        solicitud = (f"Motor={motor}\nVersión y contrato exacto: {CONTRATOS_MOTOR[motor]}\n"
                     f"GeometricPlan:\n{plan.model_dump_json()}\nPrograma:\n{codigo}")
        principal = self.rutas["revisor_codigo"]["modelo"]
        alternativo = self.rutas["revisor_codigo"]["alternativo"]
        self.modelos_revisor_codigo = [principal]
        try:
            return self.proveedor.generar_estructurado(
                principal, PROMPT_REVISOR_CODIGO, solicitud, RevisionCodigo,
                maximo_tokens=4096,
            )
        except ErrorNvidia as error:
            # Una respuesta malformada es un rechazo completo, así que permite
            # probar una alternativa. No repetir ante timeout ni transporte incierto.
            if (error.codigo != "malformed_response"
                    or alternativo == principal):
                raise
            self.modelos_revisor_codigo.append(alternativo)
            return self.proveedor.generar_estructurado(
                alternativo, PROMPT_REVISOR_CODIGO,
                solicitud, RevisionCodigo, maximo_tokens=4096,
            )

    def criticar(self, plan: PlanGeometrico, evidencia: dict):
        solicitud = (f"GeometricPlan:\n{plan.model_dump_json()}\nEvidencia determinista/visual:\n"
                     f"{json.dumps(evidencia, ensure_ascii=False, allow_nan=False)}")
        return self.proveedor.generar_estructurado(
            self.rutas["juez_textual"]["modelo"], PROMPT_CRITICO, solicitud, CriticaGeometrica,
            maximo_tokens=4096,
        )

    def revisar_visual(self, descripcion: str, plan: PlanGeometrico,
                       metricas: dict, imagen: bytes):
        solicitud = (f"Descripción original: {descripcion}\nGeometricPlan:\n{plan.model_dump_json()}\n"
                     f"Métricas deterministas (fuente de medidas):\n{json.dumps(metricas, ensure_ascii=False)}\n"
                     "Inspecciona la lámina multivista adjunta, rotulada por orientación.")
        try:
            return self.proveedor.generar_estructurado(
                self.rutas["revisor_visual"]["modelo"], PROMPT_REVISOR_VISUAL,
                solicitud, RevisionVisual, maximo_tokens=4096, imagenes_png=[imagen],
            )
        except ErrorNvidia as error:
            raise ErrorNvidia(
                f"Revisión visual inválida: {error}", getattr(error, "codigo", "malformed_response")
            ) from None


def catalogo_roles() -> dict:
    return {
        "planificador": {"modelo": NVIDIA_MODEL_PLANNER, "alternativo": NVIDIA_MODEL_PLANNER_FALLBACK},
        "revisor_codigo": {
            "modelo": NVIDIA_MODEL_CODE_REVIEWER,
            "alternativo": NVIDIA_MODEL_CODE_REVIEWER_FALLBACK,
        },
        "revisor_visual": {"modelo": NVIDIA_MODEL_VISUAL_REVIEWER},
        "juez_textual": {"modelo": NVIDIA_MODEL_TEXT_JUDGE},
        "generador": {"modelo": os.environ.get("NVIDIA_MODEL_GENERATOR", "nvidia/nemotron-3-super-120b-a12b")},
        "experimental_cosmos": {
            "modelo": MODELO_COSMOS_EXPERIMENTAL or "nvidia/cosmos3-nano-reasoner",
            "disponible_en_catalogo": MODELO_COSMOS_EXPERIMENTAL in MODELOS_NVIDIA_CATALOGO,
        },
        "modelos_catalogo_verificados": sorted(MODELOS_NVIDIA_CATALOGO),
    }
