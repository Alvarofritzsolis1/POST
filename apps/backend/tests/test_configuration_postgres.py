"""Real PostgreSQL serialization for configuration previews and manual reviews."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Organization, User
from app.ops_models import MonthlyDocument, OpsChange
from app.platform_models import UserPreferences
from app.security import hash_password

ROOT = "/api/v1/admin/configuration"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="Requiere PostgreSQL de prueba")
def test_concurrent_configuration_confirmation_and_reviews(monkeypatch):
    """One preview can apply once; two reviews reuse one shared logical record."""
    monkeypatch.setenv("APP_SECRET", "configuration-postgres-tests-" * 6)
    settings.cache_clear()
    url = os.environ["TEST_DATABASE_URL"]
    owner_engine = create_engine(url)
    schema = "configuration_qa_" + uuid4().hex
    with owner_engine.begin() as connection:
        connection.execute(text('CREATE SCHEMA "' + schema + '"'))
    engine = create_engine(url, connect_args={"options": "-csearch_path=" + schema})
    sessions = sessionmaker(engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    email, password = "qa-admin@example.test", "Synthetic-configuration-2026"
    with sessions.begin() as db:
        org = Organization(name="QA PostgreSQL")
        db.add(org)
        db.flush()
        admin = User(org_id=org.id, email=email, role="admin", password_hash=hash_password(password))
        db.add(admin)
        db.flush()
        db.add(UserPreferences(user_id=admin.id, values={"name": "Responsable QA"}))

    def override():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as first, TestClient(app) as second:
            clients = (first, second)
            for client in clients:
                response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
                assert response.status_code == 200, response.text

            def headers(client):
                return {"X-CSRF-Token": client.cookies["galant_post_csrf"]}

            boot = first.get(ROOT + "/bootstrap").json()
            site = boot["sites"][0]["id"]
            response = first.post("/api/v1/ops/contractors", headers=headers(first), json={
                "site_id": site, "name": "Contratista concurrente", "historical_code": "CT",
                "nature": "with_workers", "frequency": "fixed", "contract_status": "active",
            })
            assert response.status_code == 201, response.text
            association_id = response.json()["id"]
            response = first.post(ROOT + "/catalog", headers=headers(first), json={"name": "Certificado concurrente"})
            assert response.status_code == 201, response.text
            document_type = response.json()
            period = datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m")
            rule = {
                "document_type_id": document_type["id"], "scope": "general", "required": True,
                "period_start": period, "reason": "Ensayo concurrente con datos sintéticos",
            }
            response = first.post(ROOT + "/rules/preview", headers=headers(first), json=rule)
            assert response.status_code == 200, response.text
            proposal = {**rule, "preview_token": response.json()["preview_token"], "confirm": True}

            def apply(client):
                return client.post(ROOT + "/rules/apply", headers=headers(client), json=proposal)

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(apply, clients))
            assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
            gate = next(item for item in boot["catalog"] if item["code"] == "porteria")

            def review(index):
                client = clients[index]
                return client.put(ROOT + "/reviews", headers=headers(client), json={
                    "association_id": association_id, "period": period,
                    "document_type_id": gate["id"], "state": ("approved", "incomplete")[index],
                    "notes": "Revisión humana concurrente registrada " + str(index),
                })

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(review, (0, 1)))
            assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
            assert responses[0].json()["id"] == responses[1].json()["id"]
            with sessions() as db:
                assert db.scalar(select(func.count()).select_from(MonthlyDocument).where(
                    MonthlyDocument.association_id == association_id,
                    MonthlyDocument.period == period, MonthlyDocument.kind == "porteria",
                )) == 1
                assert db.scalar(select(func.count()).select_from(OpsChange).where(
                    OpsChange.entity_type == "configuration_review",
                )) == 2
    finally:
        app.dependency_overrides.pop(get_db, None)
        settings.cache_clear()
        engine.dispose()
        with owner_engine.begin() as connection:
            connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
        owner_engine.dispose()
