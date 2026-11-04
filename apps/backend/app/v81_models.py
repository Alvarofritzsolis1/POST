"""Additive v8.1 calendar, responsibilities, and immutable monthly assessments.

Old attendance_weeks/attendance_worker_weeks are retained untouched.
"""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid, utcnow


class CalendarWeek(Base):
    __tablename__ = "attendance_calendar_weeks"
    __table_args__ = (
        UniqueConstraint("association_id", "period", "week_number", name="uq_calendar_week_association_period"),
        Index("ix_calendar_week_org_period", "org_id", "period"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    migrated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    entered_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_on_time: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class CalendarEntry(Base):
    __tablename__ = "attendance_calendar_entries"
    __table_args__ = (UniqueConstraint("week_id", "worker_assignment_id", name="uq_calendar_entry_person_week"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    week_id: Mapped[str] = mapped_column(ForeignKey("attendance_calendar_weeks.id"), nullable=False, index=True)
    worker_assignment_id: Mapped[str] = mapped_column(ForeignKey("worker_assignments.id"), nullable=False, index=True)
    signed_dates: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CalendarDuty(Base):
    __tablename__ = "attendance_calendar_duties"
    __table_args__ = (
        UniqueConstraint("association_id", "period", "week_number", name="uq_calendar_duty_week"),
        Index("ix_calendar_duty_org_period_user", "org_id", "period", "assigned_to"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    association_id: Mapped[str] = mapped_column(ForeignKey("contractor_worksites.id"), nullable=False, index=True)
    worksite_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    assigned_to: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exempt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exemption_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MonthlyAssessment(Base):
    __tablename__ = "attendance_monthly_assessments"
    __table_args__ = (
        UniqueConstraint("org_id", "period", "user_id", "revision", name="uq_month_assessment_version"),
        Index("ix_month_assessment_org_period", "org_id", "period"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    grade_value: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    observations: Mapped[str] = mapped_column(Text, default="", nullable=False)
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
