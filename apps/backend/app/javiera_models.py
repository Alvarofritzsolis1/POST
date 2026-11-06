"""Proyecto JAVIERA: tablas aditivas, aisladas por organización.

No se guardan plantillas públicas con datos personales. Cada emisión conserva
su propia instantánea y archivo inmutable.
"""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import uid, utcnow


class JavieraTemplate(Base):
    __tablename__ = "javiera_templates"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_javiera_template_org_code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(70), nullable=False)
    area: Mapped[str] = mapped_column(String(65), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    fields: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    rule: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    layout: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    published_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraRevision(Base):
    __tablename__ = "javiera_template_revisions"
    __table_args__ = (UniqueConstraint("template_id", "revision", name="uq_javiera_template_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("javiera_templates.id"), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    contents: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JavieraMatrix(Base):
    __tablename__ = "javiera_matrices"
    __table_args__ = (UniqueConstraint("org_id", "kind", "cargo", "revision", name="uq_javiera_matrix_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    cargo: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sections: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraDossier(Base):
    __tablename__ = "javiera_dossiers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("worksites.id"), nullable=True, index=True)
    employer_id: Mapped[str | None] = mapped_column(ForeignKey("contractors.id"), nullable=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("contractors.id"), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.id"), nullable=True, index=True)
    relationship: Mapped[str] = mapped_column(String(20), default="contractor", nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraIssue(Base):
    __tablename__ = "javiera_issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("javiera_dossiers.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(70), nullable=False)
    template_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    dossier_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    issued_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    state: Mapped[str] = mapped_column(String(20), default="issued", nullable=False)


class JavieraHistory(Base):
    __tablename__ = "javiera_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("javiera_dossiers.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(70), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_state: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    event_at: Mapped[str] = mapped_column(String(32), default="")
    comment: Mapped[str] = mapped_column(String(500), default="")
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    verified_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraExcelLayout(Base):
    """Versión del XLSX original de impresión (archivo privado, no GitHub)."""
    __tablename__ = "javiera_excel_layouts"
    __table_args__ = (UniqueConstraint("org_id", "code", "revision", name="uq_javiera_excel_layout_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(70), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_sheet: Mapped[str] = mapped_column(String(120), nullable=False)
    workbook_path: Mapped[str] = mapped_column(Text, nullable=False)
    workbook_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    overrides: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    inventory: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(String(22), default="draft", nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraReviewerAuthorization(Base):
    """Designación de revisor por especialidad y organización."""
    __tablename__ = "javiera_review_authorizations"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "specialty", name="uq_javiera_authorized_reviewer"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    specialty: Mapped[str] = mapped_column(String(20), nullable=False)
    designation: Mapped[str] = mapped_column(String(240), nullable=False)
    delegated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraSignoff(Base):
    """Acta de revisión humana con criterios y observaciones, sin presunción legal."""
    __tablename__ = "javiera_signoffs"
    __table_args__ = (UniqueConstraint("org_id", "resource_kind", "resource_id", "specialty", name="uq_javiera_review_resource"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    resource_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    specialty: Mapped[str] = mapped_column(String(20), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    checklist: Mapped[dict] = mapped_column(JSON, nullable=False)
    comments: Mapped[str] = mapped_column(Text, nullable=False)
    regulatory_basis: Mapped[str] = mapped_column(String(250), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
