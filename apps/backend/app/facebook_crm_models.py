"""Facebook inbox: org-scoped leads and durable Messenger message delivery."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid, utcnow


class FacebookLead(Base):
    __tablename__ = "facebook_leads"
    __table_args__ = (
        UniqueConstraint("org_id", "page_id", "psid", name="uq_facebook_lead_page_psid"),
        Index("ix_facebook_lead_inbox", "org_id", "status", "last_inbound_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    page_id: Mapped[str] = mapped_column(String(40))
    psid: Mapped[str] = mapped_column(String(90))
    display_name: Mapped[str] = mapped_column(String(160), default="Interesado de Facebook")
    company: Mapped[str] = mapped_column(String(180), default="")
    specialty: Mapped[str] = mapped_column(String(100), default="")
    workers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability: Mapped[str] = mapped_column(String(120), default="")
    experience: Mapped[str] = mapped_column(Text, default="")
    documents_state: Mapped[str] = mapped_column(String(20), default="unverified")
    status: Mapped[str] = mapped_column(String(24), default="new")
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey("network_requirements.id"), nullable=True)
    unread: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FacebookChatMessage(Base):
    __tablename__ = "facebook_chat_messages"
    __table_args__ = (
        UniqueConstraint("page_id", "remote_id", name="uq_facebook_chat_remote"),
        Index("ix_facebook_chat_queue", "direction", "state", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("facebook_leads.id"), index=True)
    page_id: Mapped[str] = mapped_column(String(40))
    remote_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    direction: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(20), default="received")
    body: Mapped[str] = mapped_column(Text, default="")
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    operator_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FacebookTradeGuide(Base):
    """Aprobada/editable por administración; nunca confundir con requisitos legales."""
    __tablename__ = "facebook_trade_guides"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_facebook_trade_org_slug"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    slug: Mapped[str] = mapped_column(String(100))
    trade: Mapped[str] = mapped_column(String(140))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    document_guidance: Mapped[list] = mapped_column(JSON, default=list)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
