"""La deduplicación debe ser atómica entre sesiones PostgreSQL independientes."""
from concurrent.futures import ThreadPoolExecutor
import os
from tempfile import TemporaryDirectory
from uuid import uuid4

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import AuditEvent, Document, Organization, User
from app.security import hash_password


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="Requiere PostgreSQL de prueba")
def test_concurrent_uploads_create_one_document(monkeypatch):
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    email = f"concurrent-{uuid4()}@example.cl"
    with Session.begin() as db:
        org = Organization(name="Prueba concurrente")
        db.add(org)
        db.flush()
        org_id = org.id
        db.add(User(org_id=org_id, email=email,
                    password_hash=hash_password("password-prueba-2026"), role="admin"))
    with fitz.open() as pdf:
        pdf.new_page().insert_text((30, 50), "PREVIRED COMPROBANTE DE PAGO")
        payload = pdf.tobytes()
    monkeypatch.setenv("APP_SECRET", "x" * 96)
    monkeypatch.setenv("SECURE_COOKIES", "false")
    settings.cache_clear()
    def override():
        with Session() as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        with TemporaryDirectory(prefix="galant-pg-test-") as folder:
            monkeypatch.setenv("DOCUMENT_DIR", folder)
            settings.cache_clear()
            with TestClient(app) as first, TestClient(app) as second:
                for client in (first, second):
                    login = client.post("/api/v1/auth/login", json={"email": email,
                                        "password": "password-prueba-2026"})
                    assert login.status_code == 200
                def upload(client):
                    csrf = client.cookies.get("galant_post_csrf")
                    return client.post("/api/v1/documents", headers={"X-CSRF-Token": csrf},
                                       files={"file": ("same.pdf", payload, "application/pdf")},
                                       data={"category": "cotizaciones"})
                with ThreadPoolExecutor(max_workers=2) as pool:
                    responses = list(pool.map(upload, (first, second)))
                assert [response.status_code for response in responses] == [202, 202]
                assert responses[0].json()["id"] == responses[1].json()["id"]
                with Session() as db:
                    assert db.scalar(select(func.count(Document.id)).where(Document.org_id == org_id)) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)
        settings.cache_clear()
        with Session.begin() as db:
            db.execute(delete(AuditEvent).where(AuditEvent.org_id == org_id))
            db.execute(delete(Document).where(Document.org_id == org_id))
            db.execute(delete(User).where(User.org_id == org_id))
            db.execute(delete(Organization).where(Organization.id == org_id))
        engine.dispose()
