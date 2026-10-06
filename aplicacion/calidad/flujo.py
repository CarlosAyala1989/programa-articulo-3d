"""Quality Loop experimental: planea, genera, mide, revisa y repara hasta tres ciclos."""

import ast
import base64
import hashlib
import json
import re
import time
from pathlib import Path

import httpx
from sqlalchemy import select

from aplicacion.base_datos import (
    ArchivoGenerado, Ejecucion, InformeCalidad, IntentoGeneracion,
    crear_sesion, fecha_actual,
)
from aplicacion.calidad.metricas import evaluar_quality_gate, preparar_metricas
from aplicacion.calidad.modelos import PlanGeometrico
from aplicacion.calidad.nvidia import ErrorNvidia, ProveedorNvidia, RouterModelos, catalogo_roles
from aplicacion.calidad.prompts import (
    PROMPT_CRITICO, PROMPT_PLANIFICADOR, PROMPT_REPARADOR,
    PROMPT_REVISOR_CODIGO, PROMPT_REVISOR_VISUAL,
    instruccion_modeler, validar_plan_para_descripcion,
)
from aplicacion.calidad.recipes import texto_recipes
from aplicacion.calidad.recipes import CONTRATOS_MOTOR
from aplicacion.configuracion import (
    DIRECTORIO_ARTEFACTOS, MAXIMO_BYTES_CODIGO, MAXIMO_ITERACIONES_QUALITY_LOOP,
    MAXIMO_LLAMADAS_QUALITY_LOOP, MAXIMO_TOKENS_QUALITY_LOOP,
    MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR, MAXIMO_TOKENS_NVIDIA,
    MAXIMO_TOKENS_SALIDA, MODELOS_DISPONIBLES, MODELOS_NVIDIA_REGISTRADOS,
    MODELOS_LOCALES, QUALITY_ALLOW_REFERENCE_METRICS, URL_EVALUADOR, VERSION_PLANTILLA,
)
from aplicacion.costos import costo_estimado
from aplicacion.generacion import extraer_codigo, guardar_archivos, revisar_codigo, solicitar_ejecucion_cad
from aplicacion.prompts_sistema import instrucciones_sistema
from aplicacion.proveedor_deepseek import ErrorProveedor
from aplicacion.proveedores import solicitar_codigo


VERSION_PROTOCOLO = "ciel-quality-loop-v1"
NOMBRES_ARCHIVOS_CAD = {"pieza.stl", "pieza.step", "pieza.FCStd"}


class ErrorLlamadas(Exception):
    """El límite explícito de uso impidió iniciar otra llamada de modelo."""


def _json(modelo) -> dict:
    return modelo.model_dump(mode="json")


def _entrada_llamada(rol: str, respuesta, modelo_solicitado: str, proveedor: str) -> dict:
    tokens_entrada = int(getattr(respuesta, "tokens_entrada", 0) or 0)
    tokens_salida = int(getattr(respuesta, "tokens_salida", 0) or 0)
    return {
        "rol": rol, "proveedor": proveedor,
        "modelo_solicitado": modelo_solicitado,
        "modelo_informado": getattr(respuesta, "modelo", None),
        "endpoint_logico": "chat/completions",
        "tokens_entrada": tokens_entrada,
        "tokens_salida": tokens_salida,
        "costo_estimado_usd": costo_estimado(modelo_solicitado, tokens_entrada, tokens_salida),
        "latencia_segundos": float(getattr(respuesta, "latencia_segundos", 0) or 0),
        "finish_reason": getattr(respuesta, "finalizacion", "desconocida"),
        "request_id": getattr(respuesta, "request_id", None),
    }


def _guardar_candidato(ejecucion_id: str, candidate_id: str, motor: str, archivos: dict,
                       codigo: str, intento_id: int, sesion) -> list[dict]:
    requeridos = {"pieza.stl", "pieza.step"} | ({"pieza.FCStd"} if motor == "freecad" else set())
    if not requeridos.issubset(archivos):
        raise ValueError("Faltan archivos CAD obligatorios en el candidato")
    directorio = Path(DIRECTORIO_ARTEFACTOS) / "ejecuciones" / ejecucion_id
    directorio.mkdir(parents=True, exist_ok=True)
    codificados = dict(archivos)
    codificados["pieza.py"] = base64.b64encode(codigo.encode("utf-8")).decode("ascii")
    guardados = []
    for nombre, contenido in codificados.items():
        if nombre not in NOMBRES_ARCHIVOS_CAD | {"pieza.py"}:
            raise ValueError("El supervisor devolvió un nombre de archivo inesperado")
        datos = base64.b64decode(contenido, validate=True)
        if not datos or len(datos) > 20_000_000:
            raise ValueError("Un archivo de candidato está vacío o excede el límite")
        nombre_seguro = f"{candidate_id}-{nombre}"
        ruta = directorio / nombre_seguro
        ruta.write_bytes(datos)
        huella = hashlib.sha256(datos).hexdigest()
        sesion.add(ArchivoGenerado(
            ejecucion_identificador=ejecucion_id, nombre=nombre_seguro, ruta=str(ruta),
            tamano_bytes=len(datos), sha256=huella,
            rol="codigo_candidato" if nombre == "pieza.py" else "geometria_candidata",
            intento_identificador=intento_id,
        ))
        guardados.append({"nombre": nombre_seguro, "sha256": huella, "tamano_bytes": len(datos)})
    return guardados


def _guardar_lamina(ejecucion_id: str, candidate_id: str, imagen: bytes, intento_id: int, sesion) -> dict:
    if not imagen or len(imagen) > 8_000_000 or not imagen.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("La lámina multivista no es un PNG válido o supera el límite")
    directorio = Path(DIRECTORIO_ARTEFACTOS) / "ejecuciones" / ejecucion_id
    directorio.mkdir(parents=True, exist_ok=True)
    nombre = f"{candidate_id}-vistas.png"
    ruta = directorio / nombre
    ruta.write_bytes(imagen)
    huella = hashlib.sha256(imagen).hexdigest()
    sesion.add(ArchivoGenerado(
        ejecucion_identificador=ejecucion_id, nombre=nombre, ruta=str(ruta),
        tamano_bytes=len(imagen), sha256=huella, rol="lamina_multivista",
        intento_identificador=intento_id,
    ))
    return {"nombre": nombre, "sha256": huella, "tamano_bytes": len(imagen)}


def _persistir_informe(sesion, ejecucion_id: str, intento_id: int, iteracion: int,
                       candidate_id: str, parent_candidate_id: str | None, datos: dict) -> InformeCalidad:
    informe = InformeCalidad(
        ejecucion_identificador=ejecucion_id, intento_identificador=intento_id,
        iteracion=iteracion, candidate_id=candidate_id,
        parent_candidate_id=parent_candidate_id, resultado=datos,
    )
    sesion.add(informe)
    return informe


def _registrar_fallo_proveedor(ejecucion_id: str, intento_id: int, rol: str,
                               error: Exception, informe: dict | None = None) -> None:
    detalle = {"estado": "provider_error", "rol": rol,
               "error": str(error)[:1000], "tipo_error": type(error).__name__}
    with crear_sesion() as sesion:
        intento = sesion.get(IntentoGeneracion, intento_id)
        ejecucion = sesion.get(Ejecucion, ejecucion_id)
        if intento:
            intento.estado = "error_proveedor"
            intento.fase_error = "proveedor_ia"
            intento.diagnostico = f"Fallo del proveedor durante {rol}: {type(error).__name__}"
        if informe is not None and intento:
            informe["provider_error"] = detalle
            _persistir_informe(sesion, ejecucion_id, intento_id,
                               int(informe.get("iteracion", 1)), informe["candidate_id"],
                               informe.get("parent_candidate_id"), informe)
        ejecucion.estado = "bloqueada"
        ejecucion.mensaje = f"Quality Loop detenido por fallo de infraestructura del rol {rol}"
        ejecucion.fecha_fin = fecha_actual()
        configuracion = dict(ejecucion.configuracion_calidad or {})
        configuracion["estado_protocolo"] = "provider_error"
        configuracion["error_proveedor"] = detalle
        ejecucion.configuracion_calidad = configuracion
        sesion.commit()


def _consulta_evaluador(resultado_cad: dict, plan: dict, caso_id: str | None) -> dict:
    solicitud = {
        "archivos": resultado_cad["archivos"],
        "plan_geometrico": plan,
        "caso_identificador": caso_id,
        "usar_referencia": bool(QUALITY_ALLOW_REFERENCE_METRICS and caso_id),
    }
    with httpx.Client(timeout=httpx.Timeout(240.0, connect=10.0)) as cliente:
        respuesta = cliente.post(f"{URL_EVALUADOR}/inspeccionar-calidad", json=solicitud)
    if respuesta.status_code >= 500:
        raise RuntimeError(f"Evaluador CAD respondió HTTP {respuesta.status_code}")
    if respuesta.status_code >= 400:
        return {"estado": "not_available", "error": f"Evaluador CAD respondió HTTP {respuesta.status_code}"}
    try:
        datos = respuesta.json()
        if not isinstance(datos, dict) or datos.get("technical_success") is not True:
            raise ValueError
        return datos
    except (ValueError, TypeError):
        raise RuntimeError("El evaluador devolvió una respuesta malformada") from None


def _mensajes_modelador(descripcion: str, plan: dict, motor: str, historial: dict | None,
                        candidate_n: int) -> tuple[list[dict], str]:
    plan_objeto = PlanGeometrico.model_validate(plan)
    contrato = texto_recipes(plan_objeto, motor)
    instruccion = instruccion_modeler(plan_objeto.clase_modelado, CONTRATOS_MOTOR[motor], contrato)
    instruccion += "\n\nCONTRATO DE EXPORTACIÓN DEL RUNTIME ACTUAL\n" + instrucciones_sistema(motor)
    cuerpo = [f"Descripción original del usuario:\n{descripcion}",
              f"GeometricPlan validado (versión {plan_objeto.version_esquema}):\n{json.dumps(plan, ensure_ascii=False)}"]
    if historial:
        informe = historial["informe"]
        cuerpo.extend([
            "REPARACIÓN DEL CANDIDATO GANADOR ANTERIOR. No simplifiques la pieza ni elimines features que ya estaban correctas.",
            f"Código CAD completo del candidato padre {historial['candidate_id']}:\n{historial['codigo']}",
            f"Incidencias técnicas y revisión de código:\n{json.dumps(informe.get('code_review'), ensure_ascii=False)}",
            f"Métricas geométricas y Quality Gate:\n{json.dumps(informe.get('quality_metrics'), ensure_ascii=False)}\n{json.dumps(informe.get('quality_gate'), ensure_ascii=False)}",
            f"Crítica geométrica:\n{json.dumps(informe.get('critic_review'), ensure_ascii=False)}",
            "Features que deben preservarse: " + json.dumps(informe.get("preserved_features", []), ensure_ascii=False),
            "Prioridad de reparación: " + json.dumps(informe.get("repair_priority", []), ensure_ascii=False),
            f"Diagnóstico técnico: {historial.get('diagnostico', '')}",
            "Corrige la causa raíz con el menor cambio local posible. Mantén las features correctas y las cotas specified.",
        ])
        instruccion += "\n\n" + PROMPT_REPARADOR
    else:
        cuerpo.append("Genera el modelo paramétrico desde cero; no tienes acceso a una geometría de referencia.")
    cuerpo.append("Genera este candidato independiente con el mismo plan y contrato de esta iteración.")
    return ([{"role": "system", "content": instruccion},
             {"role": "user", "content": "\n\n".join(cuerpo)}], instruccion)


def _actualizar_estado_candidato(ejecucion_id: str, intento_id: int, estado: str,
                                 fase_error: str | None, diagnostico: str,
                                 codigo: str, respuesta: dict | None, solicitud: dict,
                                 resultado_cad: dict | None = None) -> None:
    with crear_sesion() as sesion:
        intento = sesion.get(IntentoGeneracion, intento_id)
        intento.estado = estado
        intento.fase_error = fase_error
        intento.diagnostico = diagnostico[:3000]
        intento.codigo = codigo
        intento.solicitud_modelo = solicitud
        if respuesta:
            intento.respuesta_modelo = respuesta.get("texto", "")
            intento.modelo_informado = respuesta.get("modelo_informado", "")
            intento.tokens_entrada = int(respuesta.get("tokens_entrada") or 0)
            intento.tokens_salida = int(respuesta.get("tokens_salida") or 0)
            intento.duracion_ia_segundos = respuesta.get("duracion_ia")
        if resultado_cad:
            intento.sintaxis_valida = resultado_cad.get("sintaxis_valida")
            intento.ejecucion_correcta = resultado_cad.get("ejecucion_correcta")
            intento.cad_valido = resultado_cad.get("cad_valido")
            intento.exportacion_valida = resultado_cad.get("exportacion_valida")
            intento.runtime_identificador = resultado_cad.get("runtime_identificador")
            intento.duracion_cad_segundos = resultado_cad.get("duracion_cad")
        intento.duracion_segundos = float((respuesta or {}).get("duracion_total", 0) or 0)
        if respuesta:
            intento.costo_estimado_usd = costo_estimado(
                solicitud.get("modelo_solicitado", ""), intento.tokens_entrada, intento.tokens_salida
            )
        sesion.commit()


def _datos_respuesta(respuesta: dict, inicio_total: float, inicio_ia: float) -> dict:
    return {**respuesta, "duracion_ia": time.monotonic() - inicio_ia,
            "duracion_total": time.monotonic() - inicio_total}


def _reserva_tokens(entrada: str, salida_maxima: int, tokens_imagen: int = 0,
                    sobrecarga: int = 0) -> int:
    """Cota operativa conservadora: ~3 caracteres de entrada por token, más salida máxima."""
    entrada_estimada = (len(entrada.encode("utf-8")) + 2) // 3
    return entrada_estimada + int(salida_maxima) + int(tokens_imagen) + int(sobrecarga)


def _tokens_observados(respuesta) -> int:
    return int(getattr(respuesta, "tokens_entrada", 0) or 0) + int(getattr(respuesta, "tokens_salida", 0) or 0)


def _reservar_en_llamada(llamada: dict, reserva: int, acumulado: int) -> tuple[dict, int]:
    observado = int(llamada.get("tokens_entrada", 0) or 0) + int(llamada.get("tokens_salida", 0) or 0)
    asignado = max(observado, reserva)
    llamada["tokens_reservados"] = reserva
    llamada["tokens_presupuestados"] = asignado
    return llamada, acumulado + asignado


def _ordenar_candidatos(resultados: list[tuple[int, dict]]) -> list[tuple[int, dict]]:
    """Prioriza aceptación de calidad, éxito técnico y score versionado, sin descartar evidencia."""
    return sorted(resultados, key=lambda item: (
        bool(item[1].get("quality_success")), bool(item[1].get("technical_success")),
        float(item[1].get("quality_score") or -1),
    ), reverse=True)


def procesar_quality_loop(identificador: str) -> None:
    """Ejecuta hasta tres iteraciones; un fallo de proveedor bloquea sin consumir una reparación."""
    with crear_sesion() as sesion:
        ejecucion = sesion.scalar(select(Ejecucion).where(
            Ejecucion.identificador == identificador
        ).with_for_update())
        if ejecucion is None or ejecucion.estado not in {"pendiente", "pausada"}:
            return
        if ejecucion.intentos:
            ejecucion.estado = "bloqueada"
            ejecucion.mensaje = "Quality Loop previo incompleto; no se repiten llamadas con facturación incierta"
            ejecucion.fecha_fin = fecha_actual()
            sesion.commit()
            return
        ejecucion.estado = "generando"
        ejecucion.mensaje = "Planificando la geometría con NVIDIA Nemotron"
        ejecucion.fecha_inicio = ejecucion.fecha_inicio or fecha_actual()
        descripcion, motor, modelo = ejecucion.descripcion, ejecucion.motor, ejecucion.modelo
        esfuerzo, caso_id = ejecucion.esfuerzo_razonamiento, ejecucion.caso_identificador
        configuracion = dict(ejecucion.configuracion_calidad or {})
        best_of_n = bool(configuracion.get("best_of_n", False))
        cantidad_candidatos = 3 if best_of_n else 1
        configuracion.update({
            "version_protocolo": VERSION_PROTOCOLO,
            "version_plantilla_legacy": VERSION_PLANTILLA,
            "maximo_iteraciones": MAXIMO_ITERACIONES_QUALITY_LOOP,
            "maximo_candidatos_por_iteracion": cantidad_candidatos,
            "maximo_llamadas_ia": MAXIMO_LLAMADAS_QUALITY_LOOP,
            "maximo_tokens_presupuestados": MAXIMO_TOKENS_QUALITY_LOOP,
            "maximo_tokens_salida_generador": MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR,
            "version_configuracion": "ciel-nvidia-routing-v1",
            "modelos_por_rol": catalogo_roles(),
            "llamadas_ia": 0, "estado_protocolo": "planificando",
            "tokens_presupuestados": 0,
            "best_of_n": best_of_n,
            "protocolo_referencia": "quality-v1-reference-authorized" if QUALITY_ALLOW_REFERENCE_METRICS and caso_id else "no-reference",
            "metricas_permiten_referencia": bool(QUALITY_ALLOW_REFERENCE_METRICS and caso_id),
        })
        ejecucion.configuracion_calidad = configuracion
        sesion.commit()

    proveedor = ProveedorNvidia()
    router = RouterModelos(proveedor)
    llamadas = 0
    tokens_presupuestados = 0
    llamadas_registradas = []
    try:
        esquema_plan = json.dumps(PlanGeometrico.model_json_schema(), ensure_ascii=False)
        entrada_plan = PROMPT_PLANIFICADOR + descripcion + esquema_plan
        reserva_plan = _reserva_tokens(entrada_plan, MAXIMO_TOKENS_NVIDIA, sobrecarga=4096)
        permitir_respaldo = (MAXIMO_LLAMADAS_QUALITY_LOOP >= 2
            and tokens_presupuestados + 2 * reserva_plan <= MAXIMO_TOKENS_QUALITY_LOOP)
        if tokens_presupuestados + reserva_plan > MAXIMO_TOKENS_QUALITY_LOOP:
            with crear_sesion() as sesion:
                ejecucion = sesion.get(Ejecucion, identificador)
                ejecucion.estado = "fallida"
                ejecucion.mensaje = "Presupuesto de tokens insuficiente para iniciar la planificación"
                ejecucion.fecha_fin = fecha_actual()
                config = dict(ejecucion.configuracion_calidad or {})
                config["estado_protocolo"] = "budget_exhausted"
                config["tokens_reservados_sin_llamar"] = reserva_plan
                ejecucion.configuracion_calidad = config
                sesion.commit()
            return
        try:
            plan, respuesta_plan = router.planificar(
                descripcion, permitir_fallback=permitir_respaldo
            )
            llamadas = proveedor.llamadas
        except (ErrorNvidia, Exception) as error:
            # El detalle seguro del cliente contiene clase/status, nunca headers ni clave.
            with crear_sesion() as sesion:
                ejecucion = sesion.get(Ejecucion, identificador)
                ejecucion.estado = "bloqueada"
                ejecucion.mensaje = f"No se pudo obtener un GeometricPlan del proveedor NVIDIA ({type(error).__name__})"
                ejecucion.fecha_fin = fecha_actual()
                config = dict(ejecucion.configuracion_calidad or {})
                config.update({"estado_protocolo": "provider_error", "error_proveedor": str(error)[:1000],
                               "llamadas_ia": max(llamadas, proveedor.llamadas),
                               "tokens_presupuestados": reserva_plan * max(1, proveedor.llamadas)})
                ejecucion.configuracion_calidad = config
                sesion.commit()
            return
        llamada_plan = _entrada_llamada(
            "planner", respuesta_plan, getattr(respuesta_plan, "modelo", ""), "nvidia_nim"
        )
        llamada_plan["llamadas_http"] = llamadas
        llamada_plan["parametros"] = {"max_tokens": MAXIMO_TOKENS_NVIDIA, "temperature": 0}
        llamada_plan, tokens_presupuestados = _reservar_en_llamada(
            llamada_plan, reserva_plan * max(1, llamadas), tokens_presupuestados
        )
        llamadas_registradas.append(llamada_plan)
        try:
            validar_plan_para_descripcion(descripcion, plan)
        except ValueError as error:
            with crear_sesion() as sesion:
                ejecucion = sesion.get(Ejecucion, identificador)
                ejecucion.estado = "bloqueada"
                ejecucion.mensaje = "El GeometricPlan no conserva literalmente las cotas especificadas"
                ejecucion.fecha_fin = fecha_actual()
                config = dict(ejecucion.configuracion_calidad or {})
                config.update({"estado_protocolo": "plan_invalid", "planner_model": respuesta_plan.modelo,
                               "planner_provider": "nvidia_nim", "plan_error": str(error),
                               "llamadas_ia": llamadas})
                ejecucion.configuracion_calidad = config
                sesion.commit()
            return
        plan_json = _json(plan)
        with crear_sesion() as sesion:
            ejecucion = sesion.get(Ejecucion, identificador)
            config = dict(ejecucion.configuracion_calidad or {})
            config.update({
                "estado_protocolo": "en_evaluacion", "geometric_plan": plan_json,
                "plan_version": plan.version_esquema,
                "planner_model": respuesta_plan.modelo,
                "planner_provider": respuesta_plan.proveedor,
                "planner_endpoint_logico": "chat/completions",
                "planner_response": llamada_plan,
                "llamadas_ia": llamadas,
                "tokens_presupuestados": tokens_presupuestados,
                "llamadas": list(llamadas_registradas),
                "candidatos": [],
            })
            ejecucion.configuracion_calidad = config
            ejecucion.mensaje = "GeometricPlan guardado; generando y revisando candidatos"
            ejecucion.maximo_intentos = MAXIMO_ITERACIONES_QUALITY_LOOP
            sesion.commit()

        candidato_padre = None
        historial_padre = None
        mejores = []
        contador_intento = 0
        informes_por_iteracion: list[list[tuple[int, dict]]] = []
        detener_por_infraestructura = False

        for iteracion in range(1, MAXIMO_ITERACIONES_QUALITY_LOOP + 1):
            resultados_iteracion = []
            if llamadas >= MAXIMO_LLAMADAS_QUALITY_LOOP:
                break
            with crear_sesion() as sesion:
                ejecucion = sesion.get(Ejecucion, identificador)
                ejecucion.numero_intentos = contador_intento
                ejecucion.mensaje = f"Quality Loop: ciclo {iteracion}/{MAXIMO_ITERACIONES_QUALITY_LOOP}"
                sesion.commit()

            for indice_candidato in range(1, cantidad_candidatos + 1):
                if llamadas >= MAXIMO_LLAMADAS_QUALITY_LOOP:
                    break
                candidate_id = f"{identificador[:8]}-i{iteracion}-c{indice_candidato}"
                parent_id = candidato_padre if iteracion > 1 else None
                mensajes, system_prompt = _mensajes_modelador(
                    descripcion, plan_json, motor, historial_padre, indice_candidato
                )
                maximo_salida_generador = (
                    MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR if modelo in MODELOS_DISPONIBLES
                    else MAXIMO_TOKENS_NVIDIA if modelo in MODELOS_NVIDIA_REGISTRADOS
                    else MAXIMO_TOKENS_SALIDA if modelo in MODELOS_LOCALES
                    else MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR
                )
                reserva_generador = _reserva_tokens(
                    json.dumps(mensajes, ensure_ascii=False), maximo_salida_generador
                )
                if llamadas >= MAXIMO_LLAMADAS_QUALITY_LOOP or (
                    tokens_presupuestados + reserva_generador > MAXIMO_TOKENS_QUALITY_LOOP
                ):
                    break
                contador_intento += 1
                with crear_sesion() as sesion:
                    ejecucion = sesion.get(Ejecucion, identificador)
                    ejecucion.numero_intentos = contador_intento
                    intento = IntentoGeneracion(
                        ejecucion_identificador=identificador, numero=contador_intento,
                        estado="consultando_ia",
                        solicitud_modelo={"calidad": {"iteracion": iteracion,
                            "candidate_id": candidate_id, "parent_candidate_id": parent_id,
                            "prompt_version": VERSION_PROTOCOLO}, "mensajes": mensajes,
                            "plantilla": VERSION_PROTOCOLO},
                    )
                    sesion.add(intento)
                    sesion.commit()
                    intento_id = intento.identificador

                if llamadas >= MAXIMO_LLAMADAS_QUALITY_LOOP:
                    _actualizar_estado_candidato(identificador, intento_id, "invalido", "presupuesto",
                        "Se alcanzó el máximo de llamadas IA configurado antes de generar este candidato.",
                        "", None, {"calidad": {"candidate_id": candidate_id}})
                    break
                inicio_total = time.monotonic()
                inicio_ia = time.monotonic()
                llamadas += 1
                with crear_sesion() as sesion:
                    ejecucion = sesion.get(Ejecucion, identificador)
                    config = dict(ejecucion.configuracion_calidad or {})
                    config["llamadas_ia"] = llamadas
                    ejecucion.configuracion_calidad = config
                    sesion.commit()
                try:
                    limite_salida = (MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR
                                     if modelo in MODELOS_DISPONIBLES else None)
                    respuesta = solicitar_codigo(modelo, mensajes, esfuerzo, limite_salida)
                except ErrorProveedor as error:
                    tokens_presupuestados += reserva_generador
                    with crear_sesion() as sesion:
                        ejecucion = sesion.get(Ejecucion, identificador)
                        config = dict(ejecucion.configuracion_calidad or {})
                        config["tokens_presupuestados"] = tokens_presupuestados
                        config["llamadas_ia"] = llamadas
                        ejecucion.configuracion_calidad = config
                        sesion.commit()
                    informe = {"iteracion": iteracion, "candidate_id": candidate_id,
                               "parent_candidate_id": parent_id}
                    _registrar_fallo_proveedor(identificador, intento_id, "generador", error, informe)
                    detener_por_infraestructura = True
                    break
                respuesta = _datos_respuesta(respuesta, inicio_total, inicio_ia)
                codigo = extraer_codigo(respuesta["texto"])
                solicitud_base = {
                    "calidad": {"iteracion": iteracion, "candidate_id": candidate_id,
                                "parent_candidate_id": parent_id, "prompt_version": VERSION_PROTOCOLO},
                    "mensajes": mensajes,
                    "perfil": respuesta.get("perfil"), "proveedor": respuesta.get("proveedor"),
                    "finalizacion": respuesta.get("finalizacion"),
                    "modelo_solicitado": modelo,
                }
                _actualizar_estado_candidato(identificador, intento_id, "respuesta_recibida", None,
                    "Respuesta CAD recibida; pendiente de revisión estática.", codigo, respuesta,
                    solicitud_base)
                llamada_generador = {
                    "rol": "generador", "proveedor": respuesta.get("proveedor"),
                    "modelo_solicitado": modelo, "modelo_informado": respuesta.get("modelo_informado"),
                    "endpoint_logico": "chat/completions" if respuesta.get("proveedor") != "ollama" else "api/chat",
                    "tokens_entrada": int(respuesta.get("tokens_entrada") or 0),
                    "tokens_salida": int(respuesta.get("tokens_salida") or 0),
                    "latencia_segundos": respuesta["duracion_ia"],
                    "finish_reason": respuesta.get("finalizacion"),
                    "parametros": respuesta.get("perfil"),
                }
                llamada_generador, tokens_presupuestados = _reservar_en_llamada(
                    llamada_generador, reserva_generador, tokens_presupuestados
                )
                llamadas_registradas.append(llamada_generador)
                respuesta_codigo = None
                imagen = None
                static_error = None
                try:
                    if respuesta.get("finalizacion") == "length":
                        raise ValueError("La respuesta del modelo se truncó por el límite de tokens")
                    if not codigo or len(codigo.encode("utf-8")) > MAXIMO_BYTES_CODIGO:
                        raise ValueError("El programa está vacío o excede el límite de bytes")
                    ast.parse(codigo)
                    revisar_codigo(codigo, motor)
                except (SyntaxError, ValueError) as error:
                    static_error = f"{type(error).__name__}: {error}"

                revision_codigo = None
                info_revisor = None
                if static_error is None:
                    reserva_revisor = _reserva_tokens(
                        PROMPT_REVISOR_CODIGO + plan.model_dump_json() + codigo,
                        4096, sobrecarga=2048,
                    )
                    if llamadas >= MAXIMO_LLAMADAS_QUALITY_LOOP or (
                        tokens_presupuestados + reserva_revisor > MAXIMO_TOKENS_QUALITY_LOOP
                    ):
                        static_error = "El presupuesto de llamadas o tokens se agotó antes del code reviewer obligatorio"
                    else:
                        antes = proveedor.llamadas
                        try:
                            revision_codigo, respuesta_revisor = router.revisar_codigo(motor, plan, codigo)
                        except (ErrorNvidia, Exception) as error:
                            incremento = max(1, proveedor.llamadas - antes)
                            llamadas += incremento
                            tokens_presupuestados += reserva_revisor * incremento
                            with crear_sesion() as sesion:
                                ejecucion = sesion.get(Ejecucion, identificador)
                                config = dict(ejecucion.configuracion_calidad or {})
                                config.update({"llamadas_ia": llamadas,
                                               "tokens_presupuestados": tokens_presupuestados})
                                ejecucion.configuracion_calidad = config
                                sesion.commit()
                            _registrar_fallo_proveedor(identificador, intento_id, "code_reviewer", error,
                                {"iteracion": iteracion, "candidate_id": candidate_id,
                                 "parent_candidate_id": parent_id})
                            detener_por_infraestructura = True
                            break
                        incremento = proveedor.llamadas - antes
                        llamadas += max(1, incremento)
                        info_revisor = _entrada_llamada("code_reviewer", respuesta_revisor,
                            respuesta_revisor.modelo, "nvidia_nim")
                        info_revisor["llamadas_http"] = max(1, incremento)
                        info_revisor["parametros"] = {"max_tokens": 4096, "temperature": 0}
                        info_revisor, tokens_presupuestados = _reservar_en_llamada(
                            info_revisor, reserva_revisor * max(1, incremento), tokens_presupuestados
                        )
                        llamadas_registradas.append(info_revisor)
                        respuesta_codigo = respuesta_revisor
                code_review_json = _json(revision_codigo) if revision_codigo else {
                    "estado": "rejected_static", "error": static_error,
                }
                candidato = {
                    "iteracion": iteracion, "candidate_id": candidate_id,
                    "parent_candidate_id": parent_id, "technical_success": False,
                    "quality_success": False, "quality_score": None,
                    "code_review": code_review_json, "provider_calls": [llamada_generador]
                        + ([info_revisor] if info_revisor else []),
                    "errores": [], "preserved_features": [], "repair_priority": [],
                    "reference_protocol": "quality-v1-reference-authorized"
                        if QUALITY_ALLOW_REFERENCE_METRICS and caso_id else "no-reference",
                }
                resultado_cad = None
                diagnostico = static_error or ""
                fase_error = "politica" if static_error else None
                estado_intento = "invalido" if static_error else "respuesta_recibida"
                if revision_codigo is not None:
                    bloquea = (not revision_codigo.accepted
                               or revision_codigo.severity in {"high", "critical"}
                               or any(issue.severidad in {"high", "critical"} for issue in revision_codigo.issues))
                    if bloquea:
                        estado_intento = "invalido"
                        fase_error = "revisor_codigo"
                        diagnostico = "Laguna rechazó el código antes de ejecutar el runtime CAD"
                        candidato["errores"].append(diagnostico)
                else:
                    bloquea = True
                    candidato["errores"].append(static_error or "El code reviewer no pudo completarse")

                if not bloquea:
                    inicio_cad = time.monotonic()
                    try:
                        resultado_cad = solicitar_ejecucion_cad(motor, codigo)
                    except RuntimeError as error:
                        diagnostico = str(error)[:1000]
                        fase_error = "infraestructura"
                        estado_intento = "error_supervisor"
                        with crear_sesion() as sesion:
                            ejecucion = sesion.get(Ejecucion, identificador)
                            ejecucion.estado = "bloqueada"
                            ejecucion.mensaje = "El supervisor CAD no pudo evaluar el candidato"
                            ejecucion.fecha_fin = fecha_actual()
                            sesion.commit()
                        detener_por_infraestructura = True
                        candidato["errores"].append(diagnostico)
                    if resultado_cad is not None:
                        resultado_cad["duracion_cad"] = time.monotonic() - inicio_cad
                        tecnico = resultado_cad.get("correcto") is True
                        candidato["technical_success"] = tecnico
                        if tecnico:
                            try:
                                inspeccion = _consulta_evaluador(resultado_cad, plan_json, caso_id)
                            except (httpx.HTTPError, RuntimeError) as error:
                                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code < 500:
                                    inspeccion = {"estado": "not_available", "error": "Evaluator rejected candidate"}
                                else:
                                    with crear_sesion() as sesion:
                                        ejecucion = sesion.get(Ejecucion, identificador)
                                        ejecucion.estado = "bloqueada"
                                        ejecucion.mensaje = f"No se pudo completar la inspección determinista ({type(error).__name__})"
                                        ejecucion.fecha_fin = fecha_actual()
                                        sesion.commit()
                                    detener_por_infraestructura = True
                                    inspeccion = {"estado": "not_available", "error": type(error).__name__}
                            if inspeccion.get("technical_success") is True:
                                geometria = inspeccion["geometric_metrics"]
                                referencia = inspeccion.get("reference_metrics") or {"estado": "not_available"}
                                metricas = preparar_metricas(plan, geometria,
                                    comparacion_referencia=referencia)
                                imagen = base64.b64decode(inspeccion["multiview_png_base64"], validate=True)
                                reserva_visual = _reserva_tokens(
                                    descripcion + plan.model_dump_json() + json.dumps(geometria, ensure_ascii=False)
                                    + PROMPT_REVISOR_VISUAL,
                                    4096, tokens_imagen=4096, sobrecarga=2048,
                                )
                                if llamadas >= MAXIMO_LLAMADAS_QUALITY_LOOP or (
                                    tokens_presupuestados + reserva_visual > MAXIMO_TOKENS_QUALITY_LOOP
                                ):
                                    candidato["errores"].append("Presupuesto agotado antes de la revisión visual obligatoria")
                                    candidato["quality_metrics"] = metricas
                                    candidato["technical_success"] = True
                                    candidato["quality_gate"] = {"accepted": False, "quality_success": False,
                                        "motivo": "presupuesto agotado antes de la revisión visual", "quality_score": None}
                                    estado_intento = "invalido"
                                    fase_error = "presupuesto"
                                    diagnostico = candidato["quality_gate"]["motivo"]
                                else:
                                    antes = proveedor.llamadas
                                    try:
                                        revision_visual, respuesta_visual = router.revisar_visual(
                                            descripcion, plan, geometria, imagen
                                        )
                                    except (ErrorNvidia, Exception) as error:
                                        incremento = max(1, proveedor.llamadas - antes)
                                        llamadas += incremento
                                        tokens_presupuestados += reserva_visual * incremento
                                        with crear_sesion() as sesion:
                                            ejecucion = sesion.get(Ejecucion, identificador)
                                            config = dict(ejecucion.configuracion_calidad or {})
                                            config.update({"llamadas_ia": llamadas,
                                                           "tokens_presupuestados": tokens_presupuestados})
                                            ejecucion.configuracion_calidad = config
                                            sesion.commit()
                                        _registrar_fallo_proveedor(identificador, intento_id,
                                            "visual_reviewer", error,
                                            {"iteracion": iteracion, "candidate_id": candidate_id,
                                             "parent_candidate_id": parent_id})
                                        detener_por_infraestructura = True
                                        break
                                    llamadas += max(1, proveedor.llamadas - antes)
                                    info_visual = _entrada_llamada("visual_reviewer", respuesta_visual,
                                        respuesta_visual.modelo, "nvidia_nim")
                                    info_visual["parametros"] = {
                                        "max_tokens": 4096, "temperature": 0, "imagenes": 1,
                                        "formato_imagen": "image/png",
                                    }
                                    info_visual, tokens_presupuestados = _reservar_en_llamada(
                                        info_visual, reserva_visual, tokens_presupuestados
                                    )
                                    llamadas_registradas.append(info_visual)
                                    candidato["provider_calls"].append(info_visual)
                                    metricas = preparar_metricas(plan, geometria, revision_visual, referencia)
                                    evidencia_critico = {"puntuaciones": metricas["puntuaciones"],
                                        "geometria_observada": geometria,
                                        "revision_visual": _json(revision_visual),
                                        "protocolo_referencia": metricas["referencia"].get("protocolo", "sin-referencia")}
                                    reserva_critica = _reserva_tokens(
                                        PROMPT_CRITICO + plan.model_dump_json()
                                        + json.dumps(evidencia_critico, ensure_ascii=False),
                                        4096, sobrecarga=2048,
                                    )
                                    if llamadas >= MAXIMO_LLAMADAS_QUALITY_LOOP or (
                                        tokens_presupuestados + reserva_critica > MAXIMO_TOKENS_QUALITY_LOOP
                                    ):
                                        candidato["quality_metrics"] = metricas
                                        candidato["visual_review"] = _json(revision_visual)
                                        candidato["quality_gate"] = {"accepted": False,
                                            "quality_success": False, "quality_score": None,
                                            "motivo": "presupuesto agotado antes del geometric critic"}
                                        estado_intento = "invalido"
                                        fase_error = "presupuesto"
                                        diagnostico = candidato["quality_gate"]["motivo"]
                                        evidencia_critico = None
                                    if evidencia_critico is None:
                                        critica = None
                                        respuesta_critica = None
                                    else:
                                        antes = proveedor.llamadas
                                        try:
                                            critica, respuesta_critica = router.criticar(plan, evidencia_critico)
                                        except (ErrorNvidia, Exception) as error:
                                            incremento = max(1, proveedor.llamadas - antes)
                                            llamadas += incremento
                                            tokens_presupuestados += reserva_critica * incremento
                                            with crear_sesion() as sesion:
                                                ejecucion = sesion.get(Ejecucion, identificador)
                                                config = dict(ejecucion.configuracion_calidad or {})
                                                config.update({"llamadas_ia": llamadas,
                                                               "tokens_presupuestados": tokens_presupuestados})
                                                ejecucion.configuracion_calidad = config
                                                sesion.commit()
                                            _registrar_fallo_proveedor(identificador, intento_id,
                                                "geometric_critic", error,
                                                {"iteracion": iteracion, "candidate_id": candidate_id,
                                                 "parent_candidate_id": parent_id})
                                            detener_por_infraestructura = True
                                            break
                                        llamadas += max(1, proveedor.llamadas - antes)
                                    if critica is not None:
                                        info_critica = _entrada_llamada("geometric_critic", respuesta_critica,
                                            respuesta_critica.modelo, "nvidia_nim")
                                        info_critica["parametros"] = {"max_tokens": 4096, "temperature": 0}
                                        info_critica, tokens_presupuestados = _reservar_en_llamada(
                                            info_critica, reserva_critica, tokens_presupuestados
                                        )
                                        llamadas_registradas.append(info_critica)
                                        candidato["provider_calls"].append(info_critica)
                                        gate = evaluar_quality_gate(metricas, True, revision_codigo,
                                                                    revision_visual, critica)
                                        candidato.update({
                                            "quality_success": gate["accepted"],
                                            "quality_score": gate["quality_score"],
                                            "quality_metrics": metricas,
                                            "visual_review": _json(revision_visual),
                                            "critic_review": _json(critica),
                                            "quality_gate": gate,
                                            "preserved_features": critica.preservar,
                                            "repair_priority": critica.prioridad_reparacion,
                                        })
                                        estado_intento = "correcto" if gate["accepted"] else "invalido"
                                        fase_error = None if gate["accepted"] else "quality_gate"
                                        diagnostico = "" if gate["accepted"] else gate["motivo"]
                            else:
                                candidato["quality_gate"] = {"accepted": False,
                                    "technical_success": True, "quality_success": False,
                                    "quality_score": None, "motivo": inspeccion.get("error", "Métricas no disponibles")}
                                candidato["errores"].append(candidato["quality_gate"]["motivo"])
                                estado_intento = "invalido"
                                fase_error = "evaluador"
                                diagnostico = candidato["quality_gate"]["motivo"]
                        else:
                            diagnostico = str(resultado_cad.get("diagnostico") or "La validación técnica CAD falló")[:3000]
                            fase_error = resultado_cad.get("fase_error") or "runtime_cad"
                            estado_intento = "invalido"
                            candidato["errores"].append(diagnostico)

                if detener_por_infraestructura:
                    break
                if resultado_cad is not None:
                    candidato["technical_result"] = {
                        "sintaxis_valida": resultado_cad.get("sintaxis_valida"),
                        "ejecucion_correcta": resultado_cad.get("ejecucion_correcta"),
                        "cad_valido": resultado_cad.get("cad_valido"),
                        "exportacion_valida": resultado_cad.get("exportacion_valida"),
                        "volumen_mm3": resultado_cad.get("volumen_mm3"),
                        "fase_error": resultado_cad.get("fase_error"),
                        "diagnostico": resultado_cad.get("diagnostico", ""),
                    }
                if resultado_cad and candidato["technical_success"]:
                    try:
                        with crear_sesion() as sesion:
                            candidato["artefactos"] = _guardar_candidato(
                                identificador, candidate_id, motor, resultado_cad["archivos"],
                                codigo, intento_id, sesion,
                            )
                            if "imagen" in locals() and isinstance(imagen, bytes):
                                candidato["lamina"] = _guardar_lamina(
                                    identificador, candidate_id, imagen, intento_id, sesion
                                )
                            sesion.commit()
                    except (ValueError, OSError, KeyError) as error:
                        candidato["errores"].append(f"Almacenamiento: {type(error).__name__}")
                        candidato["quality_success"] = False
                        candidato["quality_gate"] = {"accepted": False, "quality_success": False,
                                                       "motivo": "No se pudieron persistir los artefactos CAD"}
                        estado_intento = "error_archivos"
                        fase_error = "almacenamiento"
                        diagnostico = candidato["quality_gate"]["motivo"]

                # No se guarda una excepción opaca del runtime como supuesta crítica semántica.
                if revision_codigo and not candidato.get("code_review"):
                    candidato["code_review"] = _json(revision_codigo)
                if respuesta_codigo:
                    candidato["code_reviewer_call"] = _entrada_llamada(
                        "code_reviewer", respuesta_codigo, respuesta_codigo.modelo, "nvidia_nim"
                    )
                candidato["diagnostico"] = diagnostico
                candidato["fase_error"] = fase_error
                candidato["technical_success"] = bool(candidato.get("technical_success"))
                solicitud_final = {**solicitud_base,
                    "validacion_cad": candidato.get("technical_result", {}),
                    "quality_loop": {"quality_success": candidato["quality_success"],
                                     "candidate_id": candidate_id, "iteracion": iteracion}}
                _actualizar_estado_candidato(identificador, intento_id, estado_intento,
                    fase_error, diagnostico, codigo, respuesta, solicitud_final, resultado_cad)
                with crear_sesion() as sesion:
                    _persistir_informe(sesion, identificador, intento_id, iteracion,
                        candidate_id, parent_id, candidato)
                    config_ejecucion = sesion.get(Ejecucion, identificador)
                    config = dict(config_ejecucion.configuracion_calidad or {})
                    config["llamadas_ia"] = llamadas
                    config["tokens_presupuestados"] = tokens_presupuestados
                    config["llamadas"] = list(llamadas_registradas)
                    candidatos = list(config.get("candidatos") or [])
                    candidatos.append({"candidate_id": candidate_id, "iteracion": iteracion,
                        "parent_candidate_id": parent_id, "technical_success": candidato["technical_success"],
                        "quality_success": candidato["quality_success"],
                        "quality_score": candidato.get("quality_score"), "attempt_id": intento_id})
                    config["candidatos"] = candidatos
                    config_ejecucion.configuracion_calidad = config
                    sesion.commit()
                resultados_iteracion.append((intento_id, candidato))
                if llamadas >= MAXIMO_LLAMADAS_QUALITY_LOOP:
                    break

            if detener_por_infraestructura:
                return
            if not resultados_iteracion:
                break
            informes_por_iteracion.append(resultados_iteracion)
            elegibles = _ordenar_candidatos(resultados_iteracion)
            mejor_intento, mejor = elegibles[0]
            with crear_sesion() as sesion:
                for intento_id, candidato in resultados_iteracion:
                    informe = sesion.scalar(select(InformeCalidad).where(
                        InformeCalidad.intento_identificador == intento_id
                    ))
                    if informe:
                        datos = dict(informe.resultado)
                        datos["seleccionado_para_reparacion"] = intento_id == mejor_intento
                        datos["ranking_en_iteracion"] = 1 + next(
                            (i for i, par in enumerate(elegibles) if par[0] == intento_id), 0
                        )
                        informe.resultado = datos
                sesion.commit()
            mejores.append((iteracion, mejor_intento, mejor))
            candidato_padre = mejor["candidate_id"]
            historial_padre = {"candidate_id": candidato_padre,
                "codigo": siguiente.codigo if (siguiente := _obtener_intento(mejor_intento)) else "",
                "informe": mejor, "diagnostico": mejor.get("diagnostico", "")}
            if mejor.get("quality_success"):
                break
            if llamadas >= MAXIMO_LLAMADAS_QUALITY_LOOP:
                break

        if not mejores:
            with crear_sesion() as sesion:
                ejecucion = sesion.get(Ejecucion, identificador)
                ejecucion.estado = "fallida"
                ejecucion.mensaje = "El límite de llamadas IA no permitió completar un candidato"
                ejecucion.fecha_fin = fecha_actual()
                config = dict(ejecucion.configuracion_calidad or {})
                config.update({"estado_protocolo": "budget_exhausted", "llamadas_ia": llamadas,
                               "llamadas": llamadas_registradas,
                               "tokens_presupuestados": tokens_presupuestados})
                ejecucion.configuracion_calidad = config
                sesion.commit()
            return

        final_iteracion, final_intento_id, ganador = sorted(mejores, key=lambda item: (
            bool(item[2].get("quality_success")), bool(item[2].get("technical_success")),
            float(item[2].get("quality_score") or -1),
        ), reverse=True)[0]
        with crear_sesion() as sesion:
            ganador_informe = sesion.scalar(select(InformeCalidad).where(
                InformeCalidad.intento_identificador == final_intento_id
            ))
            if ganador_informe:
                datos = dict(ganador_informe.resultado)
                datos["seleccionado_final"] = True
                ganador_informe.resultado = datos
            ejecucion = sesion.get(Ejecucion, identificador)
            if ganador.get("technical_success"):
                intento_final = sesion.get(IntentoGeneracion, final_intento_id)
                resultado_cad = solicitar_resultado_guardado(identificador, ganador["candidate_id"], motor)
                if resultado_cad:
                    try:
                        guardar_archivos(identificador, motor, intento_final.codigo,
                            resultado_cad, final_intento_id, sesion)
                    except (ValueError, OSError, KeyError):
                        ganador["quality_success"] = False
                        ganador.setdefault("quality_gate", {})["accepted"] = False
                        ganador["quality_gate"]["quality_success"] = False
                        ejecucion.mensaje = "El CAD es técnicamente válido, pero no se pudieron guardar los archivos finales"
                        ejecucion.estado = "fallida"
                    else:
                        ejecucion.primer_exito_ejecucion = intento_final.numero
                        ejecucion.primer_exito_cad = intento_final.numero
                        ejecucion.primer_exito_exportacion = intento_final.numero
            aceptado = bool(ganador.get("quality_success"))
            ejecucion.estado = "completada" if aceptado else "fallida"
            ejecucion.mensaje = (
                f"CAD aceptado por Quality Gate (puntuación {ganador.get('quality_score'):.3f})"
                if aceptado and ganador.get("quality_score") is not None else
                "CAD técnicamente válido, pero rechazado por Quality Gate" if ganador.get("technical_success") else
                "No se obtuvo un candidato CAD técnicamente válido"
            )
            ejecucion.fecha_fin = fecha_actual()
            config = dict(ejecucion.configuracion_calidad or {})
            config.update({"estado_protocolo": "quality_accepted" if aceptado else "quality_rejected",
                "quality_success": aceptado,
                "technical_success": bool(ganador.get("technical_success")),
                "quality_score": ganador.get("quality_score"),
                "quality_gate": ganador.get("quality_gate"),
                "ganador_candidate_id": ganador.get("candidate_id"),
                "ganador_iteracion": final_iteracion,
                "llamadas_ia": llamadas, "llamadas": llamadas_registradas,
                "tokens_presupuestados": tokens_presupuestados,
                "maximo_tokens_presupuestados": MAXIMO_TOKENS_QUALITY_LOOP,
                "tokens_entrada": sum(int(c.get("tokens_entrada") or 0) for c in llamadas_registradas),
                "tokens_salida": sum(int(c.get("tokens_salida") or 0) for c in llamadas_registradas),
                "costo_estimado_usd": (sum(float(c["costo_estimado_usd"]) for c in llamadas_registradas)
                    if llamadas_registradas and all(c.get("costo_estimado_usd") is not None
                                                    for c in llamadas_registradas) else None),
                "costo_parcial_conocido_usd": sum(float(c.get("costo_estimado_usd") or 0)
                                                    for c in llamadas_registradas),
                "costo_incompleto": any(c.get("costo_estimado_usd") is None
                                         for c in llamadas_registradas),
                "ranking_global": [{**c, "seleccionado_final": c["candidate_id"] == ganador.get("candidate_id")}
                    for c in sorted(config.get("candidatos", []), key=lambda item: (
                        bool(item.get("quality_success")), bool(item.get("technical_success")),
                        float(item.get("quality_score") or -1)), reverse=True)]})
            ejecucion.configuracion_calidad = config
            sesion.commit()
    finally:
        # Solo se escribe información de configuración y uso; nunca headers ni secretos.
        pass


def _obtener_intento(identificador: int) -> IntentoGeneracion | None:
    with crear_sesion() as sesion:
        intento = sesion.get(IntentoGeneracion, identificador)
        return intento


def solicitar_resultado_guardado(ejecucion_id: str, candidate_id: str, motor: str) -> dict | None:
    """Recupera de forma acotada los artefactos candidatos almacenados fuera de PostgreSQL."""
    directorio = Path(DIRECTORIO_ARTEFACTOS) / "ejecuciones" / ejecucion_id
    nombres = [f"{candidate_id}-pieza.stl", f"{candidate_id}-pieza.step"]
    if motor == "freecad":
        nombres.append(f"{candidate_id}-pieza.FCStd")
    archivos = {}
    try:
        for nombre in nombres:
            ruta = directorio / nombre
            datos = ruta.read_bytes()
            if not datos or len(datos) > 20_000_000:
                return None
            archivos[nombre.removeprefix(f"{candidate_id}-")] = base64.b64encode(datos).decode("ascii")
        return archivos
    except OSError:
        return None
