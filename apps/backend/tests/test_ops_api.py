"""Operational records persist across sites while preserving organization scope."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Organization, User
from app.ops_models import AuditPeriod, Contractor, ContractorWorksite, OpsChange, WorkerAssignment
from app.security import hash_password


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setenv("APP_SECRET", "a" * 96)
    monkeypatch.setenv("SECURE_COOKIES", "false")
    settings.cache_clear()
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory.begin() as db:
        org1 = Organization(name="Organización A")
        org2 = Organization(name="Organización B")
        db.add_all((org1, org2))
        db.flush()
        db.add_all((
            User(org_id=org1.id, email="ops-a@example.cl", password_hash=hash_password("contrasena-segura-2026"), role="admin"),
            User(org_id=org2.id, email="ops-b@example.cl", password_hash=hash_password("contrasena-segura-2026"), role="admin"),
        ))
        org_ids = (org1.id, org2.id)

    def override():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            yield client, session_factory, org_ids
    finally:
        app.dependency_overrides.clear()
        settings.cache_clear()
        engine.dispose()


def login(client, email):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "contrasena-segura-2026"})
    assert response.status_code == 200
    return {"X-CSRF-Token": client.cookies["galant_post_csrf"]}


def test_seed_site_isolation_and_manual_crud(context):
    client, session_factory, (org1, org2) = context
    assert client.get("/api/v1/ops/sites").status_code == 401
    headers = login(client, "ops-a@example.cl")
    first = client.get("/api/v1/ops/sites").json()
    assert {site["name"] for site in first} == {"Lomas Verdes", "Brisas de Junquillar", "Concepción"}
    assert all(site["initial_period"] == "2026-09" for site in first)
    assert {site["id"] for site in client.get("/api/v1/ops/sites").json()} == {site["id"] for site in first}
    site_a, site_b = first[0]["id"], first[1]["id"]
    with session_factory() as db:
        assert db.scalar(select(AuditPeriod).where(AuditPeriod.org_id == org1, AuditPeriod.worksite_id == site_a)).period == "2026-09"

    payload = {"site_id": site_a, "name": "F&B SpA", "rut": "12.345.678-5",
               "historical_code": None, "nature": "with_workers", "frequency": "fixed"}
    missing_csrf = client.post("/api/v1/ops/contractors", json=payload)
    assert missing_csrf.status_code == 403
    created = client.post("/api/v1/ops/contractors", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    contractor = created.json()
    assert contractor["rut"] == "12345678-5"
    assert contractor["historical_code"] == ""
    assert contractor["frequency"] == "fixed"
    assert client.post("/api/v1/ops/contractors", json=payload, headers=headers).status_code == 409
    assert client.get("/api/v1/ops/contractors", params={"site_id": site_b}).json() == []

    linked = client.post("/api/v1/ops/contractors", json={**payload, "site_id": site_b,
                         "historical_code": "CT", "frequency": "sporadic"}, headers=headers)
    assert linked.status_code == 201, linked.text
    assert linked.json()["contractor_id"] == contractor["contractor_id"]
    assert client.get("/api/v1/ops/contractors", params={"site_id": site_a}).json()[0]["frequency"] == "fixed"
    patch = client.patch(f"/api/v1/ops/contractors/{linked.json()['id']}",
                         json={"contract_status": "offboarding", "frequency": "fixed"}, headers=headers)
    assert patch.status_code == 200, patch.text
    assert client.get("/api/v1/ops/contractors", params={"site_id": site_a}).json()[0]["contract_status"] == "active"
    assert client.get("/api/v1/ops/contractors", params={"site_id": site_b}).json()[0]["contract_status"] == "offboarding"

    bad_worker = client.post("/api/v1/ops/workers", json={"site_id": site_a,
                             "contractor_id": contractor["contractor_id"], "name": "Ana", "rut": "12345678-9"}, headers=headers)
    assert bad_worker.status_code == 422
    worker = client.post("/api/v1/ops/workers", json={"site_id": site_a,
                         "contractor_id": contractor["contractor_id"], "name": "Ana Díaz",
                         "rut": "11.111.111-1"}, headers=headers)
    assert worker.status_code == 201, worker.text
    assert worker.json()["rut"] == "11111111-1"
    assert len(client.get("/api/v1/ops/workers", params={"site_id": site_a}).json()) == 1
    assert client.get("/api/v1/ops/workers", params={"site_id": site_b}).json() == []
    assert client.get("/api/v1/ops/contractors", params={"site_id": site_a}).json()[0]["worker_count"] == 1
    deactivated = client.patch(f"/api/v1/ops/workers/{worker.json()['id']}", json={"active": False}, headers=headers)
    assert deactivated.status_code == 200
    assert deactivated.json()["active"] is False
    assert client.get("/api/v1/ops/contractors", params={"site_id": site_a}).json()[0]["worker_count"] == 0
    history = client.get("/api/v1/ops/history", params={"entity_type": "contractor_worksite", "entity_id": linked.json()["id"]}).json()
    assert any("contract_status" in event["changes"] for event in history)

    other_headers = login(client, "ops-b@example.cl")
    other_sites = client.get("/api/v1/ops/sites").json()
    assert len(other_sites) == 3
    assert not {site["id"] for site in other_sites} & {site["id"] for site in first}
    assert client.get("/api/v1/ops/contractors", params={"site_id": site_a}).status_code == 404
    assert client.post("/api/v1/ops/workers", json={"site_id": site_a,
           "contractor_id": contractor["contractor_id"], "name": "Intruso"}, headers=other_headers).status_code == 404
    assert client.get("/api/v1/ops/history").json() == []
    with session_factory() as db:
        assert db.scalar(select(Contractor).where(Contractor.org_id == org1)).id == contractor["contractor_id"]
        assert db.scalar(select(ContractorWorksite).where(ContractorWorksite.org_id == org2)) is None
        assert db.scalar(select(WorkerAssignment).where(WorkerAssignment.org_id == org1)).active is False
        assert db.scalar(select(OpsChange).where(OpsChange.org_id == org1)) is not None


def test_independent_cannot_have_active_workers_but_ci_code_is_historical(context):
    client, _, _ = context
    headers = login(client, "ops-a@example.cl")
    site_a, site_b = [row["id"] for row in client.get("/api/v1/ops/sites").json()[:2]]
    independent = client.post("/api/v1/ops/contractors", headers=headers, json={
        "site_id": site_a, "name": "Independiente", "rut": "12345678-5",
        "historical_code": "CI", "nature": "independent",
    }).json()
    denied = client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": site_a, "contractor_id": independent["contractor_id"],
        "name": "Ayudante", "rut": "11111111-1",
    })
    assert denied.status_code == 409

    # CI is an imported classification code; the explicitly selected nature is
    # what controls whether a worker can be assigned.
    ci_with_workers = client.post("/api/v1/ops/contractors", headers=headers, json={
        "site_id": site_a, "name": "Empresa con personal", "rut": "22222222-2",
        "historical_code": "CI", "nature": "with_workers",
    }).json()
    assignment = client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": site_a, "contractor_id": ci_with_workers["contractor_id"],
        "name": "Ayudante", "rut": "11111111-1",
    })
    assert assignment.status_code == 201, assignment.text
    worker_link = assignment.json()["id"]
    assert client.patch(f"/api/v1/ops/contractors/{ci_with_workers['id']}",
                        headers=headers, json={"nature": "independent"}).status_code == 409

    # The same company can be in another site; the nature remains global, so
    # active assignments anywhere block an incompatible reclassification.
    blocked_new_site = client.post("/api/v1/ops/contractors", headers=headers, json={
        "site_id": site_b, "name": "Empresa con personal", "rut": "22222222-2",
        "nature": "independent",
    })
    assert blocked_new_site.status_code == 409
    unclassified = client.post("/api/v1/ops/contractors", headers=headers, json={
        "site_id": site_a, "name": "Empresa sin clasificar", "rut": "76000000-0",
    }).json()
    assert client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": site_a, "contractor_id": unclassified["contractor_id"],
        "name": "Personal existente", "rut": "33333333-3",
    }).status_code == 201
    assert client.post("/api/v1/ops/contractors", headers=headers, json={
        "site_id": site_b, "name": "Empresa sin clasificar", "rut": "76000000-0",
        "nature": "independent",
    }).status_code == 409
    assert client.patch(f"/api/v1/ops/workers/{worker_link}",
                        headers=headers, json={"active": False}).status_code == 200
    assert client.patch(f"/api/v1/ops/contractors/{ci_with_workers['id']}",
                        headers=headers, json={"nature": "independent"}).status_code == 200
    assert client.patch(f"/api/v1/ops/workers/{worker_link}",
                        headers=headers, json={"active": True}).status_code == 409
