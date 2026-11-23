"""Real QLoRA telemetry: HMAC, consented tenant scope and no fabricated metrics."""
from hashlib import sha256
import hmac
import json
from time import time
from uuid import uuid4

from sqlalchemy import select
from app.max_power_models import MaxPowerEvent
from test_ai_control_center import ai_env, signin

URL = "/api/v1/admin/ai/max-power/finetune"
MASTER = "t" * 64


def _signed(org, run, sequence, *, kind="metric", step=2, total=10, loss=1.25):
    payload = {
        "org_id": org, "run_id": run, "sequence": sequence, "kind": kind,
        "dataset_sha256": "a" * 64, "model": "Qwen/Qwen3.5-4B",
        "step": step, "total_steps": total,
        "loss": loss, "gpu_memory_mb": 999.5, "weights_trained": False,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    stamp = str(int(time()))
    token = hmac.new(MASTER.encode(), org.encode(), sha256).hexdigest()
    signature = hmac.new(bytes.fromhex(token), (stamp + ".").encode() + raw,
                         sha256).hexdigest()
    return raw, {
        "content-type": "application/json",
        "x-galant-telemetry-timestamp": stamp,
        "x-galant-telemetry-signature": signature,
    }


def test_metrics_disabled_without_config_and_admin_only(ai_env, monkeypatch):
    monkeypatch.delenv("GALANT_FINETUNE_METRICS_SECRET", raising=False)
    client = ai_env["client"]
    assert client.get(URL).status_code == 401
    resident = signin(client, "resident")
    assert client.get(URL, headers=resident).status_code == 403
    admin = signin(client, "admin")
    assert client.get(URL, headers=admin).status_code == 200
    assert client.get(URL, headers=admin).json()["configured"] is False
    assert client.post(URL + "/token", headers=admin).status_code == 503


def test_signed_telemetry_is_idempotent_private_and_tenant_scoped(ai_env, monkeypatch):
    monkeypatch.setenv("GALANT_FINETUNE_METRICS_SECRET", MASTER)
    client, sessions = ai_env["client"], ai_env["sessions"]
    admin = signin(client, "admin")
    secret = client.post(URL + "/token", headers=admin)
    assert secret.status_code == 200, secret.text
    credentials = secret.json()
    org = credentials["organization_id"]
    run = str(uuid4())
    assert credentials["telemetry_token"] == hmac.new(
        MASTER.encode(), org.encode(), sha256).hexdigest()
    for seq,kind,step in ((1,"start",0),(2,"metric",2),(3,"eval",4)):
        raw,headers = _signed(org,run,seq,kind=kind,step=step)
        response = client.post(URL + "/telemetry",content=raw,headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["duplicate"] is False
    raw,headers = _signed(org,run,3,kind="eval",step=4)
    assert client.post(URL + "/telemetry",content=raw,headers=headers).json()["duplicate"]
    bad = dict(headers); bad["x-galant-telemetry-signature"] = "b"*64
    assert client.post(URL + "/telemetry",content=raw,headers=bad).status_code == 401
    malformed = dict(json.loads(raw)); malformed["message"] = "PRIVATE PERSON DATA"
    forged = json.dumps(malformed,sort_keys=True,separators=(",",":")).encode()
    token = credentials["telemetry_token"]
    sig=hmac.new(bytes.fromhex(token),
                 (headers["x-galant-telemetry-timestamp"]+".").encode()+forged,
                 sha256).hexdigest()
    bad={**headers,"x-galant-telemetry-signature":sig}
    assert client.post(URL+"/telemetry",content=forged,headers=bad).status_code == 422
    current=client.get(URL,headers=admin).json()
    assert len(current["runs"]) == 1
    assert current["runs"][0]["step"] == 4
    assert current["runs"][0]["percent"] == 40
    assert len(current["runs"][0]["points"]) == 3
    assert current["runs"][0]["weights_trained"] is False
    assert current["production_promoted"] is False
    assert "PRIVATE PERSON DATA" not in json.dumps(current)
    with sessions() as db:
        entries=list(db.scalars(select(MaxPowerEvent).where(
            MaxPowerEvent.org_id==org,MaxPowerEvent.round_id==run)))
        assert len(entries)==3
        assert all("message" not in (e.evidence or {}) for e in entries)
    regular=client.get("/api/v1/admin/ai/max-power",headers=admin).json()
    assert all(not event["event"].startswith("ft_") for event in regular["events"])
    report=client.get("/api/v1/admin/ai/max-power/export",headers=admin).json()
    assert report["finetuning"]["step"] == 4
    assert report["finetuning"]["loss_last"] == 1.25
    assert report["finetuning"]["weights_training_reported"] is False
    assert report["finetuning"]["production_promoted"] is False
    outsider=signin(client,"outside")
    assert client.get(URL,headers=outsider).json()["runs"] == []


def test_telemetry_rejects_replayed_time_and_invalid_progress(ai_env, monkeypatch):
    monkeypatch.setenv("GALANT_FINETUNE_METRICS_SECRET", MASTER)
    client=ai_env["client"]
    org=ai_env["org_id"]
    raw,headers=_signed(org,str(uuid4()),1,step=12,total=10)
    assert client.post(URL+"/telemetry",content=raw,headers=headers).status_code==422
    headers["x-galant-telemetry-timestamp"]="1"
    assert client.post(URL+"/telemetry",content=raw,headers=headers).status_code==422



def test_signed_cpu_lora_progress_is_visible_without_faking_gpu_metrics(ai_env, monkeypatch):
    monkeypatch.setenv("GALANT_FINETUNE_METRICS_SECRET", MASTER)
    client = ai_env["client"]
    admin = signin(client, "admin")
    org = ai_env["org_id"]
    run_id = str(uuid4())
    payload = {
        "org_id": org, "run_id": run_id, "sequence": 1, "kind": "paused",
        "dataset_sha256": "d" * 64, "model": "Qwen/Qwen3.5-0.8B",
        "step": 6, "total_steps": 40, "cpu_memory_mb": 3130.5,
        "weights_trained": True, "candidate_accepted": False,
        "optimizer_start_sha256": "a" * 64,
        "optimizer_end_sha256": "b" * 64,
        "optimizer_steps_new": 2,
    }
    raw=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    stamp=str(int(time()))
    token=hmac.new(MASTER.encode(),org.encode(),sha256).hexdigest()
    signature=hmac.new(bytes.fromhex(token),(stamp+".").encode()+raw,sha256).hexdigest()
    headers={"content-type":"application/json",
             "x-galant-telemetry-timestamp":stamp,
             "x-galant-telemetry-signature":signature}
    received=client.post(URL+"/telemetry",content=raw,headers=headers)
    assert received.status_code==200,received.text
    status=client.get(URL,headers=admin).json()
    row=status["runs"][0]
    assert row["model"]=="Qwen/Qwen3.5-0.8B"
    assert row["stage"]=="paused"
    assert row["percent"]==15.0
    assert row["points"][0]["cpu_memory_mb"]==3130.5
    assert row["points"][0]["gpu_memory_mb"] is None
    assert row["weights_trained"] is True
    regular = client.get("/api/v1/admin/ai/max-power", headers=admin).json()
    assert regular["cpu_learning"]["weights_trained"] is True
    assert row["points"][0]["optimizer_steps_new"] == 2
    assert row["candidate_accepted"] is False
    assert status["production_promoted"] is False
    report=client.get("/api/v1/admin/ai/max-power/export",headers=admin).json()
    assert report["finetuning"]["cpu_memory_mb_last"]==3130.5
    assert report["finetuning"]["production_promoted"] is False



def test_signed_cpu_preflight_shows_actual_capacity_but_never_learning(ai_env, monkeypatch):
    monkeypatch.setenv("GALANT_FINETUNE_METRICS_SECRET", MASTER)
    client = ai_env["client"]
    admin = signin(client, "admin")
    org = ai_env["org_id"]
    run_id = str(uuid4())
    sample = {
        "org_id": org, "run_id": run_id, "sequence": 1, "kind": "preflight",
        "dataset_sha256": "0" * 64, "model": "Qwen/Qwen3.5-0.8B",
        "step": 0, "total_steps": 0, "preflight_ready": False,
        "host_free_mb": 4945.0, "cgroup_free_mb": 4490.0,
        "cgroup_limit_mb": 5120.0, "disk_free_mb": 9100.0,
        "weights_trained": False, "candidate_accepted": False,
    }
    raw = json.dumps(sample, sort_keys=True, separators=(",", ":")).encode()
    stamp = str(int(time()))
    token = hmac.new(MASTER.encode(), org.encode(), sha256).hexdigest()
    sig = hmac.new(bytes.fromhex(token), (stamp + ".").encode() + raw, sha256).hexdigest()
    headers = {"content-type": "application/json",
               "x-galant-telemetry-timestamp": stamp,
               "x-galant-telemetry-signature": sig}
    result = client.post(URL + "/telemetry", content=raw, headers=headers)
    assert result.status_code == 200, result.text
    snapshot = client.get(URL, headers=admin).json()
    assert snapshot["runs"] == []  # Checking RAM is not a training run.
    preflight = snapshot["cpu_preflight"]
    assert preflight["stage"] == "preflight"
    assert preflight["step"] == 0
    assert preflight["percent"] is None
    assert preflight["points"][0]["preflight_ready"] is False
    assert preflight["points"][0]["host_free_mb"] == 4945.0
    assert preflight["weights_trained"] is False
    assert snapshot["production_promoted"] is False
    sample["weights_trained"] = True  # Forbidden false evidence.
    raw = json.dumps(sample, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(bytes.fromhex(token), (stamp + ".").encode() + raw, sha256).hexdigest()
    invalid = client.post(URL + "/telemetry", content=raw,
                          headers={**headers, "x-galant-telemetry-signature": sig})
    assert invalid.status_code == 422
    outsider = signin(client, "outside")
    other = client.get(URL, headers=outsider).json()
    assert other["cpu_preflight"] is None
