"""JAVIERA 16.6: documentary identities never create operational assignments."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import uid, utcnow


class JavieraLocalCompany(Base):
    __tablename__ = "javiera_local_companies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"), nullable=False, index=True)
    source_contractor_id: Mapped[str | None] = mapped_column(ForeignKey("contractors.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    rut: Mapped[str | None] = mapped_column(String(30), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraLocalPerson(Base):
    __tablename__ = "javiera_local_people"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("javiera_local_companies.id"), nullable=False, index=True)
    source_worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    rut: Mapped[str | None] = mapped_column(String(30), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraLocalDossier(Base):
    __tablename__ = "javiera_local_dossiers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("worksites.id"), nullable=False, index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("javiera_local_companies.id"), nullable=False, index=True)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("javiera_local_people.id"), nullable=True, index=True)
    relationship: Mapped[str] = mapped_column(String(20), nullable=False, default="contractor")
    parent_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    shared: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    document_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selected_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraLocalBatch(Base):
    __tablename__ = "javiera_local_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("javiera_local_dossiers.id"), nullable=False, index=True)
    codes: Mapped[list] = mapped_column(JSON, nullable=False)
    results: Mapped[list] = mapped_column(JSON, nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JavieraLocalIssue(Base):
    __tablename__ = "javiera_local_issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("javiera_local_dossiers.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(70), nullable=False)
    dossier_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    template_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    issued_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reissue_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
