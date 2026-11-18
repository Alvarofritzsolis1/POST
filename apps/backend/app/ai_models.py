"""Administrator-managed AI credentials, routing and usage (no prompts stored)."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid, utcnow


class AIConnection(Base):
    __tablename__ = "ai_connections"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_ai_connection_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(160))
    encrypted_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_status: Mapped[str] = mapped_column(String(20), default="not_tested")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    price_input_per_million: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    price_output_per_million: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIOrchestration(Base):
    __tablename__ = "ai_orchestration"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    monthly_token_limit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    task_routes: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_org_date", "org_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("ai_connections.id"), index=True)
    task: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(14, 8), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
