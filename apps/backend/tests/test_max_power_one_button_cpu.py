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
    spoof = tmp_path / "other-org"
    spoof.symlink_to(folder, target_is_directory=True)
    assert mod.approved_inputs(spoof, spoof / "approved.jsonl",
                               spoof / "approval.json", "a" * 64) is None
    (folder / "runs").symlink_to(tmp_path, target_is_directory=True)
    assert mod.approved_inputs(folder, data, manifest, "a" * 64) is None
    (folder / "runs").unlink()

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
    assert mod.select_run(folder, "f" * 64)[2] == "cannot_resume"
    (path / "candidate-adapter").mkdir()
    (path / "candidate-adapter" / "adapter_model.safetensors").write_bytes(b"checkpoint")
    (path / "run-metadata.json").write_text(json.dumps({"dataset_sha256": "f" * 64, "data_kind": "curated_synthetic"}))
    (path / "evaluation.json").write_text(json.dumps({
        "dataset_sha256": "f" * 64, "base_model": mod.MODEL, "data_kind": "curated_synthetic",
        "weights_trained": True, "lora_weights_changed": True,
        "production_promoted": False, "new_optimizer_steps": 2,
        "optimizer_start_sha256": "a" * 64, "optimizer_end_sha256": "b" * 64,
    }))
    assert mod.select_run(folder, "f" * 64)[2] == "finished"
    (path / "evaluation.json").write_text(json.dumps({"weights_trained": True}))
    assert mod.select_run(folder, "f" * 64)[2] == "cannot_resume"


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



def test_signed_cpu_work_reserves_next_slot_without_interrupting_existing_practice(tmp_path):
    mod = manager()
    org = str(uuid4())
    root = tmp_path / org
    root.mkdir()
    mod.HOME = tmp_path
    statuses = []
    mod.api_call = lambda path, secret, body=None: (
        statuses.append(body["status"]) or {"accepted": True}
        if body is not None else {"enabled": True})
    mod.snapshot = lambda path: {
        "host_free_mb": 9600, "cgroup_limit_mb": 5120,
        "cgroup_free_mb": 5060, "cgroup_used_mb": 60,
        "disk_free_mb": 140000, "logical_cpu_count": 6,
        "process_rss_mb": 30,
    }
    mod.ProgressReporter = lambda *a, **kw: type(
        "Fake", (), {"emit": lambda self, *a, **kw: {}, "close": lambda self: None})()
    mod.approved_inputs = lambda *a: ({"dataset_digest": "f" * 64}, {"signed": True})
    mod.launch = lambda *a, **kw: pytest.fail("No iniciar gradientes durante la práctica 4B")
    mod.run_once("x" * 64, {
        "enabled": True, "org_id": org, "generation": 1,
        "messenger_busy": False, "practice_busy": True,
    }, "a" * 64, {})
    assert "cpu_waiting_turn" in statuses
    assert "training" not in statuses


def test_interrupted_precheckpoint_round_is_preserved_and_retried_only_twice(tmp_path):
    mod = manager()
    root = tmp_path / str(uuid4())
    (root / "runs").mkdir(parents=True)
    digest = "e" * 64
    path, _, state = mod.select_run(root, digest)
    assert state == "new"
    for index in (1, 2):
        path.mkdir()
        (path / "run-metadata.json").write_text(json.dumps({
            "dataset_sha256": digest, "model": mod.MODEL
        }))
        result, resume, state = mod.select_run(root, digest)
        assert result == path and resume is False and state == "new"
        assert path.with_name(path.name + f".interrupted-{index}").is_dir()
    path.mkdir()
    (path / "run-metadata.json").write_text(json.dumps({
        "dataset_sha256": digest, "model": mod.MODEL
    }))
    assert mod.select_run(root, digest)[2] == "cannot_resume"
    assert path.is_dir()


def test_failed_cpu_runs_have_persistent_exponential_backoff_and_hard_cap(tmp_path, monkeypatch):
    mod = manager()
    root = tmp_path / str(uuid4())
    (root / "runs").mkdir(parents=True)
    digest = "b" * 64
    clock = [10000.0]
    monkeypatch.setattr(mod, "time", lambda: clock[0])
    assert mod.retry_ready(root, digest)
    mod.record_failure(root, digest)
    assert mod.retry_state(root, digest)[0] == 1
    assert not mod.retry_ready(root, digest)
    clock[0] += 50
    assert mod.retry_ready(root, digest)
    mod.record_failure(root, digest)
    assert not mod.retry_ready(root, digest)
    clock[0] += 100
    assert mod.retry_ready(root, digest)
    mod.record_failure(root, digest)
    clock[0] += 999999
    assert mod.retry_state(root, digest)[0] == 3
    assert not mod.retry_ready(root, digest)



def test_one_button_with_no_real_dataset_launches_isolated_curated_lab(tmp_path, monkeypatch):
    """Button ON schedules a real child execution; only signed telemetry proves gradients."""
    mod = manager()
    mod.HOME = tmp_path
    monkeypatch.setenv("GALANT_MAX_POWER_SYNTHETIC_LORA", "yes")
    org = str(uuid4())
    plan = {"enabled": True, "org_id": org, "generation": 7,
            "messenger_busy": False, "practice_busy": False}
    reports, launches = [], []
    def api_call(path, secret, body=None):
        if path == "/automation/status":
            reports.append(body["status"])
            return {"accepted": True}
        return plan
    mod.api_call = api_call
    mod.snapshot = lambda target: {
        "host_free_mb": 9600, "cgroup_limit_mb": 5120,
        "cgroup_free_mb": 5060, "cgroup_used_mb": 60,
        "disk_free_mb": 140000, "logical_cpu_count": 6,
        "process_rss_mb": 30,
    }
    mod.ProgressReporter = lambda *args, **kwargs: type(
        "Fake", (), {"emit": lambda self,*a,**kw:{}, "close":lambda self:None})()
    class FinishedProcess:
        def poll(self): return 0
        def wait(self): return 0
    def fake_launch(root, output, resume, org_arg, generation, token, public_key, control,
                    *, synthetic=False):
        launches.append({"root": root, "output": output, "synthetic": synthetic,
                         "resume": resume, "org": org_arg})
        return FinishedProcess()
    mod.launch = fake_launch
    mod.run_once("a" * 64, plan, "", {})
    assert launches and launches[0]["synthetic"] is True
    assert launches[0]["root"].name == "synthetic-lab-galant-curated-synthetic-intake-2"
    assert launches[0]["org"] == org
    assert launches[0]["resume"] is False
    assert (launches[0]["root"] / "synthetic.jsonl").is_file()
    assert "preparing_synthetic" in reports
    assert "training_synthetic" not in reports
    # A fake child returning exit 0 cannot invent an optimizer result.
    assert reports[-1] == "failed"
    assert mod.select_run(launches[0]["root"], "0" * 64)[2] == "new"



def test_real_api_button_off_revokes_manager_training_lease(ai_env, tmp_path, monkeypatch):
    """Real admin API and HMAC manager handshake; synthetic model child is mocked.

    Neural gradient bytes are tested separately on actual Qwen in ML CI.
    """
    client = ai_env["client"]
    admin = signin(client, "admin")
    monkeypatch.setenv("GALANT_FINETUNE_METRICS_SECRET", MASTER)
    monkeypatch.setenv("GALANT_MAX_POWER_SYNTHETIC_LORA", "yes")
    mod = manager()
    mod.HOME = tmp_path
    mod.snapshot = lambda target: {
        "host_free_mb": 9600, "cgroup_limit_mb": 5120,
        "cgroup_free_mb": 5070, "cgroup_used_mb": 50,
        "disk_free_mb": 140000, "logical_cpu_count": 6,
        "process_rss_mb": 20,
    }
    mod.ProgressReporter = lambda *args, **kwargs: type(
        "Fake", (), {"emit": lambda self,*a,**kw:{}, "close":lambda self:None})()
    def signed_api(path, secret, *, body=None):
        url = BASE + "/finetune" + path
        response = (client.get(url, headers=headers()) if body is None
                    else client.post(url, headers=headers(), json=body))
        if response.status_code >= 400:
            raise OSError("La sesión apagada rechaza estados obsoletos")
        return response.json()
    mod.api_call = signed_api
    started = client.post(BASE + "/control/on", headers=admin)
    assert started.status_code == 200
    plan = signed_api("/automation/plan", MASTER)
    assert plan["enabled"] is True
    launched = []
    class Child:
        seen = 0
        def poll(self):
            self.seen += 1
            return None if self.seen == 1 else 3
        def wait(self): return 3
        def terminate(self): pass
    def child_launch(root, output, resume, org, generation, token, public_key,
                     control, *, synthetic=False):
        assert synthetic is True and generation == plan["generation"]
        launched.append(control)
        return Child()
    mod.launch = child_launch
    def power_off_during_training(_seconds):
        res = client.post(BASE + "/control/off", headers=admin)
        assert res.status_code == 200
    mod.sleep = power_off_during_training
    mod.run_once(MASTER, plan, "", {}, {})
    assert launched, "El botón no inició el supervisor sintético"
    lease = json.loads(launched[0].read_text())
    assert lease["allowed"] is False
    assert lease["generation"] == plan["generation"]
    result = client.get(BASE, headers=admin).json()
    assert result["enabled"] is False
    assert result["cpu_learning"]["status"] == "off"
    assert result["cpu_learning"]["synthetic_weights_trained"] is False
