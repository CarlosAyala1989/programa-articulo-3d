"""Tablas y columnas en español para los trabajos de generación."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from aplicacion.configuracion import URL_BASE_DATOS


def fecha_actual() -> datetime:
    return datetime.now(timezone.utc)


class BaseDeclarativa(DeclarativeBase):
    pass


class Ejecucion(BaseDeclarativa):
    __tablename__ = "ejecuciones"

    identificador: Mapped[str] = mapped_column(String(36), primary_key=True)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    motor: Mapped[str] = mapped_column(String(30), nullable=False)
    modelo: Mapped[str] = mapped_column(String(60), nullable=False)
    esfuerzo_razonamiento: Mapped[str | None] = mapped_column(String(10), nullable=True)
    estado: Mapped[str] = mapped_column(String(30), nullable=False, default="pendiente")
    mensaje: Mapped[str] = mapped_column(Text, nullable=False, default="En espera")
    numero_intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    campana_identificador: Mapped[str | None] = mapped_column(
        ForeignKey("campanas.identificador"), nullable=True
    )
    caso_identificador: Mapped[str | None] = mapped_column(
        ForeignKey("casos_diseno.identificador"), nullable=True
    )
    condicion_identificador: Mapped[str | None] = mapped_column(
        ForeignKey("condiciones_experimentales.identificador"), nullable=True
    )
    modo: Mapped[str] = mapped_column(String(20), nullable=False, default="closed-loop")
    repeticion: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    orden_campana: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maximo_intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    primer_exito_ejecucion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primer_exito_cad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primer_exito_exportacion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=fecha_actual, nullable=False
    )
    fecha_actualizacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=fecha_actual, onupdate=fecha_actual, nullable=False
    )
    intentos: Mapped[list["IntentoGeneracion"]] = relationship(
        back_populates="ejecucion", order_by="IntentoGeneracion.numero"
    )
    archivos: Mapped[list["ArchivoGenerado"]] = relationship(back_populates="ejecucion")


class IntentoGeneracion(BaseDeclarativa):
    __tablename__ = "intentos_generacion"

    identificador: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ejecucion_identificador: Mapped[str] = mapped_column(
        ForeignKey("ejecuciones.identificador", ondelete="CASCADE"), nullable=False
    )
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    estado: Mapped[str] = mapped_column(String(30), nullable=False)
    respuesta_modelo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    codigo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    diagnostico: Mapped[str] = mapped_column(Text, nullable=False, default="")
    modelo_informado: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    tokens_entrada: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_salida: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duracion_segundos: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    duracion_ia_segundos: Mapped[float | None] = mapped_column(Float, nullable=True)
    duracion_cad_segundos: Mapped[float | None] = mapped_column(Float, nullable=True)
    sintaxis_valida: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ejecucion_correcta: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cad_valido: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exportacion_valida: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fase_error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    solicitud_modelo: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    runtime_identificador: Mapped[str | None] = mapped_column(String(100), nullable=True)
    costo_estimado_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=fecha_actual, nullable=False
    )
    ejecucion: Mapped[Ejecucion] = relationship(back_populates="intentos")


class ArchivoGenerado(BaseDeclarativa):
    __tablename__ = "archivos_generados"

    identificador: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ejecucion_identificador: Mapped[str] = mapped_column(
        ForeignKey("ejecuciones.identificador", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    ruta: Mapped[str] = mapped_column(Text, nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    intento_identificador: Mapped[int | None] = mapped_column(
        ForeignKey("intentos_generacion.identificador"), nullable=True
    )
    ejecucion: Mapped[Ejecucion] = relationship(back_populates="archivos")


class VersionConjunto(BaseDeclarativa):
    __tablename__ = "versiones_conjunto"

    identificador: Mapped[str] = mapped_column(String(36), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(30), nullable=False)
    finalidad: Mapped[str] = mapped_column(String(20), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    huella_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=fecha_actual)
    fecha_congelacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    casos: Mapped[list["CasoDiseno"]] = relationship(back_populates="conjunto", order_by="CasoDiseno.codigo")
    __table_args__ = (UniqueConstraint("nombre", "version", name="uq_conjunto_nombre_version"),)


class CasoDiseno(BaseDeclarativa):
    __tablename__ = "casos_diseno"

    identificador: Mapped[str] = mapped_column(String(36), primary_key=True)
    conjunto_identificador: Mapped[str] = mapped_column(
        ForeignKey("versiones_conjunto.identificador"), nullable=False
    )
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    nivel: Mapped[str] = mapped_column(String(20), nullable=False)
    familia: Mapped[str] = mapped_column(String(80), nullable=False)
    fundamento: Mapped[str] = mapped_column(Text, nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    especificacion: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    referencia_ruta: Mapped[str | None] = mapped_column(Text, nullable=True)
    referencia_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    procedencia_referencia: Mapped[str | None] = mapped_column(Text, nullable=True)
    conjunto: Mapped[VersionConjunto] = relationship(back_populates="casos")
    __table_args__ = (UniqueConstraint("conjunto_identificador", "codigo", name="uq_caso_codigo"),)


class Campana(BaseDeclarativa):
    __tablename__ = "campanas"

    identificador: Mapped[str] = mapped_column(String(36), primary_key=True)
    conjunto_identificador: Mapped[str] = mapped_column(
        ForeignKey("versiones_conjunto.identificador"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    estado: Mapped[str] = mapped_column(String(30), nullable=False, default="borrador")
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="piloto")
    semilla: Mapped[int] = mapped_column(Integer, nullable=False)
    repeticiones: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    configuracion: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    total_ejecuciones: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    maximo_generaciones: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    presupuesto_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    gasto_estimado_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False, default="Borrador")
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=fecha_actual)
    fecha_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CondicionExperimental(BaseDeclarativa):
    __tablename__ = "condiciones_experimentales"

    identificador: Mapped[str] = mapped_column(String(36), primary_key=True)
    campana_identificador: Mapped[str] = mapped_column(
        ForeignKey("campanas.identificador"), nullable=False
    )
    modelo: Mapped[str] = mapped_column(String(100), nullable=False)
    motor: Mapped[str] = mapped_column(String(30), nullable=False)
    modo: Mapped[str] = mapped_column(String(20), nullable=False)
    configuracion: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    imagen_identificador: Mapped[str | None] = mapped_column(String(100), nullable=True)
    __table_args__ = (
        UniqueConstraint("campana_identificador", "modelo", "motor", "modo", name="uq_condicion"),
    )


class InformeTopologia(BaseDeclarativa):
    __tablename__ = "informes_topologia"

    identificador: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ejecucion_identificador: Mapped[str] = mapped_column(
        ForeignKey("ejecuciones.identificador"), nullable=False
    )
    rol_malla: Mapped[str] = mapped_column(String(30), nullable=False)
    sha256_malla: Mapped[str] = mapped_column(String(64), nullable=False)
    estado: Mapped[str] = mapped_column(String(30), nullable=False)
    watertight: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dang_el: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aristas_abiertas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aristas_no_manifold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    componentes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vertices: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caras: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orientacion_consistente: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    volumen_mm3: Mapped[float | None] = mapped_column(Float, nullable=True)
    diagnostico: Mapped[str] = mapped_column(Text, nullable=False, default="")
    perfil: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint("ejecucion_identificador", "rol_malla", name="uq_topologia_ejecucion_rol"),
    )


class ComparacionDigital(BaseDeclarativa):
    __tablename__ = "comparaciones_digitales"

    identificador: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ejecucion_identificador: Mapped[str] = mapped_column(
        ForeignKey("ejecuciones.identificador"), nullable=False
    )
    estado: Mapped[str] = mapped_column(String(30), nullable=False)
    referencia_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    iou_brep: Mapped[float | None] = mapped_column(Float, nullable=True)
    chamfer_digital_mm2: Mapped[float | None] = mapped_column(Float, nullable=True)
    diferencia_volumen_mm3: Mapped[float | None] = mapped_column(Float, nullable=True)
    diagnostico: Mapped[str] = mapped_column(Text, nullable=False, default="")
    perfil: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint("ejecucion_identificador", name="uq_comparacion_ejecucion"),
    )


motor_base_datos = create_engine(URL_BASE_DATOS, pool_pre_ping=True)
crear_sesion = sessionmaker(bind=motor_base_datos, expire_on_commit=False)


def crear_tablas() -> None:
    BaseDeclarativa.metadata.create_all(motor_base_datos)
    # Expansión compatible con los trabajos del piloto creados antes de las campañas.
    cambios = {
        "ejecuciones": [
            "esfuerzo_razonamiento VARCHAR(10)",
            "campana_identificador VARCHAR(36)",
            "caso_identificador VARCHAR(36)",
            "condicion_identificador VARCHAR(36)",
            "modo VARCHAR(20) NOT NULL DEFAULT 'closed-loop'",
            "repeticion INTEGER NOT NULL DEFAULT 1",
            "orden_campana INTEGER",
            "maximo_intentos INTEGER NOT NULL DEFAULT 5",
            "primer_exito_ejecucion INTEGER",
            "primer_exito_cad INTEGER",
            "primer_exito_exportacion INTEGER",
            "fecha_inicio TIMESTAMPTZ",
            "fecha_fin TIMESTAMPTZ",
        ],
        "intentos_generacion": [
            "duracion_ia_segundos DOUBLE PRECISION",
            "duracion_cad_segundos DOUBLE PRECISION",
            "sintaxis_valida BOOLEAN",
            "ejecucion_correcta BOOLEAN",
            "cad_valido BOOLEAN",
            "exportacion_valida BOOLEAN",
            "fase_error VARCHAR(40)",
            "solicitud_modelo JSON",
            "runtime_identificador VARCHAR(100)",
            "costo_estimado_usd DOUBLE PRECISION",
        ],
        "archivos_generados": [
            "rol VARCHAR(50)",
            "intento_identificador INTEGER",
        ],
    }
    with motor_base_datos.begin() as conexion:
        for tabla, columnas in cambios.items():
            for definicion in columnas:
                nombre, resto = definicion.split(" ", 1)
                conexion.exec_driver_sql(
                    f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {nombre} {resto}"
                )
        conexion.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ejecucion_campana_celda "
            "ON ejecuciones (campana_identificador, caso_identificador, "
            "condicion_identificador, repeticion) "
            "WHERE campana_identificador IS NOT NULL"
        )
