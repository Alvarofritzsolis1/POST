"""v8.1 end-to-end permissions and monthly evaluation without files."""
from datetime import date, timedelta
from sqlalchemy import select
from app.models import User
from app.network_models import NetworkMember, NetworkMembership
from app.security import hash_password
from app.calendar_v81 import calendar_weeks
from test_control_api import env, login, create_company
from test_platform import rut


def previous_month():
    from app.control_api import today
    last = today().replace(day=1) - timedelta(days=1)
    return last.strftime("%Y-%m"), date(last.year, last.month, 1)


def test_administrative_v81_permissions_weekly_and_monthly_score(env):
    client, sessions = env
    admin_auth = login(client, "a@example.cl")
    sites = client.get("/api/v1/ops/sites").json()
    site = sites[0]["id"]
    other = sites[1]["id"]
    company = create_company(client, admin_auth, site, "CT", "Obra con firmas v8.1")
    period, first = previous_month()
    worker = client.post("/api/v1/labor/workers", headers=admin_auth, json={
        "site_id": site, "contractor_id": company["contractor_id"],
        "name": "Persona de control", "rut": rut(99000331),
        "contract": {"contract_type": "indefinite", "start_date": first.isoformat()},
    })
    assert worker.status_code == 201, worker.text
    worker_id = worker.json()["assignment_id"]
    with sessions.begin() as db:
        administrator = db.scalar(select(User).where(User.email == "a@example.cl"))
        person = User(org_id=administrator.org_id, email="semana@example.cl",
                      role="administrative", password_hash=hash_password("password-valid-2026"))
        db.add(person)
        db.flush()
        db.add(NetworkMember(user_id=person.id, name="María González"))
        db.add(NetworkMembership(user_id=person.id, site_id=site, assigned_by=administrator.id))
        user_id = person.id
    assigned = client.post("/api/v1/attendance-v81/duties/generate",
        headers=admin_auth, json={"site_id": site, "period": period, "user_id": user_id})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["created"] == len(calendar_weeks(period))
    summary = client.get("/api/v1/attendance-v81/evaluations", params={"period": period}).json()
    record = next(row for row in summary["rows"] if row["user_id"] == user_id)
    assert record["required"] == len(calendar_weeks(period))
    assert record["completed"] == 0 and record["grade"] == 1.0

    auth = login(client, "semana@example.cl")
    assert client.get("/api/v1/attendance-v81/roster",
        params={"site_id": other, "period": period}).status_code == 403
    assert client.get("/api/v1/control/contributions",
        params={"period": period}).status_code == 403
    data = client.get("/api/v1/attendance-v81/roster",
        params={"site_id": site, "period": period})
    assert data.status_code == 200, data.text
    row = next(r for r in data.json()["contractors"] if r["association_id"] == company["id"])
    assert len(row["weeks"]) == len(calendar_weeks(period))
    assert row["weeks"][0]["entries"][0]["recorded"] is False
    assert "paid_days" not in row["workers"][0]
    payload = {"association_id": company["id"], "period": period, "week_number": 1,
               "revision": 0, "complete": True,
               "notes": "Registro ingresado fuera de plazo por revisión de libros",
               "entries": [{"worker_assignment_id": worker_id,
                            "signed_dates": [first.isoformat()]}]}
    saved = client.put("/api/v1/attendance-v81/weeks", headers=auth, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["completed_on_time"] is False
    repeated = client.put("/api/v1/attendance-v81/weeks", headers=auth, json=payload)
    assert repeated.status_code == 409
    refreshed = client.get("/api/v1/attendance-v81/roster",
        params={"site_id": site, "period": period}).json()
    week = refreshed["contractors"][0]["weeks"][0]
    assert week["completed_by"] == "María González"
    assert week["state"] == "completed_late"
    assert refreshed["contractors"][0]["workers"][0]["signed_days"] == 1

    login(client, "a@example.cl")
    report = client.get("/api/v1/attendance-v81/evaluations", params={"period": period}).json()
    metric = next(row for row in report["rows"] if row["user_id"] == user_id)
    assert metric["completed"] == 1 and metric["punctual"] == 0
    assert metric["grade"] > 1.0
