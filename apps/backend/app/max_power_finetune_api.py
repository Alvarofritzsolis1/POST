"""Signed, org-scoped telemetry for REAL CPU LoRA and GPU QLoRA steps.

No chat contents, gradients, prompts, credentials, adapters or model files cross
this interface. An independent CUDA worker sends only allowlisted measurements.
No endpoint can start a trainer, promote an adapter or change production.
"""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import hmac
import os
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db
from .max_power_models import MaxPowerEvent
from .models import User, utcnow
from .security import administrator

router = APIRouter(prefix="/api/v1/admin/ai/max-power/finetune",
                   tags=["MAX POWER fine-tuning"])
KINDS = ("preflight", "start", "baseline", "metric", "eval", "checkpoint", "finished", "failed", "paused")
PREFIX = "ft_"
MAX_POINTS = 300


class Telemetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org_id: UUID
    run_id: UUID
    sequence: int = Field(ge=1, le=99_999_999)
    kind: Literal["preflight", "start", "baseline", "metric", "eval", "checkpoint", "finished", "failed", "paused"]
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model: Literal["Qwen/Qwen3.5-4B", "Qwen/Qwen3.5-0.8B"] = "Qwen/Qwen3.5-4B"
    step: int = Field(ge=0, le=10_000_000)
    total_steps: int = Field(ge=0, le=10_000_000)
    epoch: float | None = Field(default=None, ge=0, le=10_000, allow_inf_nan=False)
    loss: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    eval_loss: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    learning_rate: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    grad_norm: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    gpu_memory_mb: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    cpu_memory_mb: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    preflight_ready: bool | None = None
    host_free_mb: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    cgroup_free_mb: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    cgroup_limit_mb: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    disk_free_mb: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    gpu_memory_reserved_mb: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    elapsed_seconds: float | None = Field(default=None, ge=0, le=100_000_000, allow_inf_nan=False)
    train_samples_per_second: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    holdout_loss_before: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    holdout_loss_after: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    holdout_pass_before: int | None = Field(default=None, ge=0, le=1_000_000)
    holdout_pass_after: int | None = Field(default=None, ge=0, le=1_000_000)
    holdout_regressions: int | None = Field(default=None, ge=0, le=1_000_000)
    weights_trained: bool = False
    candidate_accepted: bool = False


def master_secret() -> bytes:
    secret = os.environ.get("GALANT_FINETUNE_METRICS_SECRET", "")
    if len(secret) < 48:
        raise HTTPException(503, "Telemetría neuronal no configurada en el servidor")
    return secret.encode("utf-8")


def scoped_token(org_id: str) -> str:
    return hmac.new(master_secret(), org_id.encode("ascii"), sha256).hexdigest()


@router.post("/token")
def issue_token(user: User = Depends(administrator)):
    """Admin-only opt-in. Token is org-scoped; send ONLY to the private CUDA host."""
    return {"organization_id": user.org_id, "telemetry_token": scoped_token(user.org_id),
            "instructions": "Mantener el token fuera de Git y usar únicamente HTTPS."}


@router.post("/telemetry")
async def ingest(request: Request,
                 x_galant_telemetry_timestamp: str = Header(default=""),
                 x_galant_telemetry_signature: str = Header(default=""),
                 db: Session = Depends(get_db)):
    body = await request.body()
    if len(body) > 4096:
        raise HTTPException(413, "Tamaño de telemetría excedido")
    try:
        stamp = int(x_galant_telemetry_timestamp)
        if abs(int(datetime.now(timezone.utc).timestamp()) - stamp) > 120:
            raise ValueError("timestamp expired")
        sample = Telemetry.model_validate_json(body)
    except (ValueError, TypeError):
        raise HTTPException(422, "Métricas o marca de tiempo no válidas") from None
    token = scoped_token(str(sample.org_id))
    mac = hmac.new(bytes.fromhex(token),
                   (str(stamp) + ".").encode("ascii") + body, sha256).hexdigest()
    if not hmac.compare_digest(mac, x_galant_telemetry_signature):
        raise HTTPException(401, "Firma de telemetría inválida")
    if sample.step > sample.total_steps and sample.total_steps > 0:
        raise HTTPException(422, "Paso fuera del total")
    if sample.kind == "preflight":
        if (sample.model != "Qwen/Qwen3.5-0.8B" or
                sample.preflight_ready is None or sample.step != 0 or
                sample.total_steps != 0 or sample.weights_trained or
                sample.candidate_accepted):
            raise HTTPException(422, "Preflight no puede declarar entrenamiento")
    elif sample.preflight_ready is not None:
        raise HTTPException(422, "Preparación solo para eventos de preflight")
    key = f"{PREFIX}{sample.sequence:08d}"
    prior = db.scalar(select(MaxPowerEvent).where(
        MaxPowerEvent.org_id == str(sample.org_id), MaxPowerEvent.round_id == str(sample.run_id),
        MaxPowerEvent.event == key))
    if prior is not None:
        if prior.evidence.get("sequence") != sample.sequence or prior.evidence.get("dataset_sha256") != sample.dataset_sha256:
            raise HTTPException(409, "Evento contradictorio")
        return {"accepted": True, "duplicate": True}
    db.add(MaxPowerEvent(
        org_id=str(sample.org_id), round_id=str(sample.run_id),
        event=key, reason=("Gradientes LoRA CPU: " if sample.model.endswith("0.8B")
                            else "Gradientes QLoRA GPU: ") + sample.kind,
        evidence=sample.model_dump(mode="json", exclude={"org_id", "run_id"}, exclude_none=True),
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"accepted": True, "duplicate": True}
    return {"accepted": True, "duplicate": False}


def _run_view(rows):
    if not rows:
        return None
    events = sorted(rows, key=lambda r: int((r.evidence or {}).get("sequence") or 0))
    last = events[-1]
    payload = last.evidence or {}
    total = int(payload.get("total_steps") or 0)
    step = int(payload.get("step") or 0)
    started = next((e for e in events if (e.evidence or {}).get("kind") == "start"), events[0])
    kind = str(payload.get("kind") or "")
    return {
        "run_id": last.round_id,
        "model": payload.get("model"),
        "dataset_sha256": payload.get("dataset_sha256"),
        "stage": kind if kind in KINDS else "unknown",
        "step": step, "total_steps": total,
        "percent": round(100 * step / total, 1) if total else None,
        "started_at": started.created_at,
        "last_update_at": last.created_at,
        "weights_trained": any(bool((r.evidence or {}).get("weights_trained")) for r in events),
        "candidate_accepted": any(bool((r.evidence or {}).get("candidate_accepted")) for r in events),
        "points": [{
            "sequence": int(e.evidence["sequence"]), "timestamp": e.created_at,
            "kind": e.evidence.get("kind"), "step": e.evidence.get("step"),
            "epoch": e.evidence.get("epoch"),
            "loss": e.evidence.get("loss"), "eval_loss": e.evidence.get("eval_loss"),
            "grad_norm": e.evidence.get("grad_norm"),
            "learning_rate": e.evidence.get("learning_rate"),
            "gpu_memory_mb": e.evidence.get("gpu_memory_mb"),
            "cpu_memory_mb": e.evidence.get("cpu_memory_mb"),
            "preflight_ready": e.evidence.get("preflight_ready"),
            "host_free_mb": e.evidence.get("host_free_mb"),
            "cgroup_free_mb": e.evidence.get("cgroup_free_mb"),
            "cgroup_limit_mb": e.evidence.get("cgroup_limit_mb"),
            "disk_free_mb": e.evidence.get("disk_free_mb"),
            "gpu_memory_reserved_mb": e.evidence.get("gpu_memory_reserved_mb"),
            "elapsed_seconds": e.evidence.get("elapsed_seconds"),
            "train_samples_per_second": e.evidence.get("train_samples_per_second"),
            "holdout_loss_before": e.evidence.get("holdout_loss_before"),
            "holdout_loss_after": e.evidence.get("holdout_loss_after"),
            "holdout_pass_before": e.evidence.get("holdout_pass_before"),
            "holdout_pass_after": e.evidence.get("holdout_pass_after"),
            "holdout_regressions": e.evidence.get("holdout_regressions"),
        } for e in events[-MAX_POINTS:]],
    }


@router.get("")
def progress(user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Read-only, bounded, actual reported metrics. Never invent progress."""
    rows = list(db.scalars(select(MaxPowerEvent).where(
        MaxPowerEvent.org_id == user.org_id,
        MaxPowerEvent.event.like("ft_%"),
        MaxPowerEvent.round_id.is_not(None),
    ).order_by(MaxPowerEvent.created_at.desc()).limit(2000)))
    runs = {}
    for row in rows:
        # Ignore unrelated old events, and prevent interleaving organizations.
        if row.event.startswith(PREFIX) and row.event[3:].isdigit():
            runs.setdefault(row.round_id, []).append(row)
    latest = sorted(runs.values(), key=lambda items: max(r.created_at for r in items), reverse=True)
    preflight_runs = [items for items in latest
                      if all((e.evidence or {}).get("kind") == "preflight" for e in items)]
    training_runs = [items for items in latest
                     if not all((e.evidence or {}).get("kind") == "preflight" for e in items)]
    latest_preflight = _run_view(preflight_runs[0]) if preflight_runs else None
    return {
        "configured": len(os.environ.get("GALANT_FINETUNE_METRICS_SECRET", "")) >= 48,
        "cpu_preflight": latest_preflight,
        "source": "signed_cpu_or_gpu_lora_gradient_training_events",
        "refresh_seconds": 5,
        "runs": [_run_view(rows) for rows in training_runs[:5]],
        "production_promoted": False,
        "disclaimer": "Solo pasos reportados por un trabajador CPU o GPU autorizado; "
                      "una pérdida descendente no demuestra mejora general.",
    }
