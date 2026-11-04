"""Red de Obras: additive records referencing GALANT's existing identities."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import uid, utcnow


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class NetworkMember(Base):
    __tablename__ = "network_members"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(180), default="")
    title: Mapped[str] = mapped_column(String(180), default="")
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    can_award: Mapped[bool] = mapped_column(Boolean, default=False)


class NetworkMembership(Base):
    __tablename__ = "network_memberships"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"), primary_key=True)
    assigned_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class NetworkToken(Base):
    __tablename__ = "network_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NetworkRequirement(Record, Base):
    __tablename__ = "network_requirements"
    __table_args__ = (
        UniqueConstraint("org_id", "client_key", name="uq_network_request_key"),
        Index("ix_network_request_site_state", "org_id", "site_id", "state"),
    )
    site_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    specialty: Mapped[str] = mapped_column(String(100))
    specialty_key: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    workers: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    deadline: Mapped[date] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(16), default="published")
    client_key: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class NetworkItem(Record, Base):
    __tablename__ = "network_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_network_item_positive"),)
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("network_requirements.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(24))
    position: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")


class NetworkCapacity(Record, Base):
    __tablename__ = "network_capacities"
    __table_args__ = (
        UniqueConstraint("org_id", "client_key", name="uq_network_capacity_key"),
    )
    site_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"), index=True)
    contractor_id: Mapped[str] = mapped_column(ForeignKey("contractors.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    specialty: Mapped[str] = mapped_column(String(100))
    specialty_key: Mapped[str] = mapped_column(String(100), index=True)
    situation: Mapped[str] = mapped_column(String(30))
    available_date: Mapped[date] = mapped_column(Date)
    workers: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(16))
    availability: Mapped[str] = mapped_column(String(16), default="estimated")
    notes: Mapped[str] = mapped_column(Text, default="")
    can_transfer: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(16), default="published")
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_on: Mapped[date] = mapped_column(Date)
    client_key: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class NetworkPendingItem(Record, Base):
    __tablename__ = "network_pending_items"
    capacity_id: Mapped[str] = mapped_column(
        ForeignKey("network_capacities.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(180))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(24))
    end_date: Mapped[date] = mapped_column(Date)


class NetworkMatch(Record, Base):
    __tablename__ = "network_matches"
    __table_args__ = (
        UniqueConstraint("requirement_id", "capacity_id", name="uq_network_match"),
    )
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("network_requirements.id"), index=True
    )
    capacity_id: Mapped[str] = mapped_column(
        ForeignKey("network_capacities.id"), index=True
    )
    score: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class NetworkCoordination(Record, Base):
    __tablename__ = "network_coordinations"
    match_id: Mapped[str] = mapped_column(ForeignKey("network_matches.id"), unique=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    state: Mapped[str] = mapped_column(String(30), default="interested")
    reason: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class NetworkConversation(Record, Base):
    __tablename__ = "network_conversations"
    coordination_id: Mapped[str] = mapped_column(
        ForeignKey("network_coordinations.id"), unique=True
    )


class NetworkParticipant(Base):
    __tablename__ = "network_participants"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("network_conversations.id"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NetworkMessage(Record, Base):
    __tablename__ = "network_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "sender_id", "client_key", name="uq_network_message_key"
        ),
        Index("ix_network_message_time", "conversation_id", "created_at", "id"),
    )
    conversation_id: Mapped[str] = mapped_column(ForeignKey("network_conversations.id"))
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    client_key: Mapped[str] = mapped_column(String(80))


class NetworkAward(Record, Base):
    __tablename__ = "network_awards"
    __table_args__ = (
        UniqueConstraint("org_id", "client_key", name="uq_network_award_key"),
        CheckConstraint(
            "quantity > 0 AND executed >= 0 AND executed <= quantity",
            name="ck_network_award_quantity",
        ),
    )
    item_id: Mapped[str] = mapped_column(ForeignKey("network_items.id"), index=True)
    contractor_id: Mapped[str] = mapped_column(ForeignKey("contractors.id"), index=True)
    capacity_id: Mapped[str | None] = mapped_column(
        ForeignKey("network_capacities.id"), nullable=True, index=True
    )
    coordination_id: Mapped[str | None] = mapped_column(
        ForeignKey("network_coordinations.id"), nullable=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    executed: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    workers: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(24), default="assigned")
    notes: Mapped[str] = mapped_column(Text, default="")
    awarded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    client_key: Mapped[str] = mapped_column(String(80))
    payload_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)


class NetworkNotification(Record, Base):
    __tablename__ = "network_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "event_key", name="uq_network_notice"),
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(180))
    title: Mapped[str] = mapped_column(String(240))
    resource_type: Mapped[str] = mapped_column(String(30))
    resource_id: Mapped[str] = mapped_column(String(36))
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NetworkAttachment(Record, Base):
    __tablename__ = "network_attachments"
    __table_args__ = (
        CheckConstraint(
            "(requirement_id IS NULL) <> (conversation_id IS NULL)",
            name="ck_network_attachment_target",
        ),
    )
    requirement_id: Mapped[str | None] = mapped_column(
        ForeignKey("network_requirements.id"), nullable=True, index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("network_conversations.id"), nullable=True, index=True
    )
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(240))
    path: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
