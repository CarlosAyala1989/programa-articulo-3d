"""Trabajos en segundo plano para que la web no espere las llamadas de IA."""

from celery import Celery

from aplicacion.base_datos import Campana, Ejecucion, crear_sesion
from aplicacion.campanas import procesar_campana
from aplicacion.configuracion import URL_REDIS
from aplicacion.generacion import procesar_ejecucion
from aplicacion.analisis import analizar_ejecucion


celeria = Celery("agente_ciel", broker=URL_REDIS, backend=URL_REDIS)
celeria.conf.update(task_track_started=True, worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 86400},
    result_backend_transport_options={"visibility_timeout": 86400}, visibility_timeout=86400,
    worker_cancel_long_running_tasks_on_connection_loss=True, broker_connection_retry_on_startup=True)


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


@celeria.task(name="procesar_campana", bind=True, max_retries=None, acks_late=True, reject_on_worker_lost=True)
def tarea_campana(self, identificador: str) -> None:
    try:
        with crear_sesion() as sesion:
            campana = sesion.get(Campana, identificador)
            automatico = bool(campana and (campana.configuracion or {}).get("automatico"))
        if automatico:
            from aplicacion.automatico import procesar_paso
            espera = procesar_paso(identificador)
            if espera is not None:
                tarea_campana.apply_async(args=[identificador], countdown=espera)
            return
    except Exception as error:
        # Si la DB/cola se desconecta, la tarea tampoco se da por perdida.
        raise self.retry(exc=error, countdown=30, max_retries=None)
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
