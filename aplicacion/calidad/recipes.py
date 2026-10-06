"""Biblioteca versionada de estrategias CAD, seleccionadas sin añadir piezas de respaldo."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    identificador: str
    operadores: frozenset[str]
    instruccion: str


RECIPES = (
    Recipe("extrusion", frozenset({"extrude", "extrusion", "extrusión", "prism"}), "Extruye un perfil planar cerrado en dirección y distancia explícitas; comprueba el sólido resultante."),
    Recipe("revolution", frozenset({"revolve", "revolution", "revolución", "axisymmetric"}), "Revoluciona un semiperfil cerrado alrededor de su eje; el perfil no debe cruzar el eje."),
    Recipe("loft", frozenset({"loft", "transition", "transición"}), "Ordena secciones cerradas compatibles por estación y conserva su inicio y orientación para evitar torsión."),
    Recipe("sweep", frozenset({"sweep", "swept", "barrido", "trajectory", "trayectoria"}), "Orienta el perfil cerrado según la tangente inicial y evita torsión y autointersecciones."),
    Recipe("hollow", frozenset({"hollow", "shell", "cavity", "cavidad", "hueco"}), "Define espesor positivo, cara de apertura y fondo; confirma que la cavidad abra donde indica el plan."),
    Recipe("curved_cut", frozenset({"cut", "pocket", "corte", "incision", "incisión", "groove"}), "Construye el cortador fuera de la superficie y atraviesa la profundidad prevista; comprueba cambio de volumen."),
    Recipe("spline_profile", frozenset({"spline", "bspline", "profile", "perfil"}), "Controla orden y tangentes del perfil; cierra un wire sin duplicar puntos y evita oscilaciones."),
    Recipe("pattern", frozenset({"pattern", "patrón", "array", "repeat", "repetición"}), "Genera instancias deterministas desde eje, cantidad y paso indicados; verifica cada instancia y su fusión."),
    Recipe("organic_relief", frozenset({"organic", "relief", "relieve", "anatomical", "anatómico"}), "Apoya el relieve en un frame local, solapa el cuerpo y evita sólidos tangentes."),
    Recipe("asymmetric_loft", frozenset({"asymmetric", "asimétrico", "freeform", "organic_freeform"}), "Desplaza y rota cada sección según el plan; no fuerces simetría no solicitada."),
    Recipe("rib", frozenset({"rib", "nervio", "web", "costilla"}), "Construye la costilla desde un perfil y espesor medible, con intersección verificable en sus apoyos."),
    Recipe("local_frame", frozenset({"frame", "marco local", "local_frame", "orientation", "orientación"}), "Define origen y ejes ortonormales por región y la transformación al sistema global."),
    Recipe("hole", frozenset({"hole", "holes", "agujero", "agujeros", "through_hole"}), "Coloca un cortador cilíndrico según diámetro, eje y posición del plan; verifica cantidad y diámetro."),
)


CONTRATOS_MOTOR = {
    "cadquery": "CadQuery 2.6.1: Workplane/Shape; isValid(), Solids(), Volume(), BoundingBox().",
    "build123d": "build123d 0.13.0 algebraico: Shape.is_valid, solids(), volume, bounding_box().",
    "freecad": "FreeCAD Python API 0.20.2 sin GUI: Part.Shape.isValid(), Solids, Volume, BoundBox.",
}


def seleccionar_recipes(plan, motor: str) -> list[Recipe]:
    if motor not in CONTRATOS_MOTOR:
        raise ValueError("Motor CAD no reconocido para seleccionar recipes")
    palabras = {operacion.casefold() for operacion in plan.operaciones}
    palabras.update(plan.clase_modelado.casefold().split("_"))
    palabras.update(feature.tipo.casefold() for feature in plan.features)
    palabras.update(feature.operacion.casefold() for feature in plan.features)
    if plan.agujeros:
        palabras.add("hole")
    return [recipe for recipe in RECIPES if recipe.operadores & palabras]


def texto_recipes(plan, motor: str) -> str:
    seleccionadas = seleccionar_recipes(plan, motor)
    receta_texto = "\n".join(
        f"[{recipe.identificador}] {recipe.instruccion}" for recipe in seleccionadas
    ) or "Sin recipe especializada; usa la operación CAD más directa para el plan."
    return f"{CONTRATOS_MOTOR[motor]}\n{receta_texto}"
