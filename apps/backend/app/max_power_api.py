"""One-button MAX POWER management with persistent measurements and no fake scores."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_quality_audit import reviewed_sample
from .ai_quality_models import AIResponseReview
from .db import get_db
from .galancito_memory import aware
from .galancito_training_models import ACTIVE, TrainingRound, TrainingWorker
from .max_power_decisions import latency_diagnosis, priority_from_reviews
from .max_power_models import MaxPowerEvent, MaxPowerState, MaxPowerMessengerTrial
from .max_power_export import build_report, MAX_EVENTS
from .models import AuditEvent, Organization, User, utcnow
from .security import administrator

router = APIRouter(prefix="/api/v1/admin/ai/max-power", tags=["MAX POWER"])

def _sample(db, org_id, since):
    return {channel: reviewed_sample(db, org_id, channel, since)
            for channel in ("messenger", "general")}

def _automatic_quality(messenger_trials, events):
    """Real model comparisons; no human labels and no invented global IQ score."""
    first_per_source = {}
    for t in reversed(messenger_trials):
        if t.status != "completed" or not t.source_run_id:
            continue
        key = (t.source_run_id, t.criterion)
        if key not in first_per_source:
            first_per_source[key] = t
    measured = []
    categories = {"context":"context_pass", "profile":"context_pass",
                  "naturalness":"naturalness_check", "safety":"safety_check"}
    for trial in first_per_source.values():
        col = categories.get(trial.criterion)
        before = (trial.metrics or {}).get("baseline", {}).get(col)
        after = (trial.metrics or {}).get("candidate", {}).get(col)
        if type(before) is bool and type(after) is bool:
            measured.append((int(before), int(after)))
    pairs = len(measured)
    automatic = {"messenger":{
        "pairs":pairs,"scope":"controles_objetivos_parciales",
        "baseline":round(100*sum(x for x,_ in measured)/pairs,1) if pairs >= 8 else None,
        "candidate":round(100*sum(y for _,y in measured)/pairs,1) if pairs >= 8 else None,
        "delta_points":round(100*sum(y-x for x,y in measured)/pairs,1) if pairs >= 8 else None,
        "production_verified":False,"minimum_cases":8,
        "notes":"Evaluaciones autónomas sobre casos reales; no equivale a calidad total ni a cambios publicados",
    }}
    general = next((event.evidence for event in events
        if event.event=="experiment_completed" and
        isinstance(event.evidence,dict) and
        event.evidence.get("holdout_baseline_rate") is not None and
        event.evidence.get("holdout_candidate_rate") is not None),None)
    gpairs = int(general.get("holdout_pairs") or 0) if general else 0
    gbase = float(general["holdout_baseline_rate"])*100 if general else None
    gcandidate = float(general["holdout_candidate_rate"])*100 if general else None
    automatic["general"]={
        "pairs":gpairs, "scope":"exactitud_aritmetica_sobre_agregados_reales",
        "baseline":round(gbase,1) if gpairs>=8 else None,
        "candidate":round(gcandidate,1) if gpairs>=8 else None,
        "delta_points":round(gcandidate-gbase,1) if gpairs>=8 else None,
        "production_verified":False,"minimum_cases":8,
        "notes":"Comparación reservada con respuestas de referencia; no mide razonamiento general completo",
    }
    return automatic

def _view(db, user, row):
    now = utcnow()
    since = now - timedelta(days=30)
    baseline = row.initial_quality if row else {}
    current = _sample(db, user.org_id, since)
    priorities = list(db.scalars(select(AIResponseReview).where(
        AIResponseReview.org_id == user.org_id,
        AIResponseReview.created_at >= since,
    ).order_by(AIResponseReview.created_at.desc()).limit(400)))
    events = list(db.scalars(select(MaxPowerEvent).where(
        MaxPowerEvent.org_id == user.org_id,
    ).order_by(MaxPowerEvent.created_at.desc()).limit(30)))
    messenger_trials = list(db.scalars(select(MaxPowerMessengerTrial).where(
        MaxPowerMessengerTrial.org_id == user.org_id
    ).order_by(MaxPowerMessengerTrial.created_at.desc()).limit(150)))
    messenger_summary = {
        "trials": len(messenger_trials),
        "objective_gains": sum(t.outcome == "objective_gain" for t in messenger_trials),
        "regressions": sum(t.outcome in ("objective_regression", "safety_regression") for t in messenger_trials),
        "inconclusive": sum(t.outcome in ("unverifiable", "no_objective_gain") for t in messenger_trials),
        "active": sum(t.status in ("queued", "running") for t in messenger_trials),
        "basis": "partial_objective_checks_not_human_quality_score",
        "limited_to_recent_150": True,
    }
    worker = db.get(TrainingWorker, 1)
    trainer_online = bool(worker and aware(worker.updated_at) >= aware(now) - timedelta(seconds=150))
    controller_online = bool(row and row.worker_seen_at and
                             aware(row.worker_seen_at) >= aware(now) - timedelta(seconds=30))
    recent = row.latest_result if row else {}
    timing = recent.get("ollama_avg") or {}
    improvement = {}
    for channel in ("messenger", "general"):
        original = baseline.get(channel, {}).get("quality_score")
        actual = current[channel]["quality_score"]
        improvement[channel] = {"initial": original, "latest": actual,
                                "delta_points": round(actual - original, 1)
                                if original is not None and actual is not None else None,
                                "evidence": "human_reviewed_sample_not_causal",
                                "sample_count": current[channel]["reviewed_cases"]}
    return {
        "enabled": bool(row.enabled) if row else False,
        "first_started_at": row.first_started_at if row else None,
        "session_started_at": row.session_started_at if row else None,
        "last_stopped_at": row.last_stopped_at if row else None,
        "active_seconds": row.on_seconds if row else 0,
        "sessions": row.sessions if row else 0,
        "experiments": row.experiments if row else 0,
        "examined_cases": row.examined_cases if row else 0,
        "observed_holdout_wins": row.lab_gains if row else 0,
        "observed_holdout_regressions": row.regressions if row else 0,
        "active_round_id": row.active_round_id if row else None,
        "status": row.last_status if row else "off",
        "reason": row.last_reason if row else "MAX POWER todavía no se ha encendido",
        "controller_online": controller_online,
        "trainer_online": trainer_online,
        "priorities": priority_from_reviews(priorities),
        "messenger_experiments": messenger_summary,
        "automatic_quality": _automatic_quality(messenger_trials, events),
        "quality": current,
        "quality_deltas": improvement,
        "latest_result": recent,
        "latency_diagnosis": latency_diagnosis(timing),
        "events": [{"id": e.id, "at": e.created_at, "event": e.event,
                    "reason": e.reason, "round_id": e.round_id, "evidence": e.evidence}
                   for e in events],
        "limitations": ("MAX POWER selecciona y evalúa automáticamente casos verificables. "
                        "Una puntuación de laboratorio no significa mejora desplegada "
                        "ni aprendizaje de pesos; resultados no verificables quedan sin nota."),
    }

@router.get("")
def status(user: User = Depends(administrator), db: Session = Depends(get_db)):
    return _view(db, user, db.get(MaxPowerState, user.org_id))

@router.get("/export", response_class=Response)
def export_chatgpt_report(max_events: int = Query(default=MAX_EVENTS, ge=1, le=MAX_EVENTS),
                          user: User = Depends(administrator), db: Session = Depends(get_db)):
    """One-click, offline JSON handoff; does not upload data to ChatGPT."""
    report = build_report(db, user, max_events=max_events)
    canonical = json.dumps(report, ensure_ascii=False, allow_nan=False,
                           sort_keys=True, separators=(",", ":")).encode("utf-8")
    report["integrity"] = {
        "algorithm": "SHA-256",
        "canonical_payload_without_integrity": sha256(canonical).hexdigest(),
    }
    content = json.dumps(report, ensure_ascii=False, allow_nan=False,
                         indent=2, sort_keys=True).encode("utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Response(content=content, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="galant-max-power-chatgpt-{stamp}.json"',
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    })

@router.post("/control/{action}")
def control(action: Literal["on", "off"], user: User = Depends(administrator),
            db: Session = Depends(get_db)):
    db.scalar(select(Organization.id).where(Organization.id == user.org_id).with_for_update())
    row = db.get(MaxPowerState, user.org_id)
    now = utcnow()
    if row is None:
        if action == "off":
            raise HTTPException(409, "MAX POWER no ha sido encendido")
        row = MaxPowerState(org_id=user.org_id, owner_id=user.id,
                            first_started_at=now, initial_quality=_sample(
                                db, user.org_id, now - timedelta(days=30)))
        db.add(row)
    if row.enabled == (action == "on"):
        raise HTTPException(409, "MAX POWER ya está en ese estado")
    if action == "on":
        row.enabled = True
        row.owner_id = user.id
        row.session_started_at = now
        row.sessions = (row.sessions or 0) + 1
        row.next_at = now
        row.last_tick_at = None
        row.last_status = "starting"
        row.last_reason = "En espera del controlador y capacidad del VPS"
        if row.first_started_at is None:
            row.first_started_at = now
    else:
        if not row.active_round_id:
            orphan = db.scalar(select(TrainingRound).where(
                TrainingRound.org_id == user.org_id,
                TrainingRound.config["orchestrator"].as_string() == "max_power",
                TrainingRound.state.in_(ACTIVE)).order_by(TrainingRound.created_at.desc()).limit(1))
            row.active_round_id = orphan.id if orphan else None
        row.enabled = False
        row.session_started_at = None
        row.last_stopped_at = now
        row.last_status = "off"
        row.last_reason = "Detenido por administración; progreso y evidencia conservados"
        if row.active_round_id:
            running = db.scalar(select(TrainingRound).where(
                TrainingRound.id == row.active_round_id,
                TrainingRound.org_id == user.org_id).with_for_update())
            if running and running.state in ACTIVE:
                running.state, running.reason, running.finished_at = (
                    "stopped", "MAX POWER apagado; resultados parciales guardados", now)
                running.lease = running.lease_until = None
            row.active_round_id = None
    row.updated_at = now
    db.add(MaxPowerEvent(org_id=user.org_id, event="power_on" if row.enabled else "power_off",
                         reason=row.last_reason))
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="ai.max_power.on" if row.enabled else "ai.max_power.off",
                      resource_id=user.org_id))
    db.commit()
    return _view(db, user, row)
