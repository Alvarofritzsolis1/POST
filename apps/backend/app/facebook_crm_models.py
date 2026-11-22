"""Facebook inbox: org-scoped leads and durable Messenger message delivery."""
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
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
    name_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    company: Mapped[str] = mapped_column(String(180), default="")
    specialty: Mapped[str] = mapped_column(String(100), default="")
    # Preserve manual classification when messages mention a different trade.
    specialty_source: Mapped[str] = mapped_column(String(16), nullable=False,
                                                 default="manual", server_default="manual")
    workers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability: Mapped[str] = mapped_column(String(120), default="")
    experience: Mapped[str] = mapped_column(Text, default="")
    documents_state: Mapped[str] = mapped_column(String(20), default="unverified")
    status: Mapped[str] = mapped_column(String(24), default="new")
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey("network_requirements.id"), nullable=True)
    unread: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_consent_state: Mapped[str] = mapped_column(String(20), nullable=False, default="not_requested", server_default="not_requested")
    ai_consent_provider: Mapped[str] = mapped_column(String(20), default="", server_default="")
    ai_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    needs_support: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    support_reason: Mapped[str] = mapped_column(String(250), default="")
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown", server_default="unknown")
    has_employees: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Volunteered professional intake, distinct from legal employment status.
    interest_type: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown")
    team_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    work_area: Mapped[str] = mapped_column(String(120), default="", server_default="")
    work_communes: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    profile_sources: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    # Optional contact information, provided voluntarily or recorded by an operator.
    contact_phone: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    phone_source: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    phone_shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Optional, voluntarily shared contact email. Not a matching or hiring signal.
    contact_email: Mapped[str] = mapped_column(String(254), nullable=False, default="", server_default="")
    email_source: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    email_shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    follow_up_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    follow_up_note: Mapped[str] = mapped_column(String(240), default="")
    follow_up_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
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
    consent_decision: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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


class FacebookLeadTrade(Base):
    """One self-declared trade per contact, independent of the legacy main specialty."""
    __tablename__ = "facebook_lead_trades"
    __table_args__ = (
        UniqueConstraint("org_id", "lead_id", "trade", name="uq_fb_lead_trade"),
        Index("ix_fb_lead_trades_contact", "org_id", "lead_id", "active"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("facebook_leads.id"), index=True)
    trade: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20), default="message")
    source_remote_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FacebookNeedAssociation(Base):
    """Human-reviewed many-to-many link; never an employment or award decision."""
    __tablename__ = "facebook_need_associations"
    __table_args__ = (
        UniqueConstraint("org_id", "lead_id", "requirement_id", name="uq_fb_need_association"),
        Index("ix_fb_association_contact", "org_id", "lead_id", "state"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("facebook_leads.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("network_requirements.id"))
    state: Mapped[str] = mapped_column(String(16), default="linked")
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FacebookLeadTrace(Base):
    """Append-only audit of trade extraction and need linking."""
    __tablename__ = "facebook_lead_trace"
    __table_args__ = (
        Index("ix_fb_lead_trace_contact", "org_id", "lead_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    lead_id: Mapped[str] = mapped_column(ForeignKey("facebook_leads.id"), index=True)
    requirement_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trade: Mapped[str | None] = mapped_column(String(120), nullable=True)
    event: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(24), default="system")
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_remote_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
