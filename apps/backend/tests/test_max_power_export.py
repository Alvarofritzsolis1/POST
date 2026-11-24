"""MAX POWER -> ChatGPT: export real evidence, never conversations or secrets."""
from hashlib import sha256
import json

from sqlalchemy import select

from test_ai_control_center import ai_env, signin
from app.max_power_models import MaxPowerEvent, MaxPowerMessengerTrial
from app.max_power_export import safe_metrics, SCHEMA
from app.models import utcnow

BASE = "/api/v1/admin/ai/max-power"

def test_report_requires_admin_and_never_crosses_organizations(ai_env):
    client = ai_env["client"]
    assert client.get(BASE + "/export").status_code == 401
    resident = signin(client, "resident")
    assert client.get(BASE + "/export", headers=resident).status_code == 403

    admin = signin(client, "admin")
    first = client.get(BASE + "/export", headers=admin)
    assert first.status_code == 200, first.text
    assert first.json()["schema"] == SCHEMA
    assert first.json()["session"]["ever_started"] is False
    assert first.json()["measured_quality"]["messenger"]["baseline"] is None
    assert "no-store" in first.headers["cache-control"]  # global middleware overrides route header
    assert first.headers["x-content-type-options"] == "nosniff"
    assert "attachment;" in first.headers["content-disposition"]

    with ai_env["sessions"].begin() as db:
        db.add(MaxPowerEvent(
            org_id=ai_env["org_id"], event="experiment_completed",
            reason="Leak test: juana@example.cl sent her password", evidence={
                "holdout_wins": 4,
                "holdout_losses": 1,
                "production_verified": False,
                "api_key": "GHOST_SECRET_XYZ",
                "prompt": "DO NOT EVER EXPORT SECRET_PROMPT",
                "conversation": "Hola Juana, +56 9 9999 9999",
                "failed_by_criterion": {"reasoning": 3, "message": "PRIVATE_TEXT"},
                "model": "qwen3.5:4b-q4_K_M",
            },
        ))
        db.add(MaxPowerMessengerTrial(
            org_id=ai_env["org_id"],
            source_run_id=None,
            criterion="context", variant="focused",
            status="completed", outcome="objective_gain",
            metrics={
                "baseline": {"context_pass": False, "leaked_name": "Juana"},
                "candidate": {"context_pass": True, "leaked_name": "Juan"},
                "model": "qwen3.5:4b-q4_K_M",
                "paired_latency_delta_ms": -125,
                "raw_message": "Contractor Juan +56944445555",
                "secret": "OTHER_SECRET_98765",
            }
        ))
    response = client.get(BASE + "/export", headers=admin)
    assert response.status_code == 200, response.text
    body = response.json()
    text = response.text
    for secret in ("GHOST_SECRET_XYZ", "SECRET_PROMPT", "PRIVATE_TEXT",
                   "juana@example.cl", "Juana", "OTHER_SECRET_98765",
                   "+56 9 9999 9999", "+56944445555"):
        assert secret not in text
    assert ai_env["org_id"] not in text
    assert body["history"]["event_count_included"] == 1
    assert body["history"]["trials_count_included"] == 1
    assert body["history"]["events"][0]["measurements"]["holdout_wins"] == 4
    assert body["history"]["events"][0]["measurements"]["failed_by_criterion"] == {"reasoning": 3}
    assert body["history"]["messenger_trials"][0]["measurements"]["paired_latency_delta_ms"] == -125
    assert body["interpretation"]["production_improvement_verified"] is False
    assert body["handling"]["automatic_github_changes"] is False

    integrity = body.pop("integrity")
    canonical = json.dumps(body, ensure_ascii=False, allow_nan=False,
                           sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert sha256(canonical).hexdigest() == integrity["canonical_payload_without_integrity"]

    outsider = signin(client, "outside")
    other = client.get(BASE + "/export", headers=outsider)
    assert other.status_code == 200
    assert other.json()["history"]["event_count_total"] == 0
    assert other.json()["history"]["trials_count_total"] == 0

def test_report_remains_available_after_stopping(ai_env):
    client = ai_env["client"]
    headers = signin(client, "admin")
    assert client.post(BASE + "/control/on", headers=headers).status_code == 200
    with ai_env["sessions"].begin() as db:
        db.add(MaxPowerEvent(org_id=ai_env["org_id"],
                             event="experiment_completed",
                             reason="Meaningful progress saved",
                             evidence={"holdout_wins": 7, "lab_verified": True}))
    assert client.post(BASE + "/control/off", headers=headers).status_code == 200
    report = client.get(BASE + "/export", headers=headers).json()
    assert report["session"]["enabled_at_export"] is False
    assert report["history"]["event_count_included"] == 3
    assert any(event["measurements"].get("holdout_wins") == 7
               for event in report["history"]["events"])
    assert report["session"]["first_started_at_utc"] is not None

def test_allowlist_drops_unknown_and_non_finite_values():
    obj = {"holdout_wins": 3, "p_value": float("nan"),
           "secret_key": "ABCD-DO-NOT-EXPORT",
           "baseline": {"safe": True, "raw_reply": "private"},
           "model": "bad model with secrets",
           "criterion": "context",
           "holdout_pairs": True,
           "failed_by_criterion": {"context": 4, "leak": "private text"}}
    assert safe_metrics(obj) == {
        "holdout_wins": 3, "p_value": None, "criterion": "context",
        "baseline": {"safe": True},
        "failed_by_criterion": {"context": 4},
        "holdout_pairs": None,
    }


def test_export_neural_progress_is_not_other_or_replaced_by_preflight(ai_env):
    with ai_env["sessions"].begin() as db:
        db.add(MaxPowerEvent(org_id=ai_env["org_id"], round_id=ai_env["org_id"], event="ft_00000001",
            reason="checkpoint", evidence={"kind":"checkpoint","step":20,"total_steps":40,"cpu_memory_mb":2153.5,"sequence":1,
            "model":"Qwen/Qwen3.5-0.8B","private_prompt":"DO_NOT_EXPORT"}))
        from uuid import uuid4
        db.add(MaxPowerEvent(org_id=ai_env["org_id"], round_id=str(uuid4()), event="ft_00000002",
            reason="preflight", evidence={"kind":"preflight","step":0,"total_steps":0,"sequence":2,"preflight_ready":True}))
    response = ai_env["client"].get(BASE + "/export", headers=signin(ai_env["client"], "admin"))
    body = response.json()
    assert body["finetuning"]["step"] == 20 and body["finetuning"]["total_steps"] == 40
    assert any(e["kind"] == "finetune_checkpoint" and e["measurements"]["step"] == 20 for e in body["history"]["events"])
    assert "DO_NOT_EXPORT" not in response.text
