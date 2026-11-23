#!/usr/bin/env python3
"""One-button CPU LoRA supervisor in its OWN constrained container.

Only the already-running MAX POWER API decides ON/OFF and owner. This worker has
no database, Messenger storage or Docker socket. Real signed approved data must
exist in /private/<org_uuid>; no synthetic data or automated consent is created.
"""
from __future__ import annotations

from hashlib import sha256
import hmac
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from time import monotonic, sleep, time
from urllib.request import Request, urlopen
from uuid import UUID

sys.path.insert(0, "/src/apps/backend")
from galant_cpu_lora_resources import capacity_gate, snapshot
from galancito_lora_progress import ProgressReporter

LOG = logging.getLogger("max_power_cpu")
HOME = Path("/private")
API = "http://api:8000/api/v1/admin/ai/max-power/finetune"
MODEL = "Qwen/Qwen3.5-0.8B"
LOOP_SECONDS = 8
PREFLIGHT_RECHECK = 600
MAX_GRACE_SECONDS = 90
MAX_STEPS = 4
CHECKPOINT_STEPS = 2


def manager_headers(secret: str, when: str | None = None) -> dict:
    stamp = when or str(int(time()))
    signature = hmac.new(secret.encode(),
                         (stamp + ".cpu-lora-supervisor").encode(), sha256).hexdigest()
    return {
        "X-Galant-Manager-Timestamp": stamp,
        "X-Galant-Manager-Signature": signature,
    }


def api_call(path: str, secret: str, *, body: dict | None = None) -> dict:
    url = API + path
    raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
    headers = manager_headers(secret)
    if raw is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, headers=headers, data=raw,
                  method="POST" if raw is not None else "GET")
    with urlopen(req, timeout=8) as response:
        return json.load(response)


def valid_plan(plan: dict) -> tuple[str, int] | None:
    if not isinstance(plan, dict) or plan.get("enabled") is not True:
        return None
    try:
        org = str(UUID(str(plan["org_id"])))
        generation = int(plan["generation"])
        if generation < 1:
            return None
        return org, generation
    except (ValueError, TypeError, KeyError):
        return None


def private_files(org: str) -> tuple[Path, Path, Path]:
    # UUID is canonicalized BEFORE entering this path; no ../ traversal.
    root = HOME / str(UUID(org))
    return root, root / "approved.jsonl", root / "approval.json"


def approved_inputs(root: Path, data: Path, manifest: Path, public_key: str):
    """Reject missing consent evidence, weak file permissions and unsignable data."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", public_key or ""):
        return None
    if (not root.is_dir() or not data.is_file() or not manifest.is_file()
            or data.is_symlink() or manifest.is_symlink()):
        return None
    if (data.stat().st_mode & 0o077) or (manifest.stat().st_mode & 0o077):
        return None
    from app.galancito_finetune_dataset import load_approved, verified_training_manifest
    try:
        bundle = load_approved(data)
        attestation = verified_training_manifest(
            data, manifest, public_key, dataset_digest=bundle["dataset_digest"],
            training_model=MODEL)
    except (ValueError, TypeError, OSError, PermissionError):
        return None
    return bundle, attestation


def select_run(root: Path, digest: str) -> tuple[Path, bool, str]:
    """One deterministic 4-step pilot per signed dataset; no endless fake epochs."""
    path = root / "runs" / ("cpu-automatic-" + digest[:24])
    if not path.exists():
        return path, False, "new"
    if (path / "evaluation.json").exists():
        return path, False, "finished"
    checkpoints = list((path / "checkpoints").glob("checkpoint-*"))
    good = [p for p in checkpoints if p.is_dir()
            and (p / "trainer_state.json").is_file()
            and (p / "optimizer.pt").is_file()
            and (p / "scheduler.pt").is_file()]
    if good:
        return path, True, "resume"
    return path, False, "cannot_resume"


def write_control(path: Path, org: str, generation: int, allowed: bool):
    """Atomic heartbeat consumed by the Trainer callback at every optimizer step."""
    data = {"org_id": org, "generation": generation, "allowed": bool(allowed)}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def launch(root: Path, output: Path, resume: bool, org: str, generation: int,
           telemetry_token: str, public_key: str, control_file: Path):
    args = [
        sys.executable, "/src/scripts/train_galancito_cpu_lora.py",
        "--dataset", str(root / "approved.jsonl"),
        "--approval-manifest", str(root / "approval.json"),
        "--output", str(output), "--max-steps", str(MAX_STEPS),
        "--checkpoint-steps", str(CHECKPOINT_STEPS), "--execute",
        "--control-file", str(control_file),
        "--expected-generation", str(generation),
        "--telemetry-url", API + "/telemetry", "--telemetry-org", org,
    ]
    if resume:
        args.append("--resume")
    env = dict(os.environ)
    env["GALANT_OFFLINE_TRAINING_APPROVED"] = "yes"
    env["GALANT_DATASET_APPROVAL_PUBLIC_KEY"] = public_key
    env["GALANT_FINETUNE_TELEMETRY_TOKEN"] = telemetry_token
    env["GALANT_FINETUNE_ALLOW_PRIVATE_HTTP"] = "yes"
    return subprocess.Popen(args, env=env, close_fds=True)


def run_once(secret: str, plan: dict, public_key: str, last_preflight: dict) -> None:
    chosen = valid_plan(plan)
    if chosen is None:
        return
    org, generation = chosen
    root, data, manifest = private_files(org)
    token = hmac.new(secret.encode(), org.encode(), sha256).hexdigest()

    def report(code: str):
        try:
            api_call("/automation/status", secret, body={
                "org_id": org, "generation": generation, "status": code})
        except (OSError, ValueError) as exc:
            LOG.warning("Estado neuronal no enviado: %s", type(exc).__name__)

    if plan.get("messenger_busy"):
        report("messenger_priority")
        return
    if plan.get("practice_busy"):
        report("practice_priority")
        return
    report("preflight")
    resources = snapshot(root if root.exists() else HOME)
    gate = capacity_gate(resources)
    key = f"{org}:{generation}"
    if last_preflight.get(key) is None or monotonic() - last_preflight[key] >= PREFLIGHT_RECHECK:
        try:
            preflight_dir = HOME / "preflights" / org
            preflight_dir.mkdir(parents=True, exist_ok=True)
            reporter = ProgressReporter(preflight_dir / str(int(time())),
                run_id=str(__import__("uuid").uuid4()), org_id=org,
                dataset_sha256="0" * 64, model=MODEL,
                telemetry_url=API + "/telemetry", telemetry_token=token)
            try:
                reporter.emit("preflight", step=0, total_steps=0,
                              preflight_ready=gate["ready"],
                              host_free_mb=resources.get("host_free_mb"),
                              cgroup_limit_mb=resources.get("cgroup_limit_mb"),
                              cgroup_free_mb=resources.get("cgroup_free_mb"),
                              disk_free_mb=resources.get("disk_free_mb"))
            finally:
                reporter.close()
            last_preflight[key] = monotonic()
        except (OSError, ValueError) as exc:
            LOG.warning("Preflight local no enviado: %s", type(exc).__name__)
    if not gate["ready"]:
        report("awaiting_resources")
        return
    approved = approved_inputs(root, data, manifest, public_key)
    if approved is None:
        report("awaiting_approved_dataset")
        return
    bundle, _ = approved
    output, resume, run_state = select_run(root, bundle["dataset_digest"])
    if run_state == "finished":
        report("awaiting_new_dataset")
        return
    if run_state == "cannot_resume":
        report("cannot_resume")
        return
    control = root / ".max-power-automatic-control.json"
    write_control(control, org, generation, True)
    report("training")
    child = launch(root, output, resume, org, generation, token, public_key, control)
    paused_since = None
    while child.poll() is None:
        sleep(LOOP_SECONDS)
        try:
            latest = api_call("/automation/plan", secret)
            Path("/tmp/max_power_cpu_manager_heartbeat").touch()
            latest_key = valid_plan(latest)
            allowed = (latest_key == (org, generation)
                       and not latest.get("messenger_busy")
                       and not latest.get("practice_busy"))
        except (OSError, ValueError):
            # Fail closed: protect Messenger when supervision cannot be proven.
            allowed = False
        write_control(control, org, generation, allowed)
        if not allowed:
            if paused_since is None:
                paused_since = monotonic()
                report("pausing")
            # If a CPU step/model load never yields, stop it. Last completed
            # checkpoint survives; no interrupted step may claim learning.
            if monotonic() - paused_since > MAX_GRACE_SECONDS:
                child.terminate()
        else:
            paused_since = None
            report("training")  # heartbeat: prevent simultaneous 4B practice
    code = child.wait()
    if code == 0:
        report("finished")
    elif code == 3:
        report("paused")
    else:
        report("failed")


def main():
    logging.basicConfig(level=logging.INFO)
    secret = os.environ.get("GALANT_FINETUNE_METRICS_SECRET", "")
    if len(secret) < 48:
        raise SystemExit("Firma interna MAX POWER no configurada")
    public_key = os.environ.get("GALANT_DATASET_APPROVAL_PUBLIC_KEY", "").strip()
    HOME.mkdir(exist_ok=True, parents=True)
    last_preflight = {}
    while True:
        try:
            plan = api_call("/automation/plan", secret)
            Path("/tmp/max_power_cpu_manager_heartbeat").touch()
            if valid_plan(plan):
                run_once(secret, plan, public_key, last_preflight)
        except (OSError, ValueError) as exc:
            LOG.warning("MAX POWER CPU en espera: %s", type(exc).__name__)
        except Exception:
            LOG.exception("Falla aislada del coordinador de pesos CPU")
        sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main()
