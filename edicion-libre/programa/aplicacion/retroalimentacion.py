"""Construye correcciones con evidencia acumulada, sin recortar el programa anterior."""

import ast
import hashlib
import re
import unicodedata


def huella_codigo(codigo: str) -> str:
    """Ignora comentarios y formato para detectar correcciones meramente cosméticas."""
    try:
        contenido = ast.dump(ast.parse(codigo), include_attributes=False)
    except SyntaxError:
        contenido = codigo.strip()
    return hashlib.sha256(contenido.encode()).hexdigest()


def firma_error(diagnostico: str) -> str:
    """La misma excepción sigue siendo la misma aunque cambie la línea del script."""
    causa = diagnostico.strip().splitlines()[0] if diagnostico.strip() else ""
    causa = re.sub(r"0x[0-9a-fA-F]+", "<direccion>", causa)
    return re.sub(r"\s+", " ", causa).strip()


def orientaciones_error(motor: str, diagnostico: str, contexto: dict) -> list[str]:
    texto = (diagnostico + " " + str(contexto.get("fragmento_codigo", ""))).lower()
    orientaciones = []
    if "fillet" in texto or "chamfer" in texto or "brep_api" in texto or "stdfail_notdone" in texto:
        orientaciones.append(
            "No apliques fillet/chamfer a todas las aristas del resultado. Localiza la "
            "operación que falló; rediseña esa unión o usa un perfil ya redondeado, "
            "una revolución o un loft. Conserva ojos, labios, surcos y demás detalles. "
            "Si el redondeo es accesorio, omítelo en esa arista concreta."
        )
    if "sólido" in texto or "b-rep" in texto or "frozenshape" in texto:
        orientaciones.append(
            "Comprueba validez y número de sólidos después de cada booleano. Los "
            "relieves deben penetrar en el cuerpo con un solapamiento de volumen, "
            "no tocarlo solo por una arista o punto. Los cortadores deben cruzar la "
            "superficie. No selecciones solo el primer sólido para ocultar piezas sueltas."
        )
    if motor == "cadquery" and ("scale" in texto or "has no attribute" in texto):
        orientaciones.append(
            "CadQuery 2.6.1: Workplane no tiene scale. No uses scale(x,y,z). "
            "Para un cuerpo ovoide usa lofts de perfiles elípticos o revolución; "
            "Workplane.sphere(radius) crea una esfera completa. Usa APIs existentes."
        )
    if motor == "cadquery" and ("loft" in texto or "revolve" in texto):
        orientaciones.append(
            "CadQuery: loft consume perfiles pendientes del mismo contexto de "
            "Workplane. Encadena los perfiles y workplane(offset=...) en una sola "
            "cadena; los desplazamientos son incrementales. Si añades wires de "
            "otros Workplane con add, agrupa todos los wires y llama a toPending "
            "una sola vez antes de loft: hacerlo dentro de un bucle vuelve a "
            "añadir perfiles pendientes duplicados. Comprueba "
            "que haya al menos dos perfiles cerrados, separados y compatibles. "
            "No revoluciones una elipse completa alrededor de un eje que la "
            "atraviesa: usa un semiperfil cerrado a un lado del eje, o un loft "
            "elíptico suave para el volumen orgánico."
        )
    if motor == "cadquery" and ("cutblind" in texto or "no solid" in texto):
        orientaciones.append(
            "cutBlind requiere un sólido en el contexto del Workplane. Para una "
            "incisión independiente construye primero un sólido cortador con "
            "extrude y réstalo al cuerpo con cut; no ejecutes cutBlind sobre un "
            "perfil aislado. Comprueba que el cortador atraviese la superficie."
        )
    if motor == "build123d" and ("cone" in texto or "unexpected keyword" in texto):
        orientaciones.append(
            "build123d 0.13.0: Cone(bottom_radius, top_radius, height); no "
            "radius_bottom ni radius_top. Cylinder(radius, height), Sphere(radius). "
            "Usa importaciones explícitas y modo algebraico."
        )
    if "trunc" in texto or contexto.get("fase_error") == "respuesta":
        orientaciones.append(
            "Entrega un programa completo que termine asignando resultado. Reduce "
            "comentarios redundantes y usa funciones y bucles para detalles repetidos; "
            "no recortes la geometría requerida."
        )
    if contexto.get("fase_error") == "tiempo":
        orientaciones.append(
            "El runtime dispone de 100 segundos. Evita cientos de booleanos sucesivos "
            "y redondeos globales; agrupa rasgos y reutiliza geometría."
        )
    return orientaciones


def orientaciones_detalle(descripcion: str) -> str:
    normalizado = unicodedata.normalize("NFKD", descripcion.lower())
    normalizado = "".join(letra for letra in normalizado if not unicodedata.combining(letra))
    if "cabeza clava" not in normalizado or "chavin" not in normalizado:
        return ""
    # Referencias de interpretación: Museo Larco y Ministerio de Cultura,
    # museos.cultura.pe/sites/default/files/publicaciones/pdf/expoicpp.pdf.
    return (
        "\n\nGuía de interpretación para cabeza clava Chavín, subordinada a las "
        "dimensiones y rasgos expresamente pedidos: construye una cabeza monolítica "
        "de volumen orgánico, con rostro humano-felínico, ojos abiertos con contornos "
        "y pupilas talladas, nariz prominente con fosas, labios y boca definidos, "
        "colmillos integrados y surcos faciales en relieve o bajorrelieve. Incluye "
        "una espiga posterior integrada para inserción, salvo que se solicite omitirla. "
        "Frente hacia -Y, ancho en X y altura en Z. Sitúa los rasgos en la superficie "
        "visible y haz que los relieves intersecten el cuerpo. No sustituyas la "
        "cabeza por una caja con agujeros ni añadas un pedestal si no se pidió. "
        "Si no hay escala, define dimensiones y profundidades proporcionadas en "
        "parámetros. Sin una referencia concreta se trata de una interpretación "
        "estilizada, no de una réplica arqueológica certificada."
    )


def construir_solicitud(descripcion: str, motor: str, historial: list[dict]) -> tuple[str, dict | None]:
    solicitud = f"Diseña este objeto CAD en milímetros:\n{descripcion}"
    solicitud += orientaciones_detalle(descripcion)
    if not historial:
        return solicitud, None
    anterior = historial[-1]
    huella = huella_codigo(anterior["codigo"])
    repetidos = sum(huella_codigo(paso["codigo"]) == huella for paso in historial)
    error_normalizado = firma_error(anterior["diagnostico"])
    errores_repetidos = sum(
        firma_error(paso["diagnostico"]) == error_normalizado
        and paso.get("fase_error") == anterior.get("fase_error") for paso in historial
    )
    secciones = [
        "\n\nCORRECCIÓN OBLIGATORIA. El intento anterior falló realmente en el runtime. "
        "Entrega de nuevo el programa Python completo. Conserva dimensiones, "
        "identidad y detalles del objetivo; corrige la causa, no solo nombres o comentarios.",
        "Historial acumulado de fallos (no vuelvas a introducir estos problemas):",
    ]
    for paso in historial:
        contexto = paso.get("contexto") or {}
        secciones.append(
            f"Intento {paso['numero']} · fase {paso.get('fase_error') or 'validación'}:\n"
            f"{paso['diagnostico']}"
        )
        if contexto.get("linea_error"):
            secciones.append(f"Línea {contexto['linea_error']} del programa generado.")
        if contexto.get("fragmento_codigo"):
            secciones.append(f"Contexto de código:\n{contexto['fragmento_codigo']}")
    contexto_anterior = anterior.get("contexto") or {}
    if contexto_anterior.get("traza_error"):
        secciones.append(f"Traza completa del último fallo:\n{contexto_anterior['traza_error']}")
    orientaciones = list(dict.fromkeys(
        orientacion for paso in historial for orientacion in orientaciones_error(
            motor, paso["diagnostico"], {**(paso.get("contexto") or {}), "fase_error": paso.get("fase_error")}
        )
    ))
    if orientaciones:
        secciones.append("Acciones técnicas para corregir:\n- " + "\n- ".join(orientaciones))
    if repetidos > 1 or errores_repetidos > 1:
        secciones.append(
            f"ATENCIÓN: el mismo programa fallido apareció {repetidos} veces y este "
            f"diagnóstico se repitió {errores_repetidos} veces. Cambia la estrategia "
            "constructiva de la operación que falla. Reenviar el mismo código o "
            "cambiar únicamente un radio sin comprobar la topología no resuelve el error."
        )
    # El programa es evidencia de entrada; la orden de reparación debe cerrar
    # el mensaje para que no parezca una plantilla que se debe copiar intacta.
    secciones.insert(1, f"Programa anterior COMPLETO, sin truncar:\n{anterior['codigo']}")
    secciones.append(
        "Antes de responder, localiza la operación señalada, sustituye su "
        "construcción por una alternativa válida para esta API y revisa los "
        "booleanos restantes. Devuelve el programa completo CORREGIDO, con los "
        "detalles originales. No reproduzcas la operación que ya falló."
    )
    solicitud += "\n".join(secciones)
    return solicitud, {
        "intentos_fuente": [paso["numero"] for paso in historial],
        "codigo_anterior_sha256": huella,
        "repeticiones_codigo": repetidos,
        "repeticiones_error": errores_repetidos,
        "codigo_anterior_completo": True,
        "orientaciones": orientaciones,
    }
