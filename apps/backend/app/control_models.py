"""GALANT manual operational controls. Additive schema; never alters OCR tables."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import uid, utcnow


class ContributionControl(Base):
    __tablename__ = "contribution_controls"
    __table_args__ = (UniqueConstraint("association_id", "period", "subject_key", name="uq_contrib_association_period_subject"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    subject_key: Mapped[str] = mapped_column(String(40), nullable=False)  # worker assignment ID or "independent"
    worker_assignment_id: Mapped[str | None] = mapped_column(ForeignKey("worker_assignments.id"), nullable=True)
    attendance_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    daily_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("4950.00"), nullable=False)
    justification: Mapped[str] = mapped_column(Text, default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    review_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    retention_status: Mapped[str] = mapped_column(String(24), default="none", nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MonthlyActivity(Base):
    __tablename__ = "monthly_activity"
    __table_args__ = (UniqueConstraint("association_id", "period", name="uq_activity_association_period"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="unconfirmed", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    changed_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ContractRegister(Base):
    __tablename__ = "contract_register"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), nullable=False, index=True)
    worker_assignment_id: Mapped[str | None] = mapped_column(ForeignKey("worker_assignments.id"), nullable=True)
    contract_type: Mapped[str] = mapped_column(String(24), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProcessCalendar(Base):
    __tablename__ = "process_calendar"
    __table_args__ = (UniqueConstraint("worksite_id", "period", "kind", name="uq_calendar_worksite_kind_month"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    worksite_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    alert_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WorkTask(Base):
    __tablename__ = "work_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    worksite_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"), nullable=False, index=True)
    association_id: Mapped[str | None] = mapped_column(ForeignKey("contractor_worksites.id"), nullable=True, index=True)
    period: Mapped[str | None] = mapped_column(String(7), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    priority: Mapped[str] = mapped_column(String(12), default="normal", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class OffboardingCase(Base):
    __tablename__ = "offboarding_cases"
    __table_args__ = (UniqueConstraint("association_id", "status", name="uq_offboarding_status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(32), default="requested", nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="open", nullable=False)
    letter_decision: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    letter_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    changed_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RequirementApplicability(Base):
    __tablename__ = "requirement_applicability"
    __table_args__ = (UniqueConstraint("association_id", "period", "kind", name="uq_applicability_association_period_kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    applicable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    justification: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
