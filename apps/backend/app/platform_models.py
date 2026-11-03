"""Additive v0.5 tables. No historical column or table is rewritten."""

from datetime import date, datetime
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
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
