"""GALANT 20: immutable private workbooks; indexes never contain matrix content."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid, utcnow


class JavieraWorkbook(Base):
    __tablename__ = "javiera_workbooks"
    __table_args__ = (UniqueConstraint("org_id", "revision", name="uq_jv_workbook_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[str | None] = mapped_column(String(36))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    original_sha256: Mapped[str] = mapped_column(String(64))
    inventory: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(800))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraWorkbookHead(Base):
    __tablename__ = "javiera_workbook_heads"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    current_id: Mapped[str | None] = mapped_column(String(36))
    published_id: Mapped[str | None] = mapped_column(String(36))
    publications: Mapped[dict] = mapped_column(JSON, default=dict)
    legacy_disabled: Mapped[bool] = mapped_column(Boolean, default=False)


class JavieraWorkbookValidation(Base):
    __tablename__ = "javiera_workbook_validations"
    __table_args__ = (UniqueConstraint("workbook_id", "code", name="uq_jv_workbook_validation"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    workbook_id: Mapped[str] = mapped_column(ForeignKey("javiera_workbooks.id"), index=True)
    code: Mapped[str] = mapped_column(String(70))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraReset(Base):
    __tablename__ = "javiera_resets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict] = mapped_column(JSON)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraArchive(Base):
    __tablename__ = "javiera_archives"
    __table_args__ = (UniqueConstraint("org_id", "kind", "resource_id", name="uq_jv_archive"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    reset_id: Mapped[str] = mapped_column(ForeignKey("javiera_resets.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
