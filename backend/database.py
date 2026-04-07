"""
database.py — Corte Perfecto
Definición de modelos SQLAlchemy y creación de tablas para SQLite.
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    DateTime, ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import enum
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./corte_perfecto.db")

# ── Engine & Session ────────────────────────────────────────────────────────
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # necesario para SQLite + async
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── Enums ───────────────────────────────────────────────────────────────────
class ServicioEnum(str, enum.Enum):
    corte = "Corte"
    tinte = "Tinte"
    peinado = "Peinado"


class EstadoCitaEnum(str, enum.Enum):
    pendiente = "pendiente"
    confirmada = "confirmada"
    cancelada = "cancelada"


# ── Modelos ─────────────────────────────────────────────────────────────────

class Cliente(Base):
    """Tabla de clientes registrados."""
    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=True)
    telefono = Column(String(20), nullable=True)
    creado_en = Column(DateTime, default=datetime.utcnow)

    citas = relationship("Cita", back_populates="cliente", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Cliente id={self.id} nombre={self.nombre!r}>"


class Servicio(Base):
    """Catálogo de servicios ofrecidos."""
    __tablename__ = "servicios"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(50), unique=True, nullable=False)
    descripcion = Column(String(255), nullable=True)
    precio = Column(Float, nullable=False)
    duracion_minutos = Column(Integer, default=30)

    citas = relationship("Cita", back_populates="servicio")

    def __repr__(self):
        return f"<Servicio {self.nombre!r} {self.precio}€>"


class Cita(Base):
    """Tabla de citas / reservas."""
    __tablename__ = "citas"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre_cliente = Column(String(100), nullable=False)   # nombre capturado por chatbot
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    servicio_id = Column(Integer, ForeignKey("servicios.id"), nullable=True)
    servicio_nombre = Column(String(50), nullable=False)   # copia desnormalizada para rapidez
    fecha = Column(String(10), nullable=False)             # YYYY-MM-DD
    hora = Column(String(5), nullable=False)               # HH:MM
    estado = Column(SAEnum(EstadoCitaEnum), default=EstadoCitaEnum.pendiente)
    notas = Column(String(500), nullable=True)
    creada_en = Column(DateTime, default=datetime.utcnow)

    cliente = relationship("Cliente", back_populates="citas")
    servicio = relationship("Servicio", back_populates="citas")

    def __repr__(self):
        return f"<Cita {self.nombre_cliente} | {self.servicio_nombre} | {self.fecha} {self.hora}>"


# ── Seed inicial ─────────────────────────────────────────────────────────────

def seed_servicios(db):
    """Inserta los servicios base si la tabla está vacía."""
    if db.query(Servicio).count() == 0:
        servicios = [
            Servicio(nombre="Corte", descripcion="Corte de cabello clásico o moderno", precio=20.0, duracion_minutos=30),
            Servicio(nombre="Tinte", descripcion="Tinte profesional con productos de alta calidad", precio=40.0, duracion_minutos=60),
            Servicio(nombre="Peinado", descripcion="Peinado para cualquier ocasión", precio=15.0, duracion_minutos=20),
        ]
        db.add_all(servicios)
        db.commit()


def init_db():
    """Crea todas las tablas y siembra datos iniciales."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_servicios(db)
    finally:
        db.close()


# ── Dependency para FastAPI ──────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
