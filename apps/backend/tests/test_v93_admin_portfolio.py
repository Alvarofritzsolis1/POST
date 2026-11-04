"""La v9.3 consolida obras sin contar semanas futuras como incumplimiento."""
from datetime import timedelta
from app.control_api import today
from app.calendar_v81 import dates_of_week, calendar_weeks
from test_control_api import env, login, create_company
from test_platform import rut


def test_portfolio_admin_includes_sites_and_correct_totals(env):
    client, sessions = env
    headers = login(client, "a@example.cl")
    sites = client.get("/api/v1/ops/sites").json()
    period = today().strftime("%Y-%m")
    one = create_company(client, headers, sites[0]["id"], "CT", "Matriz V93 A")
    create_company(client, headers, sites[1]["id"], "CT", "Matriz V93 B")
    added = client.post("/api/v1/labor/workers", headers=headers, json={
        "site_id": sites[0]["id"], "contractor_id": one["contractor_id"],
        "name": "Operario vista v93", "rut": rut(99000793),
        "contract": {"contract_type": "indefinite",
                     "start_date": (today() - timedelta(days=35)).isoformat()},
    })
    assert added.status_code == 201, added.text
    response = client.get("/api/v1/attendance-v81/portfolio", params={"period": period})
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["sites"]) >= 3
    assert data["totals"]["active_contractors"] >= 2
    for key in ("active_contractors", "required_revisions", "completed_revisions",
                "pending_revisions", "overdue_revisions", "late_completions"):
        assert data["totals"][key] == sum(row[key] for row in data["sites"])
    assert data["totals"]["completed_revisions"] <= data["totals"]["required_revisions"]
    # Las obligaciones con semanas que no han empezado todavía no deben computar.
    assert data["totals"]["required_revisions"] <= sum(
        sum(bool(dates_of_week(period, number)) for number in range(
            1, len(calendar_weeks(period)) + 1)) * row["active_contractors"]
        for row in data["sites"]
    )


def test_portfolio_deny_administrative_and_display_responsible_name(env):
    from sqlalchemy import select
    from app.models import User
    from app.calendar_v81 import deadline_utc
    from app.v81_models import CalendarDuty
    from test_v92_administrative_overview import administrative_user

    client, sessions = env
    headers = login(client, "a@example.cl")
    sites = client.get("/api/v1/ops/sites").json()
    allowed, other = sites[0]["id"], sites[1]["id"]
    period = today().strftime("%Y-%m")
    person = administrative_user(sessions, allowed)
    association = create_company(client, headers, allowed, "CT", "Responsable matriz V93")
    dates = next((n, dates_of_week(period, n)) for n in
                 range(1, len(calendar_weeks(period)) + 1) if dates_of_week(period, n))
    with sessions.begin() as db:
        admin = db.scalar(select(User).where(User.email == "a@example.cl"))
        target = db.scalar(select(User).where(User.email == person))
        db.add(CalendarDuty(
            org_id=admin.org_id, association_id=association["id"],
            worksite_id=allowed, period=period, week_number=dates[0],
            assigned_to=target.id, created_by=admin.id,
            expected_workers=[], deadline_at=deadline_utc(dates[1][-1], 2)))
    login(client, person)
    assert client.get("/api/v1/attendance-v81/portfolio",
                      params={"period": period}).status_code == 403
    assert client.get("/api/v1/attendance-v81/overview",
                      params={"period": period, "site_id": other}).status_code == 403
    summary = client.get("/api/v1/attendance-v81/overview", params={
        "period": period, "site_id": allowed})
    assert summary.status_code == 200, summary.text
    item = next(row for row in summary.json()["contractors"]
                if row["association_id"] == association["id"])
    week = next(row for row in item["weeks"] if row["week_number"] == dates[0])
    assert week["assigned_to_name"] == "Ana Contreras"
    assert "paid_days" not in str(summary.json())
