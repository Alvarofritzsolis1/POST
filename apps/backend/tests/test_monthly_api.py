"""Regression tests for a shared contractor monthly register."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Document, Organization, User
from app.security import hash_password


def test_shared_monthly_record_across_users(monkeypatch):
    monkeypatch.setenv("APP_SECRET", "a" * 96)
    monkeypatch.setenv("SECURE_COOKIES", "false")
    settings.cache_clear()
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as db:
        org = Organization(name="Organización de prueba")
        separate = Organization(name="Otra organización")
        db.add_all([org, separate])
        db.flush()
        db.add_all([
            User(org_id=org.id, email="admin1@example.cl", role="admin", password_hash=hash_password("password-seguro-2026")),
            User(org_id=org.id, email="admin2@example.cl", role="analyst", password_hash=hash_password("password-seguro-2026")),
            User(org_id=org.id, email="viewer@example.cl", role="viewer", password_hash=hash_password("password-seguro-2026")),
            User(org_id=separate.id, email="outsider@example.cl", role="admin", password_hash=hash_password("password-seguro-2026"))
        ])
        org_id = org.id
    def override_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    def login(client,email):
        result = client.post("/api/v1/auth/login", json={"email":email, "password":"password-seguro-2026"})
        assert result.status_code == 200
        return {"X-CSRF-Token":client.cookies["galant_post_csrf"]}
    try:
        with TestClient(app) as client:
            headers1 = login(client,"admin1@example.cl")
            site_id = client.get("/api/v1/ops/sites").json()[0]["id"]
            response = client.post("/api/v1/ops/contractors",
                json={"site_id":site_id,"name":"Contratista de ejemplo","nature":"with_workers"},
                headers=headers1)
            assert response.status_code == 201, response.text
            association_id = response.json()["id"]
            with sessions.begin() as db:
                owner = db.query(User).filter(User.email=="admin1@example.cl").one()
                document = Document(org_id=org_id,user_id=owner.id,
                    original_name="pago.pdf", storage_path="test.pdf",
                    sha256="c"*64,declared_type="cotizaciones",status="complete",
                    extracted={},evidence=[],warnings=[])
                db.add(document)
                db.flush()
                document_id = document.id
            response = client.post("/api/v1/ops/monthly-documents",
                json={"association_id":association_id,"period":"2026-10",
                      "kind":"cotizaciones","document_id":document_id},
                headers=headers1)
            assert response.status_code == 201, response.text
            monthly_id=response.json()["id"]
            headers2=login(client,"admin2@example.cl")
            assert any(c["id"]==association_id for c in client.get(
                "/api/v1/ops/contractors",params={"site_id":site_id}).json())
            rows=client.get("/api/v1/ops/monthly-documents",
                params={"association_id":association_id,"period":"2026-10"}).json()
            assert rows[0]["document_id"]==document_id
            updated=client.patch("/api/v1/ops/monthly-documents/"+monthly_id,
                json={"review_status":"approved","notes":"Acreditado en revisión manual"},headers=headers2)
            assert updated.status_code==200,updated.text
            login(client,"admin1@example.cl")
            records=client.get("/api/v1/ops/monthly-documents",
                params={"association_id":association_id,"period":"2026-10"}).json()
            assert records[0]["review_status"]=="approved"
            login(client,"viewer@example.cl")
            assert client.get("/api/v1/ops/monthly-documents",
                params={"association_id":association_id,"period":"2026-10"}).json()[0]["review_status"]=="approved"
            cannot_review=client.patch("/api/v1/ops/monthly-documents/"+monthly_id,
                json={"review_status":"rejected","notes":"Sin autorización"},
                headers={"X-CSRF-Token":client.cookies["galant_post_csrf"]})
            assert cannot_review.status_code==403
            login(client,"outsider@example.cl")
            assert client.get("/api/v1/ops/monthly-documents",
                params={"association_id":association_id,"period":"2026-10"}).status_code==404
            login(client,"admin1@example.cl")
            assert client.post("/api/v1/ops/monthly-documents",
                json={"association_id":association_id,"period":"2026-13",
                      "kind":"cotizaciones","document_id":document_id},
                headers={"X-CSRF-Token":client.cookies["galant_post_csrf"]}).status_code==422
            not_applicable=client.post("/api/v1/ops/monthly-documents",
                json={"association_id":association_id,"period":"2026-11",
                      "kind":"otros","not_applicable":True},
                headers={"X-CSRF-Token":client.cookies["galant_post_csrf"]})
            assert not_applicable.status_code==201,not_applicable.text
            # Regla actual: se permite aprobación manual sin PDF, conservando trazabilidad.
            approved_manual=client.patch("/api/v1/ops/monthly-documents/"+not_applicable.json()["id"],
                json={"review_status":"approved","notes":"Aprobación manual sin respaldo adjunto"},
                headers={"X-CSRF-Token":client.cookies["galant_post_csrf"]})
            assert approved_manual.status_code==200,approved_manual.text
            assert approved_manual.json()["review_source"]=="manual_without_pdf"
    finally:
        app.dependency_overrides.clear()
        settings.cache_clear()
        engine.dispose()
