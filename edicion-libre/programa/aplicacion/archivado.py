"""Carpetas visibles en Windows, guardadas por condición, prompt e intento."""

import hashlib
import json
import re
import threading
from functools import wraps
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from aplicacion.base_datos import Campana, CasoDiseno, CondicionExperimental, Ejecucion, InformeTopologia, ComparacionDigital, crear_sesion
from aplicacion.configuracion import DIRECTORIO_RESULTADOS, MODELOS_LOCALES, MODO_NATIVO


def segmento(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", texto).strip("._")[:70] or "sin_nombre"


def guardar_atomico(ruta: Path, contenido: bytes | str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + "." + uuid4().hex + ".tmp")
    try:
        temporal.write_bytes(contenido.encode("utf-8") if isinstance(contenido, str) else contenido)
        try:
            temporal.replace(ruta)
        except PermissionError:
            if not MODO_NATIVO or ruta.suffix.lower() != ".csv":
                raise
            # Excel puede mantener el CSV abierto: conservar el nuevo contenido y avanzar.
            temporal.replace(ruta.with_name(ruta.stem + "-actualizado-" + uuid4().hex[:8] + ".csv"))
    finally:
        temporal.unlink(missing_ok=True)


def guardar_json(ruta: Path, datos) -> None:
    guardar_atomico(ruta, json.dumps(datos, ensure_ascii=False, indent=2, default=str) + "\n")


def carpeta_campana(campana: Campana) -> Path:
    return Path(DIRECTORIO_RESULTADOS) / (("L45-" if (campana.configuracion or {}).get("automatico") else "Campana-") + campana.identificador)


def carpeta_ejecucion(campana: Campana, caso: CasoDiseno, ejecucion: Ejecucion) -> Path:
    perfil = MODELOS_LOCALES.get(ejecucion.modelo, {"nombre": ejecucion.modelo, "cuantizacion": "no_registrada"})
    nombre = f"{ejecucion.modelo}_{perfil['nombre']}_{perfil['cuantizacion']}"
    nivel = {"basico": "01_basico", "intermedio": "02_intermedio", "complejo": "03_complejo"}[caso.nivel]
    codigo = caso.codigo if (campana.configuracion or {}).get("automatico") else f"{caso.codigo}__R{ejecucion.repeticion}__{ejecucion.identificador[:8]}"
    return carpeta_campana(campana) / segmento(nombre) / segmento(ejecucion.motor) / segmento(ejecucion.modo) / nivel / segmento(codigo)


def guardar_ejecucion(identificador: str) -> None:
    with crear_sesion() as sesion:
        ejecucion = sesion.get(Ejecucion, identificador)
        campana = sesion.get(Campana, ejecucion.campana_identificador) if ejecucion and ejecucion.campana_identificador else None
        if not campana or (not MODO_NATIVO and not (campana.configuracion or {}).get("automatico")):
            return
        caso = sesion.get(CasoDiseno, ejecucion.caso_identificador)
        condicion = sesion.get(CondicionExperimental, ejecucion.condicion_identificador) if ejecucion.condicion_identificador else None
        carpeta = carpeta_ejecucion(campana, caso, ejecucion)
        guardar_atomico(carpeta / "prompt.txt", caso.descripcion)
        guardar_json(carpeta / "caso.json", {"codigo": caso.codigo, "nivel": caso.nivel,
            "familia": caso.familia, "fundamento": caso.fundamento, "especificacion": caso.especificacion,
            "sha256_prompt": hashlib.sha256(caso.descripcion.encode()).hexdigest()})
        guardar_json(carpeta / "resultado.json", {"ejecucion": ejecucion.identificador,
            "campana": campana.identificador, "orden": ejecucion.orden_campana,
            "modelo": ejecucion.modelo, "motor": ejecucion.motor, "modo": ejecucion.modo,
            "estado": ejecucion.estado, "mensaje": ejecucion.mensaje,
            "numero_intentos": ejecucion.numero_intentos, "maximo_intentos": ejecucion.maximo_intentos,
            "primer_exito_ejecucion": ejecucion.primer_exito_ejecucion,
            "primer_exito_cad": ejecucion.primer_exito_cad, "primer_exito_exportacion": ejecucion.primer_exito_exportacion,
            "fecha_inicio": ejecucion.fecha_inicio, "fecha_fin": ejecucion.fecha_fin,
            "condicion": condicion.configuracion if condicion else None,
            "imagen_cad": condicion.imagen_identificador if condicion else None})
        for intento in ejecucion.intentos:
            destino = carpeta / "intentos" / f"{intento.numero:02}"
            guardar_atomico(destino / "codigo.py", intento.codigo)
            guardar_atomico(destino / "respuesta_modelo.txt", intento.respuesta_modelo)
            guardar_json(destino / "solicitud.json", intento.solicitud_modelo)
            guardar_json(destino / "registro.json", {clave: getattr(intento, clave) for clave in (
                "numero", "estado", "fase_error", "diagnostico", "sintaxis_valida", "ejecucion_correcta",
                "cad_valido", "exportacion_valida", "duracion_segundos", "duracion_ia_segundos", "duracion_cad_segundos",
                "tokens_entrada", "tokens_salida", "modelo_informado", "runtime_identificador", "fecha_creacion")})
            if MODO_NATIVO and intento.modelo_informado:
                solicitud = intento.solicitud_modelo or {}
                guardar_json(destino / "respuesta_ollama.json", {**(solicitud.get("metadatos_ollama") or {}),
                    "message": {"content": intento.respuesta_modelo, "thinking": solicitud.get("razonamiento_ollama")},
                    "telemetria_windows": solicitud.get("telemetria_ollama")})
        for archivo in ejecucion.archivos:
            ruta = Path(archivo.ruta)
            if not ruta.is_file():
                continue
            bruto = ruta.read_bytes()
            if hashlib.sha256(bruto).hexdigest() != archivo.sha256:
                raise RuntimeError("La copia del resultado CAD no coincide con su hash registrado")
            guardar_atomico(carpeta / "archivos" / segmento(archivo.nombre), bruto)
        topologias = list(sesion.scalars(select(InformeTopologia).where(InformeTopologia.ejecucion_identificador == identificador)))
        comparacion = sesion.scalar(select(ComparacionDigital).where(ComparacionDigital.ejecucion_identificador == identificador))
        guardar_json(carpeta / "metricas_digitales.json", {
            "topologia": [{clave: getattr(t, clave) for clave in ("rol_malla", "estado", "watertight", "dang_el", "sha256_malla", "diagnostico")} for t in topologias],
            "referencia": {clave: getattr(comparacion, clave) for clave in ("estado", "iou_brep", "chamfer_digital_mm2", "referencia_sha256", "diagnostico")} if comparacion else None})


BLOQUEO_RESUMEN = threading.RLock()


def serializar_exportaciones(funcion):
    @wraps(funcion)
    def protegida(*args, **kwargs):
        with BLOQUEO_RESUMEN:
            return funcion(*args, **kwargs)
    return protegida


@serializar_exportaciones
def guardar_resumen(identificador: str, figuras: bool = False, copia_sqlite: bool = False) -> None:
    from aplicacion.campanas import resumen_campana
    from aplicacion.metricas import calcular_metricas_campana
    from aplicacion.resultados import convertir_csv, csv_tabla_digital, figura_compilacion
    with crear_sesion() as sesion:
        campana = sesion.get(Campana, identificador)
        carpeta = carpeta_campana(campana)
        resumen = resumen_campana(campana)
        ejecuciones = list(sesion.scalars(select(Ejecucion).where(Ejecucion.campana_identificador == identificador).order_by(Ejecucion.orden_campana)))
        filas = [{clave: getattr(e, clave) for clave in ("identificador", "orden_campana", "modelo", "motor", "modo", "estado", "numero_intentos", "mensaje")} for e in ejecuciones]
        guardar_json(carpeta / "campana.json", resumen)
        guardar_json(carpeta / "progreso.json", {"total": len(ejecuciones), "terminadas": sum(e.estado in {"completada", "fallida"} for e in ejecuciones),
            "estado": campana.estado, "mensaje": campana.mensaje,
            "actual": next((fila for fila in filas if fila["estado"] not in {"completada", "fallida", "cancelada"}), None)})
        guardar_atomico(carpeta / "ejecuciones.csv", convertir_csv(filas, list(filas[0]) if filas else ["identificador"]))
        datos = Path(__file__).resolve().parents[1] / "datos"
        from aplicacion.base_datos import VersionConjunto
        conjunto = sesion.get(VersionConjunto, campana.conjunto_identificador)
        casos = list(sesion.scalars(select(CasoDiseno).where(CasoDiseno.conjunto_identificador == campana.conjunto_identificador)))
        guardar_json(carpeta / "protocolo/conjunto.json", {"nombre": conjunto.nombre, "version": conjunto.version,
            "huella_sha256": conjunto.huella_sha256, "casos": [{k: getattr(c, k) for k in (
                "codigo", "nivel", "familia", "fundamento", "descripcion", "especificacion")} for c in casos]})
        if (campana.configuracion or {}).get("automatico"):
            for archivo in ("45_prompts_Agente_Ciel.md", "prompts_45_v1.json", "origen_prompts45.json"):
                guardar_atomico(carpeta / "protocolo" / archivo, (datos / archivo).read_bytes())
        guardar_atomico(carpeta / "protocolo/literatura_digital_v1.json", (datos / "literatura_digital_v1.json").read_bytes())
    metricas = calcular_metricas_campana(identificador)
    guardar_json(carpeta / "metricas.json", metricas)
    guardar_atomico(carpeta / "tabla_digital.csv", csv_tabla_digital(metricas))
    guardar_atomico(carpeta / "metricas.csv", convertir_csv(metricas["filas"], sorted({k for f in metricas["filas"] for k in f})))
    if MODO_NATIVO:
        from nativo.exportaciones import exportar
        exportar(identificador, carpeta, metricas, copia_sqlite=figuras or copia_sqlite)
    if figuras:
        for nivel in ("todos", "basico", "intermedio", "complejo"):
            for formato in ("svg", "png"):
                guardar_atomico(carpeta / "figuras" / f"compile-rate-{nivel}.{formato}", figura_compilacion(metricas, formato, nivel))
    guardar_atomico(carpeta / "LEEME.txt", f"Campaña {campana.nombre}: {len({e.caso_identificador for e in ejecuciones})} prompts seleccionados; {len(ejecuciones)} ejecuciones.\n"
        "Carpetas: modelo / motor / modo / dificultad / código. Cada intento conserva código, respuesta, errores y tiempos.\n"
        "Los bloqueos de infraestructura se reintentan; los fallos CAD definitivos se registran y se pasa al siguiente prompt.\n"
        "Recuperaciones operativas en solicitud.json. Una respuesta perdida antes de persistirse puede necesitar otra llamada local.\n"
        "Los archivos ya terminados no se regeneran. Progreso.json es informativo; el checkpoint autoritativo es la base de datos local.\n"
        "Figuras finales y métricas en la raíz. IoU solo con referencia independiente habilitada. Las comparaciones físicas se exportan por separado desde la interfaz.\n"
        "Tiempo total es tiempo transcurrido, incluidas pausas; latencias por intento se registran aparte.\n"
        "La literatura no usa el mismo conjunto; sus tasas no son una comparación pareada por dificultad.\n")
