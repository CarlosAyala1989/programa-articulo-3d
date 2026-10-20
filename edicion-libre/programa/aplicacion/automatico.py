"""Lote incluido: una ejecución por tarea, checkpoints y recuperación sin intervención."""

import json
from pathlib import Path

from sqlalchemy import select

from aplicacion.base_datos import Campana, Ejecucion, crear_sesion, fecha_actual
from aplicacion.campanas import crear_campana, cambiar_estado
from aplicacion.configuracion import MODELOS_LOCALES, MOTORES_DISPONIBLES, PROTOCOLO_LOTE
from aplicacion.conjuntos import importar_documento


def asegurar_lote() -> str:
    datos = Path(__file__).resolve().parents[1] / "datos/prompts_45_v1.json"
    conjunto = importar_documento(json.loads(datos.read_text(encoding="utf-8")), congelar=True)
    with crear_sesion() as sesion:
        anteriores = list(sesion.scalars(select(Campana).where(Campana.conjunto_identificador == conjunto.identificador)))
        anterior = next((c for c in anteriores if (c.configuracion or {}).get("automatico")
            and (c.configuracion or {}).get("protocolo_campana") == PROTOCOLO_LOTE), None)
        if anterior:
            return anterior.identificador
    campana = crear_campana("Automático · 45 prompts · 5 modelos", conjunto.identificador,
        list(MODELOS_LOCALES), list(MOTORES_DISPONIBLES), ["open-loop", "closed-loop"], 1, 20261013, "lote-45")
    with crear_sesion() as sesion:
        registro = sesion.get(Campana, campana.identificador)
        registro.configuracion = {**registro.configuracion, "automatico": True,
            "pausa_manual": False, "recuperaciones_operativas": 0,
            "arranque": "automático tras instalar o abrir; sin repetir ejecuciones terminadas"}
        sesion.commit()
    return campana.identificador


def registrar_incidencia(identificador: str, error: Exception) -> int:
    with crear_sesion() as sesion:
        campana = sesion.get(Campana, identificador)
        numero = (campana.configuracion or {}).get("recuperaciones_operativas", 0) + 1
        espera = min(300, 10 * 2 ** min(numero - 1, 5))
        campana.configuracion = {**campana.configuracion, "recuperaciones_operativas": numero,
            "ultima_incidencia": {"fecha": fecha_actual().isoformat(), "tipo": type(error).__name__,
                                 "diagnostico": str(error)[:2000], "reintento_en_segundos": espera}}
        if campana.estado not in {"pausada", "cancelada", "completada"}:
            campana.estado = "bloqueada"
            campana.mensaje = f"Recuperación automática en {espera} s: {str(error)[:500]}"
        sesion.commit()
    return espera


def procesar_paso(identificador: str) -> int | None:
    from aplicacion.archivado import guardar_ejecucion, guardar_resumen
    from aplicacion.generacion import procesar_ejecucion
    with crear_sesion() as sesion:
        campana = sesion.get(Campana, identificador)
        if (not campana or not (campana.configuracion or {}).get("automatico")
                or (campana.configuracion or {}).get("protocolo_campana") != PROTOCOLO_LOTE):
            return None
        if campana.estado in {"cancelada", "pausada"}:
            return None
        terminado = campana.estado == "completada"
    if terminado:
        # Solo sincronizar el resumen; jamás volver a llamar a los modelos del lote terminado.
        try:
            guardar_resumen(identificador)
            return None
        except Exception as error:
            return registrar_incidencia(identificador, error)
    try:
        with crear_sesion() as sesion:
            campana = sesion.get(Campana, identificador)
            estado = campana.estado
        if estado in {"borrador", "bloqueada"}:
            cambiar_estado(identificador, "iniciar")
        with crear_sesion() as sesion:
            campana = sesion.get(Campana, identificador)
            if campana.estado != "en_curso":
                return None
            ejecucion = sesion.scalar(select(Ejecucion).where(
                Ejecucion.campana_identificador == identificador,
                Ejecucion.estado.in_(["pendiente", "pausada", "generando", "bloqueada"])
            ).order_by(Ejecucion.orden_campana).limit(1))
            if ejecucion is None:
                # Persistir entregables antes de declarar el lote terminado; un fallo de disco se reintenta.
                siguiente = None
            else:
                siguiente = ejecucion.identificador
                ejecucion.estado = "pendiente"
                ejecucion.fecha_fin = None
                sesion.commit()
        if siguiente:
            procesar_ejecucion(siguiente)
            with crear_sesion() as sesion:
                ejecucion = sesion.get(Ejecucion, siguiente)
                campana = sesion.get(Campana, identificador)
                if campana.estado in {"cancelada", "pausada"}:
                    guardar_resumen(identificador)
                    return None
                if ejecucion.estado not in {"completada", "fallida"}:
                    raise RuntimeError(ejecucion.mensaje)
            guardar_resumen(identificador)
            return 1
        # Recuperar también carpetas cuyo guardado se interrumpió después de confirmar la DB.
        with crear_sesion() as sesion:
            terminadas = list(sesion.scalars(select(Ejecucion.identificador).where(Ejecucion.campana_identificador == identificador)))
        for ejecucion_id in terminadas:
            guardar_ejecucion(ejecucion_id)
        guardar_resumen(identificador, figuras=True)
        with crear_sesion() as sesion:
            campana = sesion.get(Campana, identificador)
            if campana.estado in {"pausada", "cancelada"}:
                return None
            campana.estado = "completada"
            campana.mensaje = "Lote terminado: 1.350 ejecuciones y resultados guardados en Documentos/CielLibre/Resultados"
            campana.fecha_fin = fecha_actual()
            sesion.commit()
        guardar_resumen(identificador)
        return None
    except Exception as error:
        espera = registrar_incidencia(identificador, error)
        try:
            guardar_resumen(identificador)
        except Exception:
            pass  # El checkpoint en la DB sigue disponible aunque el disco de salida falle.
        return espera
