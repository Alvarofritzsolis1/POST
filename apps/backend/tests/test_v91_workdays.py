"""V9.1: control de asistencia solo lunes a viernes, sin renumerar historia."""
from datetime import date
import pytest
from pydantic import ValidationError

from app.calendar_v81 import calendar_weeks, dates_of_week
from app.v81_api import SaveWeek


def test_noviembre_domingo_no_genera_semana_exigible():
    # Conservar ordinales históricos: la semana 1 empieza el domingo 01-11.
    assert len(calendar_weeks("2026-11")) == 6
    assert dates_of_week("2026-11", 1) == []
    assert dates_of_week("2026-11", 2) == [
        date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4),
        date(2026, 11, 5), date(2026, 11, 6),
    ]
    assert sum(bool(dates_of_week("2026-11", i)) for i in range(1, 7)) == 5


@pytest.mark.parametrize("period,days", [("2026-10", 22), ("2026-11", 21), ("2021-02", 20)])
def test_solo_dias_laborales_sin_perder_lunes_viernes(period, days):
    calendar_days = [day for i in range(1, len(calendar_weeks(period)) + 1)
                     for day in dates_of_week(period, i)]
    assert len(calendar_days) == days
    assert len(calendar_days) == len(set(calendar_days))
    assert all(day.weekday() < 5 for day in calendar_days)


def test_no_se_acepta_registro_para_domingo_sin_dias_laborales():
    with pytest.raises(ValidationError, match="Semana sin días laborales"):
        SaveWeek(association_id="dummy", period="2026-11", week_number=1,
                 revision=0, complete=False, entries=[])


def test_no_se_aceptan_firmas_de_sabados_y_domingos():
    with pytest.raises(ValidationError, match="Fecha fuera de la semana"):
        SaveWeek(association_id="dummy", period="2026-10", week_number=1,
                 revision=0, complete=False,
                 entries=[{"worker_assignment_id": "x", "signed_dates": ["2026-10-03"],
                           "excluded": False, "reason": ""}])


def test_weekend_signatures_remain_stored_after_weekday_edit(env):
    from sqlalchemy import select
    from app.models import User
    from app.v81_models import CalendarWeek, CalendarEntry
    from test_control_api import login, create_company
    from test_platform import rut

    client, sessions = env
    auth = login(client, "a@example.cl")
    site_id = client.get("/api/v1/ops/sites").json()[0]["id"]
    company = create_company(client, auth, site_id, "CT", "Histórico sábado V9.1")
    response = client.post("/api/v1/labor/workers", headers=auth, json={
        "site_id": site_id,
        "contractor_id": company["contractor_id"],
        "name": "Prueba histórico sábado",
        "rut": rut(99000581),
        "contract": {"contract_type": "indefinite", "start_date": "2026-10-01"},
    })
    assert response.status_code == 201, response.text
    assignment_id = response.json()["assignment_id"]
    with sessions.begin() as db:
        admin = db.scalar(select(User).where(User.email == "a@example.cl"))
        week = CalendarWeek(
            org_id=admin.org_id, association_id=company["id"],
            period="2026-10", week_number=1,
            start_date=date(2026, 10, 1), end_date=date(2026, 10, 4),
            entered_by=admin.id, updated_by=admin.id,
            state="draft", migrated=True, revision=1,
        )
        db.add(week)
        db.flush()
        db.add(CalendarEntry(
            org_id=admin.org_id, week_id=week.id,
            worker_assignment_id=assignment_id,
            signed_dates=["2026-10-03"], updated_by=admin.id,
            excluded=False, reason="",
        ))
        week_id = week.id
    saved = client.put("/api/v1/attendance-v81/weeks", headers=auth, json={
        "association_id": company["id"], "period": "2026-10",
        "week_number": 1, "revision": 1, "complete": True,
        "notes": "Histórico conservado y asistencia laboral validada",
        "entries": [{"worker_assignment_id": assignment_id,
                     "signed_dates": ["2026-10-02"],
                     "excluded": False, "reason": ""}],
    })
    assert saved.status_code == 200, saved.text
    with sessions() as db:
        stored = db.scalar(select(CalendarEntry).where(
            CalendarEntry.week_id == week_id,
            CalendarEntry.worker_assignment_id == assignment_id))
        assert stored.signed_dates == ["2026-10-02", "2026-10-03"]
    roster = client.get("/api/v1/attendance-v81/roster", params={
        "site_id": site_id, "period": "2026-10",
        "association_id": company["id"],
    })
    assert roster.status_code == 200, roster.text
    item = roster.json()["contractors"][0]
    assert item["weeks"][0]["entries"][0]["signed_dates"] == ["2026-10-02"]
    assert item["workers"][0]["signed_days"] == 1
