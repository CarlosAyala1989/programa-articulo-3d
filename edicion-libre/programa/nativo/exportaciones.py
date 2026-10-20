"""CSV completos, tabla de manufacturabilidad y copia consistente de SQLite."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from aplicacion.base_datos import Campana, CasoDiseno, ComparacionDigital, Ejecucion, InformeTopologia, crear_sesion, motor_base_datos
from aplicacion.resultados import convertir_csv


def aplanar(datos: dict, prefijo: str = "") -> dict:
    resultado = {}
    for clave, valor in datos.items():
        nombre = prefijo + clave
        if isinstance(valor, dict):
            resultado.update(aplanar(valor, nombre + "_"))
        elif isinstance(valor, list) and clave in {"primer_exito_ejecucion", "primer_exito_cad_exportable",
                "compile_rate_acumulado_pct", "compile_rate_incremental_pct", "exito_cad_acumulado_pct"}:
            resultado.update({nombre + f"_intento_{n + 1}": v for n, v in enumerate(valor)})
        else:
            resultado[nombre] = valor
    return resultado


def exportar(identificador: str, carpeta: Path, metricas: dict, copia_sqlite: bool = False) -> None:
    from aplicacion.archivado import guardar_atomico, guardar_json
    filas_intentos, filas_ejecuciones, filas_geometria = [], [], []
    with crear_sesion() as sesion:
        campana = sesion.get(Campana, identificador)
        ejecuciones = list(sesion.scalars(select(Ejecucion).where(Ejecucion.campana_identificador == identificador)
            .order_by(Ejecucion.orden_campana).options(selectinload(Ejecucion.intentos), selectinload(Ejecucion.archivos))))
        casos = {c.identificador: c for c in sesion.scalars(select(CasoDiseno).where(CasoDiseno.conjunto_identificador == campana.conjunto_identificador))}
        ids = [e.identificador for e in ejecuciones]
        topologias = {(t.ejecucion_identificador, t.rol_malla): t for t in sesion.scalars(select(InformeTopologia).where(InformeTopologia.ejecucion_identificador.in_(ids)))}
        comparaciones = {c.ejecucion_identificador: c for c in sesion.scalars(select(ComparacionDigital).where(ComparacionDigital.ejecucion_identificador.in_(ids)))}
        for ejecucion in ejecuciones:
            caso = casos[ejecucion.caso_identificador]
            ultimo = ejecucion.intentos[-1] if ejecucion.intentos else None
            perfil = ((ultimo.solicitud_modelo or {}).get("perfil") or {}) if ultimo else {}
            identidad = {"ejecucion": ejecucion.identificador, "orden": ejecucion.orden_campana,
                "caso": caso.codigo, "nivel": caso.nivel, "familia": caso.familia, "modelo": ejecucion.modelo,
                "etiqueta_ollama": perfil.get("etiqueta"), "cuantizacion": perfil.get("cuantizacion"),
                "digest_modelo": perfil.get("digest"), "motor": ejecucion.motor, "modo": ejecucion.modo,
                "prompt_sha256": hashlib.sha256(caso.descripcion.encode()).hexdigest()}
            fila = {**identidad, "estado": ejecucion.estado, "mensaje": ejecucion.mensaje,
                "intentos": ejecucion.numero_intentos, "maximo_intentos": ejecucion.maximo_intentos,
                "primer_exito_ejecucion": ejecucion.primer_exito_ejecucion, "primer_exito_cad": ejecucion.primer_exito_cad,
                "primer_exito_exportacion": ejecucion.primer_exito_exportacion, "fecha_inicio": ejecucion.fecha_inicio,
                "fecha_fin": ejecucion.fecha_fin, "tiempo_transcurrido_s": (ejecucion.fecha_fin - ejecucion.fecha_inicio).total_seconds()
                    if ejecucion.fecha_inicio and ejecucion.fecha_fin else None,
                "tokens_entrada_total": sum(i.tokens_entrada or 0 for i in ejecucion.intentos),
                "tokens_salida_total": sum(i.tokens_salida or 0 for i in ejecucion.intentos),
                "latencia_ia_total_s": sum(i.duracion_ia_segundos or 0 for i in ejecucion.intentos)
                    if any(i.duracion_ia_segundos is not None for i in ejecucion.intentos) else None,
                "latencia_cad_total_s": sum(i.duracion_cad_segundos or 0 for i in ejecucion.intentos)
                    if any(i.duracion_cad_segundos is not None for i in ejecucion.intentos) else None,
                "archivos_bytes": sum(a.tamano_bytes for a in ejecucion.archivos),
                "success_tecnico": (ejecucion.estado == "completada")
                    if ejecucion.estado in {"completada", "fallida"} else None,
                "fidelidad_geometrica_certificada": None,
                "hausdorff_fisico_mm": None, "chamfer_fisico_mm2": None, "error_dimensional_fisico_mm": None,
                "estado_metrologia_fisica": "pendiente_de_impresion_y_escaneo_reales"}
            for rol in ("nativa", "comun"):
                informe = topologias.get((ejecucion.identificador, rol))
                if informe:
                    fila.update({rol + "_" + clave: getattr(informe, clave) for clave in (
                        "estado", "watertight", "dang_el", "aristas_abiertas", "aristas_no_manifold", "componentes",
                        "vertices", "caras", "orientacion_consistente", "volumen_mm3", "sha256_malla")})
                    geometria = (informe.perfil or {}).get("geometria")
                    if geometria and rol == "nativa":
                        filas_geometria.append({**identidad, **aplanar(geometria)})
                        fila.update(aplanar({k: v for k, v in geometria.items() if k != "metadatos"}, "brep_"))
            comparacion = comparaciones.get(ejecucion.identificador)
            if comparacion:
                fila.update({k: getattr(comparacion, k) for k in ("iou_brep", "chamfer_digital_mm2", "diferencia_volumen_mm3", "referencia_sha256")})
                fila["estado_referencia"] = comparacion.estado
            filas_ejecuciones.append(fila)
            for intento in ejecucion.intentos:
                solicitud = intento.solicitud_modelo or {}
                datos = solicitud.get("metadatos_ollama") or {}
                validacion = solicitud.get("validacion_cad") or {}
                registro = {**identidad, **{k: getattr(intento, k) for k in ("numero", "estado", "fase_error", "diagnostico",
                    "sintaxis_valida", "ejecucion_correcta", "cad_valido", "exportacion_valida", "duracion_segundos",
                    "duracion_ia_segundos", "duracion_cad_segundos", "tokens_entrada", "tokens_salida", "modelo_informado",
                    "runtime_identificador", "fecha_creacion")}, "codigo_sha256": hashlib.sha256(intento.codigo.encode()).hexdigest(),
                    "solicitud_sha256": hashlib.sha256(json.dumps(solicitud.get("mensajes"), ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                    "recuperaciones_operativas": len(solicitud.get("recuperaciones_operativas") or []),
                    "razonamiento_caracteres": len(solicitud.get("razonamiento_ollama") or ""),
                    **aplanar(solicitud.get("perfil") or {}, "perfil_"),
                    **aplanar(datos, "ollama_"), **aplanar(solicitud.get("telemetria_ollama") or {}, "windows_"),
                    **aplanar(validacion.get("metricas_proceso") or {}, "cad_")}
                for clave in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
                    registro["ollama_" + clave + "_segundos"] = datos.get(clave) / 1e9 if datos.get(clave) is not None else None
                for sufijo, cantidad, duracion in (("entrada", "prompt_eval_count", "prompt_eval_duration"), ("salida", "eval_count", "eval_duration")):
                    registro["ollama_tokens_" + sufijo + "_por_segundo"] = datos.get(cantidad, 0) * 1e9 / datos[duracion] if datos.get(duracion, 0) else None
                filas_intentos.append(registro)
    for nombre, filas in (("ejecuciones.csv", filas_ejecuciones), ("intentos.csv", filas_intentos),
            ("geometria.csv", filas_geometria), ("metricas_detalladas.csv", [aplanar(f) for f in metricas["filas"] + metricas["resumen_condiciones"]])):
        guardar_atomico(carpeta / nombre, convertir_csv(filas, sorted({k for f in filas for k in f}) or ["ejecucion"]))
    manufacturabilidad = []
    for fila in metricas["filas"] + metricas["resumen_condiciones"]:
        for rol, clave in (("nativa", "topologia"), ("comun", "topologia_comun")):
            manufacturabilidad.append({**{k: fila[k] for k in ("modelo", "motor", "modo", "nivel", "n_planificado", "n_evaluable", "final")},
                "rol_stl": rol, **fila[clave], "impresion_fisica_verificada": None})
    guardar_atomico(carpeta / "manufacturabilidad.csv", convertir_csv(manufacturabilidad, sorted({k for f in manufacturabilidad for k in f})))
    plantilla = carpeta / "mediciones_fisicas.csv"
    if not plantilla.exists():
        columnas = ["ejecucion", "caso", "modelo", "motor", "modo", "pieza_impresa", "foto_pieza", "escaneo_pcd_ply", "alineacion_icp",
            "hausdorff_maximo_mm", "chamfer_fisico_mm2", "cota_critica", "nominal_mm", "medido_mm", "delta_dimensional_mm",
            "delta_media_mm", "delta_desviacion_estandar_mm", "mapa_calor", "calibracion_escaner", "estado"]
        pendientes = [{**{k: f[k] for k in ("ejecucion", "caso", "modelo", "motor", "modo")}, "estado": "no_medido"} for f in filas_ejecuciones]
        guardar_atomico(plantilla, convertir_csv(pendientes, columnas))
    registro_modelos = Path(os.environ["CIEL_REGISTRO_MODELOS"])
    guardar_atomico(carpeta / "protocolo/modelos_windows_instalados.json", registro_modelos.read_bytes())
    guardar_atomico(carpeta / "protocolo/runtimes_nativos.json", Path(os.environ["CIEL_RUNTIMES_NATIVOS"]).read_bytes())
    completadas = sum(e.estado in {"completada", "fallida"} for e in ejecuciones)
    contador_copia = carpeta / "sqlite_checkpoint.json"
    checkpoint = json.loads(contador_copia.read_text(encoding="utf-8")) if contador_copia.is_file() else {}
    ultimo = checkpoint.get("terminadas", -1)
    cierre = campana.estado == "completada" and checkpoint.get("estado") != "completada"
    if copia_sqlite or cierre or (completadas > 0 and completadas % 50 == 0 and completadas != ultimo):
        temporal = carpeta / "resultados.sqlite.tmp"
        with sqlite3.connect(str(motor_base_datos.url.database), timeout=60) as origen, sqlite3.connect(temporal) as destino:
            origen.backup(destino, pages=256, sleep=0.05)
        temporal.replace(carpeta / "resultados.sqlite")
        guardar_json(contador_copia, {"terminadas": completadas, "estado": campana.estado,
            "origen": motor_base_datos.url.database})
    guardar_json(carpeta / "alcance_metricas.json", {"protocolo": (campana.configuracion or {}).get("protocolo_campana"),
        "perfiles_generacion": (campana.configuracion or {}).get("perfiles_generacion"),
        "sqlite_activo": motor_base_datos.url.database, "n_prompts": 45, "n_ejecuciones": 1350,
        "gemma": "Q8_0 instalada por el usuario; no corresponde al perfil Q5_K_M anterior",
        "iou": "solo con STEP independiente y usar_referencias activado",
        "topologia": "DangEL y watertight digitales; no certifican una impresión física",
        "metrologia": "columnas y plantilla pendientes; requieren piezas impresas, escaneo y medidas reales",
        "comparacion_literatura": "no pareada; conjuntos y categorías de dificultad diferentes",
        "tamano_dataset_pdf": "45 casos piloto por solicitud; el PDF propone 50 a 100"})
