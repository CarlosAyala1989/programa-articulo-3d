"""Inferencia local: no hay tarifa API; electricidad e infraestructura no estimadas."""

PERFIL_TARIFA = "Ollama local; sin tarifa API; electricidad no estimada"


def costo_estimado(modelo: str, tokens_entrada: int, tokens_salida: int) -> None:
    return None


def costo_maximo_planificacion(modelo: str, maximo_tokens: int | None = None) -> None:
    return None
