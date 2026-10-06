"""Cálculo reproducible de métricas y aceptación separada del éxito técnico."""

import math


VERSION_METRICAS = "ciel-quality-metrics-v1"
UMBRAL_ACEPTACION = 0.85
PESOS = {
    "MECHANICAL_PRECISE": {"dimensional": 0.32, "topological": 0.12, "features": 0.24,
                           "silhouette": 0.04, "proportions": 0.04, "symmetry": 0.04,
                           "centroid": 0.04, "surface_area": 0.04, "hausdorff": 0.04,
                           "volume": 0.05, "silhouette_iou": 0.03,
                           "normal_consistency": 0.02, "reference_similarity": 0.06},
    "ORGANIC_FREEFORM": {"dimensional": 0.08, "topological": 0.08, "features": 0.19,
                         "silhouette": 0.23, "proportions": 0.14, "symmetry": 0.06,
                         "centroid": 0.02, "surface_area": 0.03, "hausdorff": 0.04,
                         "volume": 0.02, "silhouette_iou": 0.03,
                         "normal_consistency": 0.03, "reference_similarity": 0.10},
    "HYBRID": {"dimensional": 0.20, "topological": 0.11, "features": 0.22,
               "silhouette": 0.13, "proportions": 0.08, "symmetry": 0.05,
               "centroid": 0.04, "surface_area": 0.04, "hausdorff": 0.04,
               "volume": 0.04, "silhouette_iou": 0.03,
               "normal_consistency": 0.03, "reference_similarity": 0.06},
}


def registro(estado: str, valor=None, unidad: str = "unitless", algoritmo: str = "",
             muestras: int | None = None, semilla: int | None = None,
             tolerancia: float | None = None, perfil: str = "",
             requerido: bool = False) -> dict:
    if estado not in {"calculated", "not_applicable", "not_available", "unsupported"}:
        raise ValueError("Estado de métrica desconocido")
    return {"estado": estado, "valor": valor, "unidad": unidad, "algoritmo": algoritmo,
            "numero_muestras": muestras, "semilla": semilla, "tolerancia": tolerancia,
            "requerida_para_aceptacion": requerido,
            "perfil": perfil or VERSION_METRICAS, "version": VERSION_METRICAS}


def _numero(objeto, atributo: str):
    medida = getattr(objeto, atributo, None)
    return float(medida.valor) if medida is not None else None


def _puntaje_error(error: float, tolerancia: float, escala: float) -> float:
    return max(0.0, 1.0 - max(0.0, error - tolerancia) / max(escala, tolerancia, 1e-9))


def puntaje_dimensional(plan, observadas: dict) -> dict:
    esperadas = plan.bounding_box_esperada
    if esperadas is None:
        esperadas = {eje: plan.dimensiones_globales.get(eje) for eje in ("x", "y", "z")}
    else:
        esperadas = {eje: getattr(esperadas, eje) for eje in ("x", "y", "z")}
    esperadas = {eje: medida for eje, medida in esperadas.items() if medida is not None}
    if not esperadas:
        return registro("not_applicable", algoritmo="El plan no declara cotas globales")
    cotas = observadas.get("bounding_box_mm")
    if not isinstance(cotas, dict):
        return registro("not_available", unidad="mm", algoritmo="El runtime no reportó bounding box",
                        requerido=any(m.procedencia == "specified" for m in esperadas.values()))
    errores, puntajes, detalle = {}, [], {}
    for eje, medida in esperadas.items():
        observado = cotas.get(eje)
        if observado is None:
            return registro("not_available", unidad="mm", algoritmo=f"Falta la cota {eje} observada",
                            requerido=medida.procedencia == "specified")
        esperado = float(medida.valor)
        error = abs(float(observado) - esperado)
        tolerancia = float(medida.tolerancia or max(abs(esperado) * 0.01, 0.1))
        puntaje = _puntaje_error(error, tolerancia, max(abs(esperado) * 0.10, tolerancia))
        errores[eje] = error
        detalle[eje] = {"esperado": esperado, "observado": float(observado),
                        "error_absoluto": error, "tolerancia": tolerancia,
                        "procedencia": medida.procedencia}
        puntajes.append(puntaje)
    requerido = any(m.procedencia == "specified" for m in esperadas.values())
    return registro("calculated", {"errores_mm": errores, "por_eje": detalle,
                                   "score": sum(puntajes) / len(puntajes)}, "mm",
                    "Promedio por eje: max(0, 1-max(0,error-tolerancia)/max(10% de cota,tolerancia))",
                    tolerancia=max((float(m.tolerancia or 0) for m in esperadas.values()), default=None),
                    requerido=requerido)


def puntaje_features(plan, features_observadas: dict, revision_visual=None) -> dict:
    declaradas = [feature for feature in plan.features if feature.esencial]
    criterios = [criterio for criterio in plan.criterios_verificables if criterio.esencial]
    exigidas = {feature.feature_id for feature in declaradas}
    agujeros = [f for f in declaradas if any(p in f.tipo.casefold() for p in ("hole", "agujero"))]
    detalles, evaluadas, presentes = [], 0, 0
    for feature in agujeros:
        dimension = next(((float(d.valor), float(d.tolerancia or 0.15)) for n, d in feature.dimensiones.items()
                          if n.casefold() in {"diameter", "diametro", "diámetro"}), None)
        cantidad_esperada = next((float(d.valor) for n, d in feature.dimensiones.items()
                                  if n.casefold() in {"count", "cantidad", "number"}), 1.0)
        datos = features_observadas.get(feature.feature_id)
        if not datos or datos.get("estado") != "calculated":
            detalles.append({"feature_id": feature.feature_id, "estado": "not_available"})
            continue
        observado = float(datos.get("cantidad", 0))
        count_matches = observado >= cantidad_esperada
        diameter_observed = datos.get("diametro_mm")
        diameter_matches = (dimension is None or (diameter_observed is not None
            and abs(float(diameter_observed) - dimension[0]) <= dimension[1]))
        coincide = count_matches and diameter_matches
        evaluadas += 1
        presentes += int(coincide)
        detalles.append({"feature_id": feature.feature_id,
                         "cantidad_esperada": cantidad_esperada, "cantidad_observada": observado,
                         "diametro_esperado_mm": dimension[0] if dimension else None,
                         "diametro_observado_mm": diameter_observed,
                         "tolerancia_diametro_mm": dimension[1] if dimension else None,
                         "estado": "present" if coincide else "missing",
                         "metodo": datos.get("algoritmo", "")})
    for criterio in criterios:
        if criterio.medicion not in {"hole_count", "hole_diameter"}:
            continue
        clave = criterio.feature_id or criterio.identificador
        datos = features_observadas.get(clave)
        if not datos or datos.get("estado") != "calculated":
            detalles.append({"feature_id": clave, "estado": "not_available"})
            continue
        esperado = float(criterio.esperado or 0)
        observado = float(datos.get("cantidad" if criterio.medicion == "hole_count" else "diametro_mm", 0) or 0)
        tolerancia = float(criterio.tolerancia or (0.0 if criterio.medicion == "hole_count" else 0.1))
        coincide = abs(observado - esperado) <= tolerancia
        evaluadas += 1
        presentes += int(coincide)
        exigidas.add(clave)
        detalles.append({"feature_id": clave, "esperado": esperado, "observado": observado,
                         "tolerancia": tolerancia, "estado": "present" if coincide else "missing"})
    total = max(len(exigidas), evaluadas)
    if not total:
        return registro("not_applicable", algoritmo="El plan no declara features esenciales")
    if evaluadas < total and revision_visual is not None:
        # Las medidas OCP conservan prioridad; Kimi verifica presencia semántica solamente.
        visuales = max(0, total - evaluadas)
        score = (presentes + float(revision_visual.puntuacion_features) * visuales) / total
        return registro("calculated", {"score": score, "verificadas_deterministas": evaluadas,
                                        "features_esenciales": total, "detalle": detalles,
                                        "aporte_visual": visuales,
                                        "metodo_visual": "Kimi K3; juicio semántico, no métrica dimensional"},
                        algoritmo="Conteo determinista de agujeros y revisión semántica para rasgos no medibles",
                        requerido=True)
    if evaluadas < total:
        return registro("not_available", {"verificadas": evaluadas, "features_esenciales": total,
                                           "detalle": detalles},
                        algoritmo="El evaluador no soporta todas las features declaradas",
                        requerido=True)
    return registro("calculated", {"score": presentes / evaluadas, "verificadas_deterministas": evaluadas,
                                   "features_esenciales": total, "detalle": detalles},
                    algoritmo="Proporción de features esenciales verificadas con medición B-Rep",
                    requerido=True)


def preparar_metricas(plan, observadas: dict, revision_visual=None,
                      comparacion_referencia: dict | None = None) -> dict:
    puntuaciones = {}
    puntuaciones["dimensional"] = puntaje_dimensional(plan, observadas)
    puntuaciones["features"] = puntaje_features(plan, observadas.get("features", {}), revision_visual)
    tecnicamente_valido = bool(observadas.get("technical_success"))
    watertight = bool(observadas.get("watertight"))
    dang_el = observadas.get("dang_el")
    brep_valido = bool(observadas.get("brep_valido"))
    un_solido = observadas.get("solidos") == 1
    topo_score = (1.0 if tecnicamente_valido and brep_valido and un_solido and watertight and dang_el == 0
                  else 0.0 if tecnicamente_valido else None)
    puntuaciones["topological"] = registro(
        "calculated" if tecnicamente_valido else "not_available", topo_score,
        algoritmo="1 si CAD exporta un sólido válido y la malla es watertight con DangEL=0; 0 en otro caso",
        requerido=True,
    )
    if revision_visual is not None:
        puntuaciones["silhouette"] = registro("calculated", revision_visual.puntuacion_silueta,
                                                algoritmo="Revisión visual de ocho vistas con Kimi K3; score semántico",
                                                requerido=True)
        puntuaciones["proportions"] = registro("calculated", revision_visual.puntuacion_proporciones,
                                                 algoritmo="Revisión visual de proporciones con Kimi K3")
    else:
        puntuaciones["silhouette"] = registro("not_available", algoritmo="Revisión visual no disponible", requerido=True)
        puntuaciones["proportions"] = registro("not_available", algoritmo="Revisión visual no disponible")

    simetria_observada = observadas.get("symmetry") or {}
    simetria_estado = simetria_observada.get("estado", "not_available")
    simetria_valor = simetria_observada.get("valor")
    puntuaciones["symmetry"] = registro(
        simetria_estado, simetria_valor, "ratio",
        simetria_observada.get("algoritmo", "Distancia de vecino más cercano tras reflexión"),
        simetria_observada.get("muestras"), simetria_observada.get("semilla"),
        perfil=simetria_observada.get("perfil", VERSION_METRICAS),
        requerido=simetria_estado == "calculated",
    )

    centroide_esperado = plan.centroide_esperado
    centroide_observado = observadas.get("centroide_mm")
    if centroide_esperado is not None and isinstance(centroide_observado, list) and len(centroide_observado) == 3:
        esperado = [float(getattr(centroide_esperado, e).valor) for e in "xyz"]
        error = math.dist(esperado, [float(v) for v in centroide_observado])
        tolerancia = max([float(getattr(centroide_esperado, e).tolerancia or 0) for e in "xyz"] + [0.1])
        escala = max(math.dist([0, 0, 0], esperado) * 0.1, tolerancia)
        puntuaciones["centroid"] = registro("calculated", {"error_mm": error,
            "score": _puntaje_error(error, tolerancia, escala), "esperado_mm": esperado,
            "observado_mm": centroide_observado}, "mm",
            "Distancia euclídea entre centroide esperado y centroide B-Rep", tolerancia=tolerancia,
            requerido=any(getattr(centroide_esperado, e).procedencia == "specified" for e in "xyz"))
    else:
        puntuaciones["centroid"] = registro("not_applicable", algoritmo="El plan no declara centroide objetivo")

    # Métricas derivadas de referencia se incluyen únicamente en el protocolo explícitamente habilitado.
    referencia = comparacion_referencia or {"estado": "not_available",
        "motivo": "No se autorizó una referencia independiente para esta ejecución"}
    ref_disponible = referencia.get("estado") == "calculada"
    criterio_volumen = next((c for c in plan.criterios_verificables
                             if c.esencial and c.medicion == "volumen" and isinstance(c.esperado, (int, float))), None)
    esperado_volumen = _numero(plan, "volumen_principal")
    if criterio_volumen is not None:
        esperado_volumen = float(criterio_volumen.esperado)
    if esperado_volumen is not None:
        observado = observadas.get("volumen_mm3")
        if observado is None:
            puntuaciones["volume"] = registro("not_available", unidad="mm3",
                algoritmo="El kernel CAD no reportó volumen", requerido=True)
        else:
            error = abs(float(observado) - esperado_volumen)
            tolerancia = float((criterio_volumen.tolerancia if criterio_volumen else None)
                               or (plan.volumen_principal.tolerancia if plan.volumen_principal else None) or max(esperado_volumen * 0.01, 0.1))
            puntuaciones["volume"] = registro("calculated", {"esperado_mm3": esperado_volumen,
                "observado_mm3": float(observado), "error_mm3": error,
                "score": _puntaje_error(error, tolerancia, max(abs(esperado_volumen) * 0.10, tolerancia))},
                "mm3", "Volumen del sólido B-Rep frente a volumen declarado", tolerancia=tolerancia,
                requerido=(criterio_volumen.esencial if criterio_volumen else
                           plan.volumen_principal.procedencia == "specified"))
    else:
        puntuaciones["volume"] = registro("not_applicable", unidad="mm3",
            algoritmo="El plan no declara volumen objetivo")

    criterio_area = next((c for c in plan.criterios_verificables
                          if c.esencial and c.medicion == "area" and isinstance(c.esperado, (int, float))), None)
    area_observada = observadas.get("area_mm2")
    error_area = referencia.get("surface_area_error_relative")
    if criterio_area and area_observada is not None:
        esperado_area = float(criterio_area.esperado)
        error_absoluto = abs(float(area_observada) - esperado_area)
        tolerancia = float(criterio_area.tolerancia or max(esperado_area * 0.01, 0.1))
        puntuaciones["surface_area"] = registro("calculated", {
            "esperado_mm2": esperado_area, "observado_mm2": float(area_observada),
            "error_mm2": error_absoluto,
            "score": _puntaje_error(error_absoluto, tolerancia, max(esperado_area * 0.10, tolerancia))},
            "mm2", "Área de superficie B-Rep frente a criterio especificado",
            tolerancia=tolerancia, requerido=True)
    elif ref_disponible and isinstance(error_area, (int, float)):
        puntuaciones["surface_area"] = registro("calculated", {
            "error_relativo": error_area, "score": max(0.0, 1.0 - float(error_area))},
            "ratio", "Error relativo de área superficial contra referencia")
    else:
        puntuaciones["surface_area"] = registro("not_available" if criterio_area else "not_applicable",
            algoritmo="Área objetivo no declarada o no hay referencia autorizada")
    hausdorff = referencia.get("hausdorff_robusto_mm")
    if ref_disponible and isinstance(hausdorff, dict):
        diagonal = max(math.sqrt(sum(float(v) ** 2 for v in observadas.get("bounding_box_mm", {}).values())), 1e-9)
        error_p95 = float(hausdorff["p95"])
        hausdorff_valor = {**hausdorff, "score": max(0.0, 1.0 - error_p95 / diagonal)}
        puntuaciones["hausdorff"] = registro("calculated", hausdorff_valor, "mm",
            "Percentiles bidireccionales 95/99 y máximo de distancia superficial", muestras=8192,
            semilla=20261004)
    else:
        puntuaciones["hausdorff"] = registro("not_available", unidad="mm",
            algoritmo="Requiere referencia explícitamente autorizada")
    normal = referencia.get("normal_consistency")
    puntuaciones["normal_consistency"] = registro(
        "calculated" if ref_disponible and isinstance(normal, (int, float)) else "not_available",
        float(normal) if ref_disponible and isinstance(normal, (int, float)) else None,
        algoritmo="Acuerdo de normales de vértices vecinos; aproximación reproducible por índice",
        muestras=min(8192, int(referencia.get("perfil_calidad", {}).get("puntos_superficie", 8192)))
        if ref_disponible else None, semilla=20261004 if ref_disponible else None,
    )
    iou = referencia.get("iou_brep")
    chamfer = referencia.get("chamfer_digital_mm2")
    silhouette_datos = referencia.get("silhouette_iou")
    silhouette_iou = (silhouette_datos.get("iou_medio") if isinstance(silhouette_datos, dict)
                      else silhouette_datos)
    puntuaciones["silhouette_iou"] = registro(
        "calculated" if ref_disponible and isinstance(silhouette_iou, (int, float)) else "not_available",
        float(silhouette_iou) if ref_disponible and isinstance(silhouette_iou, (int, float)) else None,
        algoritmo="IoU de siluetas rasterizadas en cuatro vistas con cámara y encuadre comunes",
        muestras=(silhouette_datos.get("muestras", 4) if ref_disponible and isinstance(silhouette_datos, dict)
                  else 4 if ref_disponible else None),
        semilla=SEMILLA_CHAMFER if ref_disponible else None,
        perfil=silhouette_datos.get("perfil", VERSION_METRICAS) if isinstance(silhouette_datos, dict) else VERSION_METRICAS)
    hausdorff_score = hausdorff_valor["score"] if ref_disponible and isinstance(hausdorff, dict) else None
    bbox_diagonal = max(math.sqrt(sum(float(v) ** 2 for v in observadas.get("bounding_box_mm", {}).values())), 1e-9)
    chamfer_score = max(0.0, 1.0 - math.sqrt(max(0.0, float(chamfer))) / bbox_diagonal) \
        if isinstance(chamfer, (int, float)) else None
    similaridades = [float(valor) for valor in (iou, chamfer_score, hausdorff_score)
                     if isinstance(valor, (int, float))]
    puntuaciones["reference_similarity"] = registro(
        "calculated" if similaridades else "not_available",
        {"score": sum(similaridades) / len(similaridades), "iou_brep": iou,
         "chamfer_digital_mm2": chamfer, "hausdorff_robusto_mm": hausdorff}
        if similaridades else None, algoritmo="Promedio de IoU B-Rep y score Hausdorff P95 disponibles",
        muestras=8192 if similaridades else None, semilla=20261004 if similaridades else None,
        perfil=referencia.get("protocolo", "sin-referencia"),
    )
    return {
        "perfil": VERSION_METRICAS,
        "clase_modelado": plan.clase_modelado,
        "puntuaciones": puntuaciones,
        "geometria_observada": observadas,
        "referencia": referencia,
        "formula": {"pesos": PESOS[plan.clase_modelado],
                    "normalizacion": "pesos de métricas calculadas / suma de sus pesos",
                    "version": VERSION_METRICAS, "umbral": UMBRAL_ACEPTACION},
    }


def evaluar_quality_gate(metricas: dict, tecnica_correcta: bool,
                         revision_codigo, revision_visual, critica) -> dict:
    clase = metricas["clase_modelado"]
    puntuaciones = metricas["puntuaciones"]
    pesos = PESOS[clase]
    calculadas = {}
    for clave, dato in puntuaciones.items():
        valor = dato.get("valor")
        if clave in {"dimensional", "features", "centroid", "surface_area", "hausdorff", "volume"} and valor is not None:
            valor = valor.get("score")
        elif clave == "reference_similarity" and valor is not None:
            valor = valor.get("score")
        if dato.get("estado") == "calculated" and isinstance(valor, (int, float)) and math.isfinite(valor):
            calculadas[clave] = max(0.0, min(1.0, float(valor)))
    peso_total = sum(pesos[clave] for clave in calculadas if clave in pesos)
    puntuacion = (sum(calculadas[clave] * pesos[clave] for clave in calculadas if clave in pesos) / peso_total
                  if peso_total else None)
    esenciales_faltantes = [clave for clave, dato in puntuaciones.items()
                            if dato.get("requerida_para_aceptacion")
                            and dato.get("estado") in {"not_available", "unsupported"}]
    severidad_bloqueante = any(i.severidad in {"high", "critical"} for i in revision_codigo.issues)
    error_critico = any(error.severidad == "critical" for error in revision_visual.errores + critica.errores)
    aceptado = bool(
        tecnica_correcta and puntuaciones["topological"]["estado"] == "calculated"
        and puntuaciones["topological"]["valor"] == 1.0
        and revision_codigo.accepted and not severidad_bloqueante
        and revision_visual.accepted and critica.accepted and not error_critico
        and not esenciales_faltantes and puntuacion is not None
        and puntuacion >= UMBRAL_ACEPTACION
    )
    return {
        "accepted": aceptado, "technical_success": bool(tecnica_correcta),
        "quality_success": aceptado, "quality_score": round(puntuacion, 6) if puntuacion is not None else None,
        "threshold": UMBRAL_ACEPTACION, "formula_version": VERSION_METRICAS,
        "subscores": calculadas, "evidence_missing": esenciales_faltantes,
        "motivo": "aceptado" if aceptado else "quality gate rechazó o evidencia insuficiente",
        "code_review_accepted": revision_codigo.accepted,
        "visual_review_accepted": revision_visual.accepted,
        "critic_accepted": critica.accepted,
        "reference_protocol": metricas["referencia"].get("protocolo", "sin-referencia"),
    }
