"""MAX POWER: real evidence and honest limits (not fake improvement scores)."""
from types import SimpleNamespace
from app.max_power_decisions import (
    evidence_fingerprint, classify_outcome, latency_diagnosis,
    priority_from_reviews, can_run,
)

def test_fingerprint_stable_across_order():
    def case(label, count):
        return {"id": label, "category": "arithmetic", "question": "¿Cuántos?",
                "expected": count, "formula": "count",
                "evidence": {"agregados_reales": {"contratistas": count}},
                "evidence_hash": "volatile_time_must_not_affect_fingerprint"}
    a = [case("a", 1), case("b", 3)]
    assert evidence_fingerprint(a) == evidence_fingerprint(list(reversed(a)))
    assert evidence_fingerprint(a) != evidence_fingerprint([case("c", 2)])

def test_no_holdout_never_reports_gain():
    result = classify_outcome({"passed": 99, "failed": 1})
    assert result["code"] == "no_holdout"
    assert not result["lab_verified"] and not result["production_verified"]
    assert result["weights_changed"] is False

def test_regressions_block():
    x = classify_outcome({"real_holdout_gain_cases": 7, "real_holdout_regressions": 1,
                         "real_holdout_paired_cases": 8,
                         "real_learning_demonstrated": True, "real_coaching": ["foo"]})
    assert x["code"] == "regression" and not x["lab_verified"]

def test_no_improvement_explained():
    x = classify_outcome({"real_holdout_gain_cases": 0, "real_holdout_regressions": 0,
                         "real_holdout_paired_cases": 8, "real_coaching": ["guide"]})
    assert x["code"] == "plateau" and x["next"]

def test_verified_is_lab_only():
    x = classify_outcome({"real_holdout_gain_cases": 6, "real_holdout_regressions": 0,
                         "real_holdout_paired_cases": 8, "real_holdout_one_sided_p_value": 0.02,
                         "real_learning_demonstrated": True, "real_coaching": ["guide"],
                         "independent_worksite_groups": 4})
    assert x["lab_verified"] is True
    assert x["production_verified"] is False

def test_latency_components_and_missing():
    assert latency_diagnosis({})["code"] == "no_latency_evidence"
    x = latency_diagnosis({"load_ms": 2, "prompt_ms": 5, "generation_ms": 350})
    assert x["code"] == "generation_ms"
    assert x["measured_ms"] == 350

def test_audited_priorities_only():
    reviews = [SimpleNamespace(channel="messenger", ratings={"context": False, "safety": None}),
               SimpleNamespace(channel="messenger", ratings={"context": False, "safety": True})]
    assert priority_from_reviews(reviews)[0]["criterion"] == "context"
    assert priority_from_reviews(reviews)[0]["failures"] == 2

def test_resources_are_fail_closed():
    assert not can_run({"available_ram_mb": None, "host_cpu_percent": 1, "disk_free_mb": 4000})[0]
    assert not can_run({"available_ram_mb": 8000, "host_cpu_percent": 15, "disk_free_mb": 4000},
                       messenger_pending=True)[0]
    assert can_run({"available_ram_mb": 8000, "host_cpu_percent": 15, "disk_free_mb": 4000})[0]

def test_adaptive_plan_uses_resources_and_p95():
    from app.max_power_decisions import select_experiment_plan
    slow = select_experiment_plan({"available_ram_mb": 4200, "host_cpu_percent": 60}, 24, 88000)
    fast = select_experiment_plan({"available_ram_mb": 9000, "host_cpu_percent": 20}, 24, 2000)
    assert slow["cases"] == 8 and fast["cases"] == 12
    assert slow["minutes"] > fast["minutes"]
    assert slow["token_budget"] >= slow["cases"] * 4 * 2048

def test_balanced_operational_cases_come_from_distinct_worksites():
    from app.max_power_decisions import spread_live_cases_by_worksite
    cases=[{"id": f"live-{site:02}-{category}", "expected": site}
           for site in range(1,5) for category in range(1,9)]
    reordered=spread_live_cases_by_worksite(cases)
    assert len(reordered)==len(cases)
    assert sorted(row["id"] for row in reordered)==sorted(row["id"] for row in cases)
    # With 8 training + 8 reserved questions, both groups represent 4 sites.
    assert len({row["id"].split("-")[1] for row in reordered[8:16]})==4
    assert reordered==spread_live_cases_by_worksite(reordered)
