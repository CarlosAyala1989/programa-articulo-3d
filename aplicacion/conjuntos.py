"""Importación, validación y congelación de conjuntos de casos CAD."""

import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from aplicacion.base_datos import CasoDiseno, VersionConjunto, crear_sesion, fecha_actual


NIVELES = {"basico", "intermedio", "complejo"}
RUTA_CONJUNTO_PRINCIPAL = Path(__file__).resolve().parent.parent / "datos" / "prompts_60_v1.json"


def validar_documento(datos: dict) -> dict:
    if not isinstance(datos, dict):
        raise ValueError("El conjunto debe ser un objeto JSON")
    nombre = str(datos.get("nombre", "")).strip()
    version = str(datos.get("version", "")).strip()
    finalidad = str(datos.get("finalidad", "")).strip()
    casos = datos.get("casos")
    if not nombre or len(nombre) > 120 or not version or len(version) > 30:
        raise ValueError("Nombre o versión de conjunto inválidos")
    if finalidad not in {"desarrollo", "evaluacion"}:
        raise ValueError("La finalidad debe ser desarrollo o evaluación")
    if not isinstance(casos, list) or not casos:
        raise ValueError("El conjunto debe contener casos")
    if finalidad == "evaluacion" and not 50 <= len(casos) <= 100:
        raise ValueError("Un conjunto de evaluación debe contener entre 50 y 100 casos")
    if len(casos) > 100:
        raise ValueError("El conjunto excede cien casos")
    codigos = set()
    descripciones = set()
    normalizados = []
    for indice, caso in enumerate(casos, 1):
        if not isinstance(caso, dict):
            raise ValueError(f"Caso {indice}: se esperaba un objeto")
        codigo = str(caso.get("codigo", "")).strip()
        nivel = str(caso.get("nivel", "")).strip().lower()
        familia = str(caso.get("familia", "")).strip()
        fundamento = str(caso.get("fundamento", "")).strip()
        descripcion = str(caso.get("descripcion", "")).strip()
        especificacion = caso.get("especificacion") or {"unidad": "mm", "solidos_esperados": 1}
        if not codigo or len(codigo) > 20 or codigo in codigos:
            raise ValueError(f"Caso {indice}: código vacío, repetido o demasiado largo")
        if nivel not in NIVELES:
            raise ValueError(f"Caso {codigo}: nivel de dificultad no reconocido")
        if not familia or len(familia) > 80 or not fundamento:
            raise ValueError(f"Caso {codigo}: faltan familia o fundamento")
        if not 12 <= len(descripcion) <= 4000 or descripcion in descripciones:
            raise ValueError(f"Caso {codigo}: descripción inválida o duplicada")
        if not isinstance(especificacion, dict) or especificacion.get("unidad") != "mm":
            raise ValueError(f"Caso {codigo}: la especificación debe declarar milímetros")
        if especificacion.get("solidos_esperados") != 1:
            raise ValueError(f"Caso {codigo}: este perfil exige un solo sólido")
        codigos.add(codigo)
        descripciones.add(descripcion)
        normalizados.append(
            {
                "codigo": codigo,
                "nivel": nivel,
                "familia": familia,
                "fundamento": fundamento,
                "descripcion": descripcion,
                "especificacion": especificacion,
            }
        )
    if nombre == "CAD-LLMIA-60" and version == "1.0.0":
        conteos = Counter(caso["nivel"] for caso in normalizados)
        if conteos != {"basico": 20, "intermedio": 20, "complejo": 20}:
            raise ValueError("El conjunto principal exige 20 casos por nivel")
    return {"nombre": nombre, "version": version, "finalidad": finalidad, "casos": normalizados}


def huella_documento(datos: dict) -> str:
    canonico = json.dumps(datos, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def importar_documento(datos: dict, congelar: bool = False) -> VersionConjunto:
    normalizado = validar_documento(datos)
    huella = huella_documento(normalizado)
    with crear_sesion() as sesion:
        existente = sesion.scalar(
            select(VersionConjunto).where(
                VersionConjunto.nombre == normalizado["nombre"],
                VersionConjunto.version == normalizado["version"],
            )
        )
        if existente is not None:
            if existente.huella_sha256 != huella:
                raise ValueError("La versión ya existe con contenido distinto; use otra versión")
            return existente
        conjunto = VersionConjunto(
            identificador=str(uuid4()),
            nombre=normalizado["nombre"],
            version=normalizado["version"],
            finalidad=normalizado["finalidad"],
            estado="congelado" if congelar else "borrador",
            huella_sha256=huella,
            fecha_congelacion=fecha_actual() if congelar else None,
        )
        sesion.add(conjunto)
        for caso in normalizado["casos"]:
            sesion.add(
                CasoDiseno(
                    identificador=str(uuid4()),
                    conjunto_identificador=conjunto.identificador,
                    **caso,
                )
            )
        sesion.commit()
        return conjunto


def importar_csv(texto: str, nombre: str, version: str, finalidad: str) -> VersionConjunto:
    lector = csv.DictReader(io.StringIO(texto))
    obligatorias = {"codigo", "nivel", "familia", "fundamento", "descripcion"}
    if not lector.fieldnames or not obligatorias.issubset(lector.fieldnames):
        raise ValueError("El CSV requiere código, nivel, familia, fundamento y descripción")
    casos = []
    for fila in lector:
        casos.append({clave: fila[clave] for clave in obligatorias})
    return importar_documento(
        {"nombre": nombre, "version": version, "finalidad": finalidad, "casos": casos}
    )


def cargar_conjunto_principal() -> VersionConjunto:
    datos = json.loads(RUTA_CONJUNTO_PRINCIPAL.read_text(encoding="utf-8"))
    return importar_documento(datos, congelar=True)


def resumen_conjunto(conjunto: VersionConjunto) -> dict:
    with crear_sesion() as sesion:
        casos = list(sesion.scalars(select(CasoDiseno).where(
            CasoDiseno.conjunto_identificador == conjunto.identificador
        )))
    conteos = Counter(caso.nivel for caso in casos)
    return {
        "identificador": conjunto.identificador,
        "nombre": conjunto.nombre,
        "version": conjunto.version,
        "finalidad": conjunto.finalidad,
        "estado": conjunto.estado,
        "huella_sha256": conjunto.huella_sha256,
        "total": len(casos),
        "por_nivel": dict(conteos),
    }
