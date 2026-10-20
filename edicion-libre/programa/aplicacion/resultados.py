"""Entregables digitales: tasas, figura reproducible y trazas del lote local."""

import csv
import hashlib
import io
import json
import threading
import zipfile
from pathlib import Path


RUTA_LITERATURA = Path(__file__).resolve().parents[1] / "datos/literatura_digital_v1.json"
BLOQUEO_FIGURA = threading.Lock()
COLORES = ["#218c74", "#277da1", "#6a4c93", "#b565a7", "#e09f3e", "#c4c4c4"]


def convertir_csv(filas: list[dict], columnas: list[str]) -> str:
    salida = io.StringIO(newline="")
    escritor = csv.DictWriter(salida, fieldnames=columnas, extrasaction="ignore")
    escritor.writeheader()
    for fila in filas:
        escritor.writerow({clave: json.dumps(valor, ensure_ascii=False) if isinstance(valor, (dict, list)) else valor
                           for clave, valor in fila.items()})
    return salida.getvalue()


def filas_tabla_digital(metricas: dict) -> list[dict]:
    filas = []
    for fila in metricas["filas"] + metricas["resumen_condiciones"]:
        filas.append({
            "origen": "lote_local", "metodo": "Agente Ciel Libre", "modelo": fila["modelo"],
            "motor": fila["motor"], "modo": fila["modo"], "nivel": fila["nivel"],
            "n_planificado": fila["n_planificado"], "n_evaluable": fila["n_evaluable"],
            "n_bloqueado": fila["n_bloqueado"], "n_pendiente": fila["n_pendiente"],
            "final": fila["final"], "compile_rate_pct": fila["compile_rate_acumulado_pct"][-1],
            "ir_codigo_pct": fila["ir_codigo_pct"], "ir_cad_pct": fila["ir_cad_pct"],
            "iou_medio": fila["referencias"]["iou_brep_medio"],
            "n_iou": fila["referencias"]["n_iou"],
            "tiempo_total_media_s": fila["tiempo_total_media_s"],
            "tiempo_total_desviacion_s": fila["tiempo_total_desviacion_s"],
            "fuente": metricas["campana_identificador"], "comparacion_directa": True,
            "nota": "Compile Rate: ejecución sin excepción. IR código y CAD tienen criterios distintos. Bloqueos operativos excluidos del denominador.",
        })
    for referencia in json.loads(RUTA_LITERATURA.read_text(encoding="utf-8"))["filas"]:
        filas.append({"origen": "literatura", "metodo": referencia["metodo"],
            "nivel": referencia["nivel"], "compile_rate_pct": referencia["compile_rate_reportado_pct"],
            "ir_reportado_pct": referencia["ir_reportado_pct"],
            "fuente": referencia["fuente"]["url"], "pagina": referencia["fuente"]["pagina"],
            "tabla": referencia["fuente"]["tabla"], "dataset": referencia["dataset"],
            "comparacion_directa": False, "nota": referencia["nota"]})
    return filas


def csv_tabla_digital(metricas: dict) -> str:
    columnas = ["origen", "metodo", "modelo", "motor", "modo", "nivel", "n_planificado", "n_evaluable",
        "n_bloqueado", "n_pendiente", "final", "compile_rate_pct", "ir_codigo_pct", "ir_cad_pct",
        "ir_reportado_pct", "iou_medio", "n_iou", "tiempo_total_media_s", "tiempo_total_desviacion_s",
        "fuente", "pagina", "tabla", "dataset", "comparacion_directa", "nota"]
    return convertir_csv(filas_tabla_digital(metricas), columnas)


def figura_compilacion(metricas: dict, formato: str = "svg", nivel: str = "todos") -> bytes:
    # Figure aislada y acceso serializado: Matplotlib no comparte estado entre solicitudes.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    if formato not in {"svg", "png"}:
        raise ValueError("Formato de figura no reconocido")
    fuente = metricas["resumen_condiciones"] if nivel == "todos" else [
        f for f in metricas["filas"] if f["nivel"] == nivel]
    modelos = sorted({fila["modelo"] for fila in fuente})
    motores = [motor for motor in ("cadquery", "build123d", "freecad") if any(f["motor"] == motor for f in fuente)]
    with BLOQUEO_FIGURA:
        figura = Figure(figsize=(12, max(3.5, 2.5 * len(modelos))), layout="constrained")
        FigureCanvasAgg(figura)
        mapa = {(f["modelo"], f["motor"], f["modo"]): f for f in fuente}
        if not modelos or not motores:
            eje = figura.subplots()
            eje.text(0.5, 0.5, "No hay casos de este nivel", ha="center", va="center")
            eje.set_axis_off()
        else:
            ejes = figura.subplots(len(modelos), len(motores), squeeze=False)
            for i, modelo in enumerate(modelos):
                for j, motor in enumerate(motores):
                    eje = ejes[i, j]
                    for x, modo in enumerate(("open-loop", "closed-loop")):
                        fila = mapa.get((modelo, motor, modo))
                        if not fila or not fila["n_evaluable"]:
                            eje.text(x, 45, "Sin evaluables", ha="center", rotation=90, fontsize=8)
                            continue
                        cantidades = fila["primer_exito_ejecucion"] + [0] * (5 - len(fila["primer_exito_ejecucion"]))
                        cantidades.append(fila["sin_exito_ejecucion"])
                        base = 0
                        for k, cantidad in enumerate(cantidades):
                            valor = 100 * cantidad / fila["n_evaluable"]
                            eje.bar(x, valor, bottom=base, color=COLORES[k], width=0.6,
                                    label=f"Intento {k + 1}" if k < 5 else "Sin éxito")
                            if valor >= 8:
                                eje.text(x, base + valor / 2, f"{valor:.1f}%", ha="center", va="center", fontsize=8, color="white" if k < 3 else "black")
                            base += valor
                        eje.text(x, 103, f"N={fila['n_evaluable']}/{fila['n_planificado']}", ha="center", fontsize=8)
                    eje.set_title(f"{modelo} · {motor}", fontsize=11)
                    eje.set_xticks([0, 1], ["Open-loop", "Closed-loop"])
                    eje.set_ylim(0, 115)
                    eje.set_yticks([0, 25, 50, 75, 100])
                    eje.set_ylabel("Porcentaje evaluable")
                    eje.grid(axis="y", alpha=0.2)
                    eje.set_axisbelow(True)
                    eje.spines[["right", "top"]].set_visible(False)
            from matplotlib.patches import Patch
            figura.legend(handles=[Patch(facecolor=c, label=f"Intento {k+1}" if k < 5 else "Sin éxito")
                for k, c in enumerate(COLORES)], loc="outside lower center", ncol=6, frameon=False)
        estado = "Final" if metricas["final"] else "Provisional"
        figura.suptitle(f"Compile Rate acumulado por iteración · {nivel}\n{metricas['nombre']} · {estado}", fontsize=13)
        salida = io.BytesIO()
        figura.savefig(salida, format=formato, dpi=180)
        figura.clear()
        return salida.getvalue()


def paquete_resultados(datos: dict, directorio_artefactos: str, destino: Path | None = None) -> bytes | Path:
    metricas = datos["metricas"]
    salida = destino if destino is not None else io.BytesIO()
    huellas = []
    with zipfile.ZipFile(salida, "w", compression=zipfile.ZIP_DEFLATED) as paquete:
        def agregar(nombre: str, contenido: bytes | str) -> None:
            bruto = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
            paquete.writestr(nombre, bruto)
            huellas.append({"archivo": nombre, "sha256": hashlib.sha256(bruto).hexdigest()})
        agregar("datos_y_trazas.json", json.dumps(datos, ensure_ascii=False, indent=2))
        agregar("prompts.json", json.dumps(datos["conjunto"], ensure_ascii=False, indent=2))
        agregar("tabla_digital.csv", csv_tabla_digital(metricas))
        agregar("literatura_fuentes.json", RUTA_LITERATURA.read_bytes())
        campos_metricas = sorted({clave for fila in metricas["filas"] for clave in fila})
        agregar("metricas.csv", convertir_csv(metricas["filas"], campos_metricas))
        filas_ejecucion = []
        filas_intento = []
        archivos_ausentes = []
        for ejecucion in datos["ejecuciones"]:
            identidad = {c: ejecucion.get(c) for c in ("identificador", "orden", "caso", "nivel", "modelo", "motor", "modo", "repeticion")}
            filas_ejecucion.append({**identidad, **{c: ejecucion.get(c) for c in (
                "estado", "primer_exito_ejecucion", "primer_exito_cad", "primer_exito_exportacion", "fecha_inicio", "fecha_fin")}})
            for intento in ejecucion["intentos"]:
                registro = {**identidad, **{c: intento.get(c) for c in ("numero", "estado", "fase_error", "diagnostico", "sintaxis_valida", "ejecucion_correcta",
                    "cad_valido", "exportacion_valida", "duracion_segundos", "duracion_ia_segundos", "duracion_cad_segundos",
                    "tokens_entrada", "tokens_salida", "modelo_informado", "runtime_identificador", "fecha_creacion")}}
                registro["codigo_sha256"] = hashlib.sha256((intento.get("codigo") or "").encode()).hexdigest()
                filas_intento.append(registro)
                prefijo = f"ejecuciones/{ejecucion['identificador']}/intento-{intento['numero']}"
                agregar(prefijo + "/codigo.py", intento.get("codigo") or "")
                agregar(prefijo + "/respuesta.txt", intento.get("respuesta_modelo") or "")
                agregar(prefijo + "/solicitud.json", json.dumps(intento.get("solicitud_modelo"), ensure_ascii=False, indent=2))
            carpeta = (Path(directorio_artefactos) / "ejecuciones" / ejecucion["identificador"]).resolve()
            for archivo in ejecucion["archivos"]:
                ruta = carpeta / archivo["nombre"]
                # Los nombres registrados no pueden salir de la carpeta de esta ejecución.
                if ruta.resolve().parent != carpeta or not ruta.is_file() or ruta.is_symlink():
                    archivos_ausentes.append({"ejecucion": ejecucion["identificador"], "archivo": archivo["nombre"], "estado": "ausente"})
                    continue
                contenido = ruta.read_bytes()
                if hashlib.sha256(contenido).hexdigest() != archivo["sha256"]:
                    archivos_ausentes.append({"ejecucion": ejecucion["identificador"], "archivo": archivo["nombre"], "estado": "hash_distinto"})
                    continue
                agregar(f"ejecuciones/{ejecucion['identificador']}/archivos/{archivo['nombre']}", contenido)
        for nombre, filas in (("ejecuciones.csv", filas_ejecucion), ("intentos.csv", filas_intento)):
            columnas = sorted({clave for fila in filas for clave in fila}) or ["identificador"]
            agregar(nombre, convertir_csv(filas, columnas))
        for nivel in ["todos"] + sorted({f["nivel"] for f in metricas["filas"]}):
            agregar(f"figuras/compile-rate-{nivel}.svg", figura_compilacion(metricas, "svg", nivel))
        agregar("archivos_ausentes.json", json.dumps(archivos_ausentes, ensure_ascii=False, indent=2))
        agregar("LEEME.txt", "Resultados de generación y evaluación digital. No hay medidas de piezas físicas.\n"
            "Figura: segmentos por primer intento exitoso; sumar segmentos da Compile Rate acumulado.\n"
            "IR código y CAD usan denominadores evaluables, con bloqueos operativos excluidos.\n"
            "IoU requiere referencia independiente y activación explícita; sin referencia queda vacío.\n"
            "La literatura usa otro conjunto y criterios; no implica comparación directa ni ranking.\n"
            "Los 45 prompts son el tamaño solicitado, inferior al mínimo 50 del PDF.\n"
            "Consultar estado final/provisional, pendientes, bloqueos y archivos_ausentes.json.\n")
        paquete.writestr("huellas_archivos.json", json.dumps(huellas, ensure_ascii=False, indent=2))
    return destino if destino is not None else salida.getvalue()
