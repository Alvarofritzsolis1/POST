"""Additive platform tables. Historical records are never rewritten on import."""

from datetime import date, datetime
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid, utcnow


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    values: Mapped[dict] = mapped_column(JSON, default=dict)


class OrganizationSettings(Base):
    __tablename__ = "organization_settings"
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), primary_key=True
    )
    values: Mapped[dict] = mapped_column(JSON, default=dict)


class ContractorDetails(Base):
    __tablename__ = "contractor_details"
    contractor_id: Mapped[str] = mapped_column(
        ForeignKey("contractors.id"), primary_key=True
    )
    values: Mapped[dict] = mapped_column(JSON, default=dict)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(240))
    sha256: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class RetentionRate(Base):
    __tablename__ = "retention_rates"
    __table_args__ = (
        UniqueConstraint("org_id", "effective_from", name="uq_retention_org_date"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    daily_clp: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class DocumentReview(Base):
    __tablename__ = "worker_document_reviews"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "association_id",
            "subject",
            "period",
            "requirement",
            name="uq_document_review",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    association_id: Mapped[str] = mapped_column(
        ForeignKey("contractor_worksites.id"), index=True
    )
    subject: Mapped[str] = mapped_column(String(36), default="contractor")
    period: Mapped[str] = mapped_column(String(7), index=True)
    requirement: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    observation: Mapped[str] = mapped_column(String(1000), default="")
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True
    )
    reviewed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class WorkerTermination(Base):
    """An effective employment end, separate from a planned contract end."""
    __tablename__ = "worker_terminations"
    __table_args__ = (UniqueConstraint("contract_id", name="uq_termination_contract"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contract_register.id"), index=True)
    effective_date: Mapped[date] = mapped_column(Date)
    cause: Mapped[str] = mapped_column(String(80))
    ratification_mode: Mapped[str] = mapped_column(String(80), default="unrecorded")
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    signed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    review_state: Mapped[str] = mapped_column(String(24), default="missing")
    observation: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContractAttachment(Base):
    __tablename__ = "contract_attachments"
    __table_args__ = (UniqueConstraint("contract_id", "document_id", name="uq_contract_attachment"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contract_register.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    kind: Mapped[str] = mapped_column(String(24))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BackupCheckpoint(Base):
    __tablename__ = "backup_checkpoints"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SchemaVersion(Base):
    __tablename__ = "schema_versions"
    version: Mapped[str] = mapped_column(String(40), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentFinding(Base):
    """Explicit, reviewable payment finding; OCR alone never sets this status."""
    __tablename__ = "payment_findings"
    __table_args__ = (UniqueConstraint("control_id", name="uq_payment_finding_control"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    control_id: Mapped[str] = mapped_column(ForeignKey("contribution_controls.id"), index=True)
    state: Mapped[str] = mapped_column(String(24), default="unverified")
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    documented_amount: Mapped[int | None] = mapped_column(Numeric(14, 0), nullable=True)
    expected_amount: Mapped[int | None] = mapped_column(Numeric(14, 0), nullable=True)
    observation: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AttendanceRoster(Base):
    """Monthly inclusion decision; exclusions preserve earlier weekly evidence."""
    __tablename__ = "attendance_rosters"
    __table_args__ = (
        UniqueConstraint("association_id", "period", name="uq_attendance_roster_association_period"),
        Index("ix_attendance_roster_org_period", "org_id", "period"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))
    status: Mapped[str] = mapped_column(String(16), default="included")
    reason: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AttendanceWeek(Base):
    __tablename__ = "attendance_weeks"
    __table_args__ = (
        UniqueConstraint("association_id", "period", "week_number", name="uq_attendance_association_week"),
        Index("ix_attendance_week_org_period", "org_id", "period"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))
    week_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="draft")
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    entered_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_state: Mapped[str] = mapped_column(String(16), default="pending")
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AttendanceWorkerWeek(Base):
    __tablename__ = "attendance_worker_weeks"
    __table_args__ = (UniqueConstraint("week_id", "worker_assignment_id", name="uq_attendance_worker_week"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    week_id: Mapped[str] = mapped_column(ForeignKey("attendance_weeks.id"), index=True)
    worker_assignment_id: Mapped[str] = mapped_column(ForeignKey("worker_assignments.id"), index=True)
    signed_dates: Mapped[list] = mapped_column(JSON, default=list)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
