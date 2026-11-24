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
