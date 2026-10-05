"""Estimaciones explícitas de consumo; la factura del proveedor es la fuente final."""

from aplicacion.configuracion import MAXIMO_TOKENS_DEEPSEEK, MODELOS_LOCALES, TOKENS_ENTRADA_PLANIFICACION


# USD por millón de tokens, tarifa pico sin descuento de caché.
# https://api-docs.deepseek.com/quick_start/pricing/ (consulta 2026-10-04).
TARIFAS = {
    "deepseek-flash": (0.30, 1.20),
    "deepseek-v4-pro": (1.32, 3.96),
}
PERFIL_TARIFA = "DeepSeek pico sin caché, 2026-10-04"


def costo_estimado(modelo: str, tokens_entrada: int, tokens_salida: int) -> float | None:
    if modelo in MODELOS_LOCALES:
        return None
    if modelo not in TARIFAS:
        return None
    entrada, salida = TARIFAS[modelo]
    return (max(0, tokens_entrada) * entrada + max(0, tokens_salida) * salida) / 1_000_000


def costo_maximo_planificacion(modelo: str) -> float | None:
    """Estimación conservadora: incluye programa completo e historial de correcciones."""
    return costo_estimado(modelo, TOKENS_ENTRADA_PLANIFICACION, MAXIMO_TOKENS_DEEPSEEK)
