"""Reanudar explícitamente una campaña bloqueada desde su último intento guardado.

Uso: python -m aplicacion.reanudar_campana ID [--repetir-proveedor]
El segundo argumento autoriza una nueva llamada cuando no existe respuesta guardada.
"""

import argparse

from sqlalchemy import select

from aplicacion.base_datos import Campana, Ejecucion, crear_sesion
from aplicacion.campanas import cambiar_estado, procesar_campana
from aplicacion.generacion import _preparar_recuperacion, procesar_ejecucion


def reanudar_campana(identificador: str, repetir_proveedor: bool = False) -> None:
    # Validar todos los bloqueos antes de iniciar; esta inspección se revierte.
    with crear_sesion() as sesion:
        campana = sesion.scalar(select(Campana).where(
            Campana.identificador == identificador
        ).with_for_update())
        if campana is None or campana.estado != "bloqueada":
            raise ValueError("La campaña debe estar bloqueada y sin trabajador activo")
        ejecuciones = list(sesion.scalars(select(Ejecucion).where(
            Ejecucion.campana_identificador == identificador,
            Ejecucion.estado.in_(["bloqueada", "generando"]),
        ).order_by(Ejecucion.orden_campana)))
        for ejecucion in ejecuciones:
            if ejecucion.estado == "generando":
                raise ValueError("Existe una ejecución activa; no se puede duplicar")
            _preparar_recuperacion(ejecucion, list(ejecucion.intentos), repetir_proveedor)
        pendientes = [ejecucion.identificador for ejecucion in ejecuciones]
        sesion.rollback()
    # Conserva las comprobaciones de plantilla, runtime y referencias históricas.
    cambiar_estado(identificador, "iniciar")
    try:
        for pendiente in pendientes:
            procesar_ejecucion(pendiente, recuperar_interrumpido=True,
                               repetir_proveedor=repetir_proveedor)
            with crear_sesion() as sesion:
                ejecucion = sesion.get(Ejecucion, pendiente)
                if ejecucion.estado == "bloqueada":
                    raise RuntimeError(ejecucion.mensaje)
                campana = sesion.get(Campana, identificador)
                if campana.estado != "en_curso":
                    return
        procesar_campana(identificador)
    except Exception:
        with crear_sesion() as sesion:
            campana = sesion.get(Campana, identificador)
            if campana.estado == "en_curso":
                campana.estado = "bloqueada"
                campana.mensaje = "La recuperación encontró otra incidencia; revisar la ejecución"
            for ejecucion in sesion.scalars(select(Ejecucion).where(
                Ejecucion.campana_identificador == identificador,
                Ejecucion.estado == "generando",
            )):
                ejecucion.estado = "bloqueada"
                ejecucion.mensaje = "Incidencia interna durante la recuperación; se conserva la traza"
            sesion.commit()
        raise


if __name__ == "__main__":
    argumentos = argparse.ArgumentParser(description=__doc__)
    argumentos.add_argument("campana")
    argumentos.add_argument("--repetir-proveedor", action="store_true")
    opciones = argumentos.parse_args()
    reanudar_campana(opciones.campana, opciones.repetir_proveedor)
