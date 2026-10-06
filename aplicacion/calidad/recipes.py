"""Biblioteca versionada de estrategias CAD, seleccionadas sin añadir piezas de respaldo."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Recipe:
    identificador: str
    operadores: frozenset[str]
    instruccion: str


RECIPES = (
    Recipe("extrusion", frozenset({"extrude", "extrusion", "extrusión", "prism"}), "Extruye un perfil planar cerrado en dirección y distancia explícitas; comprueba el sólido resultante."),
    Recipe("revolution", frozenset({"revolve", "revolution", "revolución", "axisymmetric"}), "Revoluciona un semiperfil cerrado alrededor de su eje; el perfil no debe cruzar el eje."),
    Recipe("loft", frozenset({"loft"}), "Ordena secciones cerradas compatibles por estación y conserva su inicio y orientación para evitar torsión."),
    Recipe("transition", frozenset({"transition", "transición", "blend"}), "Conecta regiones con continuidad de forma y sin aristas o intersecciones accidentales; selecciona la operación según las secciones reales."),
    Recipe("sweep", frozenset({"sweep", "swept", "barrido", "trajectory", "trayectoria"}), "Orienta el perfil cerrado según la tangente inicial y evita torsión y autointersecciones."),
    Recipe("hollow", frozenset({"hollow", "shell", "cavity", "cavidad", "hueco"}), "Define espesor positivo, cara de apertura y fondo; confirma que la cavidad abra donde indica el plan."),
    Recipe("curved_cut", frozenset({"cut", "pocket", "corte", "incision", "incisión", "groove"}), "Construye el cortador fuera de la superficie y atraviesa la profundidad prevista; comprueba cambio de volumen."),
    Recipe("spline_profile", frozenset({"spline", "bspline", "profile", "perfil"}), "Controla orden y tangentes del perfil; cierra un wire sin duplicar puntos y evita oscilaciones."),
    Recipe("pattern", frozenset({"pattern", "patrón", "array", "repeat", "repetición"}), "Genera instancias deterministas desde eje, cantidad y paso indicados; verifica cada instancia y su fusión."),
    Recipe("organic_relief", frozenset({"organic", "relief", "relieve", "anatomical", "anatómico"}), "Apoya el relieve en un frame local, solapa el cuerpo y evita sólidos tangentes."),
    Recipe("asymmetric_loft", frozenset({"asymmetric loft", "loft asimétrico", "loft asimetrico"}), "Desplaza y rota cada sección según el plan; no fuerces simetría no solicitada."),
    Recipe("rib", frozenset({"rib", "nervio", "web", "costilla"}), "Construye la costilla desde un perfil y espesor medible, con intersección verificable en sus apoyos."),
    Recipe("local_frame", frozenset({"frame", "marco local", "local_frame", "orientation", "orientación"}), "Define origen y ejes ortonormales por región y la transformación al sistema global."),
    Recipe("hole", frozenset({"hole", "holes", "agujero", "agujeros", "through_hole"}), "Coloca un cortador cilíndrico según diámetro, eje y posición del plan; verifica cantidad y diámetro."),
)


CONTRATOS_MOTOR = {
    "cadquery": "CadQuery 2.6.1: Workplane/Shape; isValid(), Solids(), Volume(), BoundingBox().",
    "build123d": "build123d 0.13.0 algebraico: Shape.is_valid, solids(), volume, bounding_box().",
    "freecad": "FreeCAD Python API 0.20.2 sin GUI: Part.Shape.isValid(), Solids, Volume, BoundBox.",
}

# Orientaciones de API por motor; son operaciones, no piezas prefabricadas. Se adjuntan
# únicamente para las recipes seleccionadas por el plan geométrico.
API_POR_RECIPE = {
    "extrusion": {"cadquery": "Workplane.extrude(distancia)", "build123d": "extrude(perfil, amount=distancia)", "freecad": "Part.Face(wire).extrude(App.Vector(dx, dy, dz))"},
    "revolution": {"cadquery": "Workplane.revolve(angulo, eje_inicio, eje_fin)", "build123d": "revolve(perfil, axis=eje)", "freecad": "Part.Face(wire).revolve(origen, eje, angulo)"},
    "loft": {"cadquery": "Workplane con secciones pendientes y loft(ruled=False)", "build123d": "loft(sections=perfiles, ruled=False)", "freecad": "Part.makeLoft(wires, True, False)"},
    "transition": {"cadquery": "comprobar secciones y continuidad antes de elegir loft o blend local", "build123d": "comprobar perfiles y continuidad antes de elegir loft o fillet local", "freecad": "comprobar wires y continuidad antes de Part.makeLoft o transición local"},
    "sweep": {"cadquery": "Workplane.sweep(trayectoria, isFrenet=False)", "build123d": "sweep(sections=perfil, path=trayectoria, is_frenet=False)", "freecad": "wire_trayectoria.makePipeShell([wire_perfil], True, False)"},
    "hollow": {"cadquery": "Workplane.shell(espesor) o cut(cavidad) con apertura comprobada", "build123d": "offset o resta booleana de cavidad; comprobar apertura", "freecad": "Part.Shape.cut(cavidad); comprobar apertura y espesor"},
    "curved_cut": {"cadquery": "Workplane.cut(cortador barrido)", "build123d": "solido - cortador barrido", "freecad": "Part.Shape.cut(cortador barrido)"},
    "spline_profile": {"cadquery": "Workplane.spline(puntos) y cierre del wire", "build123d": "Spline(*puntos), Wire y Face planar", "freecad": "Part.BSplineCurve().interpolate(Points=puntos) y Part.Wire"},
    "pattern": {"cadquery": "pushPoints(posiciones) con patrón parametrizado", "build123d": "Locations/Pos parametrizadas y unión o corte", "freecad": "copias de Part.Shape transformadas por Placement"},
    "organic_relief": {"cadquery": "union(relieve) con intersección volumétrica", "build123d": "cuerpo + relieve con intersección volumétrica", "freecad": "cuerpo.fuse(relieve) con intersección volumétrica"},
    "asymmetric_loft": {"cadquery": "workplane(offset=incremento) con origin/xDir explícitos", "build123d": "Plane(origin=..., x_dir=..., z_dir=...) * perfil", "freecad": "wires transformados con Placement antes de Part.makeLoft"},
    "rib": {"cadquery": "Workplane.extrude(espesor) y union(cuerpo)", "build123d": "extrude(perfil, amount=espesor) + cuerpo", "freecad": "Part.Face(wire).extrude(vector).fuse(cuerpo)"},
    "local_frame": {"cadquery": "cq.Plane(origin=..., xDir=..., normal=...)", "build123d": "Plane(origin=..., x_dir=..., z_dir=...)", "freecad": "App.Placement(base, rotacion) aplicado a Part.Shape"},
    "hole": {"cadquery": "Workplane.hole(diametro) o cut(cilindro)", "build123d": "cuerpo - Cylinder(radio, longitud) posicionado", "freecad": "cuerpo.cut(Part.makeCylinder(radio, longitud, origen, eje))"},
}


def seleccionar_recipes(plan, motor: str) -> list[Recipe]:
    if motor not in CONTRATOS_MOTOR:
        raise ValueError("Motor CAD no reconocido para seleccionar recipes")
    fragmentos = [operacion.casefold() for operacion in plan.operaciones]
    fragmentos.extend(feature.tipo.casefold() for feature in plan.features)
    fragmentos.extend(feature.operacion.casefold() for feature in plan.features)
    if plan.agujeros:
        fragmentos.append("hole")
    if plan.relieves:
        fragmentos.append("organic relief")
    if plan.cavidades:
        fragmentos.append("cavity")
    if plan.trayectorias:
        fragmentos.append("trajectory")
    if plan.cortes:
        fragmentos.append("cut")
    return [recipe for recipe in RECIPES if any(
        re.search(r"(?<!\w)" + re.escape(operador) + r"(?!\w)", fragmento)
        for operador in recipe.operadores for fragmento in fragmentos
    )]


def texto_recipes(plan, motor: str) -> str:
    seleccionadas = seleccionar_recipes(plan, motor)
    receta_texto = "\n".join(
        f"[{recipe.identificador}] {recipe.instruccion} API {motor}: "
        f"{API_POR_RECIPE[recipe.identificador][motor]}." for recipe in seleccionadas
    ) or "Sin recipe especializada; usa la operación CAD más directa para el plan."
    return f"{CONTRATOS_MOTOR[motor]}\n{receta_texto}"
