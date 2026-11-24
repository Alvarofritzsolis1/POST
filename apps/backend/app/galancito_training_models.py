"""Private and organization-scoped simulation records."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .galancito_model_config import QWEN_2B
from .models import uid, utcnow

ACTIVE = ("queued", "practicing", "evaluating", "correcting", "paused")
TERMINAL = ("completed", "stopped", "error")
MODEL_ROLES = ("model", "judge", "corrector")


class TrainingRound(Base):
    __tablename__ = "galancito_training_rounds"
    __table_args__ = (
        Index("ix_training_rounds_org_date", "org_id", "created_at"),
        Index("uq_training_active_round", "org_id", unique=True,
              postgresql_where=text("state IN ('queued','practicing','evaluating','correcting','paused')"),
              sqlite_where=text("state IN ('queued','practicing','evaluating','correcting','paused')")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), default="queued")
    config: Mapped[dict] = mapped_column(JSON)
    dataset_hash: Mapped[str] = mapped_column(String(64))
    system_version: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(64))
    knowledge: Mapped[list] = mapped_column(JSON)
    aliases: Mapped[dict] = mapped_column(JSON)
    target: Mapped[int] = mapped_column(Integer)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(String(180))
    previous_id: Mapped[str | None] = mapped_column(String(36))

    def uses_legacy_local_model(self) -> bool:
        return any(spec.get("id") == "ollama" and spec.get("model") != QWEN_2B
                   for spec in (self.config.get(role, {}) for role in MODEL_ROLES))

    def stop_for_model_change(self, now: datetime) -> bool:
        if self.state not in ACTIVE or not self.uses_legacy_local_model():
            return False
        self.state = "stopped"
        self.reason = "Cambió el modelo. Repite la ronda con Qwen3.5 2B."
        self.finished_at = now
        self.lease = self.lease_until = None
        return True


class TrainingCase(Base):
    __tablename__ = "galancito_training_cases"
    __table_args__ = (Index("ix_training_cases_errors", "round_id", "passed", "position"),
                      Index("uq_training_case_id", "round_id", "case_id", unique=True),)

    round_id: Mapped[str] = mapped_column(
        ForeignKey("galancito_training_rounds.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(String(100))
    passed: Mapped[bool]
    result: Mapped[dict] = mapped_column(JSON)


class TrainingWorker(Base):
    __tablename__ = "galancito_training_worker"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resources: Mapped[dict] = mapped_column(JSON)
