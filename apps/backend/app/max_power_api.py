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
from .max_power_decisions import QWEN_MIN_RAM_MB, latency_diagnosis, priority_from_reviews
from .max_power_live import RESOURCE_EVENT, general_series, messenger_series, resource_metrics, synthetic_4b_series, latency_series
from .max_power_models import MaxPowerEvent, MaxPowerState, MaxPowerMessengerTrial
from .max_power_export import build_report, MAX_EVENTS, safe_metrics
from .max_power_practice import EVENT as PRACTICE_EVENT, QWEN_CRITERION, generate_scenarios
from .models import AuditEvent, Organization, User, utcnow
from .security import administrator

router = APIRouter(prefix="/api/v1/admin/ai/max-power", tags=["MAX POWER"])
PRACTICE_CASES = len(generate_scenarios())

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
    categories = {"context":"context_pass", "understanding":"answer_priority_check",
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

def _qwen_activity(db, row, controller_online, trials, resources, now):
    if not row or not row.enabled:
        return {"state": "off", "reason": "Qwen 4B en pausa"}
    if not controller_online:
        return {"state": "waiting", "reason": "Esperando el controlador de MAX POWER"}

    trial = next((item for item in trials if item.status == "running" and item.lease_until
                  and aware(item.lease_until) > now), None)
    if trial:
        phase = (trial.metrics or {}).get("active_phase")
        reason, completed = {
            "reference": ("Generando la respuesta de referencia", 0),
            "candidate": ("Generando la respuesta candidata", 1),
        }.get(phase, ("Preparando la evaluación", None))
        return {"state": "running", "reason": reason, "completed": completed, "total": 2,
                "unit": "respuestas", "started_at": (trial.metrics or {}).get("phase_started_at") or trial.started_at}

    if row.active_round_id:
        round_ = db.scalar(select(TrainingRound).where(
            TrainingRound.id == row.active_round_id, TrainingRound.org_id == row.org_id,
            TrainingRound.state.in_(ACTIVE)))
        if round_:
            running = bool(round_.lease and round_.lease_until and aware(round_.lease_until) > now)
            return {"state": "running" if running else "waiting",
                    "reason": "Evaluando casos de la ronda operativa" if running else
                    round_.reason or "Ronda operativa a la espera de un turno",
                    "completed": round_.completed, "total": round_.target, "unit": "casos"}

    available = resources.get("available_ram_mb")
    if row.last_status in {"cpu_neural_training", "manual_round_busy", "permission_required", "isolation_unavailable"} or (
        row.last_status == "resource_guard" and "Messenger tiene prioridad" in row.last_reason
    ):
        return {"state": "waiting", "reason": row.last_reason}
    if isinstance(available, (int, float)) and available < QWEN_MIN_RAM_MB:
        return {"state": "waiting", "reason": "RAM disponible por debajo del mínimo de Qwen 4B para proteger Messenger",
                "required_ram_mb": QWEN_MIN_RAM_MB}
    queued = min((item for item in trials if item.status == "queued"), key=lambda item: aware(item.next_at), default=None)
    if queued:
        return {"state": "waiting", "reason": queued.reason or "Ensayo en cola",
                "retry_at": queued.next_at if aware(queued.next_at) > now else None}
    return {"state": "waiting", "reason": row.last_reason}


def _view(db, user, row):
    now = utcnow()
    since = now - timedelta(days=30)
    baseline = row.initial_quality if row else {}
    current = _sample(db, user.org_id, since)
    priorities = list(db.scalars(select(AIResponseReview).where(
        AIResponseReview.org_id == user.org_id,
        AIResponseReview.created_at >= since,
    ).order_by(AIResponseReview.created_at.desc()).limit(400)))
    # QLoRA step telemetry has a dedicated graph; do not flood the ordinary
    # MAX POWER experiment history with thousands of optimizer steps.
    events = list(db.scalars(select(MaxPowerEvent).where(
        MaxPowerEvent.org_id == user.org_id,
        ~MaxPowerEvent.event.like("ft_%"),
        MaxPowerEvent.event != RESOURCE_EVENT,
    ).order_by(MaxPowerEvent.created_at.desc()).limit(30)))
    cpu_event = db.scalar(select(MaxPowerEvent).where(
        MaxPowerEvent.org_id == user.org_id,
        MaxPowerEvent.round_id == user.org_id,
        MaxPowerEvent.event == "cpu_supervisor_status"))
    cpu_state = (cpu_event.evidence or {}).get("state") if cpu_event else None
    cpu_online = bool(cpu_event and aware(cpu_event.created_at) >= aware(now) - timedelta(seconds=55))
    messenger_trials = list(db.scalars(select(MaxPowerMessengerTrial).where(
        MaxPowerMessengerTrial.org_id == user.org_id, MaxPowerMessengerTrial.criterion != QWEN_CRITERION,
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
    practice = db.scalar(select(MaxPowerEvent).where(
        MaxPowerEvent.org_id == user.org_id, MaxPowerEvent.event == PRACTICE_EVENT,
    ).order_by(MaxPowerEvent.created_at.desc()).limit(1))
    synthetic_replies = None
    trials = []
    if practice:
        trials = list(db.scalars(select(MaxPowerMessengerTrial).where(
            MaxPowerMessengerTrial.org_id == user.org_id, MaxPowerMessengerTrial.criterion == QWEN_CRITERION,
            MaxPowerMessengerTrial.metrics["dataset_sha256"].as_string() == practice.evidence.get("dataset_sha256"),
            MaxPowerMessengerTrial.metrics["protocol"].as_string() == practice.evidence.get("protocol"),
        )))
        reserved = [t for t in trials if t.status == "completed" and t.metrics.get("split") == "holdout"]
        synthetic_replies = {
            "queued_or_running": sum(t.status in ("queued", "running") for t in trials),
            "completed": sum(t.status == "completed" for t in trials),
            "blocked": sum(t.status == "blocked" for t in trials),
            "reserved_pairs": len(reserved),
            "baseline_passes": sum(t.metrics["baseline"]["understanding_check"] is True for t in reserved),
            "candidate_passes": sum(t.metrics["candidate"]["understanding_check"] is True for t in reserved),
            "gains": sum(t.outcome == "objective_gain" for t in reserved),
            "regressions": sum(t.outcome in ("objective_regression", "safety_regression") for t in reserved),
            "safety_failures": sum(t.outcome == "safety_regression" for t in reserved),
        }
    verified_cpu_update = db.scalar(select(MaxPowerEvent.id).where(
        MaxPowerEvent.org_id == user.org_id,
        MaxPowerEvent.event.like("ft_%"),
        MaxPowerEvent.evidence["model"].as_string() == "Qwen/Qwen3.5-0.8B",
        MaxPowerEvent.evidence["data_kind"].as_string() == "human_reviewed_real",
        MaxPowerEvent.evidence["weights_trained"].as_boolean().is_(True),
    ).limit(1))
    synthetic_cpu_update = db.scalar(select(MaxPowerEvent.id).where(
        MaxPowerEvent.org_id == user.org_id,
        MaxPowerEvent.event.like("ft_%"),
        MaxPowerEvent.evidence["model"].as_string() == "Qwen/Qwen3.5-0.8B",
        MaxPowerEvent.evidence["data_kind"].as_string() == "curated_synthetic",
        MaxPowerEvent.evidence["weights_trained"].as_boolean().is_(True),
    ).limit(1))
    controller_online = bool(row and row.worker_seen_at and
                             aware(row.worker_seen_at) >= aware(now) - timedelta(seconds=30))
    resources = safe_metrics(worker.resources) if trainer_online else {}
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
        "cpu_learning": {
            "status": cpu_state if cpu_online else "manager_offline",
            "reason": (cpu_event.reason if cpu_online else
                       "El controlador neuronal no ha informado recientemente"),
            "last_update_at": cpu_event.created_at if cpu_event else None,
            "manager_online": cpu_online,
            "weights_trained": bool(verified_cpu_update),
            "synthetic_weights_trained": bool(synthetic_cpu_update),
            "training_kind": "curated_synthetic" if cpu_state in {"preparing_synthetic", "training_synthetic", "finished_synthetic"} else "human_reviewed_real" if cpu_state == "training" else "none",
            "model": "Qwen/Qwen3.5-0.8B",
        },
        "priorities": priority_from_reviews(priorities),
        "messenger_experiments": messenger_summary,
        "automatic_quality": _automatic_quality(messenger_trials, events),
        "synthetic_practice": {**practice.evidence, "at": practice.created_at} if practice else None,
        "synthetic_qwen": synthetic_replies,
        "resource_snapshot": resources,
        "live_activity": {
            "updated_at": now,
            "controller_at": row.worker_seen_at if row else None,
            "next_check_at": row.next_at if row and row.enabled and aware(row.next_at) > now else None,
            "practice_cases": PRACTICE_CASES,
            "qwen": _qwen_activity(db, row, controller_online, messenger_trials + trials, resources, now),
        },
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

@router.get("/live/history")
def live_history(user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Private, bounded historical series; no inference or external API calls."""
    now = utcnow()
    org = user.org_id
    events = list(db.scalars(select(MaxPowerEvent).where(
        MaxPowerEvent.org_id == org, MaxPowerEvent.event == "experiment_completed"
    ).order_by(MaxPowerEvent.created_at.desc(), MaxPowerEvent.id.desc()).limit(500)))
    trials = list(db.scalars(select(MaxPowerMessengerTrial).where(
        MaxPowerMessengerTrial.org_id == org, MaxPowerMessengerTrial.status == "completed",
        MaxPowerMessengerTrial.criterion != QWEN_CRITERION,
        MaxPowerMessengerTrial.completed_at.is_not(None)
    ).order_by(MaxPowerMessengerTrial.completed_at.desc(), MaxPowerMessengerTrial.id.desc()).limit(500)))
    resources = list(db.scalars(select(MaxPowerEvent).where(
        MaxPowerEvent.org_id == org, MaxPowerEvent.event == RESOURCE_EVENT,
        MaxPowerEvent.created_at >= now - timedelta(hours=24)
    ).order_by(MaxPowerEvent.created_at.desc()).limit(1440)))
    synthetic = list(db.scalars(select(MaxPowerMessengerTrial).where(
        MaxPowerMessengerTrial.org_id == org, MaxPowerMessengerTrial.status == "completed",
        MaxPowerMessengerTrial.criterion == QWEN_CRITERION,
        MaxPowerMessengerTrial.completed_at.is_not(None)
    ).order_by(MaxPowerMessengerTrial.completed_at.desc(), MaxPowerMessengerTrial.id.desc()).limit(500)))
    return {"at": now, "general": general_series(reversed(events)),
            "synthetic_4b": synthetic_4b_series(reversed(synthetic)),
            "latency_4b": latency_series(sorted(trials + synthetic, key=lambda t: (aware(t.completed_at), t.id))),
            "messenger": messenger_series(reversed(trials)),
            "resources": [{"at": event.created_at, **resource_metrics(event.evidence or {})}
                          for event in reversed(resources)],
            "scope": "latest_500_experiments_per_channel_not_production_quality",
            "resource_interval_seconds": 60}


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
    row.session_generation = (row.session_generation or 0) + 1
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
        # Cancel all outstanding Messenger claims without deleting evidence.
        # A running Qwen call may finish, but the fenced claim cannot commit.
        trials = list(db.scalars(select(MaxPowerMessengerTrial).where(
            MaxPowerMessengerTrial.org_id == user.org_id,
            MaxPowerMessengerTrial.status == "running").with_for_update()))
        for trial in trials:
            trial.status = "queued"
            trial.lease_until = None
            trial.claim_token = None
            trial.next_at = now
        if row.last_tick_at:
            row.on_seconds += int(min(15, max(0, (
                aware(now) - aware(row.last_tick_at)).total_seconds())))
            row.last_tick_at = None
        row.enabled = False
        row.session_started_at = None
        row.last_stopped_at = now
        row.last_status = "off"
        row.last_reason = "Detenido por administración; progreso y evidencia conservados"
        # Make OFF visible synchronously; the sidecar may be finishing one
        # slow optimizer step before noticing the changed session generation.
        cpu_event = db.scalar(select(MaxPowerEvent).where(
            MaxPowerEvent.org_id == user.org_id,
            MaxPowerEvent.round_id == user.org_id,
            MaxPowerEvent.event == "cpu_supervisor_status").with_for_update())
        if cpu_event is not None:
            previous = cpu_event.evidence or {}
            active = previous.get("state") in {
                "training", "training_synthetic", "preparing_synthetic", "pausing"
            }
            # OFF revokes the generation immediately, but a slow child can
            # still be winding down. Preserve a bounded reservation across
            # OFF -> ON rather than allowing the private 4B to race LoRA.
            prior_until = previous.get("draining_until_epoch")
            until = max(
                float(prior_until) if isinstance(prior_until, (int, float)) else 0,
                aware(now).timestamp() + 180 if active else 0,
            )
            cpu_event.reason = "MAX POWER apagado: permiso neuronal revocado"
            cpu_event.evidence = {"state": "off", "generation": row.session_generation,
                                  "draining_until_epoch": until}
            cpu_event.created_at = now
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
