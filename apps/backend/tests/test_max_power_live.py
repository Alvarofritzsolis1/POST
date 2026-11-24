from datetime import datetime, timezone
from types import SimpleNamespace

from app.max_power_live import general_series, messenger_series, resource_metrics
from app.max_power_decisions import can_run

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


def event(**overrides):
    return SimpleNamespace(created_at=NOW, evidence={
        "source":"real_db_aggregate", "dataset_hash":"set-1", "round_state":"completed",
        "holdout_pairs":8, "holdout_baseline_rate":0.5, "holdout_candidate_rate":0.75,
        "holdout_wins":2, "holdout_losses":0, **overrides})


def trial(n, **overrides):
    return SimpleNamespace(source_run_id=str(n), criterion="understanding", status="completed",
        completed_at=NOW, outcome="objective_gain", metrics={"auto_evaluated":True,
        "baseline":{"answer_priority_check":False},"candidate":{"answer_priority_check":True}},
        **overrides)


def test_general_excludes_partial_duplicate_and_invalid():
    result = general_series([event(round_state="interrupted"), event(), event(),
                             event(dataset_hash="set-2", holdout_candidate_rate=2),
                             event(dataset_hash="set-3", holdout_pairs=7)])
    assert len(result) == 1
    assert result[0]["delta"] == 25
    assert result[0]["lab_verified"] is False


def test_general_can_decrease():
    result = general_series([event(holdout_candidate_rate=0.25, holdout_wins=0, holdout_losses=2)])
    assert result[0]["delta"] == -25


def test_messenger_distinct_evidence_minimum_and_regression():
    trials = [trial(n) for n in range(8)]
    duplicate = trial(0)
    synthetic = trial(9)
    synthetic.source_run_id = None
    regression = trial(10)
    regression.outcome = "safety_regression"
    regression.metrics["baseline"]["answer_priority_check"] = True
    regression.metrics["candidate"]["answer_priority_check"] = False
    points = messenger_series([*trials, duplicate, synthetic, regression])
    assert len(points) == 9
    assert points[6]["delta"] is None
    assert points[7]["delta"] == 100
    assert points[8]["delta"] < 100
    assert points[8]["net_cases"] == 7
    assert points[8]["safety_regressions"] == 1


def test_resources_only_finite_numeric_measurements():
    assert resource_metrics({"host_cpu_percent":83.2,"available_ram_mb":float("nan"),
                             "worker_ram_mb":True,"secret":"private"}) == {"host_cpu_percent":83.2}


def test_intensive_cpu_admission_keeps_hard_guards():
    snapshot = {"host_cpu_percent":85,"available_ram_mb":9000,"disk_free_mb":10000}
    assert not can_run(snapshot)[0]
    assert can_run(snapshot, intensive=True)[0]
    assert not can_run(snapshot, intensive=True, messenger_pending=True)[0]
    assert not can_run({**snapshot,"available_ram_mb":1000}, intensive=True)[0]
    assert not can_run({**snapshot,"host_cpu_percent":95}, intensive=True)[0]


def test_waiting_turn_does_not_block_but_active_or_draining_does():
    from datetime import timedelta
    from app.max_power_live import cpu_event_blocks
    assert not cpu_event_blocks({"state":"cpu_waiting_turn"},NOW,NOW)
    assert not cpu_event_blocks({"state":"legacy_lab_disabled"},NOW,NOW)
    assert cpu_event_blocks({"state":"training_synthetic"},NOW,NOW)
    assert not cpu_event_blocks({"state":"training"},NOW-timedelta(seconds=60),NOW)
    assert cpu_event_blocks({"state":"off","draining_until_epoch":NOW.timestamp()+10},NOW,NOW)


def test_synthetic_4b_only_reserved_completed_verified_model():
    from app.max_power_live import synthetic_4b_series, latency_series
    def item(case, split="holdout", model="qwen3.5:4b-q4_K_M", status="completed"):
        return SimpleNamespace(status=status,completed_at=NOW,metrics={
            "dataset_sha256":"abc","protocol":"v1","case_id":case,
            "model":model,"split":split,"baseline":{"understanding_check":False},
            "candidate":{"understanding_check":True},
            "before_timing_ms":{"ollama_total_ms":3000,"prompt_ms":2000},
            "after_timing_ms":{"ollama_total_ms":2000,"generation_ms":1000}})
    trials = [item("a"),item("a"),item("b","development"),item("c",model="qwen0.8b"),item("d",status="queued")]
    points = synthetic_4b_series(trials)
    assert len(points) == 1
    assert points[0]["preliminary"] is True
    assert points[0]["pairs"] == 1
    assert points[0]["candidate"] == 100
    times = latency_series([trials[0],trials[3],trials[4]])
    assert len(times) == 2
    assert times[0]["total_seconds"] == 3
    assert times[1]["generation_seconds"] == 1


def test_4b_memory_gate_requires_real_residency(monkeypatch):
    from app import max_power_worker as worker
    monkeypatch.setattr(worker,"isolated_model_resident",lambda _:False)
    assert not worker.qwen_memory_ready({"available_ram_mb":7000})
    assert worker.qwen_memory_ready({"available_ram_mb":9000})
    monkeypatch.setattr(worker,"isolated_model_resident",lambda _:True)
    assert worker.qwen_memory_ready({"available_ram_mb":4000})
    assert not worker.qwen_memory_ready({"available_ram_mb":2000})
    assert not worker.qwen_memory_ready({})


def test_dispatch_admission_uses_warm_model_policy(monkeypatch):
    from app import max_power_worker as worker
    monkeypatch.setattr(worker,"MAX_POWER_ISOLATED",True)
    monkeypatch.setattr(worker,"isolated_model_resident",lambda _:True)
    snapshot = {"host_cpu_percent":40,"available_ram_mb":4000,"disk_free_mb":10000}
    assert worker.practice_admission(snapshot)[0]
    assert not worker.practice_admission(snapshot,messenger_pending=True)[0]
    assert not worker.practice_admission({**snapshot,"available_ram_mb":2000})[0]
    monkeypatch.setattr(worker,"isolated_model_resident",lambda _:False)
    assert not worker.practice_admission(snapshot)[0]
    assert worker.practice_admission({**snapshot,"available_ram_mb":9000})[0]
    monkeypatch.setattr(worker,"MAX_POWER_ISOLATED",False)
    assert not worker.practice_admission({**snapshot,"available_ram_mb":9000})[0]
