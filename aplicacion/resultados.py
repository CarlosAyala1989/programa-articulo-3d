"""Exportaciones digitales por campaña y ejecución, disponibles durante su progreso."""

import csv
import hashlib
import io
import json
import re
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path


VERSION_EXPORTACION = "ciel-exportaciones-v1"
RUTA_LITERATURA = Path(__file__).resolve().parents[1] / "datos/literatura_digital_v1.json"
BLOQUEO_FIGURA = threading.Lock()
COLORES = ["#218c74", "#277da1", "#6a4c93", "#b565a7", "#e09f3e", "#c4c4c4"]


def convertir_csv(filas: list[dict]) -> str:
    columnas = sorted({clave for fila in filas for clave in fila}) or ["identificador"]
    salida = io.StringIO(newline="")
    escritor = csv.DictWriter(salida, fieldnames=columnas)
    escritor.writeheader()
    for fila in filas:
        # Excel no debe interpretar descripciones o respuestas de IA como fórmulas.
        valores = {}
        for clave, valor in fila.items():
            if isinstance(valor, (dict, list)):
                valor = json.dumps(valor, ensure_ascii=False, default=str)
            if isinstance(valor, str) and valor.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                valor = "'" + valor
            valores[clave] = valor
        escritor.writerow(valores)
    return salida.getvalue()


def aplanar(datos: dict, prefijo: str = "") -> dict:
    resultado = {}
    for clave, valor in datos.items():
        nombre = prefijo + clave
        if isinstance(valor, dict):
            resultado.update(aplanar(valor, nombre + "_"))
        elif isinstance(valor, list) and clave in {"primer_exito_ejecucion", "primer_exito_cad_exportable",
                                                 "compile_rate_acumulado_pct", "exito_cad_acumulado_pct"}:
            resultado.update({f"{nombre}_intento_{indice + 1}": numero for indice, numero in enumerate(valor)})
        else:
            resultado[nombre] = valor
    return resultado


def csv_tabla_digital(metricas: dict) -> str:
    filas = []
    for fila in metricas["filas"] + metricas["resumen_condiciones"]:
        compile_rate = fila["compile_rate_acumulado_pct"][-1]
        filas.append({
            "origen": "campana", "metodo": "Agente Ciel", "comparacion_directa": True,
            **{clave: fila.get(clave) for clave in ("modelo", "esfuerzo_razonamiento", "motor", "modo", "nivel",
                "n_planificado", "n_evaluable", "n_pendiente", "n_bloqueado", "n_cancelado", "final")},
            "compile_rate_pct": compile_rate,
            "ir_codigo_pct": round(100 - compile_rate, 4) if compile_rate is not None else None,
            "ir_cad_pct": fila["ir_cad_pct"],
            **aplanar(fila["referencias"], "referencia_"),
            **aplanar(fila["topologia"], "stl_"),
            "campana_identificador": metricas["campana_identificador"],
        })
    for referencia in json.loads(RUTA_LITERATURA.read_text(encoding="utf-8"))["filas"]:
        filas.append({"origen": "literatura", "metodo": referencia["metodo"], "nivel": referencia["nivel"],
            "compile_rate_pct": referencia["compile_rate_reportado_pct"],
            "ir_reportado_pct": referencia["ir_reportado_pct"], "fuente": referencia["fuente"]["url"],
            "pagina": referencia["fuente"]["pagina"], "tabla": referencia["fuente"]["tabla"],
            "dataset": referencia["dataset"], "comparacion_directa": False, "nota": referencia["nota"]})
    return convertir_csv(filas)


def csv_registros(datos: dict, tipo: str) -> str:
    filas = []
    for ejecucion in datos["ejecuciones"]:
        identidad = {clave: ejecucion.get(clave) for clave in ("identificador", "orden", "caso", "nivel",
                    "modelo", "esfuerzo_razonamiento", "motor", "modo", "repeticion", "estado")}
        if tipo == "ejecuciones":
            filas.append({**identidad, **{clave: ejecucion.get(clave) for clave in (
                "descripcion", "mensaje", "numero_intentos", "primer_exito_ejecucion", "primer_exito_cad",
                "primer_exito_exportacion", "technical_success", "quality_success", "fecha_creacion", "fecha_inicio", "fecha_fin")},
                "tokens_entrada": sum(i.get("tokens_entrada") or 0 for i in ejecucion["intentos"]),
                "tokens_salida": sum(i.get("tokens_salida") or 0 for i in ejecucion["intentos"]),
                "archivos_bytes": sum(a.get("tamano_bytes") or 0 for a in ejecucion["archivos"])})
        elif tipo == "intentos":
            for intento in ejecucion["intentos"]:
                filas.append({**identidad, "estado_ejecucion": ejecucion.get("estado"), **{clave: valor for clave, valor in intento.items()
                    if clave not in {"identificador", "solicitud_modelo", "respuesta_modelo", "codigo"}},
                    "codigo_sha256": hashlib.sha256((intento.get("codigo") or "").encode()).hexdigest(),
                    **aplanar((intento.get("solicitud_modelo") or {}).get("perfil") or {}, "perfil_")})
        elif tipo == "geometria":
            for informe in ejecucion.get("topologia", []):
                filas.append({**identidad, **aplanar(informe, "malla_")})
        else:
            raise ValueError("Tipo de CSV no reconocido")
    return convertir_csv(filas)


def figura_compilacion(metricas: dict, formato: str = "svg", nivel: str = "todos", tipo: str = "codigo") -> bytes:
    # Figure aislada y acceso serializado: Matplotlib no comparte estado entre solicitudes.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    if formato not in {"svg", "png", "pdf"}:
        raise ValueError("Formato de figura no reconocido")
    if tipo not in {"codigo", "cad"}:
        raise ValueError("Tipo de figura no reconocido")
    clave_exito = "primer_exito_ejecucion" if tipo == "codigo" else "primer_exito_cad_exportable"
    clave_fallo = "sin_exito_ejecucion" if tipo == "codigo" else "sin_cad_exportable"
    titulo = "Compile Rate" if tipo == "codigo" else "Éxito CAD exportable"
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
                        cantidades = fila[clave_exito] + [0] * (5 - len(fila[clave_exito]))
                        cantidades.append(fila[clave_fallo])
                        base = 0
                        for k, cantidad in enumerate(cantidades):
                            valor = 100 * cantidad / fila["n_evaluable"]
                            eje.bar(x, valor, bottom=base, color=COLORES[k], width=0.6,
                                    label=f"Intento {k + 1}" if k < 5 else "Sin éxito")
                            if valor >= 8:
                                eje.text(x, base + valor / 2, f"{valor:.1f}%", ha="center", va="center", fontsize=8, color="white" if k < 3 else "black")
                            base += valor
                        eje.text(x, 103, f"N={fila['n_evaluable']}/{fila['n_planificado']}", ha="center", fontsize=8)
                    eje.set_title(f"{modelo}\n{motor}", fontsize=11)
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
        figura.suptitle(f"{titulo} acumulado por iteración · {nivel}\n{metricas['nombre']} · {estado}", fontsize=13)
        salida = io.BytesIO()
        figura.savefig(salida, format=formato, dpi=180)
        figura.clear()
        return salida.getvalue()


def paquete_resultados(datos: dict, directorio_artefactos: str, destino: Path) -> Path:
    """Construye el ZIP en disco; incluye solo archivos registrados y verificados."""
    huellas, incidencias = [], []
    raiz = Path(directorio_artefactos).resolve()
    with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED) as paquete:
        def agregar(nombre: str, contenido: bytes | str) -> None:
            bruto = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
            paquete.writestr(nombre, bruto)
            huellas.append({"archivo": nombre, "tamano_bytes": len(bruto),
                            "sha256": hashlib.sha256(bruto).hexdigest()})

        agregar("datos_y_trazas.json", json.dumps(datos, ensure_ascii=False, indent=2, default=str))
        if datos.get("conjunto"):
            agregar("prompts.json", json.dumps(datos["conjunto"], ensure_ascii=False, indent=2, default=str))
        for tipo in ("ejecuciones", "intentos", "geometria"):
            agregar(f"{tipo}.csv", csv_registros(datos, tipo))
        metricas = datos.get("metricas")
        if metricas:
            agregar("literatura_fuentes.json", RUTA_LITERATURA.read_bytes())
            agregar("tabla_digital.csv", csv_tabla_digital(metricas))
            agregar("metricas.csv", convertir_csv([aplanar(f) for f in metricas["filas"]]))
            niveles = ["todos"] + sorted({f["nivel"] for f in metricas["filas"]})
            for nivel in niveles:
                for tipo in ("codigo", "cad"):
                    for formato in ("svg", "png", "pdf"):
                        agregar(f"figuras/{tipo}-{nivel}.{formato}", figura_compilacion(metricas, formato, nivel, tipo))
        for ejecucion in datos["ejecuciones"]:
            identificador = ejecucion["identificador"]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", identificador):
                incidencias.append({"ejecucion": identificador, "estado": "identificador_no_seguro"})
                continue
            carpeta = raiz / "ejecuciones" / identificador
            for intento in ejecucion["intentos"]:
                numero = intento["numero"]
                if not isinstance(numero, int) or numero < 1:
                    continue
                prefijo = f"ejecuciones/{identificador}/intento-{numero}"
                agregar(prefijo + "/codigo.py", intento.get("codigo") or "")
                agregar(prefijo + "/respuesta.txt", intento.get("respuesta_modelo") or "")
                agregar(prefijo + "/solicitud.json", json.dumps(intento.get("solicitud_modelo"), ensure_ascii=False, indent=2, default=str))
            for archivo in ejecucion["archivos"]:
                nombre = archivo["nombre"]
                ruta = carpeta / nombre
                estado = None
                if not nombre or Path(nombre).name != nombre or "\\" in nombre or ruta.is_symlink() or ruta.resolve().parent != carpeta:
                    estado = "ruta_no_segura"
                else:
                    try:
                        contenido = ruta.read_bytes()
                        if hashlib.sha256(contenido).hexdigest() != archivo["sha256"]:
                            estado = "hash_distinto"
                    except OSError:
                        estado = "ausente_o_ilegible"
                if estado:
                    incidencias.append({"ejecucion": identificador, "archivo": nombre, "estado": estado})
                else:
                    agregar(f"ejecuciones/{identificador}/archivos/{nombre}", contenido)
        agregar("archivos_ausentes.json", json.dumps(incidencias, ensure_ascii=False, indent=2))
        agregar("LEEME.txt", "Exportación digital Agente Ciel. Consultar version_exportacion y fecha_exportacion en datos_y_trazas.json.\n"
            "Si provisional=true, contiene lo guardado hasta la descarga. Descargar de nuevo al terminar.\n"
            "Los bloqueos y pendientes no cuentan como fallos geométricos evaluables. Sin evaluables las tasas están vacías.\n"
            "El éxito técnico y la aceptación de calidad se registran por separado. IoU requiere referencia independiente habilitada.\n"
            "Las filas de literatura son contexto con fuentes; usan otros datasets y no constituyen una comparación directa.\n"
            "No incluye claves, configuración de cuentas ni una copia de la base de datos del servidor.\n"
            "Los archivos CAD ausentes, inseguros o con hash distinto se indican en archivos_ausentes.json.\n")
        paquete.writestr("huellas_archivos.json", json.dumps(huellas, ensure_ascii=False, indent=2))
    return destino


def metadatos_exportacion(provisional: bool) -> dict:
    return {"version_exportacion": VERSION_EXPORTACION, "provisional": provisional,
            "fecha_exportacion": datetime.now(timezone.utc).isoformat()}
