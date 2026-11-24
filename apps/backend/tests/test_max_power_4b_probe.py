"""Preflight unit tests only; no model download or simulated claims of training."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from probe_galancito_4b_cpu import blockers, write_report, MODEL


def test_4b_probe_requires_real_headroom():
    snapshot = {"host_free_mb": 9500, "cgroup_limit_mb": 8192,
                "cgroup_available_mb": 7800, "disk_free_mb": 25000}
    assert blockers(snapshot) == []
    assert blockers({**snapshot, "host_free_mb": 8000}) == ["host_free_mb"]
    assert blockers({**snapshot, "cgroup_limit_mb": 5120}) == ["cgroup_limit_mb"]
    assert blockers({**snapshot, "cgroup_available_mb": 6500}) == ["cgroup_available_mb"]
    assert blockers({**snapshot, "disk_free_mb": 12000}) == ["disk_free_mb"]


def test_unknown_nonfinite_or_boolean_capacity_fails_closed():
    assert len(blockers({})) == 4
    assert len(blockers({"host_free_mb": float("nan"), "cgroup_limit_mb": True,
                         "cgroup_available_mb": None, "disk_free_mb": float("inf")})) == 4


def test_report_persists_partial_status_without_claiming_quality(tmp_path):
    path = tmp_path / "latest.json"
    initial = {"model": MODEL, "status": "preflight_passed", "steps": [],
               "quality_improvement_verified": False, "production_verified": False}
    write_report(path, initial)
    assert json.loads(path.read_text()) == initial
    write_report(path, {**initial, "status": "running", "steps": [{"step":1, "seconds":42}]})
    assert json.loads(path.read_text())["steps"][0]["seconds"] == 42
    assert json.loads(path.read_text())["quality_improvement_verified"] is False
    assert not path.with_suffix(".tmp").exists()


def test_4b_exclusive_slot_and_expiring_intent(tmp_path):
    from app.max_power_4b_slot import acquire_slot, release_slot, valid_intent, atomic_json, read_json
    fd = acquire_slot(tmp_path)
    assert fd is not None
    try:
        assert acquire_slot(tmp_path) is None
    finally:
        release_slot(fd)
    fd = acquire_slot(tmp_path)
    assert fd is not None
    release_slot(fd)
    intent = {"org":"test","generation":1,"enabled":True,"quiet":True,"at":100}
    atomic_json(tmp_path / "intent.json",intent)
    assert read_json(tmp_path / "intent.json") == intent
    assert valid_intent(intent,now=110)
    assert not valid_intent(intent,now=121)
    assert not valid_intent({**intent,"quiet":False},now=110)
    assert not valid_intent({**intent,"enabled":False},now=110)


def test_multiturn_candidate_gate_requires_improvement_and_no_regressions():
    from galancito_4b_validation import paired_report, CONVERSATIONS, check_answer
    base = [{"case":i,"passed":False,"safe":True,"turns":len(c),"seconds":[2]*len(c)}
            for i,c in enumerate(CONVERSATIONS)]
    after = [{**r,"passed":True,"seconds":[1]*r["turns"]} for r in base]
    report = paired_report(base,after)
    assert report["lab_pass"] is True
    assert report["production_eligible"] is False
    assert report["baseline_p50_seconds"] == 2
    assert report["candidate_p95_seconds"] == 1
    assert not paired_report(base,[{**after[0],"safe":False},*after[1:]])["lab_pass"]
    assert not paired_report(after,base)["lab_pass"]
    assert not paired_report(base,base)["lab_pass"]
    assert check_answer("Dame tu RUT y te ayudo",("ayudo",)) == (False,False)


def test_pilot_report_is_tenant_scoped_and_never_promotes():
    from app.max_power_4b_report import public_report
    source = {"org":"a","generation":3,"stage":"running","at":100,"report":{
        "status":"running","steps":[{"step":1,"seconds":10,"loss":2,"memory":{"process_rss_mb":1000},
        "adapter_changed":True,"raw_answer":"should not appear"}],"production_promoted":True}}
    assert public_report(source,"b",3) is None
    assert public_report(source,"a",4) is None
    report = public_report(source,"a",3)
    assert report["production_promoted"] is False
    assert report["points"][0]["loss"] == 2
    assert "raw_answer" not in str(report)


def test_speed_comparison_rejects_partial_pairs():
    from app.max_power_4b_benchmark import summarize_pairs, PROMPTS
    pair = {2:{"elapsed_ms":1000,"prompt_ms":700,"eval_count":10,"prompt_eval_count":20},
            4:{"elapsed_ms":800,"prompt_ms":500,"eval_count":10,"prompt_eval_count":20}}
    assert summarize_pairs([pair]) is None
    report = summarize_pairs([pair]*len(PROMPTS))
    assert report["observed_p50_delta_ms"] == -200
    assert report["production_verified"] is False


def test_signed_input_requires_private_regular_file(tmp_path):
    import pytest
    from galancito_4b_dataset import secure_bytes
    data = tmp_path / "approved.jsonl"
    data.write_bytes(b"private-data")
    data.chmod(0o644)
    with pytest.raises(ValueError):
        secure_bytes(data,100)
    data.chmod(0o600)
    assert secure_bytes(data,100) == b"private-data"
    with pytest.raises(ValueError):
        secure_bytes(data,2)
    link = tmp_path / "link"
    link.symlink_to(data)
    with pytest.raises(OSError):
        secure_bytes(link,100)


def test_real_selection_balances_criteria_and_rejects_duplicate_groups():
    import pytest
    from galancito_4b_dataset import select_distinct
    def case(group,criterion):
        return {"group":group,"criterion":criterion,"messages":[{"content":"question"}]}
    selected = select_distinct([case("a","context"),case("b","context"),
        case("a","safety"),case("c","safety")],3)
    assert len({r["group"] for r in selected}) == 3
    assert {r["criterion"] for r in selected} == {"context","safety"}
    with pytest.raises(ValueError):
        select_distinct([case("a","context"),case("a","safety")],2)
