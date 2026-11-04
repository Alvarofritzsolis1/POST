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
