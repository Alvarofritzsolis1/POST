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
PREFLIGHT_RECHECK = 60
RECOVERY_RECHECK = 1800
MAX_GRACE_SECONDS = 90
MAX_STEPS = 4
SYNTHETIC_STEPS = 40  # bounded pilot, not a full epoch over 2,000 examples
CHECKPOINT_STEPS = 2
MAX_FAILED_ATTEMPTS = 3


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


def verified_finished_run(path: Path, digest: str) -> bool:
    """A marker file alone never proves that optimizer weights changed."""
    evidence = path / "evaluation.json"
    adapter = path / "candidate-adapter" / "adapter_model.safetensors"
    metadata_path = path / "run-metadata.json"
    if (path.is_symlink() or evidence.is_symlink() or adapter.is_symlink()
            or metadata_path.is_symlink() or not adapter.is_file()
            or adapter.stat().st_size == 0 or not metadata_path.is_file()):
        return False
    try:
        report = json.loads(evidence.read_text(encoding="utf-8"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        beginning, ending = report.get("optimizer_start_sha256"), report.get("optimizer_end_sha256")
        return bool(
            report.get("dataset_sha256") == digest
            and metadata.get("dataset_sha256") == digest
            and report.get("data_kind") in ("curated_synthetic", "human_reviewed_real")
            and report.get("data_kind") == metadata.get("data_kind")
            and report.get("base_model") == MODEL
            and report.get("weights_trained") is True
            and report.get("lora_weights_changed") is True
            and report.get("production_promoted") is False
            and type(report.get("new_optimizer_steps")) is int
            and report["new_optimizer_steps"] > 0
            and isinstance(beginning, str) and re.fullmatch(r"[0-9a-f]{64}", beginning)
            and isinstance(ending, str) and re.fullmatch(r"[0-9a-f]{64}", ending)
            and beginning != ending
        )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return False


def select_run(root: Path, digest: str) -> tuple[Path, bool, str]:
    """One deterministic 4-step pilot per signed dataset; no endless fake epochs."""
    path = root / "runs" / ("cpu-automatic-" + digest[:24])
    if not path.exists():
        return path, False, "new"
    if (path / "evaluation.json").exists():
        return path, False, "finished" if verified_finished_run(path, digest) else "cannot_resume"
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


def retry_ready(root: Path, digest: str, *, recoverable: bool = False) -> bool:
    attempts, when = retry_state(root, digest)
    if attempts >= MAX_FAILED_ATTEMPTS:
        return recoverable and time() - when >= RECOVERY_RECHECK
    return time() - when >= (min(900, 45 * 2**(attempts-1)) if attempts else 0)


def recoverable_checkpoint(root: Path, digest: str) -> bool:
    """Only matching incomplete checkpoints can receive a delayed retry."""
    path = root / "runs" / ("cpu-automatic-" + digest[:24])
    meta = path / "run-metadata.json"
    if (path.is_symlink() or meta.is_symlink() or not meta.is_file()
            or (path / "evaluation.json").exists() or (path / "checkpoints").is_symlink()):
        return False
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        total = data["max_steps"]
        if (data.get("dataset_sha256") != digest or data.get("model") != MODEL
                or type(total) is not int or not 1 <= total <= 1000):
            return False
        good = [p for p in (path / "checkpoints").glob("checkpoint-*")
                if p.is_dir() and not p.is_symlink()
                and p.name.rsplit("-", 1)[-1].isdigit()
                and all((p / name).is_file() and not (p / name).is_symlink()
                        for name in ("trainer_state.json", "optimizer.pt", "scheduler.pt",
                                     "adapter_model.safetensors"))]
        return bool(good and 0 < max(int(p.name.rsplit("-", 1)[-1]) for p in good) < total)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def write_control(path: Path, org: str, generation: int, allowed: bool):
    """Atomic heartbeat consumed by the Trainer callback at every optimizer step."""
    data = {"org_id": org, "generation": generation, "allowed": bool(allowed)}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def launch(root: Path, output: Path, resume: bool, org: str, generation: int,
           telemetry_token: str, public_key: str, control_file: Path, *,
           synthetic: bool = False):
    args = [
        sys.executable, "/src/scripts/train_galancito_cpu_lora.py",
        "--dataset", str(root / ("synthetic.jsonl" if synthetic else "approved.jsonl")),
        "--output", str(output), "--max-steps", str(SYNTHETIC_STEPS if synthetic else MAX_STEPS),
        "--checkpoint-steps", str(CHECKPOINT_STEPS), "--execute",
        "--control-file", str(control_file),
        "--expected-generation", str(generation),
        "--telemetry-url", API + "/telemetry", "--telemetry-org", org,
    ]
    if synthetic:
        args.append("--synthetic-development")
    else:
        args.extend(["--approval-manifest", str(root / "approval.json")])
    if resume:
        args.append("--resume")
    env = dict(os.environ)
    env["GALANT_SYNTHETIC_DEV_TRAINING"] = "yes" if synthetic else "no"
    env["GALANT_OFFLINE_TRAINING_APPROVED"] = "no" if synthetic else "yes"
    env["GALANT_DATASET_APPROVAL_PUBLIC_KEY"] = public_key
    env["GALANT_FINETUNE_TELEMETRY_TOKEN"] = telemetry_token
    env["GALANT_FINETUNE_ALLOW_PRIVATE_HTTP"] = "yes"
    return subprocess.Popen(args, env=env, close_fds=True)


def newly_recorded_optimizer_step(output: Path, initial_bytes: int) -> bool:
    """Only report training after a NEW optimizer step appears in journal.

    A process, a model download or an inherited checkpoint is not learning.
    """
    journal = output / "training-metrics.jsonl"
    try:
        if journal.is_symlink() or not journal.is_file():
            return False
        with journal.open("rb") as stream:
            stream.seek(initial_bytes)
            for line in stream:
                try:
                    item = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if (item.get("data_kind") == "curated_synthetic"
                        and item.get("kind") in ("metric", "checkpoint")
                        and type(item.get("step")) is int
                        and item["step"] > 0):
                    return True
    except (OSError, ValueError):
        return False
    return False


def run_once(secret: str, plan: dict, public_key: str, last_preflight: dict,
             status_cache: dict | None = None) -> None:
    chosen = valid_plan(plan)
    if chosen is None:
        return
    org, generation = chosen
    status_cache = status_cache if status_cache is not None else {}
    root, data, manifest = private_files(org)
    token = hmac.new(secret.encode(), org.encode(), sha256).hexdigest()

    def report(code: str, *, blockers=None):
        marker = (org, generation)
        old = status_cache.get(marker)
        if old and old[0] == code and monotonic() - old[1] < 25:
            return
        try:
            api_call("/automation/status", secret, body={
                "org_id": org, "generation": generation, "status": code,
                **({"blockers": blockers} if blockers else {})})
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
                              cgroup_available_mb=resources.get("cgroup_available_mb"),
                              cgroup_reclaimable_mb=resources.get("cgroup_reclaimable_mb"),
                              disk_free_mb=resources.get("disk_free_mb"))
            finally:
                reporter.close()
            last_preflight[key] = monotonic()
        except (OSError, ValueError) as exc:
            LOG.warning("Preflight local no enviado: %s", type(exc).__name__)
    if not gate["ready"]:
        report("awaiting_resources", blockers=gate["blockers"])
        return
    approved = approved_inputs(root, data, manifest, public_key)
    synthetic = False
    if approved is None:
        if os.environ.get("GALANT_MAX_POWER_SYNTHETIC_LORA") != "yes":
            report("awaiting_approved_dataset")
            return
        # Synthetic laboratory never reads Messenger or private labor records.
        # Its input is recreated solely from the known code-owned fixtures.
        try:
            from max_power_synthetic_lab import prepare_lab
            root, bundle = prepare_lab(root)
            synthetic = True
        except (OSError, ValueError) as exc:
            LOG.warning("Corpus de laboratorio no utilizable: %s", type(exc).__name__)
            report("synthetic_data_invalid")
            return
    else:
        bundle, _ = approved
    digest = bundle["dataset_digest"]
    output = root / "runs" / ("cpu-automatic-" + digest[:24])
    if verified_finished_run(output, digest):
        report("finished_synthetic" if synthetic else "awaiting_new_dataset")
        return
    recoverable = recoverable_checkpoint(root, digest)
    if not retry_ready(root, digest, recoverable=recoverable):
        attempts, _ = retry_state(root, digest)
        report("retry_cooldown" if attempts < MAX_FAILED_ATTEMPTS or recoverable else "retry_exhausted")
        return
    if plan.get("practice_busy"):
        # Give already-running 4B practice its full turn; prevent new rounds
        # from starting so authorized CPU LoRA eventually gets CPU time.
        report("cpu_waiting_turn")
        return
    # select_run can archive an interrupted directory; only do so to launch.
    output, resume, run_state = select_run(root, digest)
    if run_state == "finished":
        report("finished_synthetic" if synthetic else "awaiting_new_dataset")
        return
    if run_state == "cannot_resume":
        report("cannot_resume")
        return
    if recoverable and retry_state(root, digest)[0] >= MAX_FAILED_ATTEMPTS:
        # Reserve the next cooldown BEFORE starting; a supervisor restart
        # cannot create an unbounded retry loop.
        record_failure(root, digest)
    control = root / ".max-power-automatic-control.json"
    write_control(control, org, generation, True)
    journal = output / "training-metrics.jsonl"
    initial_bytes = journal.stat().st_size if journal.is_file() and not journal.is_symlink() else 0
    report("preparing_synthetic" if synthetic else "training")
    child = launch(root, output, resume, org, generation, token, public_key, control,
                   synthetic=synthetic)
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
            if monotonic() - paused_since > MAX_GRACE_SECONDS + 15:
                child.kill()
            elif monotonic() - paused_since > MAX_GRACE_SECONDS:
                child.terminate()
        else:
            paused_since = None
            report(("training_synthetic" if newly_recorded_optimizer_step(output, initial_bytes)
                    else "preparing_synthetic") if synthetic else "training")  # supervised heartbeat
    code = child.wait()
    if code == 0:
        if verified_finished_run(output, bundle["dataset_digest"]):
            report("finished_synthetic" if synthetic else "finished")
        else:
            # Exit zero alone is not proof of a completed gradient update.
            record_failure(root, bundle["dataset_digest"])
            report("failed")
    elif code == 3 or (code in (-15, -9) and paused_since is not None):
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
