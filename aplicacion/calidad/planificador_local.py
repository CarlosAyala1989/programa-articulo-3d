"""Plan geométrico mínimo de respaldo cuando NIM no entrega un plan utilizable."""

import re
import unicodedata

from aplicacion.calidad.modelos import (
    CajaPlan, CriterioPlan, DimensionPlan, FeaturePlan, PlanGeometrico,
)


def _normalizar(texto: str) -> str:
    return "".join(
        letra for letra in unicodedata.normalize("NFD", texto.casefold())
        if unicodedata.category(letra) != "Mn"
    )


def _dimension(valor: str | float) -> DimensionPlan:
    if isinstance(valor, str):
        valor = float(valor.replace(",", "."))
    return DimensionPlan(valor=float(valor), procedencia="specified")


def construir_plan_local(descripcion: str) -> PlanGeometrico:
    """Conserva cotas literales y rasgos nombrados; no inventa detalle ausente."""
    texto = _normalizar(descripcion)
    caja = re.search(
        r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*[x×]\s*"
        r"(\d+(?:[.,]\d+)?)\s*[x×]\s*"
        r"(\d+(?:[.,]\d+)?)\s*(?:mm|milimetros?)\b",
        texto,
    )
    dimensiones = [_dimension(valor) for valor in caja.groups()] if caja else []
    caja_esperada = CajaPlan(x=dimensiones[0], y=dimensiones[1], z=dimensiones[2]) if caja else None
    globales = ({"x": dimensiones[0], "y": dimensiones[1], "z": dimensiones[2]}
                if caja else {})

    rasgos_organicos = any(palabra in texto for palabra in (
        "organico", "organica", "cabeza", "rostro", "figura", "escultura", "animal",
    ))
    rasgos_mecanicos = bool(caja) or any(palabra in texto for palabra in (
        "casa", "placa", "bloque", "soporte", "agujero", "tornillo", "mm",
    ))
    clase = ("HYBRID" if rasgos_organicos and rasgos_mecanicos else
             "ORGANIC_FREEFORM" if rasgos_organicos else "MECHANICAL_PRECISE")

    categoria = next((nombre for palabra, nombre in (
        ("casa", "casa"), ("cabeza", "cabeza"), ("rostro", "rostro"),
        ("placa", "placa"), ("soporte", "soporte"), ("figura", "figura"),
    ) if palabra in texto), "pieza descrita")
    rasgos = [
        FeaturePlan(
            feature_id="cuerpo_principal", nombre="cuerpo principal", tipo=categoria,
            operacion="extrude", dimensiones=globales,
            descripcion="Volumen principal; la descripción original conserva los detalles.",
        )
    ]

    def agregar(
        identificador: str, nombre: str, tipo: str, expresion: str,
        dimensiones_feature: dict[str, DimensionPlan] | None = None,
    ) -> None:
        match = re.search(
            rf"\b(?:{expresion})\b[^,;.\n]{{0,120}}?\b(?:de\s+)?"
            r"(\d+(?:[.,]\d+)?)\s*[x×]\s*"
            r"(\d+(?:[.,]\d+)?)\s*(?:mm|milimetros?)\b",
            texto,
        )
        cotas = dict(dimensiones_feature or {})
        if match:
            cotas.setdefault("ancho", _dimension(match.group(1)))
            cotas.setdefault("alto", _dimension(match.group(2)))
        rasgos.append(FeaturePlan(
            feature_id=identificador, nombre=nombre, tipo=tipo,
            operacion="cut" if tipo in {"puerta", "ventana"} else "extrude",
            padre_id="cuerpo_principal", dimensiones=cotas,
            descripcion=f"Rasgo nombrado en la descripción: {nombre}.",
        ))

    if "techo" in texto or "cubierta" in texto:
        agregar("techo", "techo", "cubierta", r"techo|cubierta")
    if "puerta" in texto:
        agregar("puerta", "puerta", "puerta", "puerta")
    if "ventana" in texto:
        cantidad = 2 if re.search(r"\b(?:dos|2)\s+ventanas?\b", texto) else 1
        nombres = (("ventana_izquierda", "ventana_derecha") if cantidad == 2
                   else ("ventana",))
        for nombre in nombres:
            agregar(nombre, nombre.replace("_", " "), "ventana", "ventanas?")
    if any(palabra in texto for palabra in ("agujero", "perforacion", "orificio")):
        if not any(rasgo.tipo == "agujero" for rasgo in rasgos):
            agregar("agujero", "agujero", "agujero", "agujero|perforacion|orificio")
    if len(rasgos) == 1:
        if any(palabra in texto for palabra in ("curva", "redonde", "fillet", "radio")):
            agregar("curvas", "curvas y transiciones", "curva", "curva|redonde|fillet|radio")

    criterios = []
    if caja:
        for eje, dimension in zip(("x", "y", "z"), dimensiones):
            criterios.append(CriterioPlan(
                identificador=f"bbox_{eje}", feature_id="cuerpo_principal",
                medicion=f"bbox_{eje}", esperado=dimension.valor, esencial=True,
            ))
    cortes = [rasgo.feature_id for rasgo in rasgos if rasgo.operacion == "cut"]
    return PlanGeometrico(
        clase_modelado=clase, categoria=categoria,
        dimensiones_globales=globales, bounding_box_esperada=caja_esperada,
        features=rasgos, operaciones=["extrude"] + (["cut"] if cortes else []),
        cortes=cortes, rasgos_esenciales=[rasgo.feature_id for rasgo in rasgos],
        criterios_verificables=criterios,
        comentarios_inferidos=[
            "Plan local de contingencia: retiene solo cotas y rasgos nombrados literalmente; "
            "el generador debe seguir la descripción completa y validar el CAD.",
        ],
    )
