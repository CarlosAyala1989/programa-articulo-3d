"""Migra el esquema y deja visibles ejecuciones interrumpidas tras reiniciar."""

import os

from sqlalchemy import select

from aplicacion.base_datos import Campana, Ejecucion, crear_sesion, crear_tablas, fecha_actual
from aplicacion.configuracion import MODO_NATIVO, PROTOCOLO_LOTE


def preparar_reinicio(programar: bool = True) -> None:
    crear_tablas()
    if os.environ.get("CIEL_AUTOMATICO") == "1":
        from aplicacion.automatico import asegurar_lote
        asegurar_lote()
    with crear_sesion() as sesion:
        if MODO_NATIVO:
            for campana in sesion.scalars(select(Campana)):
                if ((campana.configuracion or {}).get("automatico")
                        and (campana.configuracion or {}).get("protocolo_campana") != PROTOCOLO_LOTE
                        and campana.estado in {"borrador", "en_curso", "bloqueada"}):
                    campana.estado = "pausada"
                    campana.mensaje = "Protocolo anterior conservado; el lote nuevo usa otra campaña"
        interrumpidas = list(sesion.scalars(select(Ejecucion).where(
            Ejecucion.estado == "generando"
        )))
        for ejecucion in interrumpidas:
            campana = sesion.get(Campana, ejecucion.campana_identificador) if ejecucion.campana_identificador else None
            if campana and (campana.configuracion or {}).get("automatico"):
                ejecucion.estado = "pendiente"
                ejecucion.mensaje = "Recuperando el último intento persistido después del reinicio"
                continue
            ejecucion.estado = "bloqueada"
            ejecucion.mensaje = "Interrumpida por reinicio; revisar respuesta y posible costo antes de otro ensayo"
            ejecucion.fecha_fin = fecha_actual()
        activas = list(sesion.scalars(select(Campana).where(Campana.estado == "en_curso")))
        for campana in activas:
            if (campana.configuracion or {}).get("automatico"):
                continue
            if any(e.campana_identificador == campana.identificador for e in interrumpidas):
                campana.estado = "bloqueada"
                campana.mensaje = "Una ejecución quedó interrumpida; revisar antes de otra campaña"
            else:
                campana.estado = "pausada"
                campana.mensaje = "Trabajador reiniciado; reanudar para continuar pendientes"
        sesion.commit()
        automaticas = [c.identificador for c in sesion.scalars(select(Campana))
                       if ((c.configuracion or {}).get("automatico")
                           and (not MODO_NATIVO or (c.configuracion or {}).get("protocolo_campana") == PROTOCOLO_LOTE)
                           and c.estado in {"borrador", "en_curso", "bloqueada", "completada"})]
    if programar:
        if MODO_NATIVO:
            from aplicacion.tareas_nativas import tarea_campana
        else:
            from aplicacion.tareas import tarea_campana
        for identificador in automaticas:
            tarea_campana.delay(identificador)


if __name__ == "__main__":
    preparar_reinicio()
    os.execvp("celery", ["celery", "-A", "aplicacion.tareas:celeria", "worker",
                         "--loglevel=INFO", "--concurrency=1"])
