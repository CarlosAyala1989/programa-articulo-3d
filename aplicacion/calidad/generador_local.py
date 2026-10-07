"""CAD determinista de contingencia para el Quality Loop cuando NIM se agota."""

from aplicacion.calidad.modelos import PlanGeometrico


def generar_cadquery_de_casa(plan: PlanGeometrico) -> str:
    """Modela la caja, el techo a dos aguas y los huecos descritos en el plan."""
    if plan.categoria != "casa":
        raise ValueError("El respaldo local solo está definido para planes de categoría casa")
    caja = plan.bounding_box_esperada
    if caja is None:
        raise ValueError("El generador local requiere dimensiones globales verificables")
    ancho, fondo, alto_total = caja.x.valor, caja.y.valor, caja.z.valor
    if min(ancho, fondo, alto_total) <= 0:
        raise ValueError("Las dimensiones de contingencia deben ser positivas")
    puerta = next((feature for feature in plan.features if feature.tipo == "puerta"), None)
    ventanas = [feature for feature in plan.features if feature.tipo == "ventana"]
    techo = any(feature.tipo in {"cubierta", "techo"} for feature in plan.features)
    ancho_puerta = (puerta.dimensiones.get("ancho").valor
                    if puerta and puerta.dimensiones.get("ancho") else 0.0)
    alto_puerta = (puerta.dimensiones.get("alto").valor
                   if puerta and puerta.dimensiones.get("alto") else alto_total * 0.75)
    ancho_ventana = (ventanas[0].dimensiones.get("ancho").valor
                     if ventanas and ventanas[0].dimensiones.get("ancho") else ancho * 0.15)
    alto_ventana = (ventanas[0].dimensiones.get("alto").valor
                    if ventanas and ventanas[0].dimensiones.get("alto") else alto_total * 0.35)
    alto_muro = alto_total * (2.0 / 3.0) if techo else alto_total
    profundidad_rebaje = min(fondo * 0.12, max(fondo * 0.04, 0.5))
    frente = fondo / 2.0 - profundidad_rebaje / 2.0
    lineas = [
        "import cadquery as cq",
        f"ancho = {ancho!r}", f"fondo = {fondo!r}", f"alto_total = {alto_total!r}",
        f"alto_muro = {alto_muro!r}", f"profundidad_rebaje = {profundidad_rebaje!r}",
        f"frente = {frente!r}",
        "paredes = cq.Workplane('XY').box(ancho, fondo, alto_muro).translate((0, 0, alto_muro / 2))",
    ]
    if techo:
        lineas.extend([
            "perfil_techo = cq.Workplane('XZ').polyline([",
            "    (-ancho / 2, alto_muro), (ancho / 2, alto_muro), (0, alto_total)",
            "]).close().extrude(fondo).translate((0, fondo / 2, 0))",
            "resultado = paredes.union(perfil_techo)",
        ])
    else:
        lineas.append("resultado = paredes")
    if puerta:
        lineas.extend([
            f"cortador_puerta = cq.Workplane('XY').box({ancho_puerta!r}, profundidad_rebaje, {alto_puerta!r})",
            f"cortador_puerta = cortador_puerta.translate((0, frente, {min(alto_puerta, alto_total) / 2!r}))",
            "resultado = resultado.cut(cortador_puerta)",
        ])
    for indice, ventana in enumerate(ventanas):
        ancho_actual = ventana.dimensiones.get("ancho").valor if ventana.dimensiones.get("ancho") else ancho_ventana
        alto_actual = ventana.dimensiones.get("alto").valor if ventana.dimensiones.get("alto") else alto_ventana
        posicion_x = (-ancho / 3.0 if indice == 0 else ancho / 3.0) if len(ventanas) == 2 else 0.0
        nombre = f"cortador_ventana_{indice + 1}"
        lineas.extend([
            f"{nombre} = cq.Workplane('XY').box({ancho_actual!r}, profundidad_rebaje, {alto_actual!r})",
            f"{nombre} = {nombre}.translate(({posicion_x!r}, frente, {min(alto_actual, alto_muro) / 2!r}))",
            f"resultado = resultado.cut({nombre})",
        ])
    return "\n".join(lineas)
