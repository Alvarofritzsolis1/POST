"""Persistent operational records, independent of the OCR document queue.

Existing tables are untouched. ``app.cli init-db`` creates these additive tables
for an existing installation as well as for a fresh database.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import uid, utcnow


class Worksite(Base):
    __tablename__ = "worksites"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_worksite_org_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditPeriod(Base):
    __tablename__ = "audit_periods"
    __table_args__ = (UniqueConstraint("worksite_id", "period", name="uq_audit_period_site_month"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    worksite_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Contractor(Base):
    __tablename__ = "contractors"
    __table_args__ = (UniqueConstraint("org_id", "rut", name="uq_contractor_org_rut"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    rut: Mapped[str | None] = mapped_column(String(12), nullable=True)
    nature: Mapped[str] = mapped_column(String(20), default="unclassified", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ContractorWorksite(Base):
    __tablename__ = "contractor_worksites"
    __table_args__ = (UniqueConstraint("worksite_id", "contractor_id", name="uq_contractor_worksite"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    worksite_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"), nullable=False, index=True)
    contractor_id: Mapped[str] = mapped_column(ForeignKey("contractors.id"), nullable=False, index=True)
    historical_code: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), default="unclassified", nullable=False)
    contract_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    imported_statuses: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (UniqueConstraint("org_id", "rut", name="uq_worker_org_rut"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    rut: Mapped[str | None] = mapped_column(String(12), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WorkerAssignment(Base):
    __tablename__ = "worker_assignments"
    __table_args__ = (UniqueConstraint("worksite_id", "contractor_id", "worker_id", name="uq_worker_assignment"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    worksite_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"), nullable=False, index=True)
    contractor_id: Mapped[str] = mapped_column(ForeignKey("contractors.id"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    imported_statuses: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class OpsChange(Base):
    __tablename__ = "ops_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    changes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MonthlyDocument(Base):
    """Documento de un contratista/obra para un mes de competencia.

    El archivo OCR permanece en documents; la aprobación documental es humana
    y no altera el resultado del motor OCR ni su evidencia original.
    """
    __tablename__ = "monthly_documents"
    __table_args__ = (
        UniqueConstraint("association_id", "period", "kind", "document_id",
                         name="uq_monthly_document_link"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), index=True, nullable=False)
    contractor_id: Mapped[str] = mapped_column(ForeignKey("contractors.id"), index=True, nullable=False)
    period: Mapped[str] = mapped_column(String(7), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True, index=True)
    review_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
