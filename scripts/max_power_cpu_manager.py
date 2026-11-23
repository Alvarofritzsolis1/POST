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
MAX_FAILED_ATTEMPTS = 3


def manager_headers(secret: str, when: str | None = None,
                    *, method: str = "GET", route: str = "/automation/plan",
                    body: bytes = b"") -> dict:
    stamp = when or str(int(time()))
    assert (method, route) in {("GET", "/automation/plan"), ("POST", "/automation/status")}
    signed = f"{stamp}.{method}.{route}.{sha256(body).hexdigest()}".encode("ascii")
    signature = hmac.new(secret.encode(), signed, sha256).hexdigest()
    return {
        "X-Galant-Manager-Timestamp": stamp,
        "X-Galant-Manager-Signature": signature,
    }


def api_call(path: str, secret: str, *, body: dict | None = None) -> dict:
    url = API + path
    raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
    method = "POST" if raw is not None else "GET"
    headers = manager_headers(secret, method=method, route=path, body=raw or b"")
    if raw is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, headers=headers, data=raw,
                  method=method)
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


def readiness_blocker(root: Path, data: Path, manifest: Path, public_key: str) -> str | None:
    """Classify missing prerequisites without opening or exporting private examples."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", public_key or ""):
        return "approval_public_key_missing"
    if not root.is_dir():
        return "approved_dataset_missing"
    if root.is_symlink() or (root / "runs").is_symlink():
        return "approved_dataset_rejected"
    if not data.is_file():
        return "approved_dataset_missing"
    if not manifest.is_file():
        return "approval_manifest_missing"
    if data.is_symlink() or manifest.is_symlink():
        return "approved_dataset_rejected"
    try:
        if (data.stat().st_mode & 0o077) or (manifest.stat().st_mode & 0o077):
            return "private_file_permissions"
    except OSError:
        return "approved_dataset_rejected"
    return None


def approved_inputs(root: Path, data: Path, manifest: Path, public_key: str):
    """Reject missing consent evidence, weak file permissions and unsignable data."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", public_key or ""):
        return None
    if (not root.is_dir() or root.is_symlink()
            or (root / "runs").is_symlink()
            or not data.is_file() or not manifest.is_file()
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
    # An interrupted model load or the first optimizer step may have written
    # metadata but not a checkpoint. Do not remain deadlocked forever. Preserve
    # the failed attempt under its organization (no deletion or model promotion)
    # and allow up to two bounded, fresh retries. Never replace a candidate.
    meta = path / "run-metadata.json"
    if not meta.is_file() or path.is_symlink() or (path / "candidate-adapter").exists():
        return path, False, "cannot_resume"
    try:
        parsed = json.loads(meta.read_text(encoding="utf-8"))
        if parsed.get("dataset_sha256") != digest or parsed.get("model") != MODEL:
            return path, False, "cannot_resume"
        if (path / "checkpoints").is_symlink():
            return path, False, "cannot_resume"
        for attempt in (1, 2):
            archive = path.with_name(path.name + f".interrupted-{attempt}")
            if not archive.exists() and not archive.is_symlink():
                path.rename(archive)
                LOG.warning("Checkpoint no iniciado; ronda privada conservada para reintentar: %s", attempt)
                return path, False, "new"
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return path, False, "cannot_resume"


def retry_state(root: Path, digest: str) -> tuple[int, float]:
    """Persistent bounded retries: resource failures never cause a tight loop."""
    path = root / "runs" / ("cpu-automatic-" + digest[:24] + ".failures.json")
    if not path.is_file() or path.is_symlink():
        return 0, 0.0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return max(0, min(MAX_FAILED_ATTEMPTS, int(data["count"]))), max(0.0, float(data["at"]))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return MAX_FAILED_ATTEMPTS, time()  # fail closed on corrupt retry state


def record_failure(root: Path, digest: str):
    previous, _ = retry_state(root, digest)
    path = root / "runs" / ("cpu-automatic-" + digest[:24] + ".failures.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"count": min(MAX_FAILED_ATTEMPTS, previous+1), "at": time()})
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def retry_ready(root: Path, digest: str) -> bool:
    attempts, when = retry_state(root, digest)
    if attempts >= MAX_FAILED_ATTEMPTS:
        return False
    return time() - when >= (min(900, 45 * 2**(attempts-1)) if attempts else 0)


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


def run_once(secret: str, plan: dict, public_key: str, last_preflight: dict,
             status_cache: dict | None = None) -> None:
    chosen = valid_plan(plan)
    if chosen is None:
        return
    org, generation = chosen
    status_cache = status_cache if status_cache is not None else {}
    root, data, manifest = private_files(org)
    token = hmac.new(secret.encode(), org.encode(), sha256).hexdigest()

    def report(code: str):
        marker = (org, generation)
        old = status_cache.get(marker)
        if old and old[0] == code and monotonic() - old[1] < 25:
            return
        try:
            api_call("/automation/status", secret, body={
                "org_id": org, "generation": generation, "status": code})
            status_cache[marker] = (code, monotonic())
        except (OSError, ValueError) as exc:
            LOG.warning("Estado neuronal no enviado: %s", type(exc).__name__)

    if plan.get("messenger_busy"):
        report("messenger_priority")
        return
    # Do not reserve CPU time until signed private examples and sufficient
    # real resources exist; evaluation practice must otherwise keep running.
    resources = snapshot(root if root.exists() else HOME)
    gate = capacity_gate(resources)
    key = f"{org}:{generation}"
    if last_preflight.get(key) is None or monotonic() - last_preflight[key] >= PREFLIGHT_RECHECK:
        report("preflight")
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
    missing = readiness_blocker(root, data, manifest, public_key)
    if missing:
        report(missing)
        return
    approved = approved_inputs(root, data, manifest, public_key)
    if approved is None:
        report("approved_dataset_rejected")
        return
    bundle, _ = approved
    output, resume, run_state = select_run(root, bundle["dataset_digest"])
    if not retry_ready(root, bundle["dataset_digest"]):
        report("retry_cooldown" if retry_state(root, bundle["dataset_digest"])[0] < MAX_FAILED_ATTEMPTS
               else "retry_exhausted")
        return
    if run_state == "finished":
        report("awaiting_new_dataset")
        return
    if run_state == "cannot_resume":
        report("cannot_resume")
        return
    if plan.get("practice_busy"):
        # Give already-running 4B practice its full turn; prevent new rounds
        # from starting so authorized CPU LoRA eventually gets CPU time.
        report("cpu_waiting_turn")
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
    elif code == 3 or (code == -15 and paused_since is not None):
        report("paused")
    else:
        record_failure(root, bundle["dataset_digest"])
        report("failed")


def main():
    logging.basicConfig(level=logging.INFO)
    secret = os.environ.get("GALANT_FINETUNE_METRICS_SECRET", "")
    if len(secret) < 48:
        raise SystemExit("Firma interna MAX POWER no configurada")
    public_key = os.environ.get("GALANT_DATASET_APPROVAL_PUBLIC_KEY", "").strip()
    HOME.mkdir(exist_ok=True, parents=True)
    last_preflight = {}
    status_cache = {}
    while True:
        try:
            plan = api_call("/automation/plan", secret)
            Path("/tmp/max_power_cpu_manager_heartbeat").touch()
            if valid_plan(plan):
                run_once(secret, plan, public_key, last_preflight, status_cache)
        except (OSError, ValueError) as exc:
            LOG.warning("MAX POWER CPU en espera: %s", type(exc).__name__)
        except Exception:
            LOG.exception("Falla aislada del coordinador de pesos CPU")
        sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main()
