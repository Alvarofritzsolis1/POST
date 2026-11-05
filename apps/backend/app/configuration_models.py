"""Additive, organization-scoped documentary configuration with immutable rules."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid, utcnow


class ConfigurationSettings(Base):
    __tablename__ = "configuration_settings"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    porteria_start_period: Mapped[str] = mapped_column(String(7))
    alert_days: Mapped[int] = mapped_column(Integer, default=7)
    repeated_periods: Mapped[int] = mapped_column(Integer, default=3)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ConfigurationDocumentType(Base):
    __tablename__ = "configuration_document_types"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_config_document_code"),
                      UniqueConstraint("org_id", "normalized_name", name="uq_config_document_name"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    normalized_name: Mapped[str] = mapped_column(String(180))
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="General")
    level: Mapped[str] = mapped_column(String(40), default="contractor")
    frequency: Mapped[str] = mapped_column(String(20), default="monthly")
    conditions: Mapped[str] = mapped_column(Text, default="")
    system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConfigurationRule(Base):
    __tablename__ = "configuration_rules"
    __table_args__ = (Index("ix_config_rule_org_type_period", "org_id", "document_type_id", "period_start", "period_end"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    document_type_id: Mapped[str] = mapped_column(ForeignKey("configuration_document_types.id"))
    scope: Mapped[str] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(3), nullable=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("worksites.id"), nullable=True)
    association_id: Mapped[str | None] = mapped_column(ForeignKey("contractor_worksites.id"), nullable=True)
    required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    frequency: Mapped[str] = mapped_column(String(20), default="monthly")
    activation_from_period: Mapped[str | None] = mapped_column(String(7), nullable=True)
    period_start: Mapped[str] = mapped_column(String(7))
    period_end: Mapped[str | None] = mapped_column(String(7), nullable=True)
    due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_month_offset: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GateMovement(Base):
    """Manually transcribed access evidence; never inferred from a missing file."""
    __tablename__ = "configuration_gate_movements"
    __table_args__ = (UniqueConstraint("association_id", "period", "worker_key", "movement_date", name="uq_gate_movement"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    worker_key: Mapped[str] = mapped_column(String(180))
    worker_name: Mapped[str] = mapped_column(String(180))
    worker_rut: Mapped[str | None] = mapped_column(String(12), nullable=True)
    movement_date: Mapped[str] = mapped_column(String(10))
    notes: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConfigurationObligationSnapshot(Base):
    """Historical obligation identity and rule provenance, independent of live reviews."""
    __tablename__ = "configuration_obligation_snapshots"
    __table_args__ = (UniqueConstraint("association_id", "period", name="uq_config_obligation_snapshot"),
                      Index("ix_config_snapshot_org_period", "org_id", "period"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
