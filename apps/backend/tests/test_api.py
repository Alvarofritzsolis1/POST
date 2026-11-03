import fitz
import pytest
from io import BytesIO
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Document, Organization, User
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
    upload_bytes = pdf_bytes()
    def send():
        return client.post("/api/v1/documents", headers={"X-CSRF-Token": csrf}, files={"file": ("test.pdf", upload_bytes, "application/pdf")}, data={"category":"cotizaciones"})
    first = send()
    assert first.status_code == 202
    doc = first.json()
    assert doc["status"] == "queued"
    assert client.get("/api/v1/documents/" + doc["id"]).status_code == 200
    assert "evidence" not in client.get("/api/v1/documents").json()[0]
    assert client.get("/api/v1/documents/" + doc["id"] + "/file").status_code == 200
    assert client.get("/api/v1/dashboard").json()["total"] == 1
    assert send().json()["id"] == doc["id"]
    other_module = client.post("/api/v1/documents", headers={"X-CSRF-Token": csrf},
                               files={"file": ("test.pdf", upload_bytes, "application/pdf")},
                               data={"category": "f30_1"})
    assert other_module.status_code == 202
    assert other_module.json()["id"] != doc["id"]

def test_reject_malformed_pdf(client):
    client.post("/api/v1/auth/login", json={"email":"admin@example.cl","password":"contrasena-segura-2026"})
    csrf = client.cookies.get("galant_post_csrf")
    result = client.post("/api/v1/documents", headers={"X-CSRF-Token": csrf}, files={"file": ("falso.pdf", b"no es pdf", "application/pdf")}, data={"category":"auto"})
    assert result.status_code == 415


def test_excel_endpoint_uses_completed_document_result(client):
    from app.version import VERSION
    assert client.get("/api/v1/version").json()["version"] == VERSION
    client.post("/api/v1/auth/login", json={"email":"admin@example.cl","password":"contrasena-segura-2026"})
    csrf = client.cookies.get("galant_post_csrf")
    uploaded = client.post("/api/v1/documents", headers={"X-CSRF-Token": csrf},
                           files={"file": ("test.pdf", pdf_bytes(), "application/pdf")},
                           data={"category": "cotizaciones"}).json()
    url = "/api/v1/documents/" + uploaded["id"] + "/report"
    assert client.get(url).status_code == 409
    session = next(app.dependency_overrides[get_db]())
    with session:
        doc = session.get(Document, uploaded["id"])
        doc.status = "complete"
        doc.detected_type = "cotizaciones"
        doc.payment_status = "Pendiente de revisión"
        doc.page_count = 1
        doc.extracted = {"periodo": "2026-10", "ruts_validos": [], "controles_por_pagina": []}
        session.commit()
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    workbook = load_workbook(BytesIO(response.content), read_only=True)
    values = {row[0]: row[1] for row in workbook["Resumen"].iter_rows(min_row=2, values_only=True)}
    assert values["Estado documental"] == "Pendiente de revisión"
    assert values["Período de remuneraciones"] == "2026-10"
    retried = client.post("/api/v1/documents/" + uploaded["id"] + "/retry",
                          headers={"X-CSRF-Token": csrf})
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["payment_status"] is None
    assert retried.json()["extracted"] == {}
