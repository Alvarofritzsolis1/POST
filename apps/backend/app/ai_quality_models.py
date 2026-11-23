"""Human-reviewed, evidence-linked AI response ratings. No chat content is persisted."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import uid, utcnow


class AIResponseReview(Base):
    __tablename__ = "ai_response_reviews"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_ai_response_review_run"),
        UniqueConstraint("org_id", "channel", "evidence_kind", "evidence_id",
                         name="uq_ai_review_real_evidence"),
        Index("ix_ai_response_reviews_org_channel", "org_id", "channel", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("galancito_runs.id"), nullable=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ratings: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AIRealPracticeTrial(Base):
    """Real Qwen execution and human outcome; no private conversation text stored."""
    __tablename__ = "ai_real_practice_trials"
    __table_args__ = (
        Index("ix_ai_real_trial_org_channel", "org_id", "channel", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("ai_response_reviews.id"), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    criterion: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    variant: Mapped[str] = mapped_column(String(36), nullable=False, default="focused")
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="reconstructed")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="practice")
    verification_nonce: Mapped[str] = mapped_column(String(36), nullable=False, default=uid)
    outcome: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
