import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Organization, User
from app.security import hash_password

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_SECRET", "a" * 96)
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path))
    monkeypatch.setenv("SECURE_COOKIES", "false")
    settings.cache_clear()
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        org = Organization(name="Empresa de prueba")
        db.add(org); db.flush()
        db.add(User(org_id=org.id, email="admin@example.cl", password_hash=hash_password("contrasena-segura-2026"), role="admin"))
    def override():
        with Session() as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        settings.cache_clear()
        engine.dispose()

def pdf_bytes():
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((35, 65), "PREVIRED - COMPROBANTE DE PAGO")
        page.insert_text((35, 90), "Periodo: 10/2026")
        return pdf.tobytes()

def test_auth_upload_and_deduplicate(client):
    assert client.get("/api/v1/documents").status_code == 401
    result = client.post("/api/v1/auth/login", json={"email":"admin@example.cl","password":"contrasena-segura-2026"})
    assert result.status_code == 200
    csrf = client.cookies.get("galant_post_csrf")
    assert csrf
    assert client.post("/api/v1/documents", files={"file": ("test.pdf", pdf_bytes(), "application/pdf")}, data={"category":"cotizaciones"}).status_code == 403
    def send():
        return client.post("/api/v1/documents", headers={"X-CSRF-Token": csrf}, files={"file": ("test.pdf", pdf_bytes(), "application/pdf")}, data={"category":"cotizaciones"})
    first = send()
    assert first.status_code == 202
    doc = first.json()
    assert doc["status"] == "queued"
    assert client.get("/api/v1/documents/" + doc["id"]).status_code == 200
    assert client.get("/api/v1/documents/" + doc["id"] + "/file").status_code == 200
    assert client.get("/api/v1/dashboard").json()["total"] == 1
    assert send().json()["id"] == doc["id"]

def test_reject_malformed_pdf(client):
    client.post("/api/v1/auth/login", json={"email":"admin@example.cl","password":"contrasena-segura-2026"})
    csrf = client.cookies.get("galant_post_csrf")
    result = client.post("/api/v1/documents", headers={"X-CSRF-Token": csrf}, files={"file": ("falso.pdf", b"no es pdf", "application/pdf")}, data={"category":"auto"})
    assert result.status_code == 415
