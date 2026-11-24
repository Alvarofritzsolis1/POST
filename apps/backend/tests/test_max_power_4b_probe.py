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

def test_final_target_is_last_dense_projection_only():
    import pytest
    from probe_galancito_4b_cpu import select_target
    names=["model.layers.0","model.layers.0.mlp.down_proj","model.layers.1","model.layers.1.mlp.down_proj"]
    assert select_target(names)=="model.layers.1.mlp.down_proj"
    with pytest.raises(RuntimeError):
        select_target(names+["model.layers.2"])


def test_exact_base_revision():
    import pytest
    from probe_galancito_4b_cpu import snapshot_revision,REVISION
    config=Path("/cache/models--Qwen--Qwen3.5-4B/snapshots")/REVISION/"config.json"
    assert snapshot_revision(config,REVISION)==REVISION
    with pytest.raises(RuntimeError):
        snapshot_revision(config,"b"*40)
    with pytest.raises(RuntimeError):
        snapshot_revision(Path("/cache/models--Qwen--Qwen3.5-0.8B/snapshots")/REVISION/"config.json")


def test_neural_shared_lock_and_session_fence(tmp_path):
    from app.max_power_4b_control import lock,release,authorized,write,read
    from time import time
    fd=lock(tmp_path)
    assert fd is not None
    assert lock(tmp_path) is None
    release(fd)
    fd=lock(tmp_path)
    assert fd is not None
    release(fd)
    value={"org":"tenant","generation":7,"allowed":True,"at":time()}
    write(tmp_path/"intent.json",value)
    assert authorized(read(tmp_path/"intent.json"),"tenant",7)
    assert not authorized(value,"tenant",8)
    assert not authorized({**value,"at":time()-60},"tenant",7)
    assert not authorized({**value,"allowed":False},"tenant",7)


def test_4b_gate_does_not_claim_quality_on_tie_or_regression():
    from galancito_4b_conversation_gate import CASES,compare
    failed=[{"passed":False,"safe":True} for _ in CASES]
    passed=[{"passed":True,"safe":True} for _ in CASES]
    assert compare(failed,passed)["lab_pass"]
    assert not compare(passed,passed)["lab_pass"]
    assert not compare(passed,failed)["lab_pass"]
    assert not compare(failed,passed)["production_verified"]


def test_neural_report_never_exports_raw_chat_or_promotes():
    from app.max_power_4b_control import measured_report
    result=measured_report({"stage":"training","at":123,"generation":1,"report":{
        "steps":[{"step":1,"grad_norm":0.5,"loss":2,"seconds":5,"adapter_changed":True,
                  "raw_answer":"private"}],"production_promoted":True}})
    assert result["completed_steps"]==1
    assert result["production_promoted"] is False
    assert "private" not in str(result)


def test_signed_dataset_group_selection_requires_independent_groups():
    import pytest
    # Docker places the shared dataset validator beside the worker. Unit
    # tests use the exact backend module without modifying production imports.
    import sys
    from app import galancito_finetune_dataset
    from unittest.mock import patch
    with patch.dict(sys.modules,{"galancito_finetune_dataset":galancito_finetune_dataset}):
        from galancito_4b_approved import select_groups
    def row(g,c): return {"group":g,"criterion":c}
    picked=select_groups([row("a","context"),row("a","safety"),row("b","context"),row("c","safety")],3)
    assert len({r["group"] for r in picked})==3
    with pytest.raises(ValueError):
        select_groups([row("a","context"),row("a","safety")],2)
