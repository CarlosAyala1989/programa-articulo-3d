"""Límites publicados, con fuentes y versión; no equivalen a cuotas de cuenta."""

from copy import deepcopy


VERSION_LIMITES = "limites-oficiales-2026-10-20-v1"
_NIM = "https://docs.api.nvidia.com/nim/reference/"
_OPENAI = "https://developers.openai.com/api/docs/models/"
LIMITES_MODELOS = {
    **{modelo: {
        "contexto": 1_048_576, "salida": 393_216, "contexto_compartido": True,
        "fuentes": ["https://api-docs.deepseek.com/api/create-chat-completion/",
                    "https://api-docs.deepseek.com/quick_start/agent_integrations/codex/"],
    } for modelo in ("deepseek-flash", "deepseek-v4-pro")},
    **{f"codex-cli::{modelo}": {
        "entrada": 922_000, "contexto": 1_050_000, "salida": 128_000,
        "contexto_compartido": True, "gestion": "cli",
        "fuentes": [_OPENAI + modelo],
    } for modelo in ("gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna",
                     "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")},
    **{f"antigravity-cli::gemini-3.8-flash-{esfuerzo}": {
        "entrada": 1_048_576, "salida": 65_536, "contexto_compartido": False,
        "gestion": "cli", "fuentes": ["https://ai.google.dev/gemini-api/docs/tokens"],
    } for esfuerzo in ("low", "medium", "high")},
    **{f"antigravity-cli::{modelo}": {
        "contexto": 1_000_000, "salida": 128_000, "contexto_compartido": True,
        "gestion": "cli", "fuentes": [
            f"https://platform.claude.com/docs/en/models/{documento}/overview"],
    } for modelo, documento in (("claude-sonnet-4-6", "sonnet-4-6"),
                                ("claude-opus-4-6-thinking", "opus-4-6"))},
    "antigravity-cli::gpt-oss-120b-medium": {
        "contexto": 131_072, "salida": 131_072, "contexto_compartido": True,
        "gestion": "cli", "fuentes": [_OPENAI + "gpt-oss-120b"],
    },
    "nvidia/nemotron-3-super-120b-a12b": {
        "contexto": 1_048_576, "salida": 32_768, "contexto_compartido": True,
        "fuentes": [_NIM + "nvidia-nemotron-3-super-120b-a12b-infer",
                    _NIM + "nvidia-nemotron-3-super-120b-a12b"],
    },
    "moonshotai/kimi-k3": {
        "contexto": 1_048_576, "salida": 65_536, "contexto_compartido": True,
        "fuentes": [_NIM + "moonshotai-kimi-k3-infer", _NIM + "moonshotai-kimi-k3"],
    },
    "google/gemma-4-31b-it": {
        "contexto": 262_144, "salida": 32_768, "contexto_compartido": True,
        "fuentes": [_NIM + "google-gemma-4-31b-it-infer",
                    "https://ai.google.dev/gemma/docs/core/model_card_4"],
    },
    "z-ai/glm-5.3": {
        "contexto": 1_048_576, "salida": 131_072, "contexto_compartido": True,
        "fuentes": ["https://docs.z.ai/api-reference/llm/chat-completion",
                    _NIM + "z-ai-glm-5-3-infer", _NIM + "z-ai-glm-5-3"],
    },
}


def limites_modelo(modelo: str) -> dict:
    limites = deepcopy(LIMITES_MODELOS.get(modelo, {}))
    gestion_cli = modelo.partition("::")[0] in {"codex-cli", "antigravity-cli"}
    limites.setdefault("gestion", "cli" if gestion_cli else "api")
    return {"version": VERSION_LIMITES, **limites,
            "entrada_recortada_por_aplicacion": False,
            "salida_configurada": None if gestion_cli else limites.get("salida"),
            "nota": ("Referencia del modelo en la API de su creador. La suscripción y el CLI "
                     "controlan los límites efectivos; este adaptador no expone un ajuste de tokens."
                     if gestion_cli else
                     "Entrada y salida comparten contexto; la entrada, las instrucciones y el "
                     "historial consumen espacio. El proveedor valida el contexto disponible."
                     if limites.get("contexto_compartido") else
                     "El proveedor gestiona el contexto; no se ha verificado un máximo para esta ruta.")}


def maximo_salida(modelo: str) -> int | None:
    return LIMITES_MODELOS.get(modelo, {}).get("salida")
