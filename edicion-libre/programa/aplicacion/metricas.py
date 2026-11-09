"""Métricas digitales con cohortes y denominadores explícitos."""

from collections import defaultdict
from statistics import mean, median, stdev

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from aplicacion.base_datos import (
    Campana, CasoDiseno, ComparacionDigital, Ejecucion, InformeTopologia,
    crear_sesion,
)


ESTADOS_EVALUABLES = {"completada", "fallida"}


def porcentaje(numerador: int, denominador: int) -> float | None:
    return round(100 * numerador / denominador, 4) if denominador else None


def resumen_grupo(
    ejecuciones: list[Ejecucion], topologias: dict, comparaciones: dict, modo: str,
    topologias_comunes: dict | None = None,
) -> dict:
    evaluables = [e for e in ejecuciones if e.estado in ESTADOS_EVALUABLES]
    n = len(evaluables)
    maximo = 1 if modo == "open-loop" else 5
    primeros_ejecucion = [sum(e.primer_exito_ejecucion == k for e in evaluables) for k in range(1, maximo + 1)]
    primeros_cad = [sum(e.primer_exito_exportacion == k for e in evaluables) for k in range(1, maximo + 1)]
    acumulado = 0
    compile_acumulado = []
    for cantidad in primeros_ejecucion:
        acumulado += cantidad
        compile_acumulado.append(porcentaje(acumulado, n))
    cad_acumulado = []
    acumulado = 0
    for cantidad in primeros_cad:
        acumulado += cantidad
        cad_acumulado.append(porcentaje(acumulado, n))
    def resumen_topologia(informes: dict) -> dict:
        validas = [informes[e.identificador] for e in evaluables if e.identificador in informes and informes[e.identificador].estado == "analizada"]
        watertight = sum(t.watertight is True for t in validas)
        aptas = sum(t.watertight is True and t.dang_el == 0 for t in validas)
        dang = [t.dang_el for t in validas if t.dang_el is not None]
        return {
            "n_stl_analizado": len(validas), "n_watertight": watertight,
            "watertight_pct_condicional": porcentaje(watertight, len(validas)),
            "cobertura_stl_pct": porcentaje(len(validas), n),
            "exito_malla_sobre_campana_pct": porcentaje(aptas, n),
            "dang_el_medio": round(mean(dang), 3) if dang else None,
        }
    comparaciones_validas = [comparaciones[e.identificador] for e in evaluables if e.identificador in comparaciones and comparaciones[e.identificador].estado == "calculada"]
    iou = [c.iou_brep for c in comparaciones_validas if c.iou_brep is not None]
    chamfer = [c.chamfer_digital_mm2 for c in comparaciones_validas if c.chamfer_digital_mm2 is not None]
    diferencias_volumen = [c.diferencia_volumen_mm3 for c in comparaciones_validas if c.diferencia_volumen_mm3 is not None]
    intentos = [i for e in evaluables for i in e.intentos]
    costos = [i.costo_estimado_usd for i in intentos if i.costo_estimado_usd is not None]
    latencias_ia = [i.duracion_ia_segundos for i in intentos if i.duracion_ia_segundos is not None]
    latencias_cad = [i.duracion_cad_segundos for i in intentos if i.duracion_cad_segundos is not None]
    tiempo_total = [
        (e.fecha_fin - e.fecha_inicio).total_seconds()
        for e in evaluables if e.fecha_fin and e.fecha_inicio
    ]
    return {
        "n_planificado": len(ejecuciones), "n_evaluable": n,
        "n_pendiente": sum(e.estado in {"pendiente", "generando", "pausada"} for e in ejecuciones),
        "n_bloqueado": sum(e.estado == "bloqueada" for e in ejecuciones),
        "n_cancelado": sum(e.estado == "cancelada" for e in ejecuciones),
        "final": n == len(ejecuciones),
        "primer_exito_ejecucion": primeros_ejecucion,
        "primer_exito_cad_exportable": primeros_cad,
        "compile_rate_acumulado_pct": compile_acumulado,
        "exito_cad_acumulado_pct": cad_acumulado,
        "sin_exito_ejecucion": n - sum(primeros_ejecucion),
        "sin_cad_exportable": n - sum(primeros_cad),
        "ir_cad_pct": porcentaje(n - sum(primeros_cad), n),
        "ir_codigo_pct": porcentaje(n - sum(primeros_ejecucion), n),
        "compile_rate_incremental_pct": [porcentaje(cantidad, n) for cantidad in primeros_ejecucion],
        "intentos_observados": len(intentos),
        "tokens_entrada": sum(i.tokens_entrada or 0 for i in intentos),
        "tokens_salida": sum(i.tokens_salida or 0 for i in intentos),
        "costo_estimado_usd": round(sum(costos), 6) if costos else None,
        "perfil_costo": "estimación pico sin caché; no es factura real" if costos else "sin tarifa API aplicable",
        "latencia_ia_media_s": round(mean(latencias_ia), 3) if latencias_ia else None,
        "latencia_cad_media_s": round(mean(latencias_cad), 3) if latencias_cad else None,
        "tiempo_total_mediana_s": round(median(tiempo_total), 3) if tiempo_total else None,
        "tiempo_total_media_s": round(mean(tiempo_total), 3) if tiempo_total else None,
        "tiempo_total_desviacion_s": round(stdev(tiempo_total), 3) if len(tiempo_total) > 1 else None,
        "topologia": resumen_topologia(topologias),
        "topologia_comun": resumen_topologia(topologias_comunes or {}),
        "referencias": {
            "n_iou": len(iou), "iou_brep_medio": round(mean(iou), 5) if iou else None,
            "n_chamfer": len(chamfer),
            "chamfer_digital_mm2_medio": round(mean(chamfer), 5) if chamfer else None,
            "n_diferencia_volumen": len(diferencias_volumen),
            "diferencia_volumen_mm3_media": round(mean(diferencias_volumen), 5)
            if diferencias_volumen else None,
        },
    }


def calcular_metricas_campana(identificador: str) -> dict:
    with crear_sesion() as sesion:
        campana = sesion.get(Campana, identificador)
        if campana is None:
            raise LookupError("Campaña no encontrada")
        ejecuciones = list(sesion.scalars(select(Ejecucion).where(
            Ejecucion.campana_identificador == identificador
        ).options(selectinload(Ejecucion.intentos))))
        casos = {caso.identificador: caso for caso in sesion.scalars(select(CasoDiseno).where(
            CasoDiseno.conjunto_identificador == campana.conjunto_identificador
        ))}
        ids = [e.identificador for e in ejecuciones]
        topologias = {}
        topologias_comunes = {}
        comparaciones = {}
        if ids:
            for informe in sesion.scalars(select(InformeTopologia).where(
                InformeTopologia.ejecucion_identificador.in_(ids)
            )):
                destino = topologias if informe.rol_malla == "nativa" else topologias_comunes
                destino[informe.ejecucion_identificador] = informe
            for comparacion in sesion.scalars(select(ComparacionDigital).where(
                ComparacionDigital.ejecucion_identificador.in_(ids)
            )):
                comparaciones[comparacion.ejecucion_identificador] = comparacion
        grupos = defaultdict(list)
        grupos_condicion = defaultdict(list)
        for ejecucion in ejecuciones:
            caso = casos.get(ejecucion.caso_identificador)
            nivel = caso.nivel if caso else "sin_nivel"
            grupos[(ejecucion.modelo, ejecucion.motor, ejecucion.modo, nivel)].append(ejecucion)
            grupos_condicion[(ejecucion.modelo, ejecucion.motor, ejecucion.modo)].append(ejecucion)
        filas = []
        perfiles = (campana.configuracion or {}).get("perfiles_generacion", {})
        for clave, grupo in sorted(grupos.items()):
            modelo, motor, modo, nivel = clave
            filas.append({
                "modelo": modelo, "motor": motor, "modo": modo, "nivel": nivel,
                "esfuerzo_razonamiento": perfiles.get(modelo, {}).get("reasoning_effort"),
                **resumen_grupo(grupo, topologias, comparaciones, modo, topologias_comunes),
            })
        condiciones = []
        for clave, grupo in sorted(grupos_condicion.items()):
            modelo, motor, modo = clave
            condiciones.append({
                "modelo": modelo, "motor": motor, "modo": modo, "nivel": "todos",
                "esfuerzo_razonamiento": perfiles.get(modelo, {}).get("reasoning_effort"),
                **resumen_grupo(grupo, topologias, comparaciones, modo, topologias_comunes),
            })
        por_celda = {}
        for ejecucion in ejecuciones:
            caso = casos.get(ejecucion.caso_identificador)
            if caso:
                clave = (ejecucion.modelo, ejecucion.modo, caso.nivel,
                         caso.codigo, ejecucion.repeticion, ejecucion.motor)
                por_celda[clave] = ejecucion
        comparaciones_motores = []
        for modelo, motor, modo, nivel in sorted(grupos):
            if motor == "cadquery":
                continue
            pares = []
            for ejecucion in grupos[(modelo, motor, modo, nivel)]:
                caso = casos.get(ejecucion.caso_identificador)
                if not caso:
                    continue
                base = por_celda.get((modelo, modo, nivel, caso.codigo,
                                      ejecucion.repeticion, "cadquery"))
                if base and base.estado in ESTADOS_EVALUABLES and ejecucion.estado in ESTADOS_EVALUABLES:
                    pares.append((base, ejecucion))
            n_pares = len(pares)
            comparaciones_motores.append({
                "modelo": modelo, "modo": modo, "nivel": nivel,
                "motor_comparado": motor, "motor_base": "cadquery",
                "n_pares_evaluables": n_pares,
                "delta_compile_pct": round(100 * sum(
                    int(e.primer_exito_ejecucion is not None) - int(b.primer_exito_ejecucion is not None)
                    for b, e in pares
                ) / n_pares, 4) if n_pares else None,
                "delta_exito_cad_pct": round(100 * sum(
                    int(e.primer_exito_exportacion is not None) - int(b.primer_exito_exportacion is not None)
                    for b, e in pares
                ) / n_pares, 4) if n_pares else None,
            })
        from aplicacion.comparativa import filas_externas
        return {
            "referencias_externas": filas_externas(sesion, campana),
            "campana_identificador": identificador, "nombre": campana.nombre,
            "estado": campana.estado,
            "final": bool(filas) and all(fila["final"] for fila in filas),
            "definiciones": {
                "compile_rate": "script que termina sin excepción; acumulado por primer intento exitoso / N evaluable",
                "ir_cad": "ejecuciones sin CAD válido y exportable / N evaluable",
                "ir_codigo": "ejecuciones sin script que termina sin excepción / N evaluable; no es IR geométrico",
                "n_evaluable": "ejecuciones completadas o agotadas; bloqueos operativos fuera del denominador",
                "topologia": "un STL nativo final por ejecución; ausentes no valen cero",
                "iou_chamfer": "solo con referencia independiente válida; ausencia no equivale a cero",
            },
            "filas": filas,
            "resumen_condiciones": condiciones,
            "comparaciones_motores": comparaciones_motores,
        }
