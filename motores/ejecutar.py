"""Ejecuta un programa CAD en un proceso y devuelve archivos nativos verificados."""

import base64
import contextlib
import io
import json
import os
import struct
import time
import traceback
from pathlib import Path


PREFIJO_SALIDA = "SALIDA_CAD:"
DIRECTORIO = Path("/tmp/ciel")
TESSELACION = {"desviacion_lineal_mm": 0.02, "desviacion_angular_rad": 0.05,
              "relativa": False, "perfil": "detalle-v2"}


def codificar_archivos(nombres: list[str]) -> dict[str, str]:
    archivos = {}
    for nombre in nombres:
        ruta = DIRECTORIO / nombre
        datos = ruta.read_bytes()
        if not datos or len(datos) > 20_000_000:
            raise ValueError(f"El archivo {nombre} está vacío o supera 20 MB")
        archivos[nombre] = base64.b64encode(datos).decode("ascii")
    return archivos


def validar_cadquery(objeto: object) -> tuple[object, float]:
    import cadquery as cq

    if isinstance(objeto, cq.Workplane) and len(objeto.vals()) != 1:
        raise ValueError(
            f"La Workplane contiene {len(objeto.vals())} objetos: fusiona los relieves "
            "con el cuerpo. No uses val() para descartar las piezas restantes."
        )
    forma = objeto.val() if isinstance(objeto, cq.Workplane) else objeto
    if not isinstance(forma, cq.Shape) or not forma.isValid():
        raise ValueError("CadQuery no devolvió una forma B-Rep válida")
    if len(forma.Solids()) != 1 or forma.Volume() <= 0:
        raise ValueError(f"Se exige un sólido; se obtuvieron {len(forma.Solids())}, volumen {forma.Volume():.6f} mm³")
    return forma, float(forma.Volume())


def exportar_stl_ocp(forma: object, ruta: Path) -> None:
    """Malla absoluta y angular fina; STEP conserva la geometría B-Rep exacta."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    from OCP.StlAPI import StlAPI_Writer

    BRepTools.Clean_s(forma.wrapped)
    mallador = BRepMesh_IncrementalMesh(
        forma.wrapped, TESSELACION["desviacion_lineal_mm"], False,
        TESSELACION["desviacion_angular_rad"], True,
    )
    mallador.Perform()
    escritor = StlAPI_Writer()
    escritor.ASCIIMode = False
    if not escritor.Write(forma.wrapped, str(ruta)):
        raise ValueError("No se pudo exportar la malla STL de detalle fino")


def exportar_cadquery(forma: object) -> None:
    import cadquery as cq

    cq.exporters.export(forma, str(DIRECTORIO / "pieza.step"), exportType="STEP")
    exportar_stl_ocp(forma, DIRECTORIO / "pieza.stl")


def validar_build123d(objeto: object) -> tuple[object, float]:
    from build123d import Shape

    forma = objeto.part if hasattr(objeto, "part") else objeto
    validez = forma.is_valid if isinstance(forma, Shape) else False
    if callable(validez):
        validez = validez()
    if not isinstance(forma, Shape) or not validez:
        raise ValueError("build123d no devolvió una forma B-Rep válida")
    if len(forma.solids()) != 1 or forma.volume <= 0:
        raise ValueError(f"Se exige un sólido; se obtuvieron {len(forma.solids())}, volumen {forma.volume:.6f} mm³")
    return forma, float(forma.volume)


def exportar_build123d(forma: object) -> None:
    from build123d import export_step

    export_step(forma, str(DIRECTORIO / "pieza.step"))
    exportar_stl_ocp(forma, DIRECTORIO / "pieza.stl")


def exportar_stl_freecad(forma: object, ruta: Path) -> None:
    import FreeCAD
    import Part
    import MeshPart

    malla = MeshPart.meshFromShape(
        Shape=forma, LinearDeflection=TESSELACION["desviacion_lineal_mm"],
        AngularDeflection=TESSELACION["desviacion_angular_rad"], Relative=False,
    )
    vertices, triangulos = malla.Topology
    with ruta.open("wb") as archivo:
        archivo.write(b"Agente Ciel FreeCAD".ljust(80, b"\0"))
        archivo.write(struct.pack("<I", len(triangulos)))
        for indices in triangulos:
            puntos = [vertices[indice] for indice in indices]
            vector_a = puntos[1].sub(puntos[0])
            vector_b = puntos[2].sub(puntos[0])
            normal = vector_a.cross(vector_b)
            longitud = normal.Length
            if longitud > 0:
                normal.normalize()
            else:
                normal = type(normal)(0, 0, 0)
            archivo.write(struct.pack("<3f", normal.x, normal.y, normal.z))
            for punto in puntos:
                archivo.write(struct.pack("<3f", punto.x, punto.y, punto.z))
            archivo.write(struct.pack("<H", 0))


def validar_freecad(objeto: object) -> tuple[object, float, object]:
    import FreeCAD as App
    import Part

    documento = getattr(objeto, "Document", None) or App.ActiveDocument or App.newDocument("PiezaCiel")
    if not hasattr(objeto, "Document"):
        figura = documento.addObject("Part::Feature", "Resultado")
        figura.Shape = objeto
        objeto = figura
    documento.recompute()
    forma = objeto.Shape if hasattr(objeto, "Shape") else objeto
    if not isinstance(forma, Part.Shape) or not forma.isValid():
        raise ValueError("FreeCAD no devolvió una forma B-Rep válida")
    if len(forma.Solids) != 1 or forma.Volume <= 0:
        raise ValueError(f"Se exige un sólido; se obtuvieron {len(forma.Solids)}, volumen {forma.Volume:.6f} mm³")
    return forma, float(forma.Volume), documento


def exportar_freecad(forma: object, documento: object) -> None:
    import FreeCAD as App

    forma.exportStep(str(DIRECTORIO / "pieza.step"))
    exportar_stl_freecad(forma, DIRECTORIO / "pieza.stl")
    ruta_documento = DIRECTORIO / "pieza.FCStd"
    documento.saveAs(str(ruta_documento))
    App.closeDocument(documento.Name)
    reabierto = App.openDocument(str(ruta_documento))
    recuperable = any(
        hasattr(elemento, "Shape")
        and not elemento.Shape.isNull()
        and elemento.Shape.isValid()
        and elemento.Shape.Volume > 0
        for elemento in reabierto.Objects
    )
    App.closeDocument(reabierto.Name)
    if not recuperable:
        raise ValueError("El documento FCStd no conservó un sólido válido al reabrirse")


def respuesta_error(fase: str, error: Exception, codigo: str = "", **estados: object) -> dict:
    marcos = traceback.extract_tb(error.__traceback__)
    generados = [marco for marco in marcos if marco.filename == "<codigo-generado>"]
    linea = generados[-1].lineno if generados else getattr(error, "lineno", None)
    fragmento = ""
    if linea and codigo:
        lineas = codigo.splitlines()
        fragmento = "\n".join(
            f"{'>>' if indice + 1 == linea else '  '} {indice + 1}: {lineas[indice]}"
            for indice in range(max(0, linea - 3), min(len(lineas), linea + 2))
        )
        fragmento = fragmento[:2500]
    resultado = {
        "correcto": False,
        "fase_error": fase,
        "diagnostico": f"{type(error).__name__}: {error}"[:3000],
        "sintaxis_valida": estados.get("sintaxis_valida"),
        "ejecucion_correcta": estados.get("ejecucion_correcta"),
        "cad_valido": estados.get("cad_valido"),
        "exportacion_valida": estados.get("exportacion_valida"),
        "linea_error": linea,
        "fragmento_codigo": fragmento,
        "traza_error": "".join(traceback.format_exception(type(error), error, error.__traceback__))[-6000:],
    }
    if linea:
        resultado["diagnostico"] += f"\nLínea {linea} del programa generado.\n{fragmento}"
    resultado["diagnostico"] = resultado["diagnostico"][:3000]
    return resultado


def ejecutar() -> dict:
    motor = os.environ.get("MOTOR_CAD")
    codigo = base64.b64decode(os.environ["CODIGO_BASE64"], validate=True).decode("utf-8")
    DIRECTORIO.mkdir(parents=True, exist_ok=True)
    espacio = {"__name__": "__main__"}
    try:
        programa = compile(codigo, "<codigo-generado>", "exec")
    except Exception as error:
        return respuesta_error("sintaxis", error, codigo=codigo, sintaxis_valida=False, ejecucion_correcta=False)
    inicio = time.monotonic()
    try:
        # La salida libre del script se captura para conservar un protocolo JSON estable.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            exec(programa, espacio)
    except Exception as error:
        return respuesta_error("ejecucion", error, codigo=codigo, sintaxis_valida=True, ejecucion_correcta=False)
    duracion_codigo = time.monotonic() - inicio
    try:
        objeto = espacio.get("resultado")
        if objeto is None:
            raise ValueError("El programa no asignó la pieza final a 'resultado'")
        if motor == "cadquery":
            forma, volumen = validar_cadquery(objeto)
            nombres = ["pieza.stl", "pieza.step"]
        elif motor == "build123d":
            forma, volumen = validar_build123d(objeto)
            nombres = ["pieza.stl", "pieza.step"]
        elif motor == "freecad":
            forma, volumen, documento = validar_freecad(objeto)
            nombres = ["pieza.stl", "pieza.step", "pieza.FCStd"]
        else:
            raise ValueError("Motor CAD desconocido")
    except Exception as error:
        return respuesta_error(
            "cad", error, codigo=codigo, sintaxis_valida=True, ejecucion_correcta=True, cad_valido=False
        )
    try:
        if motor == "cadquery":
            exportar_cadquery(forma)
        elif motor == "build123d":
            exportar_build123d(forma)
        else:
            exportar_freecad(forma, documento)
        archivos = codificar_archivos(nombres)
    except Exception as error:
        return respuesta_error(
            "exportacion", error, codigo=codigo, sintaxis_valida=True, ejecucion_correcta=True,
            cad_valido=True, exportacion_valida=False,
        )
    return {
        "correcto": True,
        "sintaxis_valida": True,
        "ejecucion_correcta": True,
        "cad_valido": True,
        "exportacion_valida": True,
        "duracion_codigo_segundos": duracion_codigo,
        "volumen_mm3": volumen,
        "archivos": archivos,
        "teselacion": TESSELACION,
    }


if __name__ == "__main__":
    try:
        respuesta = ejecutar()
    except Exception as error:
        respuesta = respuesta_error("protocolo", error)
    print(PREFIJO_SALIDA + json.dumps(respuesta, ensure_ascii=False), flush=True)
