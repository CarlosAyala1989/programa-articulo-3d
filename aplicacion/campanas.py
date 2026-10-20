"""Diseño factorial, orden reproducible y ciclo de vida de campañas digitales."""

import random
from collections import Counter
from uuid import uuid4

import httpx

from sqlalchemy import select

from aplicacion.base_datos import (
    Campana, CasoDiseno, CondicionExperimental, Ejecucion, VersionConjunto,
    crear_sesion, fecha_actual,
)
from aplicacion.configuracion import (
    MAXIMO_TOKENS_DEEPSEEK, MODELOS_DISPONIBLES, MODELOS_LOCALES, MOTORES_DISPONIBLES,
    TOKENS_ENTRADA_PLANIFICACION, URL_SUPERVISOR, VERSION_PLANTILLA, perfil_generacion, resolver_esfuerzo,
)
from aplicacion.costos import PERFIL_TARIFA, costo_maximo_planificacion
from aplicacion.limites_modelos import limites_modelo
from aplicacion.proveedores import modelos_configurados, verificar_modelo_local
from aplicacion.proveedor_deepseek import ErrorProveedor


MODOS = ("open-loop", "closed-loop")


def resolver_esfuerzos_campana(modelos: list[str], esfuerzo: str | None = None,
                              por_modelo: dict[str, str] | None = None) -> dict:
    por_modelo = por_modelo or {}
    if any(modelo not in modelos for modelo in por_modelo):
        raise ValueError("El esfuerzo pertenece a un modelo no seleccionado")
    if esfuerzo is not None and not any(modelo in MODELOS_DISPONIBLES for modelo in modelos):
        raise ValueError("El esfuerzo global histórico requiere un modelo DeepSeek; usa esfuerzos_por_modelo")
    return {modelo: resolver_esfuerzo(modelo, por_modelo.get(modelo,
                esfuerzo if modelo in MODELOS_DISPONIBLES else None)) for modelo in modelos}


def validar_matriz(
    conjunto: VersionConjunto, casos: list[CasoDiseno], modelos: list[str],
    motores: list[str], modos: list[str], repeticiones: int, tipo: str,
) -> None:
    if tipo not in {"piloto", "principal"}:
        raise ValueError("El tipo debe ser piloto o principal")
    if conjunto.estado != "congelado":
        raise ValueError("El conjunto debe estar congelado")
    if not modelos or len(set(modelos)) != len(modelos) or any(m not in modelos_configurados() for m in modelos):
        raise ValueError("Lista de modelos vacía, duplicada o no configurada")
    if not motores or len(set(motores)) != len(motores) or any(m not in MOTORES_DISPONIBLES for m in motores):
        raise ValueError("Lista de motores inválida")
    if not modos or len(set(modos)) != len(modos) or any(m not in MODOS for m in modos):
        raise ValueError("Lista de modos inválida")
    if not 1 <= repeticiones <= 5:
        raise ValueError("Se permiten de una a cinco repeticiones")
    if not casos:
        raise ValueError("Se requiere al menos un caso")
    if tipo == "principal":
        if conjunto.finalidad != "evaluacion" or len(casos) != 60:
            raise ValueError("La campaña principal requiere los 60 casos congelados de evaluación")
        if Counter(caso.nivel for caso in casos) != {"basico": 20, "intermedio": 20, "complejo": 20}:
            raise ValueError("La campaña principal requiere 20 casos por dificultad")
        if set(motores) != set(MOTORES_DISPONIBLES) or set(modos) != set(MODOS):
            raise ValueError("La campaña principal cruza los tres motores con ambos modos")


def previsualizar(
    casos: int, modelos: list[str], motores: list[str], modos: list[str], repeticiones: int,
) -> dict:
    ejecuciones = casos * len(modelos) * len(motores) * len(modos) * repeticiones
    llamadas_por_modelo = {
        modelo: casos * len(motores) * repeticiones * sum(1 if modo == "open-loop" else 5 for modo in modos)
        for modelo in modelos
    }
    costo = sum((costo_maximo_planificacion(modelo) or 0) * llamadas for modelo, llamadas in llamadas_por_modelo.items())
    return {
        "ejecuciones": ejecuciones,
        "maximo_generaciones": sum(llamadas_por_modelo.values()),
        "maximo_por_modelo": llamadas_por_modelo,
        "costo_planificacion_usd": round(costo, 4),
        "supuesto_costo": f"{TOKENS_ENTRADA_PLANIFICACION} tokens de entrada y hasta "
                          f"{MAXIMO_TOKENS_DEEPSEEK} de salida (incluido razonamiento) "
                          "por llamada pagada; " + PERFIL_TARIFA,
        "costo_local": "No incluye electricidad ni infraestructura Ollama",
    }


def crear_campana(
    nombre: str, conjunto_identificador: str, modelos: list[str], motores: list[str],
    modos: list[str], repeticiones: int, semilla: int, tipo: str,
    codigos_caso: list[str] | None = None, presupuesto_usd: float | None = None,
    esfuerzo_razonamiento: str | None = None,
    esfuerzos_por_modelo: dict[str, str] | None = None,
) -> Campana:
    if not nombre.strip() or len(nombre) > 150:
        raise ValueError("Nombre de campaña inválido")
    if presupuesto_usd is not None and presupuesto_usd <= 0:
        raise ValueError("El presupuesto debe ser positivo")
    esfuerzos = resolver_esfuerzos_campana(modelos, esfuerzo_razonamiento, esfuerzos_por_modelo)
    perfiles = {modelo: perfil_generacion(modelo, esfuerzos[modelo]) for modelo in modelos}
    with crear_sesion() as sesion:
        conjunto = sesion.get(VersionConjunto, conjunto_identificador)
        if conjunto is None:
            raise ValueError("Conjunto no encontrado")
        todos = list(sesion.scalars(select(CasoDiseno).where(CasoDiseno.conjunto_identificador == conjunto_identificador)))
        if codigos_caso is None:
            casos = todos
        else:
            if len(set(codigos_caso)) != len(codigos_caso):
                raise ValueError("Hay códigos de caso duplicados")
            por_codigo = {caso.codigo: caso for caso in todos}
            if any(codigo not in por_codigo for codigo in codigos_caso):
                raise ValueError("Un código de caso no pertenece al conjunto")
            casos = [por_codigo[codigo] for codigo in codigos_caso]
        validar_matriz(conjunto, casos, modelos, motores, modos, repeticiones, tipo)
        vista = previsualizar(len(casos), modelos, motores, modos, repeticiones)
        identificador = str(uuid4())
        campana = Campana(
            identificador=identificador, conjunto_identificador=conjunto_identificador,
            nombre=nombre.strip(), estado="borrador", tipo=tipo, semilla=semilla,
            repeticiones=repeticiones,
            configuracion={
                "modelos": modelos, "motores": motores, "modos": modos,
                "codigos_caso": sorted(caso.codigo for caso in casos),
                "conjunto_sha256": conjunto.huella_sha256,
                "politica_parada": "primer CAD válido y exportado; máximo cinco closed-loop, uno open-loop",
                "plantilla": VERSION_PLANTILLA, "limite_cad_segundos": 100,
                "perfiles_generacion": perfiles,
                "limites_modelos": {modelo: limites_modelo(modelo) for modelo in modelos},
                "esfuerzo_razonamiento": next((perfil["reasoning_effort"] for perfil in perfiles.values()
                                              if "reasoning_effort" in perfil), None),
                "esfuerzos_por_modelo": esfuerzos,
                "protocolo_esfuerzo": "ciel-esfuerzo-por-modelo-v1",
                "teselacion_nativa": "detalle-v2: absoluta 0.02 mm, angular 0.05 rad",
                "tarifa": PERFIL_TARIFA,
            },
            total_ejecuciones=vista["ejecuciones"],
            maximo_generaciones=vista["maximo_generaciones"],
            presupuesto_usd=presupuesto_usd,
            mensaje="Matriz preparada; iniciar cuando corresponda",
        )
        sesion.add(campana)
        condiciones = []
        for modelo in modelos:
            for motor in motores:
                for modo in modos:
                    condicion = CondicionExperimental(
                        identificador=str(uuid4()), campana_identificador=identificador,
                        modelo=modelo, motor=motor, modo=modo,
                        configuracion={**perfiles[modelo],
                                       "plantilla": VERSION_PLANTILLA},
                    )
                    sesion.add(condicion)
                    condiciones.append(condicion)
        aleatorio = random.Random(semilla)
        orden = 0
        for repeticion in range(1, repeticiones + 1):
            casos_bloque = list(casos)
            aleatorio.shuffle(casos_bloque)
            for caso in casos_bloque:
                condiciones_bloque = list(condiciones)
                aleatorio.shuffle(condiciones_bloque)
                for condicion in condiciones_bloque:
                    orden += 1
                    sesion.add(Ejecucion(
                        identificador=str(uuid4()), descripcion=caso.descripcion,
                        motor=condicion.motor, modelo=condicion.modelo,
                        esfuerzo_razonamiento=perfiles[condicion.modelo].get("reasoning_effort"),
                        estado="pendiente", mensaje="Programada en campaña",
                        campana_identificador=identificador, caso_identificador=caso.identificador,
                        condicion_identificador=condicion.identificador,
                        modo=condicion.modo, repeticion=repeticion,
                        orden_campana=orden,
                        maximo_intentos=1 if condicion.modo == "open-loop" else 5,
                    ))
        sesion.commit()
        return campana


def resumen_campana(campana: Campana) -> dict:
    with crear_sesion() as sesion:
        estados = Counter(sesion.scalars(
            select(Ejecucion.estado).where(Ejecucion.campana_identificador == campana.identificador)
        ))
    return {
        "identificador": campana.identificador, "nombre": campana.nombre,
        "tipo": campana.tipo, "estado": campana.estado, "mensaje": campana.mensaje,
        "conjunto_identificador": campana.conjunto_identificador,
        "configuracion": campana.configuracion, "semilla": campana.semilla,
        "repeticiones": campana.repeticiones, "total_ejecuciones": campana.total_ejecuciones,
        "maximo_generaciones": campana.maximo_generaciones,
        "presupuesto_usd": campana.presupuesto_usd,
        "gasto_estimado_usd": campana.gasto_estimado_usd,
        "estados_ejecucion": dict(estados),
        "fecha_creacion": campana.fecha_creacion,
        "fecha_inicio": campana.fecha_inicio, "fecha_fin": campana.fecha_fin,
    }


def cambiar_estado(identificador: str, accion: str) -> Campana:
    with crear_sesion() as sesion:
        campana = sesion.scalar(select(Campana).where(Campana.identificador == identificador).with_for_update())
        if campana is None:
            raise LookupError("Campaña no encontrada")
        if accion == "iniciar":
            if campana.estado not in {"borrador", "pausada", "bloqueada"}:
                raise ValueError("La campaña no se puede reanudar en su estado actual")
            if campana.configuracion.get("plantilla") != VERSION_PLANTILLA:
                raise ValueError("Cambió la plantilla de generación; cree una campaña nueva para conservar el protocolo")
            try:
                with httpx.Client(timeout=15) as cliente:
                    respuesta = cliente.get(f"{URL_SUPERVISOR}/imagenes")
                    respuesta.raise_for_status()
                    imagenes = respuesta.json()
            except (httpx.HTTPError, ValueError) as error:
                raise ValueError(f"No se pudo verificar el runtime CAD: {type(error).__name__}") from error
            condiciones = list(sesion.scalars(select(CondicionExperimental).where(
                CondicionExperimental.campana_identificador == identificador
            )))
            for condicion in condiciones:
                imagen = imagenes.get(condicion.motor)
                if not imagen:
                    raise ValueError(f"Falta la imagen CAD de {condicion.motor}")
                if condicion.imagen_identificador and condicion.imagen_identificador != imagen:
                    raise ValueError(f"Cambió la imagen CAD de {condicion.motor}; cree otra campaña")
                condicion.imagen_identificador = imagen
                if condicion.modelo in MODELOS_LOCALES:
                    try:
                        identidad = verificar_modelo_local(condicion.modelo)
                    except ErrorProveedor as error:
                        raise ValueError(f"Modelo local no verificable: {error}") from error
                    anterior = condicion.configuracion.get("modelo_local")
                    if anterior and anterior.get("digest") != identidad.get("digest"):
                        raise ValueError(f"Cambió el digest de {condicion.modelo}; cree otra campaña")
                    condicion.configuracion = {**condicion.configuracion, "modelo_local": identidad}
            casos = list(sesion.scalars(select(CasoDiseno).where(
                CasoDiseno.conjunto_identificador == campana.conjunto_identificador,
                CasoDiseno.codigo.in_(campana.configuracion["codigos_caso"]),
            )))
            referencias = {caso.codigo: caso.referencia_sha256 for caso in casos}
            anteriores = campana.configuracion.get("referencias_sha256")
            if anteriores is not None and anteriores != referencias:
                raise ValueError("Las referencias cambiaron tras iniciar; cree otra campaña")
            campana.configuracion = {**campana.configuracion, "imagenes_cad": imagenes,
                                     "referencias_sha256": referencias}
            campana.estado = "en_curso"
            campana.mensaje = "Ejecutando matriz digital"
            campana.fecha_inicio = campana.fecha_inicio or fecha_actual()
        elif accion == "pausar":
            if campana.estado != "en_curso":
                raise ValueError("La campaña no está en curso")
            campana.estado = "pausada"
            campana.mensaje = "Pausada; se completará la ejecución ya iniciada"
        elif accion == "cancelar":
            if campana.estado not in {"borrador", "en_curso", "pausada", "bloqueada"}:
                raise ValueError("La campaña ya terminó")
            campana.estado = "cancelada"
            campana.mensaje = "Cancelada por el investigador"
            campana.fecha_fin = fecha_actual()
            pendientes = sesion.scalars(select(Ejecucion).where(
                Ejecucion.campana_identificador == identificador,
                Ejecucion.estado == "pendiente",
            ))
            for ejecucion in pendientes:
                ejecucion.estado = "cancelada"
                ejecucion.mensaje = "Cancelada antes de iniciar"
                ejecucion.fecha_fin = fecha_actual()
        else:
            raise ValueError("Acción de campaña no reconocida")
        sesion.commit()
        return campana


def procesar_campana(identificador: str) -> None:
    from aplicacion.generacion import procesar_ejecucion

    while True:
        with crear_sesion() as sesion:
            campana = sesion.get(Campana, identificador)
            if campana is None or campana.estado != "en_curso":
                return
            ejecucion = sesion.scalar(select(Ejecucion).where(
                Ejecucion.campana_identificador == identificador,
                Ejecucion.estado.in_(["pendiente", "pausada"]),
            ).order_by(Ejecucion.orden_campana).limit(1))
            if ejecucion is None:
                bloqueadas = sesion.scalar(select(Ejecucion.identificador).where(
                    Ejecucion.campana_identificador == identificador,
                    Ejecucion.estado.in_(["bloqueada", "generando"]),
                ).limit(1))
                campana.estado = "bloqueada" if bloqueadas else "completada"
                campana.mensaje = (
                    "Terminó la cola con incidencias operativas" if bloqueadas
                    else "Todas las ejecuciones programadas terminaron"
                )
                campana.fecha_fin = fecha_actual()
                sesion.commit()
                return
            siguiente = ejecucion.identificador
        procesar_ejecucion(siguiente)
        with crear_sesion() as sesion:
            ejecucion = sesion.get(Ejecucion, siguiente)
            campana = sesion.get(Campana, identificador)
            if ejecucion.estado == "bloqueada" and campana.estado == "en_curso":
                campana.estado = "bloqueada"
                campana.mensaje = "Incidencia operativa; revisar la ejecución antes de continuar pendientes"
                sesion.commit()
                return
