"""Durable per-step telemetry for isolated CPU LoRA and CUDA QLoRA (Python stdlib only).

Every recorded sample is a real callback measurement, never a simulated demo.
Metric JSONL never contains conversation text, model outputs, passwords or keys.
An optional background sender signs requests for the GALANT admin dashboard.
Local records survive network failures and can be replayed after a restart.
"""
from __future__ import annotations

import hmac
from hashlib import sha256
import json
import os
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Event, Thread
from time import time, sleep
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

KINDS = frozenset(("preflight", "start", "baseline", "metric", "eval", "checkpoint", "finished", "failed", "paused"))
NUMBERS = frozenset((
    "epoch", "loss", "eval_loss", "learning_rate", "grad_norm",
    "gpu_memory_mb", "gpu_memory_reserved_mb", "cpu_memory_mb",
    "host_free_mb", "cgroup_free_mb", "cgroup_limit_mb", "disk_free_mb",
    "optimizer_steps_new", "elapsed_seconds",
    "train_samples_per_second", "holdout_loss_before", "holdout_loss_after",
    "holdout_pass_before", "holdout_pass_after", "holdout_regressions",
))


def _number(value):
    if type(value) not in (int, float):
        return None
    from math import isfinite
    val = float(value)
    return val if isfinite(val) and val >= 0 else None


class ProgressReporter:
    def __init__(self, directory: Path, *, run_id: str, org_id: str | None,
                 dataset_sha256: str, telemetry_url: str | None = None,
                 telemetry_token: str | None = None,
                 model: str = "Qwen/Qwen3.5-4B"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "training-metrics.jsonl"
        self.run_id = str(UUID(run_id))
        self.org_id = str(UUID(org_id)) if org_id else None
        self.digest = dataset_sha256
        if model not in {"Qwen/Qwen3.5-4B", "Qwen/Qwen3.5-0.8B"}:
            raise ValueError("Modelo sin perfil de telemetría autorizado")
        self.model = model
        self.url = telemetry_url
        self.token = telemetry_token
        if bool(self.url) != bool(self.token) or bool(self.url) != bool(self.org_id):
            raise ValueError("Telemetría remota requiere URL HTTPS, organización y token")
        if self.url:
            parsed = urlsplit(self.url)
            if (parsed.scheme != "https" or not parsed.netloc or parsed.username
                    or parsed.password or parsed.fragment or parsed.query
                    or not parsed.path.endswith("/admin/ai/max-power/finetune/telemetry")):
                raise ValueError("Endpoint de telemetría debe ser HTTPS y tener una ruta GALANT válida")
            if not isinstance(self.token, str) or len(self.token) != 64:
                raise ValueError("Token de telemetría inválido")
            try:
                bytes.fromhex(self.token)
            except ValueError as exc:
                raise ValueError("Token de telemetría inválido") from exc
        self.sequence = 0
        self.queued = Queue(maxsize=512)
        self.stop = Event()
        self.worker = None
        if self.path.exists():
            replay = []
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if (item.get("run_id") != self.run_id or item.get("dataset_sha256") != self.digest
                        or item.get("model") != self.model):
                    raise ValueError("Historial de métricas incompatible con esta ejecución")
                self.sequence = max(self.sequence, int(item["sequence"]))
                if self.url:
                    replay.append(item)
            # The complete history stays on disk; replay the latest bounded
            # window without blocking checkpoint recovery on an old long run.
            for item in replay[-512:]:
                self.queued.put_nowait(item)
        if self.url:
            self.worker = Thread(target=self._send_loop, daemon=True, name="galant-lora-telemetry")
            self.worker.start()

    def emit(self, kind: str, *, step: int, total_steps: int,
             weights_trained=False, candidate_accepted=False, **metrics):
        if kind not in KINDS:
            raise ValueError("Tipo de medición desconocido")
        self.sequence += 1
        entry = {
            "org_id": self.org_id, "run_id": self.run_id,
            "sequence": self.sequence, "kind": kind,
            "dataset_sha256": self.digest, "model": self.model,
            "step": int(step), "total_steps": int(total_steps),
            "weights_trained": bool(weights_trained),
            "candidate_accepted": bool(candidate_accepted),
        }
        if kind == "preflight" and isinstance(metrics.get("preflight_ready"), bool):
            entry["preflight_ready"] = metrics["preflight_ready"]
        # Hashes identify changes in adapter tensors without revealing their
        # contents. Only allow a pair of genuine 64-digit SHA-256 digests.
        before = metrics.get("optimizer_start_sha256")
        after = metrics.get("optimizer_end_sha256")
        if (kind in {"finished", "paused"}
                and isinstance(before, str) and isinstance(after, str)
                and len(before) == len(after) == 64
                and all(c in "0123456789abcdef" for c in before + after)):
            entry["optimizer_start_sha256"] = before
            entry["optimizer_end_sha256"] = after
        # Only numerical measurements and a boolean readiness state are serialized.
        for key in NUMBERS:
            val = _number(metrics.get(key))
            if val is not None:
                entry[key] = (int(val) if key.startswith("holdout_pass")
                              or key == "holdout_regressions" else val)
        if not self.org_id:
            entry.pop("org_id")
        encoded = json.dumps(entry, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
        with self.path.open("a", encoding="utf-8") as writer:
            writer.write(encoded + "\n")
            writer.flush()
            os.fsync(writer.fileno())  # persistent progress before network send
        if self.url:
            try:
                self.queued.put_nowait(entry)
            except Full:
                pass  # JSONL remains the durable source for replay
        return entry

    def _send_loop(self):
        while not self.stop.is_set() or not self.queued.empty():
            try:
                entry = self.queued.get(timeout=0.2)
            except Empty:
                continue
            attempts = 0
            while True:
                try:
                    raw = json.dumps(entry, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()
                    stamp = str(int(time()))
                    signature = hmac.new(bytes.fromhex(self.token),
                                         (stamp + ".").encode() + raw, sha256).hexdigest()
                    request = Request(self.url, data=raw, method="POST",
                                      headers={"Content-Type": "application/json",
                                               "X-Galant-Telemetry-Timestamp": stamp,
                                               "X-Galant-Telemetry-Signature": signature})
                    with urlopen(request, timeout=3) as response:
                        if response.status != 200:
                            raise OSError("Telemetry rejected")
                    break
                except (OSError, ValueError):
                    attempts += 1
                    if attempts >= 3 or self.stop.is_set():
                        break
                    sleep(min(8, attempts * 2))
            self.queued.task_done()

    def close(self):
        if self.worker:
            self.stop.set()
            self.worker.join(timeout=5)
