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
