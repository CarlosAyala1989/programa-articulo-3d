"""Trabajos en segundo plano para que la web no espere las llamadas de IA."""

from celery import Celery

from aplicacion.base_datos import Campana, Ejecucion, crear_sesion
from aplicacion.campanas import procesar_campana
from aplicacion.configuracion import URL_REDIS
from aplicacion.generacion import procesar_ejecucion
from aplicacion.analisis import analizar_ejecucion


celeria = Celery("agente_ciel", broker=URL_REDIS, backend=URL_REDIS)
celeria.conf.update(task_track_started=True, worker_prefetch_multiplier=1)


@celeria.task(name="procesar_generacion")
def tarea_generacion(identificador: str) -> None:
    try:
        procesar_ejecucion(identificador)
    except Exception:
        # Un error no previsto también debe dejar el trabajo en un estado visible.
        with crear_sesion() as sesion:
            ejecucion = sesion.get(Ejecucion, identificador)
            if ejecucion is not None and ejecucion.estado in {"pendiente", "generando"}:
                ejecucion.estado = "bloqueada"
                ejecucion.mensaje = "Ocurrió un error interno en el trabajador"
                sesion.commit()
        raise


@celeria.task(name="procesar_campana")
def tarea_campana(identificador: str) -> None:
    try:
        procesar_campana(identificador)
    except Exception:
        with crear_sesion() as sesion:
            campana = sesion.get(Campana, identificador)
            if campana is not None and campana.estado == "en_curso":
                campana.estado = "bloqueada"
                campana.mensaje = "Incidencia interna del trabajador; revisar ejecuciones"
                sesion.commit()
        raise


@celeria.task(name="analizar_ejecucion")
def tarea_analisis(identificador: str) -> None:
    analizar_ejecucion(identificador)
