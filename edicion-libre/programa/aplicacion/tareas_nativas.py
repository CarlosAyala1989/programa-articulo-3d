"""Un trabajador secuencial de Windows, sin Celery, Redis ni servicios de cola."""

import heapq
import itertools
import logging
import threading
import time
from collections.abc import Callable


REGISTRO = logging.getLogger("ciel.nativo.cola")


class ColaNativa:
    def __init__(self) -> None:
        self.condicion = threading.Condition()
        self.cola: list[tuple] = []
        self.pendientes: set[tuple[str, str]] = set()
        self.contador = itertools.count()
        self.detener = False
        self.hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        with self.condicion:
            if self.hilo and self.hilo.is_alive():
                return
            self.detener = False
            self.hilo = threading.Thread(target=self.procesar, name="ciel-trabajador-nativo", daemon=True)
            self.hilo.start()

    def programar(self, tarea, identificador: str, espera: float = 0) -> None:
        clave = (tarea.nombre, identificador)
        with self.condicion:
            if self.detener:
                raise RuntimeError("El trabajador se está cerrando")
            if clave in self.pendientes:
                return
            self.pendientes.add(clave)
            heapq.heappush(self.cola, (time.monotonic() + max(0, espera), next(self.contador), tarea, identificador))
            self.condicion.notify_all()

    def procesar(self) -> None:
        while True:
            with self.condicion:
                while not self.detener:
                    if not self.cola:
                        self.condicion.wait()
                    elif self.cola[0][0] > time.monotonic():
                        self.condicion.wait(self.cola[0][0] - time.monotonic())
                    else:
                        _, _, tarea, identificador = heapq.heappop(self.cola)
                        break
                if self.detener:
                    return
            espera = None
            try:
                espera = tarea.funcion(identificador)
            except Exception:
                REGISTRO.exception("Falló la tarea %s de %s", tarea.nombre, identificador)
                if tarea.nombre == "campana":
                    try:
                        from aplicacion.automatico import registrar_incidencia
                        espera = registrar_incidencia(identificador, RuntimeError("Error del trabajador nativo; consulta el registro"))
                    except Exception:
                        REGISTRO.exception("No se pudo persistir la incidencia")
                        espera = 30
            finally:
                with self.condicion:
                    self.pendientes.discard((tarea.nombre, identificador))
            if espera is not None and not self.detener:
                self.programar(tarea, identificador, espera)

    def cerrar(self) -> None:
        with self.condicion:
            self.detener = True
            self.condicion.notify_all()


COLA = ColaNativa()


class TareaNativa:
    def __init__(self, nombre: str, funcion: Callable) -> None:
        self.nombre, self.funcion = nombre, funcion

    def delay(self, identificador: str) -> None:
        COLA.programar(self, identificador)

    def apply_async(self, args: list, countdown: float = 0) -> None:
        COLA.programar(self, args[0], countdown)


def procesar_generacion(identificador: str) -> None:
    from aplicacion.generacion import procesar_ejecucion
    procesar_ejecucion(identificador)


def procesar_analisis(identificador: str) -> None:
    from aplicacion.analisis import analizar_ejecucion
    analizar_ejecucion(identificador)


def procesar_campana_nativa(identificador: str) -> int | None:
    from aplicacion.base_datos import Campana, crear_sesion
    with crear_sesion() as sesion:
        campana = sesion.get(Campana, identificador)
        automatico = bool(campana and (campana.configuracion or {}).get("automatico"))
    if automatico:
        from aplicacion.automatico import procesar_paso
        return procesar_paso(identificador)
    from aplicacion.campanas import procesar_campana
    procesar_campana(identificador)
    return None


tarea_generacion = TareaNativa("generacion", procesar_generacion)
tarea_analisis = TareaNativa("analisis", procesar_analisis)
tarea_campana = TareaNativa("campana", procesar_campana_nativa)
