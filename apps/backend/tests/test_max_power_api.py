"""Security and durable control contract for MAX POWER."""
from sqlalchemy import select
from test_ai_control_center import ai_env, signin
from app.max_power_models import MaxPowerEvent, MaxPowerState

BASE = "/api/v1/admin/ai/max-power"

def test_admin_only_and_persistent_on_off(ai_env):
    client, sessions = ai_env["client"], ai_env["sessions"]
    assert client.get(BASE).status_code == 401
    resident = signin(client, "resident")
    assert client.get(BASE).status_code == 403
    assert client.post(BASE + "/control/on", headers=resident).status_code == 403
    headers = signin(client, "admin")
    before = client.get(BASE).json()
    assert not before["enabled"] and before["quality_deltas"]["general"]["delta_points"] is None
    first = client.post(BASE + "/control/on", headers=headers)
    assert first.status_code == 200, first.text
    state = first.json()
    assert state["enabled"] is True and state["sessions"] == 1
    assert state["experiments"] == 0 and state["observed_holdout_wins"] == 0
    assert client.post(BASE + "/control/on", headers=headers).status_code == 409
    off = client.post(BASE + "/control/off", headers=headers)
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    assert off.json()["first_started_at"].split("+")[0] == state["first_started_at"].split("+")[0]
    again = client.post(BASE + "/control/on", headers=headers)
    assert again.status_code == 200, again.text
    assert again.json()["sessions"] == 2
    assert again.json()["first_started_at"].split("+")[0] == state["first_started_at"].split("+")[0]
    with sessions() as db:
        row = db.get(MaxPowerState, ai_env["org_id"])
        assert row.enabled and row.sessions == 2
        events = list(db.scalars(select(MaxPowerEvent).where(
            MaxPowerEvent.org_id == ai_env["org_id"])))
        assert len(events) == 3
    outsider = signin(client, "outside")
    assert client.get(BASE).json()["sessions"] == 0
    assert client.post(BASE + "/control/off", headers=outsider).status_code == 409
