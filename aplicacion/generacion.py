"""Generación independiente por condición y reparación cerrada de hasta cinco pasos."""

import ast
import base64
import hashlib
import re
import time
from pathlib import Path

import httpx
from sqlalchemy import select

from aplicacion.base_datos import (
    ArchivoGenerado, Campana, CondicionExperimental, Ejecucion, IntentoGeneracion,
    crear_sesion, fecha_actual,
)
from aplicacion.configuracion import (
    DIRECTORIO_ARTEFACTOS, MODELOS_LOCALES, MODELOS_NVIDIA_REGISTRADOS, VERSION_REINTENTOS_NVIDIA,
    URL_SUPERVISOR, VERSION_PLANTILLA, perfil_generacion, resolver_esfuerzo,
)
from aplicacion.limites_modelos import limites_modelo
from aplicacion.costos import PERFIL_TARIFA, costo_estimado, costo_maximo_planificacion
from aplicacion.proveedor_deepseek import ErrorProveedor
from aplicacion.proveedores import solicitar_codigo, verificar_modelo_local
from aplicacion.retroalimentacion import construir_solicitud
from aplicacion.reintentos_nvidia import ReintentoNvidiaCancelado
from aplicacion.prompts_sistema import instrucciones_sistema


IMPORTACIONES_PERMITIDAS = {
    "cadquery": {"cadquery", "math"},
    "build123d": {"build123d", "math"},
    "freecad": {"FreeCAD", "Part", "PartDesign", "Sketcher", "math"},
}
MODULOS_OCP_PERMITIDOS = {"cadquery", "build123d"}
SIMBOLOS_OCP_PERMITIDOS = {
    "OCP.gp": {"gp_Pnt", "gp_Vec", "gp_Dir", "gp_Ax1", "gp_Pln", "gp_Trsf"},
    "OCP.GeomAPI": {"GeomAPI_PointsToBSpline", "GeomAPI_PointsToBSplineSurface"},
    "OCP.Geom": {"Geom_BSplineCurve", "Geom_BSplineSurface"},
    "OCP.BRepBuilderAPI": {"BRepBuilderAPI_MakeEdge", "BRepBuilderAPI_MakeWire",
                            "BRepBuilderAPI_MakeFace", "BRepBuilderAPI_MakeVertex",
                            "BRepBuilderAPI_MakeSolid", "BRepBuilderAPI_Transform"},
    "OCP.BRepPrimAPI": {"BRepPrimAPI_MakePrism", "BRepPrimAPI_MakeRevol",
                         "BRepPrimAPI_MakeCylinder", "BRepPrimAPI_MakeSphere"},
    "OCP.BRepAlgoAPI": {"BRepAlgoAPI_Fuse", "BRepAlgoAPI_Cut", "BRepAlgoAPI_Common"},
    "OCP.BRepCheck": {"BRepCheck_Analyzer"},
    "OCP.TColgp": {"TColgp_Array1OfPnt", "TColgp_Array1OfPnt2d"},
}
FUNCIONES_PROHIBIDAS = {
    "open", "eval", "exec", "compile", "__import__", "input", "breakpoint",
    "getattr", "setattr", "delattr", "vars", "globals", "locals", "dir",
}
ATRIBUTOS_ARCHIVO_PROHIBIDOS = {
    "open", "read", "read_text", "read_bytes", "write", "write_text", "write_bytes",
    "importStep", "importStl", "importBrep", "export", "exportStep", "exportStl",
    "saveAs", "load", "loadMesh", "save", "unlink", "mkdir", "rmdir",
}
ARCHIVOS_PERMITIDOS = {"pieza.stl", "pieza.step", "pieza.FCStd"}


def extraer_codigo(texto: str) -> str:
    bloques = re.findall(r"```(?:python|py)?\s*\n(.*?)```", texto, re.I | re.S)
    return (bloques[0] if bloques else texto.strip()).strip().lstrip("\ufeff")


def revisar_codigo(codigo: str, motor: str) -> None:
    if not codigo:
        raise ValueError("El código está vacío")
    arbol = ast.parse(codigo)
    permitidas = IMPORTACIONES_PERMITIDAS[motor]
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for nombre in nodo.names:
                if nombre.name.split(".")[0] == "OCP":
                    raise ValueError("OCP requiere importaciones from-module restringidas")
                if nombre.name.split(".")[0] not in permitidas:
                    raise ValueError(f"Importación no permitida: {nombre.name}")
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level:
                raise ValueError("Las importaciones relativas no están permitidas")
            if nodo.module and nodo.module.startswith("OCP."):
                if motor not in MODULOS_OCP_PERMITIDOS or nodo.module not in SIMBOLOS_OCP_PERMITIDOS:
                    raise ValueError(f"Módulo OCP no permitido: {nodo.module}")
                simbolos = {alias.name for alias in nodo.names}
                if simbolos - SIMBOLOS_OCP_PERMITIDOS[nodo.module]:
                    raise ValueError(f"Símbolo OCP no permitido: {sorted(simbolos - SIMBOLOS_OCP_PERMITIDOS[nodo.module])[0]}")
            elif not nodo.module or nodo.module.split(".")[0] not in permitidas:
                raise ValueError(f"Importación no permitida: {nodo.module}")
        elif isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
            if nodo.func.id in FUNCIONES_PROHIBIDAS:
                raise ValueError(f"Función no permitida: {nodo.func.id}")
        elif isinstance(nodo, ast.Attribute):
            if nodo.attr.startswith("__"):
                raise ValueError("No se permiten atributos especiales")
            if nodo.attr in ATRIBUTOS_ARCHIVO_PROHIBIDOS:
                raise ValueError(f"Acceso a archivo no permitido: {nodo.attr}")
        elif isinstance(nodo, ast.Name) and nodo.id in {"__builtins__", "__import__"}:
            raise ValueError("No se permiten nombres internos")


def solicitar_ejecucion_cad(motor: str, codigo: str) -> dict:
    try:
        with httpx.Client(timeout=210) as cliente:
            respuesta = cliente.post(
                f"{URL_SUPERVISOR}/ejecutar", json={"motor": motor, "codigo": codigo}
            )
        respuesta.raise_for_status()
        return respuesta.json()
    except (httpx.HTTPError, ValueError) as error:
        raise RuntimeError(
            f"El supervisor CAD no respondió correctamente: {type(error).__name__}"
        ) from error


def guardar_archivos(
    identificador: str, motor: str, codigo: str, codificados: dict,
    identificador_intento: int, sesion,
) -> None:
    requeridos = {"pieza.stl", "pieza.step"}
    if motor == "freecad":
        requeridos.add("pieza.FCStd")
    if not requeridos.issubset(codificados):
        raise ValueError("Faltan archivos CAD obligatorios")
    directorio = Path(DIRECTORIO_ARTEFACTOS) / "ejecuciones" / identificador
    directorio.mkdir(parents=True, exist_ok=True)
    candidatos = dict(codificados)
    candidatos["pieza.py"] = base64.b64encode(codigo.encode("utf-8")).decode("ascii")
    for nombre, contenido in candidatos.items():
        if nombre not in ARCHIVOS_PERMITIDOS | {"pieza.py"}:
            raise ValueError("El supervisor devolvió un nombre de archivo inesperado")
        datos = base64.b64decode(contenido, validate=True)
        if not datos or len(datos) > 20_000_000:
            raise ValueError(f"El archivo {nombre} está vacío o excede el límite")
        ruta = directorio / nombre
        ruta.write_bytes(datos)
        sesion.add(
            ArchivoGenerado(
                ejecucion_identificador=identificador, nombre=nombre, ruta=str(ruta),
                tamano_bytes=len(datos), sha256=hashlib.sha256(datos).hexdigest(),
                rol="nativo" if nombre != "pieza.py" else "codigo_final",
                intento_identificador=identificador_intento,
            )
        )


def _maximo_tokens_ejecucion(sesion, ejecucion: Ejecucion) -> int | None:
    """Recupera el límite fijado al crear la campaña o al iniciar sus intentos."""
    if ejecucion.campana_identificador:
        campana = sesion.get(Campana, ejecucion.campana_identificador)
        perfiles = (campana.configuracion or {}).get("perfiles_generacion", {})
        limite = (perfiles.get(ejecucion.modelo) or {}).get("max_tokens")
        if limite is not None:
            return limite
    for intento in ejecucion.intentos:
        limite = ((intento.solicitud_modelo or {}).get("perfil") or {}).get("max_tokens")
        if limite is not None:
            return limite
    return None


def _reintentos_nvidia_ejecucion(sesion, ejecucion: Ejecucion) -> bool:
    if ejecucion.modelo not in MODELOS_NVIDIA_REGISTRADOS:
        return False
    if ejecucion.campana_identificador:
        campana = sesion.get(Campana, ejecucion.campana_identificador)
        perfil = (campana.configuracion or {}).get("perfiles_generacion", {}).get(ejecucion.modelo, {})
        return perfil.get("protocolo_reintentos") == VERSION_REINTENTOS_NVIDIA
    for intento in ejecucion.intentos:
        perfil = (intento.solicitud_modelo or {}).get("perfil")
        if perfil:
            return perfil.get("protocolo_reintentos") == VERSION_REINTENTOS_NVIDIA
    return True


def _controles_reintento_nvidia(identificador: str, identificador_intento: int, solicitud: dict):
    def comprobar():
        with crear_sesion() as sesion:
            ejecucion = sesion.get(Ejecucion, identificador)
            campana = sesion.get(Campana, ejecucion.campana_identificador) if ejecucion.campana_identificador else None
            if ejecucion.estado == "cancelada" or (campana and campana.estado == "cancelada"):
                raise ReintentoNvidiaCancelado()

    def registrar(incidencia):
        solicitud.setdefault("reintentos_operativos", []).append(incidencia)
        with crear_sesion() as sesion:
            intento = sesion.get(IntentoGeneracion, identificador_intento)
            intento.estado = "esperando_proveedor"
            intento.solicitud_modelo = dict(solicitud)
            ejecucion = sesion.get(Ejecucion, identificador)
            ejecucion.mensaje = (f"NVIDIA sin respuesta válida ({incidencia['codigo']}); "
                f"reintento operativo {incidencia['numero']} en {incidencia['espera_segundos']:g} s. "
                "Se conserva el mismo intento CAD")
            sesion.commit()
    return registrar, comprobar


def _bloqueo_campana(sesion, ejecucion: Ejecucion) -> str | None:
    if ejecucion.estado == "cancelada":
        return "cancelada"
    if not ejecucion.campana_identificador:
        return None
    campana = sesion.get(Campana, ejecucion.campana_identificador)
    if campana.estado == "cancelada":
        ejecucion.estado = "cancelada"
        ejecucion.mensaje = "Cancelada antes de la próxima generación"
        ejecucion.fecha_fin = fecha_actual()
        return "cancelada"
    if (campana.configuracion or {}).get("plantilla", VERSION_PLANTILLA) != VERSION_PLANTILLA:
        campana.estado = "bloqueada"
        campana.mensaje = "Cambió la plantilla de generación; cree una campaña nueva para conservar el protocolo"
        ejecucion.estado = "bloqueada"
        ejecucion.mensaje = campana.mensaje
        return "plantilla"
    if ejecucion.condicion_identificador:
        condicion = sesion.get(CondicionExperimental, ejecucion.condicion_identificador)
        if condicion and condicion.imagen_identificador:
            try:
                with httpx.Client(timeout=12) as cliente:
                    respuesta = cliente.get(f"{URL_SUPERVISOR}/imagenes")
                    respuesta.raise_for_status()
                    imagen_actual = respuesta.json().get(ejecucion.motor)
            except (httpx.HTTPError, ValueError) as error:
                campana.estado = "bloqueada"
                ejecucion.estado = "bloqueada"
                ejecucion.mensaje = f"No se pudo verificar la imagen CAD: {type(error).__name__}"
                return "runtime"
            if imagen_actual != condicion.imagen_identificador:
                campana.estado = "bloqueada"
                ejecucion.estado = "bloqueada"
                ejecucion.mensaje = "La imagen CAD cambió durante la campaña"
                return "runtime"
    costo_previsto = costo_maximo_planificacion(
        ejecucion.modelo, _maximo_tokens_ejecucion(sesion, ejecucion)
    ) or 0
    if campana.presupuesto_usd is not None and campana.gasto_estimado_usd + costo_previsto > campana.presupuesto_usd:
        campana.estado = "pausada"
        campana.mensaje = "Pausada por límite de presupuesto estimado"
        ejecucion.estado = "pausada"
        ejecucion.mensaje = "Presupuesto estimado insuficiente antes de la llamada"
        return "presupuesto"
    return None


def procesar_ejecucion(identificador: str) -> None:
    with crear_sesion() as sesion:
        modo = sesion.scalar(select(Ejecucion.modo).where(Ejecucion.identificador == identificador))
    if modo == "quality-loop":
        from aplicacion.calidad.flujo import procesar_quality_loop
        procesar_quality_loop(identificador)
        return
    with crear_sesion() as sesion:
        ejecucion = sesion.scalar(select(Ejecucion).where(
            Ejecucion.identificador == identificador
        ).with_for_update())
        if ejecucion is None or ejecucion.estado not in {"pendiente", "pausada"}:
            return
        if _bloqueo_campana(sesion, ejecucion):
            sesion.commit()
            return
        intentos_previos = list(ejecucion.intentos)
        if any(intento.estado not in {"invalido"} for intento in intentos_previos):
            ejecucion.estado = "bloqueada"
            ejecucion.mensaje = "Un intento previo quedó sin desenlace; revisar antes de repetir IA"
            sesion.commit()
            return
        ejecucion.estado = "generando"
        ejecucion.mensaje = "Consultando el proveedor de IA"
        ejecucion.fecha_inicio = ejecucion.fecha_inicio or fecha_actual()
        descripcion, motor, modelo = ejecucion.descripcion, ejecucion.motor, ejecucion.modelo
        # Las trazas anteriores permiten recuperar la selección al reanudar trabajos antiguos.
        esfuerzo_anterior = next(((intento.solicitud_modelo or {}).get("perfil", {}).get("reasoning_effort")
                                  for intento in intentos_previos
                                  if (intento.solicitud_modelo or {}).get("perfil")), None)
        esfuerzo = resolver_esfuerzo(modelo, ejecucion.esfuerzo_razonamiento or esfuerzo_anterior)
        maximo_tokens = _maximo_tokens_ejecucion(sesion, ejecucion)
        reintentos_nvidia = _reintentos_nvidia_ejecucion(sesion, ejecucion)
        ejecucion.esfuerzo_razonamiento = esfuerzo
        maximo = 1 if ejecucion.modo == "open-loop" else min(ejecucion.maximo_intentos, 5)
        siguiente_intento = len(intentos_previos) + 1
        historial = [{
            "numero": intento.numero, "codigo": intento.codigo,
            "diagnostico": intento.diagnostico, "fase_error": intento.fase_error,
            "contexto": (intento.solicitud_modelo or {}).get("validacion_cad") or {},
        } for intento in intentos_previos]
        sesion.commit()

    for numero in range(siguiente_intento, maximo + 1):
        with crear_sesion() as sesion:
            ejecucion = sesion.get(Ejecucion, identificador)
            if _bloqueo_campana(sesion, ejecucion):
                sesion.commit()
                return
            ejecucion.numero_intentos = numero
            ejecucion.mensaje = f"Generando intento {numero} de {maximo}"
            intento = IntentoGeneracion(
                ejecucion_identificador=identificador, numero=numero, estado="consultando_ia"
            )
            sesion.add(intento)
            sesion.commit()
            identificador_intento = intento.identificador

        solicitud, retroalimentacion = construir_solicitud(descripcion, motor, historial)
        mensajes = [
            {"role": "system", "content": instrucciones_sistema(motor)},
            {"role": "user", "content": solicitud},
        ]
        solicitud_registrada = {
            "mensajes": mensajes, "plantilla": VERSION_PLANTILLA,
            "limites_modelo": limites_modelo(modelo),
            "retroalimentacion": retroalimentacion,
            "perfil": perfil_generacion(modelo, esfuerzo, maximo_tokens),
        }
        if modelo in MODELOS_NVIDIA_REGISTRADOS and not reintentos_nvidia:
            solicitud_registrada["perfil"].pop("protocolo_reintentos", None)
        with crear_sesion() as sesion:
            sesion.get(IntentoGeneracion, identificador_intento).solicitud_modelo = solicitud_registrada
            sesion.commit()
        if modelo in MODELOS_LOCALES:
            try:
                identidad_actual = verificar_modelo_local(modelo)
                with crear_sesion() as sesion:
                    ejecucion = sesion.get(Ejecucion, identificador)
                    condicion = (sesion.get(CondicionExperimental, ejecucion.condicion_identificador)
                                 if ejecucion.condicion_identificador else None)
                    esperado = ((condicion.configuracion.get("modelo_local") or {}).get("digest")
                                if condicion else None)
                    if not esperado and numero > 1:
                        primero = ejecucion.intentos[0].solicitud_modelo or {}
                        esperado = (primero.get("perfil") or {}).get("digest")
                    if esperado and identidad_actual.get("digest") != esperado:
                        raise ErrorProveedor("El digest del modelo local cambió durante la ejecución")
            except ErrorProveedor as error:
                with crear_sesion() as sesion:
                    intento = sesion.get(IntentoGeneracion, identificador_intento)
                    ejecucion = sesion.get(Ejecucion, identificador)
                    intento.estado = "error_proveedor"
                    intento.fase_error = "identidad_modelo"
                    intento.diagnostico = str(error)
                    ejecucion.estado = "bloqueada"
                    ejecucion.mensaje = str(error)
                    sesion.commit()
                return
        inicio_total = time.monotonic()
        inicio_ia = time.monotonic()
        try:
            if reintentos_nvidia:
                registrar, comprobar = _controles_reintento_nvidia(identificador, identificador_intento, solicitud_registrada)
                respuesta = solicitar_codigo(modelo, mensajes, esfuerzo, maximo_tokens,
                    reintentos_nvidia=True, registrar_reintento=registrar, comprobar_continuacion=comprobar)
            else:
                respuesta = solicitar_codigo(modelo, mensajes, esfuerzo, maximo_tokens)
        except ReintentoNvidiaCancelado:
            with crear_sesion() as sesion:
                intento = sesion.get(IntentoGeneracion, identificador_intento)
                intento.estado = "cancelado"
                intento.diagnostico = "Campaña cancelada durante la recuperación de NVIDIA"
                intento.duracion_ia_segundos = time.monotonic() - inicio_ia
                ejecucion = sesion.get(Ejecucion, identificador)
                ejecucion.estado = "cancelada"
                ejecucion.mensaje = intento.diagnostico
                ejecucion.fecha_fin = fecha_actual()
                sesion.commit()
            return
        except ErrorProveedor as error:
            with crear_sesion() as sesion:
                intento = sesion.get(IntentoGeneracion, identificador_intento)
                ejecucion = sesion.get(Ejecucion, identificador)
                intento.estado = "error_proveedor"
                intento.fase_error = "proveedor"
                intento.solicitud_modelo = {**solicitud_registrada, "modelo": modelo}
                intento.diagnostico = str(error)
                intento.duracion_ia_segundos = time.monotonic() - inicio_ia
                intento.duracion_segundos = time.monotonic() - inicio_total
                ejecucion.estado = "bloqueada"
                ejecucion.mensaje = str(error)
                ejecucion.fecha_fin = fecha_actual()
                sesion.commit()
            return

        duracion_ia = time.monotonic() - inicio_ia
        codigo = extraer_codigo(respuesta["texto"])
        # Persistir la respuesta antes de ejecutar CAD evita repetir una llamada ya recibida.
        with crear_sesion() as sesion:
            intento = sesion.get(IntentoGeneracion, identificador_intento)
            intento.respuesta_modelo = respuesta["texto"]
            intento.codigo = codigo
            intento.modelo_informado = respuesta["modelo_informado"]
            intento.tokens_entrada = respuesta["tokens_entrada"]
            intento.tokens_salida = respuesta["tokens_salida"]
            intento.costo_estimado_usd = costo_estimado(modelo, intento.tokens_entrada, intento.tokens_salida)
            intento.duracion_ia_segundos = duracion_ia
            intento.solicitud_modelo = {**solicitud_registrada, "perfil": respuesta.get("perfil"),
                                       "proveedor": respuesta.get("proveedor"),
                                       "finalizacion": respuesta.get("finalizacion"),
                                       "tarifa": PERFIL_TARIFA if intento.costo_estimado_usd is not None else None}
            intento.estado = "respuesta_recibida"
            ejecucion = sesion.get(Ejecucion, identificador)
            if ejecucion.campana_identificador and intento.costo_estimado_usd is not None:
                campana = sesion.get(Campana, ejecucion.campana_identificador)
                campana.gasto_estimado_usd += intento.costo_estimado_usd
            sesion.commit()
        diagnostico = ""
        resultado_cad = None
        estado = "invalido"
        fase_error = None
        sintaxis_valida = None
        ejecucion_correcta = None
        cad_valido = None
        exportacion_valida = None
        duracion_cad = None
        contexto_local = {}
        try:
            if respuesta["finalizacion"] == "length":
                raise ValueError("La respuesta de IA se truncó por el límite de salida")
            try:
                ast.parse(codigo)
            except SyntaxError as error:
                sintaxis_valida = False
                fase_error = "sintaxis"
                lineas = codigo.splitlines()
                contexto_local = {
                    "linea_error": error.lineno,
                    "fragmento_codigo": "\n".join(
                        f"{indice + 1}: {lineas[indice]}" for indice in range(
                            max(0, (error.lineno or 1) - 3), min(len(lineas), (error.lineno or 1) + 2)
                        )
                    )[:2500],
                }
                raise ValueError(f"Error de sintaxis: línea {error.lineno}: {error.msg}") from error
            sintaxis_valida = True
            revisar_codigo(codigo, motor)
            with crear_sesion() as sesion:
                ejecucion = sesion.get(Ejecucion, identificador)
                ejecucion.mensaje = f"Validando CAD del intento {numero}"
                sesion.commit()
            inicio_cad = time.monotonic()
            resultado_cad = solicitar_ejecucion_cad(motor, codigo)
            duracion_cad = time.monotonic() - inicio_cad
            with crear_sesion() as sesion:
                ejecucion = sesion.get(Ejecucion, identificador)
                condicion = (sesion.get(CondicionExperimental, ejecucion.condicion_identificador)
                             if ejecucion.condicion_identificador else None)
                if condicion and condicion.imagen_identificador != resultado_cad.get("runtime_identificador"):
                    raise RuntimeError("El runtime CAD ejecutado no coincide con la imagen congelada")
            sintaxis_valida = resultado_cad.get("sintaxis_valida", sintaxis_valida)
            ejecucion_correcta = resultado_cad.get("ejecucion_correcta")
            cad_valido = resultado_cad.get("cad_valido")
            exportacion_valida = resultado_cad.get("exportacion_valida")
            fase_error = resultado_cad.get("fase_error")
            if resultado_cad.get("correcto") is True:
                estado = "correcto"
            else:
                diagnostico = str(resultado_cad.get("diagnostico") or "Resultado CAD inválido")[:3000]
        except ValueError as error:
            fase_error = fase_error or ("respuesta" if sintaxis_valida is None else "politica")
            ejecucion_correcta = False
            diagnostico = str(error)[:3000]
        except RuntimeError as error:
            with crear_sesion() as sesion:
                intento = sesion.get(IntentoGeneracion, identificador_intento)
                ejecucion = sesion.get(Ejecucion, identificador)
                intento.estado = "error_supervisor"
                intento.fase_error = "infraestructura"
                intento.respuesta_modelo = respuesta["texto"]
                intento.codigo = codigo
                intento.solicitud_modelo = {**solicitud_registrada, "perfil": respuesta.get("perfil")}
                intento.diagnostico = str(error)
                intento.duracion_ia_segundos = duracion_ia
                intento.duracion_segundos = time.monotonic() - inicio_total
                ejecucion.estado = "bloqueada"
                ejecucion.mensaje = str(error)
                ejecucion.fecha_fin = fecha_actual()
                sesion.commit()
            return

        resultado_validacion = {
            "fase_error": fase_error, "diagnostico": diagnostico, **contexto_local,
            **{clave: valor for clave, valor in (resultado_cad or {}).items() if clave != "archivos"},
        }
        with crear_sesion() as sesion:
            intento = sesion.get(IntentoGeneracion, identificador_intento)
            ejecucion = sesion.get(Ejecucion, identificador)
            intento.respuesta_modelo = respuesta["texto"]
            intento.codigo = codigo
            intento.modelo_informado = respuesta["modelo_informado"]
            intento.tokens_entrada = respuesta["tokens_entrada"]
            intento.tokens_salida = respuesta["tokens_salida"]
            intento.costo_estimado_usd = costo_estimado(modelo, intento.tokens_entrada, intento.tokens_salida)
            intento.solicitud_modelo = {
                **solicitud_registrada, "perfil": respuesta.get("perfil"),
                "finalizacion": respuesta.get("finalizacion"),
                "proveedor": respuesta.get("proveedor"),
                "tarifa": PERFIL_TARIFA if intento.costo_estimado_usd is not None else None,
                "validacion_cad": resultado_validacion,
            }
            intento.duracion_ia_segundos = duracion_ia
            intento.duracion_cad_segundos = duracion_cad
            intento.duracion_segundos = time.monotonic() - inicio_total
            intento.estado = estado
            intento.diagnostico = diagnostico
            intento.sintaxis_valida = sintaxis_valida
            intento.ejecucion_correcta = ejecucion_correcta
            intento.cad_valido = cad_valido
            intento.exportacion_valida = exportacion_valida
            intento.fase_error = fase_error
            intento.runtime_identificador = resultado_cad.get("runtime_identificador") if resultado_cad else None
            if ejecucion_correcta and ejecucion.primer_exito_ejecucion is None:
                ejecucion.primer_exito_ejecucion = numero
            if cad_valido and ejecucion.primer_exito_cad is None:
                ejecucion.primer_exito_cad = numero
            if estado == "correcto":
                try:
                    guardar_archivos(
                        identificador, motor, codigo, resultado_cad["archivos"],
                        identificador_intento, sesion,
                    )
                except (ValueError, OSError, KeyError) as error:
                    intento.estado = "error_archivos"
                    intento.fase_error = "almacenamiento"
                    intento.diagnostico = f"No se pudieron guardar los archivos: {type(error).__name__}"
                    ejecucion.estado = "bloqueada"
                    ejecucion.mensaje = intento.diagnostico
                else:
                    ejecucion.primer_exito_exportacion = numero
                    ejecucion.estado = "completada"
                    volumen = resultado_cad.get("volumen_mm3")
                    ejecucion.mensaje = (
                        f"Pieza válida en el intento {numero}; volumen {volumen:.2f} mm³"
                        if isinstance(volumen, (int, float))
                        else f"Pieza válida en el intento {numero}"
                    )
                ejecucion.fecha_fin = fecha_actual()
                sesion.commit()
                if ejecucion.estado == "completada":
                    from aplicacion.analisis import analizar_ejecucion, registrar_incidencia
                    try:
                        analizar_ejecucion(identificador)
                    except Exception as error:
                        registrar_incidencia(
                            identificador, f"Falló la persistencia del análisis: {type(error).__name__}"
                        )
                return
            ejecucion.mensaje = f"Intento {numero}: {diagnostico}"
            sesion.commit()
        historial.append({
            "numero": numero, "codigo": codigo, "diagnostico": diagnostico,
            "fase_error": fase_error,
            "contexto": resultado_validacion,
        })

    with crear_sesion() as sesion:
        ejecucion = sesion.get(Ejecucion, identificador)
        ejecucion.estado = "fallida"
        ejecucion.mensaje = f"Se agotaron los {maximo} intentos sin obtener CAD válido"
        ejecucion.fecha_fin = fecha_actual()
        sesion.commit()
