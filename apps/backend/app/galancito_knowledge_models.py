"""Additive learning data, separate from historical contractor documents."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid, utcnow


class Knowledge(Base):
    __tablename__ = "galancito_knowledge"
    __table_args__ = (Index("ix_galancito_knowledge_scope", "org_id", "status", "scope"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(80), default="General")
    kind: Mapped[str] = mapped_column(String(20), default="faq")
    scope: Mapped[str] = mapped_column(String(20), default="red_obras")
    content: Mapped[str] = mapped_column(Text)
    phrases: Mapped[list] = mapped_column(JSON, default=list)
    search_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __mapper_args__ = {"version_id_col": version}


class KnowledgeVersion(Base):
    __tablename__ = "galancito_knowledge_versions"
    __table_args__ = (UniqueConstraint("knowledge_id", "version", name="uq_galancito_knowledge_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("galancito_knowledge.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    responsible_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssistantRun(Base):
    """Metrics and feedback only. Never stores chat text, tokens or private prompts."""
    __tablename__ = "galancito_runs"
    __table_args__ = (Index("ix_galancito_runs_period", "org_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    intent: Mapped[str] = mapped_column(String(30), default="unknown")
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    timings: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
