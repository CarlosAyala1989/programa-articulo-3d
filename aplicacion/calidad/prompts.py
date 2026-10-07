"""Prompts independientes para planificar, modelar, revisar y reparar."""

from aplicacion.calidad.modelos import CoordenadaPlan, DimensionPlan, PlanGeometrico


SEGURIDAD_COMUN = """No ejecutes herramientas, no accedas a archivos ni a referencias del benchmark.
Las cotas explícitas de la descripción son autoritativas. El código CAD generado se valida en
una política AST y se ejecuta aislado. Nunca declares medidas observadas sin evidencia numérica."""

PROMPT_PLANIFICADOR = """Eres un arquitecto geométrico CAD. No generes código Python.
Traduce la descripción a un GeometricPlan verificable conforme al esquema JSON suministrado.
Clasifica como MECHANICAL_PRECISE, ORGANIC_FREEFORM o HYBRID. Incluye sistema de coordenadas,
frente, dimensiones globales, componentes con feature_id estable, operaciones, perfiles,
trayectorias, relaciones padre/hijo, simetrías, restricciones y criterios verificables.
Cada medida es un objeto con valor, unidad mm y procedencia specified o inferred. Usa specified
solo para cotas presentes literalmente en la descripción; no cambies ni redondees esas cotas.
Si infieres una medida, marca inferred y explica brevemente la inferencia. Las coordenadas
derivadas por centrado, simetría, origen o alineación —incluido el valor cero— son inferred salvo
que la descripción indique literalmente esa coordenada. No marques como specified medidas o
posiciones calculadas a partir de otras cotas. No inventes una referencia ni una exactitud
arqueológica. Devuelve únicamente JSON válido, sin Markdown."""

ESTRATEGIAS = {
    "MECHANICAL_PRECISE": "cotas exactas, sketches acotados, extrusión, revolución, agujeros, patrones y operaciones simples; evita splines y lofts si no los pide la geometría.",
    "ORGANIC_FREEFORM": "volumen primario, masas secundarias, transiciones y detalles; usa secciones asimétricas, curvas spline/BSpline, lofts y sweeps donde corresponda; integra relieves con intersección y abre cortes a la superficie; evita primitivas pegadas como sustituto.",
    "HYBRID": "separa regiones mecánicas de cotas exactas y regiones libres; usa una estrategia paramétrica para cada dominio y declara cómo se relacionan, sin sacrificar las cotas.",
}

PROMPT_REVISOR_CODIGO = """Eres un revisor senior de Python CAD. No ejecutes ni reescribas el programa.
Revisa errores de API para el motor/versión proporcionados, imports, código muerto, redundancia,
excepciones ocultas, geometría degenerada, operaciones CAD frágiles, frames incorrectos,
seguridad, coste de cómputo y cualquier intento de evadir validadores. No juzgues semejanza visual.
No cambies cotas. Devuelve solo JSON con accepted, severity y issues; una severidad critical/high
debe impedir la ejecución. Si no hay defectos, issues es una lista vacía."""

PROMPT_CRITICO = """Eres un inspector geométrico CAD separado del generador. No generes código.
Evalúa el GeometricPlan frente a evidencia determinista y la revisión visual. Distingue dimensiones,
topología, estructura, features, superficie, silueta y comparación con referencia. Las métricas
faltantes conservan estado not_available o not_applicable: no las conviertas en cero. No declares
medidas basándote en imágenes. Por cada defecto indica feature_id cuando sea posible, esperado,
observado, severidad, causa probable y estrategia de reparación. Incluye preservar con las features
correctas. Devuelve JSON válido, sin puntuación global inventada."""

PROMPT_REVISOR_VISUAL = """Eres inspector visual de geometría CAD. Compara descripción y plan con las
vistas FRONT, BACK, LEFT, RIGHT, TOP, BOTTOM, ISO_A e ISO_B. Evalúa silueta, proporción, rasgos,
orientación y coherencia entre vistas; identifica features faltantes, deformadas o mal ubicadas.
No evalúes Python, no inventes cotas ni afirmes exactitud dimensional a partir de imágenes.
No aceptes solo porque se parece en general. Usa feature_id cuando sea posible. Devuelve JSON."""

PROMPT_REPARADOR = """Eres especialista en reparación CAD paramétrica. Devuelve el programa Python
completo corregido para el mismo motor. Conserva el GeometricPlan y las cotas explícitas. Preserva
las features identificadas como correctas; corrige primero la causa raíz de mayor prioridad.
No simplifiques la pieza para que compile ni repitas estrategias que ya fallaron. Si el problema es
local, evita reconstruir el cuerpo entero. Atiende las incidencias del revisor de código, métricas,
crítica, features a preservar e historial. Devuelve exclusivamente Python completo."""


def instruccion_modeler(clase: str, contrato_motor: str, recipes: str = "") -> str:
    estrategia = ESTRATEGIAS[clase]
    return (
        "Eres un ingeniero senior de CAD paramétrico. Recibes descripción original y un "
        "GeometricPlan ya validado. El plan es la autoridad: conserva cotas specified, relaciones "
        "y todas las features esenciales. No reinterpretes ni suprimas features. Sigue el contrato "
        "del motor CAD, la política AST y las recipes seleccionadas. Construye de lo general a lo "
        f"particular: {estrategia}\nLa pieza final debe asignarse a resultado. Devuelve Python "
        "completo únicamente. No escribas archivos ni uses red, procesos o GUI.\n" + SEGURIDAD_COMUN
        + "\n\nCONTRATO DEL MOTOR\n" + contrato_motor
        + "\n\nRECIPES PERTINENTES\n" + (recipes or "Sin recipe especializada; elige la operación CAD más directa.")
    )


def catalogo_operadores() -> dict[str, str]:
    return {"planificador": PROMPT_PLANIFICADOR, "revisor_codigo": PROMPT_REVISOR_CODIGO,
            "critico": PROMPT_CRITICO, "revisor_visual": PROMPT_REVISOR_VISUAL,
            "reparador": PROMPT_REPARADOR}


def validar_plan_para_descripcion(descripcion: str, plan: PlanGeometrico) -> None:
    """Evita que el plan etiquete como explícita una cota ausente o alterada."""
    import re

    valores = {float(valor.replace(",", ".")) for valor in re.findall(
        r"(?<![\w.])[+-]?\d+(?:[.,]\d+)?", descripcion
    )}
    # Las descripciones del estudio suelen expresar cantidades en palabras (p. ej.,
    # «cuatro agujeros»). Reconocerlas evita que una cota explícita se rechace como inventada.
    palabras = re.findall(r"[a-záéíóúüñ]+", descripcion.casefold())
    acentos = str.maketrans("áéíóúü", "aeiouu")
    palabras = [palabra.translate(acentos) for palabra in palabras]
    unidades = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3,
                "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
                "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
                "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
                "dieciocho": 18, "diecinueve": 19, "veinte": 20,
                "veintiuno": 21, "veintiun": 21, "veintidos": 22, "veintitres": 23,
                "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
                "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
                "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
                "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100,
                "ciento": 100, "mil": 1000}
    valores.update(float(unidades[p]) for p in palabras if p in unidades)
    for i in range(len(palabras) - 2):
        decena, conector, unidad = palabras[i:i + 3]
        if decena in {"treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"} \
                and conector == "y" and unidad in unidades and 0 < unidades[unidad] < 10:
            valores.add(float(unidades[decena] + unidades[unidad]))
    for i in range(len(palabras) - 1):
        centena, resto = palabras[i:i + 2]
        if centena == "ciento" and resto in unidades and 0 <= unidades[resto] < 100:
            valores.add(float(100 + unidades[resto]))

    def validar_valores(objeto):
        if isinstance(objeto, (DimensionPlan, CoordenadaPlan)):
            if objeto.procedencia == "specified" and objeto.valor not in valores:
                raise ValueError("GeometricPlan alteró o inventó una cota marcada specified")
        elif isinstance(objeto, PlanGeometrico):
            for valor in objeto.dimensiones_globales.values():
                validar_valores(valor)
            if objeto.bounding_box_esperada:
                validar_valores(objeto.bounding_box_esperada)
            if objeto.volumen_principal:
                validar_valores(objeto.volumen_principal)
            if objeto.centroide_esperado:
                validar_valores(objeto.centroide_esperado)
            for feature in objeto.features:
                for valor in feature.dimensiones.values():
                    validar_valores(valor)
                if feature.posicion:
                    validar_valores(feature.posicion)
                if feature.espesor:
                    validar_valores(feature.espesor)
                for punto in feature.perfil + feature.trayectoria:
                    validar_valores(punto)
            for valor in objeto.espesores.values():
                validar_valores(valor)
            for valor in objeto.tolerancias.values():
                validar_valores(valor)
            for criterio in objeto.criterios_verificables:
                if isinstance(criterio.esperado, (int, float)) and criterio.esencial:
                    if criterio.esperado not in valores:
                        raise ValueError("GeometricPlan alteró o inventó un criterio dimensional explícito")
        elif hasattr(type(objeto), "model_fields"):
            for nombre in type(objeto).model_fields:
                validar_valores(getattr(objeto, nombre))
        elif isinstance(objeto, dict):
            for valor in objeto.values():
                validar_valores(valor)
        elif isinstance(objeto, (list, tuple)):
            for valor in objeto:
                validar_valores(valor)

    from aplicacion.calidad.modelos import DimensionPlan
    validar_valores(plan)
