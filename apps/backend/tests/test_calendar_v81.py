"""v8.1 calendar, DST, grade and non-destructive legacy attendance regression."""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import select, func
from app.calendar_v81 import calendar_weeks, dates_of_week, deadline_utc, grade
from app.platform_models import AttendanceWeek, AttendanceWorkerWeek
from app.v81_models import CalendarWeek, CalendarEntry
from app.migrations import v8_1_0
from app.models import User
from test_control_api import env, login, create_company
from test_platform import rut


def test_real_calendar_months_four_five_six():
    assert len(calendar_weeks("2021-02")) == 4
    assert len(calendar_weeks("2026-10")) == 5
    assert len(calendar_weeks("2026-11")) == 6
    assert [(str(a),str(b)) for a,b in calendar_weeks("2026-10")] == [
        ("2026-10-01", "2026-10-04"), ("2026-10-05", "2026-10-11"),
        ("2026-10-12", "2026-10-18"), ("2026-10-19", "2026-10-25"),
        ("2026-10-26", "2026-10-31")]
    assert len(dates_of_week("2026-11", 6)) == 1
    assert len({day for week in range(1, 6) for day in dates_of_week("2026-10", week)}) == 31


def test_grade_not_confusing_completion_with_punctuality():
    result = grade(5, 4, 5)
    assert result["completion"] == 100.0
    assert result["punctuality"] == 80.0
    assert result["grade"] == 6.6
    assert grade(0, 0, 0)["grade"] is None
    assert grade(0, 0, 5)["grade"] == 1.0


def test_deadline_has_chilean_tz_not_fixed_offset():
    winter = deadline_utc(date(2026, 7, 12), 1)
    summer = deadline_utc(date(2026, 11, 8), 1)
    assert winter.utcoffset() == timedelta(0)
    assert winter.hour != summer.hour
    assert winter.tzinfo is timezone.utc


def test_legacy_migration_keeps_original_rows_and_signed_days(env):
    client, sessions = env
    head = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    company = create_company(client, head, site, "CT", "Histórica con asistencia")
    new_worker = client.post("/api/v1/labor/workers", headers=head, json={
        "site_id": site, "contractor_id": company["contractor_id"],
        "name": "Trabajador Migrado", "rut": rut(99000321),
        "contract": {"contract_type": "indefinite", "start_date": "2026-10-01"}
    })
    assert new_worker.status_code == 201, new_worker.text
    assignment = new_worker.json()["assignment_id"]
    with sessions.begin() as db:
        admin = db.scalar(select(User).where(User.email == "a@example.cl"))
        legacy = AttendanceWeek(org_id=admin.org_id, association_id=company["id"],
            period="2026-10", week_number=1, state="completed",
            entered_by=admin.id, updated_by=admin.id,
            completed_by=admin.id, completed_at=datetime(2026, 10, 9, tzinfo=timezone.utc))
        db.add(legacy)
        db.flush()
        db.add(AttendanceWorkerWeek(org_id=admin.org_id, week_id=legacy.id,
            worker_assignment_id=assignment, signed_dates=[
                "2026-10-01", "2026-10-02", "2026-10-05"],
            updated_by=admin.id))
        legacy_id = legacy.id
    with sessions.begin() as db:
        v8_1_0.upgrade(db)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AttendanceWeek)) == 1
        assert db.get(AttendanceWeek, legacy_id) is not None
        weeks = db.scalars(select(CalendarWeek).where(
            CalendarWeek.period == "2026-10").order_by(CalendarWeek.week_number)).all()
        assert len(weeks) == 2
        assert all(w.state == "draft" and w.migrated for w in weeks)
        rows = db.scalars(select(CalendarEntry)).all()
        assert sorted(x for r in rows for x in r.signed_dates) == [
            "2026-10-01", "2026-10-02", "2026-10-05"]
    with sessions.begin() as db:
        v8_1_0.upgrade(db)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(CalendarWeek)) == 2
        assert db.scalar(select(func.count()).select_from(AttendanceWorkerWeek)) == 1
