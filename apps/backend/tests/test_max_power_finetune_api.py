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
