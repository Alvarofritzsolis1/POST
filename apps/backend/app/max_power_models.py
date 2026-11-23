"""Durable, organization-scoped MAX POWER state; no conversation text stored."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid, utcnow

class MaxPowerState(Base):
    __tablename__ = "ai_max_power_states"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    on_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    experiments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    examined_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lab_gains: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    regressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_round_id: Mapped[str | None] = mapped_column(String(36))
    last_round_id: Mapped[str | None] = mapped_column(String(36))
    last_evidence_hash: Mapped[str | None] = mapped_column(String(64))
    last_status: Mapped[str] = mapped_column(String(40), nullable=False, default="idle")
    last_reason: Mapped[str] = mapped_column(String(280), nullable=False, default="No se ha iniciado MAX POWER")
    latest_result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    initial_quality: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class MaxPowerEvent(Base):
    __tablename__ = "ai_max_power_events"
    __table_args__ = (Index("ix_ai_max_power_events_org_time", "org_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(String(280), nullable=False)
    round_id: Mapped[str | None] = mapped_column(String(36))
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class MaxPowerMessengerTrial(Base):
    """Audited Messenger replay without copied messages or personal information.

    A human review identifies a defect; automatic objective checks identify
    narrow improvements, not general-purpose learning or production success.
    """
    __tablename__ = "ai_max_power_messenger_trials"
    __table_args__ = (
        UniqueConstraint("org_id", "review_id", "criterion", "variant",
                         name="uq_max_power_messenger_review_variant"),
        UniqueConstraint("org_id", "source_run_id", "criterion", "variant",
                         name="uq_max_power_messenger_auto_run_variant"),
        Index("ix_max_power_messenger_queue", "status", "next_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    review_id: Mapped[str | None] = mapped_column(ForeignKey("ai_response_reviews.id"), nullable=True)
    source_run_id: Mapped[str | None] = mapped_column(ForeignKey("galancito_runs.id"), nullable=True)
    criterion: Mapped[str] = mapped_column(String(30), nullable=False)
    variant: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str | None] = mapped_column(String(280))
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
