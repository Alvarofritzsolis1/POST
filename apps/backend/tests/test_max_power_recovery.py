"""MAX POWER crash recovery, idempotence and session fencing.

These tests are intentionally independent of Ollama and never assert fake
learning gains; they verify durable state transitions in the real DB layer.
"""
from sqlalchemy import select
from app.galancito_training_models import TrainingRound
from app.max_power_worker import tick
from app.max_power_models import MaxPowerState, MaxPowerEvent, MaxPowerMessengerTrial
from test_ai_control_center import ai_env, signin

BASE = "/api/v1/admin/ai/max-power"

class StaticSampler:
    def sample(self):
        return {"available_ram_mb": 8192, "host_cpu_percent": 25,
                "disk_free_mb": 8096, "worker_ram_mb": 20,
                "worker_ram_limit_mb": 384, "worker_cores": 1,
                "host_ram_mb": 8192, "host_cores": 2}

def test_finished_round_is_recorded_once_across_repeated_ticks(ai_env):
    client, sessions = ai_env["client"], ai_env["sessions"]
    admin = signin(client, "admin")
    assert client.post(BASE + "/control/on", headers=admin).status_code == 200
    with sessions.begin() as db:
        state = db.get(MaxPowerState, ai_env["org_id"])
        original_generation = state.session_generation
        row = TrainingRound(
            org_id=ai_env["org_id"], created_by=state.owner_id,
            target=8, completed=8, state="completed",
            config={"orchestrator":"max_power", "cases": 2, "cycles": 4,
                    "profile":"interno", "suite":"live", "model":{"model":"qwen3.5:4b-q4_K_M"}},
            dataset_hash="b"*64, prompt_version="a"*64,
            system_version="20.9.22-rc1@test", knowledge=[], aliases={},
            metrics={"passed":8, "failed":0, "turns":8,
                     "evidence_type":"live_database", "real_holdout_paired_cases":2,
                     "real_holdout_gain_cases":0, "real_holdout_regressions":0,
                     "real_coaching":["example rule"]})
        db.add(row)
        db.flush()
        round_id = row.id
        state.active_round_id = round_id
    with sessions() as db:
        tick(db, StaticSampler())
    with sessions() as db:
        tick(db, StaticSampler())
        state = db.get(MaxPowerState, ai_env["org_id"])
        assert state.experiments == 1
        assert state.examined_cases == 8
        assert state.session_generation == original_generation
        assert state.last_round_id == round_id
        assert state.lab_gains == 0
        journals = list(db.scalars(select(MaxPowerEvent).where(
            MaxPowerEvent.org_id == ai_env["org_id"],
            MaxPowerEvent.round_id == round_id,
            MaxPowerEvent.event == "experiment_completed")))
        assert len(journals) == 1
        # Simulate an old row ID restored by a previous process.
        state.active_round_id = round_id
        db.commit()
        tick(db, StaticSampler())
    with sessions() as db:
        state = db.get(MaxPowerState, ai_env["org_id"])
        assert state.experiments == 1
        assert state.examined_cases == 8

def test_power_cycle_invalidates_messenger_claim_without_discarding_queue(ai_env):
    client, sessions = ai_env["client"], ai_env["sessions"]
    admin = signin(client, "admin")
    assert client.post(BASE + "/control/on", headers=admin).status_code == 200
    with sessions.begin() as db:
        state = db.get(MaxPowerState, ai_env["org_id"])
        generation = state.session_generation
        db.add(MaxPowerMessengerTrial(org_id=ai_env["org_id"], review_id=None,
               source_run_id=None, criterion="context", variant="focused",
               status="running", attempts=1, claim_token="old-inference-token"))
    assert client.post(BASE + "/control/off", headers=admin).status_code == 200
    with sessions() as db:
        state = db.get(MaxPowerState, ai_env["org_id"])
        trial = db.scalar(select(MaxPowerMessengerTrial).where(
            MaxPowerMessengerTrial.org_id == ai_env["org_id"]))
        assert trial.status == "queued"
        assert trial.claim_token is None
        assert state.session_generation == generation + 1
    assert client.post(BASE + "/control/on", headers=admin).status_code == 200
    with sessions() as db:
        state = db.get(MaxPowerState, ai_env["org_id"])
        assert state.session_generation == generation + 2
        assert state.experiments == 0
        assert state.sessions == 2

def test_fingerprint_accepts_repeated_ids_with_different_real_evidence():
    from app.max_power_decisions import evidence_fingerprint
    base={"id":"same", "category":"contratistas", "question":"¿Cuántos?",
          "expected":2, "formula":"n",
          "evidence":{"agregados_reales":{"obra_1":2}}}
    other={**base, "evidence":{"agregados_reales":{"obra_2":2}}}
    result=evidence_fingerprint([base,other])
    assert result == evidence_fingerprint([other,base])
    assert result != evidence_fingerprint([base])


def test_inference_started_before_off_on_cannot_record_fake_improvement(ai_env, monkeypatch):
    """A slow completed inference is fenced after OFF/ON, even if it looks better."""
    from app import max_power_messenger as messenger
    client, sessions = ai_env["client"], ai_env["sessions"]
    admin = signin(client, "admin")
    assert client.post(BASE + "/control/on", headers=admin).status_code == 200
    with sessions.begin() as db:
        db.add(MaxPowerMessengerTrial(
            org_id=ai_env["org_id"], review_id=None, source_run_id=None,
            criterion="context", variant="focused", status="queued"))
    monkeypatch.setattr(messenger, "SessionLocal", sessions)
    def after_slow_inference(_trial_id):
        stopped = client.post(BASE + "/control/off", headers=admin)
        assert stopped.status_code == 200, stopped.text
        restarted = client.post(BASE + "/control/on", headers=admin)
        assert restarted.status_code == 200, restarted.text
        return ("objective_gain", "Se corrigió una pregunta repetida",
                {"channel":"messenger","objective_gain":True,
                 "paired_latency_delta_ms":-300,"production_verified":False})
    monkeypatch.setattr(messenger, "evaluate_trial", after_slow_inference)
    assert messenger.process_one()
    with sessions() as db:
        state = db.get(MaxPowerState, ai_env["org_id"])
        trial = db.scalar(select(MaxPowerMessengerTrial).where(
            MaxPowerMessengerTrial.org_id == ai_env["org_id"]))
        assert state.experiments == 0
        assert state.session_generation == 3
        assert trial.status == "queued"
        assert trial.outcome is None
        assert trial.claim_token is None
        accepted = list(db.scalars(select(MaxPowerEvent).where(
            MaxPowerEvent.org_id == ai_env["org_id"],
            MaxPowerEvent.event == "messenger_experiment")))
        assert accepted == []
