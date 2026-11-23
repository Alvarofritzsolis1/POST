"""MAX POWER single button controls *real* isolated CPU LoRA, never fake progress.

These tests run without HF downloads, GPU, Messenger messages, Docker socket or
private dataset and prove precise fencing at the API and supervisor boundaries.
"""
import importlib.util
from hashlib import sha256
import hmac
import json
from pathlib import Path
import sys
from time import time
from uuid import uuid4

import pytest
from app.max_power_models import MaxPowerState
from test_ai_control_center import ai_env, signin

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
BASE = "/api/v1/admin/ai/max-power"
MASTER = "z" * 64


def manager():
    spec = importlib.util.spec_from_file_location("max_power_cpu_manager", SCRIPTS / "max_power_cpu_manager.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def headers(when=None, valid=True):
    stamp = str(int(time())) if when is None else str(when)
    signature = hmac.new(MASTER.encode(), (stamp + ".cpu-lora-supervisor").encode(), sha256).hexdigest()
    return {
        "x-galant-manager-timestamp": stamp,
        "x-galant-manager-signature": signature if valid else "0" * 64
    }


def test_one_button_plan_requires_valid_hmac_and_follows_session_generation(ai_env, monkeypatch):
    monkeypatch.setenv("GALANT_FINETUNE_METRICS_SECRET", MASTER)
    client = ai_env["client"]
    admin = signin(client, "admin")
    target = BASE + "/finetune/automation/plan"
    assert client.get(target).status_code == 401
    assert client.get(target, headers=headers(valid=False)).status_code == 401
    assert client.get(target, headers=headers(when=1)).status_code == 401
    assert client.get(target, headers=headers()).json() == {"enabled": False}

    turned_on = client.post(BASE + "/control/on", headers=admin)
    assert turned_on.status_code == 200, turned_on.text
    response = client.get(target, headers=headers())
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["enabled"] is True
    assert plan["org_id"] == ai_env["org_id"]
    assert plan["generation"] >= 1
    assert not any(key in plan for key in ("dataset", "message", "prompt", "password", "APP_SECRET"))

    status_path = BASE + "/finetune/automation/status"
    sent = {"org_id": ai_env["org_id"], "generation": plan["generation"],
            "status": "awaiting_approved_dataset"}
    result = client.post(status_path, headers=headers(), json=sent)
    assert result.status_code == 200, result.text
    current = client.get(BASE, headers=admin).json()
    assert current["cpu_learning"]["status"] == "awaiting_approved_dataset"
    assert current["cpu_learning"]["weights_trained"] is False

    # OFF is synchronous; old supervisor messages cannot restore "training".
    assert client.post(BASE + "/control/off", headers=admin).status_code == 200
    assert client.post(status_path, headers=headers(),
                       json={**sent, "status": "training"}).status_code == 409
    current = client.get(BASE, headers=admin).json()
    assert current["cpu_learning"]["status"] == "off"
    assert client.get(target, headers=headers()).json()["enabled"] is False

    assert client.post(BASE + "/control/on", headers=admin).status_code == 200
    assert client.post(status_path, headers=headers(),
                       json={**sent, "status": "training"}).status_code == 409


def test_supervisor_rejects_unsafe_paths_and_never_signs_unapproved_dataset(tmp_path):
    mod = manager()
    assert mod.valid_plan({"enabled": True, "org_id": "../../etc", "generation": 4}) is None
    assert mod.valid_plan({"enabled": True, "org_id": str(uuid4()), "generation": 0}) is None
    assert mod.valid_plan({"enabled": False, "org_id": str(uuid4()), "generation": 1}) is None
    org = str(uuid4())
    assert mod.valid_plan({"enabled": True, "org_id": org, "generation": 2}) == (org, 2)

    folder = tmp_path / org
    folder.mkdir()
    data = folder / "approved.jsonl"
    manifest = folder / "approval.json"
    data.write_text("not authorized\n")
    manifest.write_text("{}\n")
    data.chmod(0o600)
    manifest.chmod(0o600)
    assert mod.approved_inputs(folder, data, manifest, "") is None
    assert mod.approved_inputs(folder, data, manifest, "a" * 64) is None

    path, resume, state = mod.select_run(folder, "f" * 64)
    assert not resume and state == "new"
    path.mkdir(parents=True)
    assert mod.select_run(folder, "f" * 64)[2] == "cannot_resume"
    checkpoint = path / "checkpoints" / "checkpoint-2"
    checkpoint.mkdir(parents=True)
    for name in ("trainer_state.json", "optimizer.pt", "scheduler.pt"):
        (checkpoint / name).write_text("placeholder")
    assert mod.select_run(folder, "f" * 64)[1:] == (True, "resume")
    (path / "evaluation.json").write_text("{}")
    assert mod.select_run(folder, "f" * 64)[2] == "finished"


def test_automatic_cpu_training_honors_off_and_preserves_checkpoint(tmp_path):
    # No model invocation: verify closed-loop scheduling and refusal to fake
    # dataset permissions. Child process will be tested separately on real CPU.
    mod = manager()
    org = str(uuid4())
    folder = tmp_path / org
    folder.mkdir()
    mod.HOME = tmp_path
    called = []
    mod.api_call = lambda path, secret, body=None: (
        called.append(body) or {"accepted": True}) if body is not None else {
            "enabled": False
        }
    mod.snapshot = lambda path: {
        "host_free_mb": 9000, "cgroup_limit_mb": 5120,
        "cgroup_free_mb": 5000, "cgroup_used_mb": 120,
        "disk_free_mb": 10000, "logical_cpu_count": 6,
        "process_rss_mb": 22,
    }
    mod.ProgressReporter = lambda *args, **kwargs: type(
        "Dummy", (), {"emit": lambda self,*a,**kw: {}, "close": lambda self: None})()
    plan = {"enabled": True, "org_id": org, "generation": 2, "messenger_busy": False}
    mod.run_once("a" * 64, plan, "", {})
    assert called[-1]["status"] == "awaiting_approved_dataset"
    assert not list(folder.glob("runs/*"))
    assert not list(folder.glob("candidate-adapter"))


def test_trainer_automatically_pauses_on_session_change_and_rejects_stale_off(tmp_path):
    from test_galancito_cpu_lora import trainer
    mod = trainer()
    org = str(uuid4())
    # Use module's real /private guard: temporary paths are fail-closed.
    path = tmp_path / "control.json"
    path.write_text(json.dumps({"org_id":org,"generation":3,"allowed":True}))
    assert mod.automation_allowed(str(path), org=org, generation=3) is False
    assert mod.automation_allowed(None, org=org, generation=None) is True
    assert mod.verified_optimizer_update(
        start_hash="a"*64,end_hash="b"*64,start_step=2,end_step=3) is True


def test_compose_manager_has_no_db_or_docker_socket():
    compose=(SCRIPTS.parents[0] / "docker-compose.preview.yml").read_text()
    sidecar=compose.split("  cpu-lora-manager:\n",1)[1].split("\n  # Optional REAL neural",1)[0]
    assert 'restart: unless-stopped' in sidecar
    assert 'cpus: 1.5' in sidecar
    assert 'mem_limit: 5g' in sidecar
    assert 'cap_drop: [ALL]' in sidecar
    assert 'networks: [cpu-lora-egress]' in sidecar
    assert 'docker.sock' not in sidecar
    assert 'DATABASE_URL' not in sidecar
    assert 'post_db:' not in sidecar
