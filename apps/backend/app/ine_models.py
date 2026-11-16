"""INE: transcripción inmutable del Excel y registros editables independientes."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import uid, utcnow


class IneOriginal(Base):
    """Archivo original exacto, no se reescribe ni se actualiza."""
    __tablename__ = "ine_originals"
    __table_args__ = (UniqueConstraint("org_id", "sha256", name="uq_ine_original_sha"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IneSheet(Base):
    """Lectura fiel de todas las hojas y celdas; no editable."""
    __tablename__ = "ine_sheets"
    __table_args__ = (UniqueConstraint("original_id", "position", name="uq_ine_sheet_pos"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    original_id: Mapped[str] = mapped_column(ForeignKey("ine_originals.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(120), nullable=False)
    cells: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class IneRow(Base):
    """Fila editable en la plataforma; nunca cambia la hoja original."""
    __tablename__ = "ine_rows"
    __table_args__ = (UniqueConstraint("org_id", "period", "source_sheet", "source_row", name="uq_ine_source_row"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("worksites.id"), nullable=True, index=True)
    site_name: Mapped[str] = mapped_column(String(200), nullable=False)
    supervisor: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    cct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cesp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ind: Mapped[int | None] = mapped_column(Integer, nullable=True)
    th: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_sheet: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    source_row: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    original_values: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IneChange(Base):
    """Auditoría append-only, visible únicamente para administradores."""
    __tablename__ = "ine_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    row_id: Mapped[str] = mapped_column(ForeignKey("ine_rows.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(180), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    previous: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    current: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
