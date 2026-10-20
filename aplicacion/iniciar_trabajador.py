"""Migra el esquema y deja visibles ejecuciones interrumpidas tras reiniciar."""

import os

from sqlalchemy import select

from aplicacion.base_datos import Campana, Ejecucion, crear_sesion, crear_tablas, fecha_actual


def preparar_reinicio() -> None:
    crear_tablas()
    with crear_sesion() as sesion:
        interrumpidas = list(sesion.scalars(select(Ejecucion).where(
            Ejecucion.estado == "generando"
        )))
        for ejecucion in interrumpidas:
            ejecucion.estado = "bloqueada"
            ejecucion.mensaje = "Interrumpida por reinicio; revisar respuesta y posible costo antes de otro ensayo"
            ejecucion.fecha_fin = fecha_actual()
        activas = list(sesion.scalars(select(Campana).where(Campana.estado == "en_curso")))
        for campana in activas:
            if any(e.campana_identificador == campana.identificador for e in interrumpidas):
                campana.estado = "bloqueada"
                campana.mensaje = "Una ejecución quedó interrumpida; revisar antes de otra campaña"
            else:
                campana.estado = "pausada"
                campana.mensaje = "Trabajador reiniciado; reanudar para continuar pendientes"
        sesion.commit()


def argumentos_trabajador() -> list[str]:
    """Dos campañas pueden avanzar en paralelo; cada campaña conserva su orden."""
    valor = os.environ.get("CIEL_CONCURRENCIA", "2")
    try:
        concurrencia = int(valor)
    except ValueError:
        raise ValueError("CIEL_CONCURRENCIA debe ser un entero positivo") from None
    if concurrencia < 1:
        raise ValueError("CIEL_CONCURRENCIA debe ser un entero positivo")
    return ["celery", "-A", "aplicacion.tareas:celeria", "worker",
            "--loglevel=INFO", f"--concurrency={concurrencia}"]


if __name__ == "__main__":
    argumentos = argumentos_trabajador()
    preparar_reinicio()
    os.execvp("celery", argumentos)
