"""An existing OCR database must survive the additive operational schema setup."""

import sys

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app import cli
from app.db import Base
from app.models import AuditEvent, Document, Organization, User


def test_init_db_adds_operational_tables_without_losing_documents(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'existing.db'}")
    Base.metadata.create_all(
        engine,
        tables=[model.__table__ for model in (Organization, User, Document, AuditEvent)],
    )
    with Session(engine) as db:
        org = Organization(name="Organización existente")
        db.add(org)
        db.flush()
        user = User(org_id=org.id, email="prior@example.cl", password_hash="hash")
        db.add(user)
        db.flush()
        doc = Document(
            org_id=org.id,
            user_id=user.id,
            original_name="comprobante.pdf",
            storage_path="/private/comprobante.pdf",
            sha256="a" * 64,
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr(cli, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(sys, "argv", ["galant", "init-db"])
    cli.main()

    tables = set(inspect(engine).get_table_names())
    assert {"worksites", "audit_periods", "contractors", "contractor_worksites",
            "workers", "worker_assignments", "ops_changes"} <= tables
    with Session(engine) as db:
        assert db.scalar(select(Document.id).where(Document.id == doc_id)) == doc_id
    engine.dispose()
