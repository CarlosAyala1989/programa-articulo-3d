"""Fuente Unicode incluida para figuras reproducibles en Windows y Linux."""
from pathlib import Path
from PIL import ImageFont

RUTA_FUENTE = Path(__file__).resolve().parents[1] / 'datos/fuentes/DejaVuSans.ttf'


def fuente(tamano: int):
    return ImageFont.truetype(str(RUTA_FUENTE), tamano)
