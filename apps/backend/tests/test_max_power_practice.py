"""Synthetic practice, durable evidence and the public Messenger intake path."""
from sqlalchemy import func, select

from app.config import settings
from app.facebook_chat_worker import process_chat_next
from app.facebook_crm_models import FacebookLead
from app.max_power_messenger import objective_checks, process_one, schedule_synthetic_reply
from app.max_power_models import MaxPowerEvent, MaxPowerMessengerTrial, MaxPowerState
from app.max_power_practice import EVENT, SOURCE, generate_scenarios, practice_id, reply_cases, run_practice
from app.max_power_worker import tick
from test_ai_control_center import ai_env, signin
from test_facebook_crm import enable_messaging, incoming
from test_max_power_recovery import StaticSampler
from test_network import network

BASE = "/api/v1/admin/ai/max-power"


def test_fixed_synthetic_evidence_scores_fields_without_grading_humanity():
    scenarios = generate_scenarios()
    result = run_practice(scenarios)
    assert practice_id(scenarios) == practice_id(generate_scenarios())
    assert result["source"] == SOURCE
    assert result["weights_changed"] is result["production_verified"] is False
    for split in ("development", "holdout"):
        report = result[split]
        assert report["failed_checks"] == []
        assert report["safety"]["gate_passed"]
        assert report["dimensions"]["humanity"] == {"passed": None, "samples": 0}
        for counts in report["fields"].values():
            assert counts["passed"] == counts["samples"] > 0
    assert result["holdout"]["fields"]["employee_count"]["samples"] >= 2


def test_power_on_runs_once_without_model_or_real_cases(ai_env, monkeypatch):
    monkeypatch.setattr("app.max_power_worker.MAX_POWER_ISOLATED", False)
    monkeypatch.setattr("app.max_power_worker._pressure", lambda name: 0)
    client, sessions = ai_env["client"], ai_env["sessions"]
    admin = signin(client, "admin")
    assert client.post(BASE + "/control/on", headers=admin).status_code == 200
    with sessions() as db:
        tick(db, StaticSampler())
    status = client.get(BASE, headers=admin).json()
    assert status["enabled"] and status["status"] == "synthetic_practice_completed"
    practice = status["synthetic_practice"]
    assert practice["source"] == SOURCE and practice["holdout"]["cases"] > 8
    assert status["automatic_quality"]["messenger"]["pairs"] == 0
    assert status["experiments"] == 0
    export = client.get(BASE + "/export", headers=admin).json()
    assert export["synthetic_practice"]["source"] == SOURCE
    assert "example.invalid" not in str(export)
    outsider = signin(client, "outside")
    assert client.get(BASE, headers=outsider).json()["synthetic_practice"] is None
    admin = signin(client, "admin")
    assert client.post(BASE + "/control/off", headers=admin).status_code == 200
    assert client.post(BASE + "/control/on", headers=admin).status_code == 200
    with sessions() as db:
        tick(db, StaticSampler())
        assert db.get(MaxPowerState, ai_env["org_id"]).last_status == "awaiting_new_evidence"
        assert db.scalar(select(func.count()).select_from(MaxPowerEvent).where(MaxPowerEvent.event == EVENT)) == 1
        assert db.scalar(select(func.count()).select_from(FacebookLead)) == 0


def test_recent_messenger_traffic_delays_practice(ai_env, monkeypatch):
    monkeypatch.setattr("app.max_power_worker.messenger_recent", lambda db: True)
    client, sessions = ai_env["client"], ai_env["sessions"]
    admin = signin(client, "admin")
    assert client.post(BASE + "/control/on", headers=admin).status_code == 200
    with sessions() as db:
        tick(db, StaticSampler())
        assert db.get(MaxPowerState, ai_env["org_id"]).last_status == "resource_guard"
        assert db.scalar(select(func.count()).select_from(MaxPowerEvent).where(MaxPowerEvent.event == EVENT)) == 0


def test_webhook_answers_question_preserves_manual_count_and_sources(network, monkeypatch):
    enable_messaging(network, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "")
    settings.cache_clear()
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda page, psid, body, token: sent.append(body) or f"sent-{len(sent)}")
    first = "Soy gasfiter, busco pega y ofrezco servicios. Puedo ir con dos maestros."
    assert incoming(network, text=first, mid="first-professional").status_code == 200
    assert process_chat_next(network["Session"])
    assert incoming(network, text="Tenemos un trabajador contratado.", mid="hired-professional").status_code == 200
    assert process_chat_next(network["Session"])
    lead = network["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["interest_type"] == "both"
    assert lead["workers"] == 3
    assert lead["has_employees"] is True
    assert lead["employee_count"] == 1
    endpoint = "/facebook/leads/" + lead["id"]
    assert network["send"](network["admin"], endpoint, {"employee_count": 2}, "PATCH").status_code == 200
    assert incoming(network, text="Corrijo, tengo 4 trabajadores contratados. ¿Cuánto pagan?",
                    mid="manual-and-question").status_code == 200
    assert process_chat_next(network["Session"])
    lead = network["admin"].get("/api/v1/network" + endpoint).json()["lead"]
    assert lead["workers"] == 3
    assert lead["employee_count"] == 2
    assert lead["profile"]["sources"]["employee_count"]["source"] == "manual"
    assert lead["profile"]["sources"]["workers"]["message_id"] == "first-professional"
    assert "pago depende" in sent[-1]
    assert "?" not in sent[-1]


def test_audit_flags_repeat_of_known_non_trade_field():
    case = {"question": "Quiero saber cuánto pagan", "history": [
        {"role": "inbound", "text": "Trabajo en Coronel. Puedo partir el 30/11/2026."}
    ]}
    checks = objective_checks(case, "¿En qué comuna puedes trabajar?")
    assert checks["repeated_fields"] == ["work_communes"]
    assert checks["question_displaced"]


def test_synthetic_model_trials_checkpoint_once_per_case(ai_env, monkeypatch):
    client, sessions = ai_env["client"], ai_env["sessions"]
    admin = signin(client, "admin")
    assert client.post(BASE + "/control/on", headers=admin).status_code == 200
    monkeypatch.setattr("app.max_power_messenger.SessionLocal", sessions)
    # Exercise queue and scoring only. Actual inference has a separate local probe.
    monkeypatch.setattr("app.max_power_messenger._answer", lambda policy, prompt, seed, org: (
        "El equipo de la obra confirma el pago y los cupos.", {"ollama_total_ms": 50}))
    scenarios = generate_scenarios()
    org_id = ai_env["org_id"]
    for _ in reply_cases(scenarios):
        with sessions.begin() as db:
            assert schedule_synthetic_reply(db, org_id, scenarios)
        assert process_one()
    with sessions.begin() as db:
        assert not schedule_synthetic_reply(db, org_id, scenarios)
        rows = list(db.scalars(select(MaxPowerMessengerTrial)))
        assert len(rows) == len(reply_cases(scenarios))
        assert all(t.status == "completed" and t.source_run_id is None for t in rows)
        assert all(t.metrics["source"] == SOURCE and t.metrics["weights_changed"] is False for t in rows)
        assert db.get(MaxPowerState, org_id).experiments == 0
