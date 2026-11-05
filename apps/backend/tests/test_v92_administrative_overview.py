"""V9.2: todos los contratistas, vigencia, finiquitos, permisos y domingos."""
from datetime import date, timedelta
from sqlalchemy import select

from app.control_api import today
from app.models import User
from app.network_models import NetworkMember, NetworkMembership
from app.security import hash_password
from app.calendar_v81 import dates_of_week
from test_control_api import env, login, create_company
from test_platform import rut


def administrative_user(sessions, site_id):
    with sessions.begin() as session:
        admin = session.scalar(select(User).where(User.email == "a@example.cl"))
        person = User(org_id=admin.org_id, email="vista92@example.cl",
                      role="administrative",
                      password_hash=hash_password("password-valid-2026"))
        session.add(person)
        session.flush()
        session.add(NetworkMember(user_id=person.id, name="Ana Contreras"))
        session.add(NetworkMembership(user_id=person.id, site_id=site_id, assigned_by=admin.id))
    return "vista92@example.cl"


def test_overview_shows_every_active_contractor_without_search(env):
    client, sessions = env
    auth = login(client, "a@example.cl")
    sites = client.get("/api/v1/ops/sites").json()
    site = sites[0]["id"]
    first = create_company(client, auth, site, "CT", "Contratista visible V92")
    second = create_company(client, auth, site, "CT", "Contratista sin personal V92")
    started = today() - timedelta(days=20)
    worker = client.post("/api/v1/labor/workers", headers=auth, json={
        "site_id": site, "contractor_id": first["contractor_id"],
        "name": "Trabajador vigente v92", "rut": rut(99000691),
        "contract": {"contract_type": "indefinite", "start_date": started.isoformat()},
    })
    assert worker.status_code == 201, worker.text

    response = client.get("/api/v1/attendance-v81/overview",
                          params={"site_id": site, "period": "2026-11"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["week_count"] == 5
    assert data["summary"]["active_contractors"] >= 2
    listed = {row["association_id"]: row for row in data["contractors"]}
    assert first["id"] in listed and second["id"] in listed
    assert listed[first["id"]]["classification"] == "CT"
    assert listed[second["id"]]["classification"] == "CT"
    assert listed[second["id"]]["contractor_active"] is True
    assert listed[second["id"]]["staff"] == []
    assert listed[first["id"]]["staff"][0]["labor_state"] == "vigente"
    assert all(row["dates"] and all(date.fromisoformat(d).weekday() < 5
                for d in row["dates"]) for row in listed[first["id"]]["weeks"])
    assert all("entries" not in w for row in data["contractors"] for w in row["weeks"])
    assert "paid_days" not in str(data)
    assert dates_of_week("2026-11", 1) == []


def test_overview_and_personal_grade_respect_assigned_site(env):
    client, sessions = env
    admin = login(client, "a@example.cl")
    sites = client.get("/api/v1/ops/sites").json()
    assigned_site, other_site = sites[0]["id"], sites[1]["id"]
    person = administrative_user(sessions, assigned_site)
    credentials = login(client, person)

    allowed = client.get("/api/v1/attendance-v81/overview", params={
        "site_id": assigned_site, "period": "2026-11",
    })
    assert allowed.status_code == 200, allowed.text
    forbidden = client.get("/api/v1/attendance-v81/overview", params={
        "site_id": other_site, "period": "2026-11",
    })
    assert forbidden.status_code == 403, forbidden.text
    profile = client.get("/api/v1/attendance-v81/my-evaluation",
                         params={"period": "2026-11"})
    assert profile.status_code == 200, profile.text
    assert profile.json()["required"] == 0
    assert profile.json()["grade"] is None
    assert client.get("/api/v1/attendance-v81/evaluations",
                      params={"period": "2026-11"}).status_code == 403


def test_overview_historical_snapshot_before_termination(env):
    client, sessions = env
    admin = login(client, "a@example.cl")
    site_id = client.get("/api/v1/ops/sites").json()[0]["id"]
    company = create_company(client, admin, site_id, "CT", "Historial laboral V92")
    created = client.post("/api/v1/labor/workers", headers=admin, json={
        "site_id": site_id, "contractor_id": company["contractor_id"],
        "name": "Trabajador histórico V92", "rut": rut(99000692),
        "contract": {"contract_type": "indefinite", "start_date": "2026-09-01"},
    })
    assert created.status_code == 201, created.text
    assignment = created.json()["assignment_id"]
    from app.control_models import ContractRegister
    from app.platform_models import WorkerTermination
    with sessions.begin() as db:
        contract = db.scalar(select(ContractRegister).where(
            ContractRegister.worker_assignment_id == assignment))
        admin_user = db.scalar(select(User).where(User.email == "a@example.cl"))
        contract.status = "ended"
        worker_assignment = db.get(__import__(
            "app.ops_models", fromlist=["WorkerAssignment"]).WorkerAssignment, assignment)
        worker_assignment.active = False
        db.add(WorkerTermination(
            org_id=admin_user.org_id, contract_id=contract.id,
            effective_date=date(2026, 10, 20), cause="other",
            created_by=admin_user.id, review_state="missing",
        ))
    before = client.get("/api/v1/attendance-v81/overview", params={
        "site_id": site_id, "period": "2026-09", "as_of": "2026-09-15",
    })
    assert before.status_code == 200, before.text
    b = next(r for r in before.json()["contractors"] if r["association_id"] == company["id"])
    assert b["staff"][0]["labor_state"] == "vigente"
    after = client.get("/api/v1/attendance-v81/overview", params={
        "site_id": site_id, "period": "2026-10", "as_of": "2026-10-25",
    })
    assert after.status_code == 200, after.text
    a = next(r for r in after.json()["contractors"] if r["association_id"] == company["id"])
    assert a["staff"][0]["labor_state"] == "terminado"
    assert a["pending_finiquitos"] == 1
