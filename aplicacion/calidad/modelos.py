"""Contratos versionados del plan geométrico y las revisiones de IA."""

import re
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class ModeloEstricto(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DimensionPlan(ModeloEstricto):
    valor: float
    procedencia: Literal["specified", "inferred"]
    tolerancia: float | None = Field(default=None, ge=0)
    unidad: str = "mm"

    @model_validator(mode="after")
    def validar_unidad(self):
        if self.valor < 0:
            raise ValueError("Una dimensión no puede ser negativa")
        if self.unidad not in {"mm", "mm2", "mm3", "cm", "m", "deg", "rad", "unitless"}:
            raise ValueError("Unidad no admitida en GeometricPlan")
        return self


class CoordenadaPlan(ModeloEstricto):
    """Coordenada con signo; las cotas dimensionales permanecen no negativas por contrato."""

    valor: float
    procedencia: Literal["specified", "inferred"]
    tolerancia: float | None = Field(default=None, ge=0)
    unidad: str = "mm"

    @model_validator(mode="after")
    def validar_unidad(self):
        if self.unidad not in {"mm", "mm2", "mm3", "cm", "m", "deg", "rad", "unitless"}:
            raise ValueError("Unidad no admitida en GeometricPlan")
        return self


class VectorPlan(ModeloEstricto):
    x: CoordenadaPlan
    y: CoordenadaPlan
    z: CoordenadaPlan


class CajaPlan(ModeloEstricto):
    x: DimensionPlan
    y: DimensionPlan
    z: DimensionPlan


class SistemaCoordenadas(ModeloEstricto):
    origen: tuple[float, float, float] = (0.0, 0.0, 0.0)
    eje_x: tuple[float, float, float] = (1.0, 0.0, 0.0)
    eje_y: tuple[float, float, float] = (0.0, 1.0, 0.0)
    eje_z: tuple[float, float, float] = (0.0, 0.0, 1.0)
    orientacion_frente: Literal["+X", "-X", "+Y", "-Y", "+Z", "-Z"] = "+Y"


class FeaturePlan(ModeloEstricto):
    feature_id: str = Field(min_length=2, max_length=64)
    nombre: str = Field(min_length=1, max_length=120)
    tipo: str = Field(min_length=1, max_length=60)
    operacion: str = Field(default="", max_length=80)
    padre_id: str | None = Field(default=None, max_length=64)
    dimensiones: dict[str, DimensionPlan] = Field(default_factory=dict)
    posicion: VectorPlan | None = None
    eje: tuple[float, float, float] | None = None
    esencial: bool = True
    region: str | None = Field(default=None, max_length=120)
    dependencias: list[str] = Field(default_factory=list)
    relaciones: dict[str, str] = Field(default_factory=dict)
    perfil: list[VectorPlan] = Field(default_factory=list)
    trayectoria: list[VectorPlan] = Field(default_factory=list)
    espesor: DimensionPlan | None = None
    descripcion: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validar_id(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", self.feature_id):
            raise ValueError("feature_id debe ser un identificador estable en snake_case")
        return self


class CriterioPlan(ModeloEstricto):
    identificador: str = Field(min_length=2, max_length=64)
    feature_id: str | None = None
    medicion: Literal["bbox_x", "bbox_y", "bbox_z", "volumen", "area", "centroide",
                       "hole_count", "hole_diameter", "symmetry", "visual_presence"]
    esperado: float | tuple[float, float, float] | None = None
    tolerancia: float | None = Field(default=None, ge=0)
    unidad: str = "mm"
    esencial: bool = True


class PlanGeometrico(ModeloEstricto):
    version_esquema: Literal["ciel-geometric-plan-v1"] = "ciel-geometric-plan-v1"
    unidades: Literal["mm"] = "mm"
    clase_modelado: Literal["MECHANICAL_PRECISE", "ORGANIC_FREEFORM", "HYBRID"]
    categoria: str = Field(default="", max_length=120)
    sistema_coordenadas: SistemaCoordenadas = Field(default_factory=SistemaCoordenadas)
    dimensiones_globales: dict[str, DimensionPlan] = Field(default_factory=dict)
    bounding_box_esperada: CajaPlan | None = None
    volumen_principal: DimensionPlan | None = None
    centroide_esperado: VectorPlan | None = None
    features: list[FeaturePlan] = Field(min_length=1, max_length=100)
    dependencias: dict[str, list[str]] = Field(default_factory=dict)
    simetrias: list[dict] = Field(default_factory=list)
    restricciones: list[str] = Field(default_factory=list)
    operaciones: list[str] = Field(default_factory=list)
    trayectorias: list[list[VectorPlan]] = Field(default_factory=list)
    espesores: dict[str, DimensionPlan] = Field(default_factory=dict)
    agujeros: list[str] = Field(default_factory=list)
    cavidades: list[str] = Field(default_factory=list)
    relieves: list[str] = Field(default_factory=list)
    cortes: list[str] = Field(default_factory=list)
    regiones_secundarias: list[str] = Field(default_factory=list)
    tolerancias: dict[str, DimensionPlan] = Field(default_factory=dict)
    rasgos_esenciales: list[str] = Field(default_factory=list)
    criterios_verificables: list[CriterioPlan] = Field(default_factory=list)
    comentarios_inferidos: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validar_referencias(self):
        ids = [feature.feature_id for feature in self.features]
        if len(ids) != len(set(ids)):
            raise ValueError("feature_id debe ser único dentro del plan")
        conocidos = set(ids)
        for feature in self.features:
            if feature.padre_id and feature.padre_id not in conocidos:
                raise ValueError(f"Padre inexistente: {feature.padre_id}")
            if set(feature.dependencias) - conocidos:
                raise ValueError(f"Dependencia inexistente en {feature.feature_id}")
        for criterio in self.criterios_verificables:
            if criterio.feature_id and criterio.feature_id not in conocidos:
                raise ValueError(f"Criterio refiere feature_id inexistente: {criterio.feature_id}")
        return self


class IncidenciaRevision(ModeloEstricto):
    categoria: str = Field(min_length=1, max_length=80)
    linea: int | None = Field(default=None, ge=1)
    feature_id: str | None = None
    descripcion: str = Field(min_length=1, max_length=1200)
    reparacion: str = Field(default="", max_length=1200)
    severidad: Literal["none", "low", "medium", "high", "critical"] = "low"


class RevisionCodigo(ModeloEstricto):
    accepted: bool
    severity: Literal["none", "low", "medium", "high", "critical"]
    issues: list[IncidenciaRevision] = Field(default_factory=list)


class ErrorGeometrico(ModeloEstricto):
    feature_id: str | None = None
    esperado: str | float | None = None
    observado: str | float | None = None
    severidad: Literal["low", "medium", "high", "critical"]
    causa_probable: str
    estrategia_reparacion: str


class CriticaGeometrica(ModeloEstricto):
    accepted: bool
    errores: list[ErrorGeometrico] = Field(
        default_factory=list, validation_alias=AliasChoices("errores", "errors")
    )
    preservar: list[str] = Field(default_factory=list)
    prioridad_reparacion: list[str] = Field(default_factory=list)
    observacion: str = ""


class RevisionVisual(ModeloEstricto):
    accepted: bool
    puntuacion_silueta: float = Field(ge=0, le=1)
    puntuacion_proporciones: float = Field(ge=0, le=1)
    puntuacion_features: float = Field(ge=0, le=1)
    errores: list[ErrorGeometrico] = Field(
        default_factory=list, validation_alias=AliasChoices("errores", "errors")
    )
    observacion: str = ""
