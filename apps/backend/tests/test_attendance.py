"""Weekly signatures, provenance, alerts and paid-day comparison."""
from datetime import date, timedelta
from io import BytesIO

import fitz
from openpyxl import load_workbook
from sqlalchemy import select

from app.config import settings
from app.control_api import today
from app.ops_models import OpsChange
from app.platform_models import AttendanceWeek, AttendanceWorkerWeek
from test_control_api import env, login, create_company
from test_platform import rut


def previous_month():
    last = today().replace(day=1) - timedelta(days=1)
    return last.strftime("%Y-%m"), date(last.year, last.month, 1)


def test_weekly_attendance_roles_provenance_balance_alerts_and_exclusion(env, monkeypatch, tmp_path):
    client, sessions = env
    admin = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]
    company = create_company(client, admin, site["id"], "CT", "Contratista de firmas")
    period, first = previous_month()
    worker = client.post("/api/v1/labor/workers", headers=admin, json={
        "site_id": site["id"], "contractor_id": company["contractor_id"],
        "name": "Persona con firmas", "rut": rut(99000128),
        "contract": {"contract_type": "indefinite", "start_date": str(first)},
    }).json()
    assignment_id = worker["assignment_id"]
    paid = client.put("/api/v1/ops/contributions", headers=admin, json={
        "association_id": company["id"], "subject": assignment_id,
        "period": period, "paid_days": 1, "confirmed": False,
    })
    assert paid.status_code == 200, paid.text
    account = client.post("/api/v1/admin/users", headers=admin, json={
        "email": "administrativa@example.cl", "password": "password-valid-2026",
        "role": "administrative", "name": "Administrativa de prueba",
        "site_ids": [site["id"]]})
    assert account.status_code == 201, account.text
    roster_url = f"/api/v1/attendance/roster?site_id={site['id']}&period={period}"
    before = client.get(roster_url).json()
    assert len(before["contractors"][0]["weeks"]) == 5
    assert before["summary"]["overdue_weeks"] >= 4
    assert before["contractors"][0]["weeks"][0]["state"] == "overdue"
    assert client.get("/api/v1/labor/alerts", params={"period": period, "site_id": site["id"]}).json()["summary"]["attendance_overdue"] >= 4
    administrative = login(client, "administrativa@example.cl")
    # Only contract registration is allowed; an empty form still fails validation.
    assert client.post("/api/v1/labor/workers", headers=administrative, json={}).status_code == 422
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path))
    settings.cache_clear()
    pdf = fitz.open()
    pdf.new_page()
    pdf_content = pdf.tobytes()
    pdf.close()
    evidence = client.post("/api/v1/documents", headers=administrative,
                           files={"file": ("firmas.pdf", pdf_content, "application/pdf")})
    assert evidence.status_code == 403, "Administrativo no puede cargar archivos"
    document_id = None
    first_day = str(first)
    second_day = str(first + timedelta(days=1))
    payload = {"association_id": company["id"], "period": period, "week_number": 1,
               "entries": [{"worker_assignment_id": assignment_id,
                            "signed_dates": [first_day, second_day]}],
               "complete": True, "source_document_id": document_id,
               "notes": "Planilla de firmas archivada por administración"}
    invalid = client.put("/api/v1/attendance/weeks", headers=administrative,
                         json={**payload, "entries": [{"worker_assignment_id": assignment_id,
                                                      "signed_dates": [str(first + timedelta(days=7))]}]})
    assert invalid.status_code == 422
    completed = client.put("/api/v1/attendance/weeks", headers=administrative, json=payload)
    assert completed.status_code == 200, completed.text
    week_id = completed.json()["id"]
    assert client.put(f"/api/v1/attendance/weeks/{week_id}/review", headers=administrative,
                      json={"state": "approved"}).status_code == 403
    data = client.get(roster_url).json()
    row = data["contractors"][0]
    assert (row["signed_days"], row["paid_days"], row["missing_payment_days"]) == (2, None, None)
    assert row["weeks"][0]["entered_by"] == "Administrativa de prueba"
    assert row["weeks"][0]["source_document_id"] == document_id
    assert row["weeks"][0]["entered_at"] and row["weeks"][0]["completed_at"]
    assert row["weeks"][0]["completed_on_time"] is False
    assert row["weeks"][0]["state"] == "completed"
    assert data["summary"]["overdue_weeks"] == before["summary"]["overdue_weeks"] - 1
    assert client.get("/api/v1/labor/alerts", params={"period": period, "site_id": site["id"]}).status_code == 403
    assert client.get("/api/v1/attendance/export", params={"site_id": site["id"], "period": period}).status_code == 403
    admin = login(client, "a@example.cl")
    financial = client.get(roster_url).json()["contractors"][0]
    assert (financial["paid_days"], financial["missing_payment_days"]) == (1, 1)
    assert client.get("/api/v1/labor/alerts", params={"period": period, "site_id": site["id"]}).json()["summary"]["attendance_overdue"] == data["summary"]["overdue_weeks"]
    exported = client.get("/api/v1/attendance/export", params={"site_id": site["id"], "period": period})
    assert exported.status_code == 200
    book = load_workbook(BytesIO(exported.content), read_only=True)
    assert book.sheetnames == [f"Semana {number}" for number in range(1, 6)]
    assert any(cell == "Persona con firmas" for row in book["Semana 1"].iter_rows(values_only=True) for cell in row)
    book.close()
    admin = login(client, "a@example.cl")
    approved = client.put(f"/api/v1/attendance/weeks/{week_id}/review", headers=admin,
                          json={"state": "approved"})
    assert approved.status_code == 200, approved.text
    assert client.get(roster_url).json()["contractors"][0]["weeks"][0]["state"] == "approved"
    administrative = login(client, "administrativa@example.cl")
    corrected = client.put("/api/v1/attendance/weeks", headers=administrative,
                           json={**payload, "notes": "Se corrigió la transcripción de la planilla"})
    assert corrected.status_code == 200, corrected.text
    assert client.get(roster_url).json()["contractors"][0]["weeks"][0]["review_state"] == "pending"
    admin = login(client, "a@example.cl")
    added = client.post("/api/v1/labor/workers", headers=admin, json={
        "site_id": site["id"], "contractor_id": company["contractor_id"],
        "name": "Persona agregada a base", "rut": rut(99000129),
        "contract": {"contract_type": "indefinite", "start_date": str(first)},
    })
    assert added.status_code == 201, added.text
    data = client.get(roster_url).json()
    assert data["contractors"][0]["weeks"][0]["state"] == "overdue"
    assert data["contractors"][0]["weeks"][0]["missing_workers"] == 1
    assert data["summary"]["signed_days"] == 2  # Old signatures remain visible.
    administrative = login(client, "administrativa@example.cl")
    assert client.put("/api/v1/attendance/weeks", headers=administrative, json=payload).status_code == 422
    excluded = client.put("/api/v1/attendance/roster", headers=administrative,
                          json={"association_id": company["id"], "period": period,
                                "status": "excluded", "reason": "Sin acceso temporal a obra"})
    assert excluded.status_code == 200, excluded.text
    data = client.get(roster_url).json()
    assert data["summary"]["contractors"] == 0 and data["summary"]["signed_days"] == 0
    assert data["summary"]["overdue_weeks"] == 0
    assert data["contractors"][0]["weeks"][0]["saved_state"] == "completed"
    assert client.put("/api/v1/attendance/roster", headers=administrative,
                      json={"association_id": company["id"], "period": period,
                            "status": "included"}).status_code == 200
    assert client.get(roster_url).json()["summary"]["signed_days"] == 2
    with sessions() as db:
        week = db.scalar(select(AttendanceWeek).where(AttendanceWeek.id == week_id))
        assert week.entered_at and week.updated_at and week.completed_at
        assert db.scalar(select(AttendanceWorkerWeek).where(AttendanceWorkerWeek.week_id == week_id)).signed_dates == [first_day, second_day]
        assert db.scalars(select(OpsChange).where(OpsChange.entity_type == "attendance_roster")).first()
    login(client, "outside@example.cl")
    assert client.get(roster_url).status_code == 404
    assert client.put("/api/v1/attendance/weeks", headers={"X-CSRF-Token": client.cookies["galant_post_csrf"]}, json=payload).status_code == 404


def test_fifth_week_28_day_february_is_not_applicable(env):
    client, _ = env
    admin = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]
    company = create_company(client, admin, site["id"], "CT", "Empresa febrero")
    roster = client.get("/api/v1/attendance/roster", params={"site_id": site["id"], "period": "2025-02"}).json()
    assert roster["contractors"][0]["weeks"][4]["state"] == "not_applicable"
    assert client.put("/api/v1/attendance/weeks", headers=admin, json={
        "association_id": company["id"], "period": "2025-02", "week_number": 5,
        "complete": False}).status_code == 422


def test_independent_is_excluded_from_automatic_attendance_alerts(env):
    client, _ = env
    admin = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]
    company = create_company(client, admin, site["id"], "CI", "Independiente QA", "independent")
    period, _ = previous_month()
    roster = client.get("/api/v1/attendance/roster", params={"site_id": site["id"], "period": period}).json()
    row = next(item for item in roster["contractors"] if item["association_id"] == company["id"])
    assert row["roster_status"] == "excluded"
    assert roster["summary"]["overdue_weeks"] == 0
    assert client.put("/api/v1/attendance/weeks", headers=admin, json={
        "association_id": company["id"], "period": period, "week_number": 1,
        "notes": "Firma del propio contratista", "complete": True}).status_code == 422
    assert client.put("/api/v1/attendance/roster", headers=admin, json={
        "association_id": company["id"], "period": period, "status": "included"}).status_code == 200
    assert client.get("/api/v1/attendance/roster", params={"site_id": site["id"], "period": period}).json()["summary"]["overdue_weeks"] >= 4
