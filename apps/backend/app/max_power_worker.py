"""Autonomous low-priority conductor; loops indefinitely until switched off.

Schedules real Qwen experiments and lightweight synthetic intake evaluation.
Production prompts, weights, permissions and external API settings are fixed.
"""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import logging
import re
from pathlib import Path
from time import sleep
from fastapi import HTTPException
from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError

from .db import SessionLocal
from .galancito_memory import aware
from .galancito_real_learning import collect_live_cases
from .galancito_trainer import messenger_busy, heartbeat, process_next
from .facebook_crm_models import FacebookChatMessage
from .galancito_training import ResourceSampler, summarize, inference_percentile_ms
from .galancito_training_api import RoundInput, start
from .galancito_training_models import ACTIVE, TrainingCase, TrainingRound, TrainingWorker
from .galancito_training_model import TrainingModel
from .max_power_decisions import QWEN_MIN_RAM_MB, can_run, classify_outcome, evidence_fingerprint, select_experiment_plan, worksite_holdout_sign_test
from .max_power_models import MaxPowerEvent, MaxPowerState, MaxPowerMessengerTrial
from .max_power_messenger import schedule_next, process_one, schedule_synthetic_reply
from .max_power_practice import EVENT as PRACTICE_EVENT, generate_scenarios, practice_id, run_practice
from .config import settings
from .galancito_general import QWEN_4B
from .galancito_local import MAX_POWER_ISOLATED
from .models import Organization, User, utcnow

logger = logging.getLogger(__name__)
QUIET_WINDOW_SECONDS = 90

def messenger_recent(db):
    """A training job must yield while Messenger has recent inbound traffic.

    An outbound queue check alone misses the interval before the reply is queued.
    This is conservative admission control, not inference preemption.
    """
    return db.scalar(select(FacebookChatMessage.id).where(
        FacebookChatMessage.direction == "inbound",
        FacebookChatMessage.created_at >= utcnow() - timedelta(seconds=QUIET_WINDOW_SECONDS),
    ).limit(1)) is not None

IDLE_SECONDS = 20
RECHECK_SECONDS = 300
RESOURCE_RECHECK_SECONDS = 30

def _pressure(name):
    try:
        line = next(x for x in Path("/proc/pressure/" + name).read_text().splitlines() if x.startswith("some "))
        result = re.search(r"avg10=([0-9.]+)", line)
        return float(result.group(1)) if result else 0
    except (OSError, StopIteration, ValueError):
        return 0

def set_wait(row, now, code, reason, seconds=RECHECK_SECONDS):
    row.last_status, row.last_reason = code, reason[:280]
    row.next_at = now + timedelta(seconds=seconds)


def _practice_or_wait(db, row, now, reason, *, qwen_ready, wait_status="awaiting_new_evidence", retry_seconds=600):
    scenarios = generate_scenarios()
    run_id = practice_id(scenarios)
    recorded = db.scalar(select(MaxPowerEvent.id).where(
        MaxPowerEvent.org_id == row.org_id, MaxPowerEvent.event == PRACTICE_EVENT,
        MaxPowerEvent.round_id == run_id))
    if recorded:
        if qwen_ready and schedule_synthetic_reply(db, row.org_id, scenarios):
            set_wait(row, now, "synthetic_model_evaluation", "Qwen 4B evalúa respuestas sintéticas en el laboratorio", 30)
            return
        set_wait(row, now, wait_status, reason + ". La práctica sintética vigente ya se evaluó", retry_seconds)
        return
    result = run_practice(scenarios)
    count = result["development"]["cases"] + result["holdout"]["cases"]
    detail = f"Práctica sintética completada: {count} fichas evaluadas en almacenamiento aislado"
    db.add(MaxPowerEvent(org_id=row.org_id, event=PRACTICE_EVENT, round_id=run_id,
                         reason=detail, evidence=result))
    set_wait(row, now, "synthetic_practice_completed", detail + ". " + reason, 60)

def _result(db, row, completed, now):
    metrics = completed.metrics or {}
    # Count independently represented worksites, not 8 correlated questions
    # about one worksite as 8 independent empirical observations.
    cases = int((completed.config or {}).get("cases") or 0)
    cycles = int((completed.config or {}).get("cycles") or 0)
    if cases and cycles >= 4 and completed.completed == completed.target:
        paired_rows = list(db.scalars(select(TrainingCase).where(
            TrainingCase.round_id == completed.id,
            TrainingCase.position >= (cycles - 2) * cases,
        ).order_by(TrainingCase.position)))
        if len(paired_rows) == 2 * cases:
            def comparable(entry):
                result = entry.result or {}
                return {"case_id": entry.case_id,
                        "passed": result.get("passed"),
                        "evidence_hash": (result.get("evidence") or {}).get("evidence_hash")}
            clustered = worksite_holdout_sign_test(
                [comparable(e) for e in paired_rows[:cases]],
                [comparable(e) for e in paired_rows[cases:]])
            if clustered:
                metrics = {**metrics, **clustered}
    outcome = classify_outcome(metrics)
    interrupted = completed.state != "completed" or completed.completed != completed.target
    fingerprint = row.last_evidence_hash
    previous = row.latest_result or {}
    repeat_failures = (int(previous.get("consecutive_failures") or 0)
                       if previous.get("evidence_fingerprint") == fingerprint else 0)
    failures = repeat_failures + 1 if interrupted else 0
    if interrupted:
        # Include only the already-sanitized worker reason, never private text.
        detail = str(completed.reason or "motivo no registrado")[:110]
        outcome = {**outcome, "code": "interrupted",
                   "reason": f"Ronda {completed.state}: {detail}; mejora no verificada",
                   "next": "Reintento controlado del mismo conjunto" if failures < 3
                           else "Esperar datos nuevos tras tres rondas fallidas",
                   "lab_verified": False}
    samples = int(metrics.get("ollama_timing_samples") or 0)
    totals = metrics.get("ollama_timing_totals") or {}
    timing = {k: round(v / samples, 2) for k, v in totals.items()
              if samples > 0 and isinstance(v, (int, float))}
    # Durable idempotency: a terminal round may be revisited after a restart.
    already = db.scalar(select(MaxPowerEvent.id).where(
        MaxPowerEvent.org_id == row.org_id,
        MaxPowerEvent.event == "experiment_completed",
        MaxPowerEvent.round_id == completed.id))
    if already:
        row.active_round_id = None
        row.last_round_id = completed.id
        set_wait(row, now, "awaiting_new_evidence",
                 "Experimento ya registrado; no se duplicó el resultado", 60)
        return
    row.experiments += 1
    row.examined_cases += int(completed.completed or 0)
    # Interrupted work may preserve evidence, but is never tallied as a gain.
    if completed.state == "completed" and completed.completed == completed.target:
        row.lab_gains += outcome["holdout_wins"]
    row.regressions += outcome["holdout_losses"]
    row.last_round_id = completed.id
    row.active_round_id = None
    statistics = summarize(metrics, "interno")
    # Only paired, identical reserved questions support a latency comparison.
    paired_speed = None
    if cases and cycles >= 4 and completed.completed == completed.target:
        rows = list(db.scalars(select(TrainingCase).where(
            TrainingCase.round_id == completed.id,
            TrainingCase.position >= (cycles - 2) * cases,
        ).order_by(TrainingCase.position)))
        baseline, candidate = rows[:cases], rows[cases:]
        def sample(case):
            try:
                return float(case.result["turns"][0]["inference_ms"])
            except (KeyError, IndexError, TypeError, ValueError):
                return None
        if len(baseline) == len(candidate) == cases and all(
            a.result.get("evidence", {}).get("evidence_hash") == b.result.get("evidence", {}).get("evidence_hash")
            for a, b in zip(baseline, candidate)):
            before = [sample(a) for a in baseline]
            after = [sample(b) for b in candidate]
            if all(v is not None and v >= 0 for v in before + after):
                p50_before = inference_percentile_ms(before, 0.5)
                p50_after = inference_percentile_ms(after, 0.5)
                paired_speed = {"pairs": cases, "baseline_p50_ms": p50_before,
                                "candidate_p50_ms": p50_after,
                                "delta_p50_ms": round(p50_after - p50_before, 2),
                                "baseline_p95_ms": inference_percentile_ms(before, 0.95),
                                "candidate_p95_ms": inference_percentile_ms(after, 0.95),
                                "verified_in_production": False,
                                "note": "Prueba exploratoria pareada; no demuestra ganancia de rendimiento sostenida"}
    row.latest_result = {**outcome, "completed_at": now.isoformat(),
                         "round_state": completed.state, "model": (completed.config or {}).get("model", {}).get("model"),
                         "evaluated_cases": completed.completed, "ollama_avg": timing,
                         "inference_p50_ms": statistics["inference_p50_ms"],
                         "inference_p95_ms": statistics["inference_p95_ms"],
                         "inference_samples": statistics["inference_samples"],
                         "paired_speed": paired_speed,
                         "evidence_fingerprint": fingerprint,
                         "consecutive_failures": failures}
    # No falsely asserted production gain. A lab win still awaits review/promotion.
    # Keep value-bearing aggregate evidence even after routine training-case pruning.
    audit_snapshot = {
        "source": "real_db_aggregate", "model": row.latest_result["model"],
        "system_version": completed.system_version,
        "prompt_version": completed.prompt_version,
        "dataset_hash": completed.dataset_hash,
        "evaluated_cases": completed.completed,
        "holdout_baseline_rate": metrics.get("real_holdout_baseline_pass_rate"),
        "holdout_candidate_rate": metrics.get("real_holdout_pass_rate"),
        "failed_by_criterion": metrics.get("errors", {}),
        "cycle_summaries": metrics.get("cycles", {}),
        "inference_p50_ms": statistics["inference_p50_ms"],
        "inference_p95_ms": statistics["inference_p95_ms"],
        "paired_speed": paired_speed,
        **{k: row.latest_result[k] for k in
           ("holdout_pairs", "holdout_wins", "holdout_losses", "p_value",
            "independent_worksite_groups", "worksite_wins",
            "worksite_losses",
            "lab_verified", "production_verified", "weights_changed")},
    }
    db.add(MaxPowerEvent(org_id=row.org_id, event="experiment_completed",
                         reason=outcome["reason"], round_id=completed.id,
                         evidence=audit_snapshot))
    if interrupted:
        # The old code consumed this evidence when queuing, even if all A/B
        # comparisons failed. Retry it with backoff, then stop until new facts
        # arrive to avoid burning CPU forever on a persistently broken model.
        if failures < 3:
            row.last_evidence_hash = None
            set_wait(row, now, "retry_after_failure",
                     outcome["reason"] + ". " + outcome["next"],
                     seconds=600 * 2 ** (failures - 1))
        else:
            set_wait(row, now, "awaiting_new_evidence",
                     outcome["reason"] + ". " + outcome["next"],
                     seconds=600)
    else:
        set_wait(row, now, outcome["code"], outcome["reason"] + ". " + outcome["next"])

def tick(db, sampler, *, sampled=None):
    """One transactional decision per organization, protected by row locks."""
    now = utcnow()
    # Lock Organization before MaxPowerState, matching the API/start() lock order.
    # This avoids deadlocks when an admin presses off during a new queue operation.
    org_ids = list(db.scalars(select(MaxPowerState.org_id).where(
        MaxPowerState.enabled.is_(True)).limit(12)))
    if not org_ids:
        return
    snapshot = {**(sampler.sample() if sampled is None else sampled),
                "cpu_pressure_avg10": _pressure("cpu"),
                "memory_pressure_avg10": _pressure("memory"),
                "io_pressure_avg10": _pressure("io")}
    for org_id in org_ids:
        locked_org = db.scalar(select(Organization.id).where(
            Organization.id == org_id).with_for_update(skip_locked=True))
        if not locked_org:
            continue
        row = db.scalar(select(MaxPowerState).where(MaxPowerState.org_id == org_id,
            MaxPowerState.enabled.is_(True)).with_for_update(skip_locked=True))
        if row is None:
            continue
        row.worker_seen_at = now
        if row.last_tick_at:
            # Count actual controller uptime, not days when the VPS was powered off.
            seconds = max(0, (aware(now) - aware(row.last_tick_at)).total_seconds())
            row.on_seconds += int(min(seconds, 15))
        row.last_tick_at = now
        row.updated_at = now
        if not row.active_round_id:
            # Recover a committed queue after interruption between start() and checkpoint.
            # Recover active work first, then the oldest terminal round with no
            # recorded completion. Do not reprocess historical completed rounds.
            orphan = db.scalar(select(TrainingRound).where(
                TrainingRound.org_id == row.org_id,
                TrainingRound.config["orchestrator"].as_string() == "max_power",
                TrainingRound.state.in_(ACTIVE),
            ).order_by(TrainingRound.created_at.desc()).limit(1))
            if orphan is None:
                orphan = db.scalar(select(TrainingRound).outerjoin(
                    MaxPowerEvent, and_(MaxPowerEvent.org_id == TrainingRound.org_id,
                        MaxPowerEvent.round_id == TrainingRound.id,
                        MaxPowerEvent.event == "experiment_completed")
                ).where(
                    TrainingRound.org_id == row.org_id,
                    TrainingRound.config["orchestrator"].as_string() == "max_power",
                    TrainingRound.state.in_(("completed", "stopped", "error")),
                    MaxPowerEvent.id.is_(None),
                ).order_by(TrainingRound.created_at.asc()).limit(1))
            if orphan:
                row.active_round_id = orphan.id
        if row.active_round_id:
            current = db.scalar(select(TrainingRound).where(
                TrainingRound.id == row.active_round_id, TrainingRound.org_id == row.org_id))
            if current is not None and current.state in ACTIVE:
                row.last_status = "evaluating"
                row.last_reason = f"Prueba operativa: {current.completed} de {current.target} casos"
                continue
            if current is not None:
                _result(db, row, current, now)
            else:
                row.active_round_id = None
                set_wait(row, now, "missing_round", "Ronda no encontrada; se conservan datos anteriores")
            continue
        remaining_wait = aware(row.next_at) - aware(now)
        # Older releases applied a five-minute wait to the memory gate. Recheck
        # that inherited wait on startup so enabled organizations can practice.
        if remaining_wait > timedelta() and not (row.last_status == "resource_guard" and
                                                  remaining_wait > timedelta(seconds=RESOURCE_RECHECK_SECONDS)):
            continue
        # Existing manual practice always takes precedence.
        current = db.scalar(select(TrainingRound.id).where(
            TrainingRound.org_id == row.org_id, TrainingRound.state.in_(ACTIVE)))
        if current:
            set_wait(row, now, "manual_round_busy", "Práctica Bot está ocupado; MAX POWER espera", 60)
            continue
        # CPU LoRA and 4B practice must never compete for the same six CPUs.
        # The separate, signed supervisor refreshes this durable heartbeat
        # while genuine optimizer steps run.
        cpu_event = db.scalar(select(MaxPowerEvent).where(
            MaxPowerEvent.org_id == row.org_id,
            MaxPowerEvent.round_id == row.org_id,
            MaxPowerEvent.event == "cpu_supervisor_status"))
        if (cpu_event is not None
                and (cpu_event.evidence or {}).get("state") in ("training", "training_synthetic", "pausing", "cpu_waiting_turn")
                and aware(cpu_event.created_at) >= aware(now) - timedelta(seconds=55)):
            set_wait(row, now, "cpu_neural_training",
                     ("Reservando turno para LoRA CPU verificado; práctica 4B en espera" if
                      (cpu_event.evidence or {}).get("state") == "cpu_waiting_turn" else
                      "LoRA CPU actualiza pesos en un contenedor aislado; prueba 4B en espera"), 30)
            continue
        ok, reason = can_run(snapshot, messenger_pending=bool(
            messenger_busy(db) or messenger_recent(db)))
        if not ok:
            set_wait(row, now, "resource_guard", reason, RESOURCE_RECHECK_SECONDS)
            continue
        owner = db.get(User, row.owner_id)
        if not owner or not owner.enabled or owner.org_id != row.org_id or owner.role != "admin":
            set_wait(row, now, "permission_required", "No hay administrador autorizado para prácticas", 300)
            continue
        cfg = settings()
        isolated_model_ready = MAX_POWER_ISOLATED and snapshot["available_ram_mb"] >= QWEN_MIN_RAM_MB
        qwen_ready = isolated_model_ready and cfg.galancito_local_ai_enabled and cfg.galancito_local_model == QWEN_4B
        if qwen_ready:
            if schedule_next(db, owner):
                set_wait(row, now, "messenger_evaluation",
                         "Probando fallas de Messenger auditadas con Qwen local", 30)
                continue
        try:
            cases = collect_live_cases(db, owner)
        except ValueError as exc:
            _practice_or_wait(db, row, now, str(exc).rstrip("."), qwen_ready=qwen_ready)
            continue
        # Eight reserved pairs are the minimum required for this live evaluator.
        if len(cases) < 16:
            _practice_or_wait(db, row, now,
                              "Se necesitan 16 casos operativos autorizados para obtener 8 pares reservados",
                              qwen_ready=qwen_ready)
            continue
        if not MAX_POWER_ISOLATED:
            _practice_or_wait(db, row, now, "Qwen 4B requiere un Ollama de práctica aislado",
                              qwen_ready=False, wait_status="isolation_unavailable", retry_seconds=300)
            continue
        if not isolated_model_ready:
            _practice_or_wait(db, row, now, "Qwen 4B requiere 8 GB de RAM disponible para proteger Messenger",
                              qwen_ready=False, wait_status="resource_guard", retry_seconds=RESOURCE_RECHECK_SECONDS)
            continue
        worker = db.get(TrainingWorker, 1)
        if not (worker and aware(worker.updated_at) >= aware(now) - timedelta(seconds=150)):
            _practice_or_wait(db, row, now, "El motor de práctica de Qwen 4B no está operativo",
                              qwen_ready=False, wait_status="trainer_unavailable", retry_seconds=30)
            continue
        fingerprint = evidence_fingerprint(cases)
        if row.last_evidence_hash == fingerprint:
            # The unchanged live A/B set cannot be rerun as a new gain, but
            # this must not starve a separate pending synthetic intake lab.
            _practice_or_wait(db, row, now,
                "No hay datos operativos nuevos: no se repite la comparación A/B",
                qwen_ready=qwen_ready)
            continue
        plan = select_experiment_plan(snapshot, len(cases),
                (row.latest_result or {}).get("inference_p95_ms"))
        try:
            result = start(db, owner, RoundInput(
                profile="interno", suite="live", model="ollama",
                cases=plan["cases"], cycles=plan["cycles"],
                minutes=plan["minutes"], cpu_limit_percent=70,
                ram_limit_mb=0, token_budget=plan["token_budget"],
                cost_budget=0, night=False), orchestrator="max_power", commit=False)
        except Exception as exc:
            # A blocked start must not invent a completed experiment or success.
            logger.warning("MAX POWER could not schedule a round: %s", type(exc).__name__)
            explanation = (str(exc.detail) if isinstance(exc, HTTPException) and
                           isinstance(exc.detail, str) else
                           "No se pudo iniciar una ronda real; revisar modelo, datos y motor")
            db.rollback()
            locked = db.get(MaxPowerState, row.org_id)
            if locked is not None:
                set_wait(locked, now, "cannot_schedule", explanation, 300)
                db.commit()
            continue
        row.active_round_id = result["id"]
        row.last_evidence_hash = fingerprint
        row.last_status = "evaluating"
        row.last_reason = "Prueba A/B operativa: muestras reales, sin cambiar pesos"
        row.next_at = now + timedelta(seconds=20)
        db.add(MaxPowerEvent(org_id=row.org_id, event="experiment_queued",
                             reason=row.last_reason, round_id=result["id"],
                             evidence={"evidence_fingerprint": fingerprint,
                                       "planned_cases": result["target"], "data_type": "db_aggregate",
                                       "budget_minutes": plan["minutes"], "plan_basis": plan["basis"]}))
    db.commit()

def main():
    from . import main as _application  # registers all SQLAlchemy models
    logging.basicConfig(level=logging.INFO)
    sampler = ResourceSampler()
    practice_sampler = ResourceSampler()
    local_model = TrainingModel()
    task = None
    # Integrate the preexisting practice engine: ON works with a single button,
    # even if the separate optional 'training' Docker profile is not running.
    # The trainer uses a PostgreSQL advisory lock to prevent duplicate claims.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="max-power-practice") as executor:
        while True:
            try:
                with SessionLocal() as db:
                    enabled = db.scalar(select(MaxPowerState.org_id).where(
                        MaxPowerState.enabled.is_(True)).limit(1)) is not None
                sampled = sampler.sample() if enabled else None
                if sampled is not None:
                    with SessionLocal.begin() as db:
                        heartbeat(db, sampled, utcnow())
                with SessionLocal() as db:
                    tick(db, sampler, sampled=sampled)
                # Container-health probe reflects a successfully completed DB tick.
                Path("/tmp/max_power_controller_heartbeat").touch()
                if task is not None and task.done():
                    try:
                        task.result()
                    except Exception:
                        logger.exception("MAX POWER practice cycle failed; durable state preserved")
                    task = None
                if enabled and task is None:
                    with SessionLocal() as db:
                        due = db.scalar(select(MaxPowerMessengerTrial.id).join(
                            MaxPowerState, MaxPowerMessengerTrial.org_id == MaxPowerState.org_id
                        ).where(MaxPowerState.enabled.is_(True),
                          MaxPowerMessengerTrial.status.in_(("queued", "running")),
                          MaxPowerMessengerTrial.next_at <= utcnow()).limit(1))
                    if due:
                        with SessionLocal() as db:
                            pending = bool(messenger_busy(db) or messenger_recent(db))
                        snapshot = {**practice_sampler.sample(),
                                    "cpu_pressure_avg10": _pressure("cpu"),
                                    "memory_pressure_avg10": _pressure("memory"),
                                    "io_pressure_avg10": _pressure("io")}
                        allowed, block_reason = can_run(snapshot, messenger_pending=pending)
                        if allowed and MAX_POWER_ISOLATED and snapshot["available_ram_mb"] >= QWEN_MIN_RAM_MB:
                            task = executor.submit(process_one)
                        else:
                            logger.debug("MAX POWER Messenger practice yielded: %s", block_reason)
                    else:
                        with SessionLocal() as db:
                            active = db.scalar(select(TrainingRound.id).where(
                                TrainingRound.state.in_(ACTIVE),
                                TrainingRound.config["orchestrator"].as_string() == "max_power").limit(1))
                        if active:
                            task = executor.submit(process_next, sampler=practice_sampler,
                                                   training_model=local_model,
                                                   only_orchestrator="max_power")
            except SQLAlchemyError as exc:
                logger.warning("MAX POWER waiting for database: %s", type(exc).__name__)
            except Exception:
                logger.exception("MAX POWER controller cycle failed")
            sleep(5)

if __name__ == "__main__":
    main()
