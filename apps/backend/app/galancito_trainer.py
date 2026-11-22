"""Durable simulation worker. No Meta credentials, delivery calls or private chats."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import logging
from time import monotonic, sleep
from types import SimpleNamespace

from sqlalchemy import delete, exists, select, text
from sqlalchemy.exc import SQLAlchemyError

from .ai_gateway import AIServiceError, invoke, monthly_tokens, record_usage
from .ai_models import AIConnection, AIOrchestration
from .config import settings
from .db import SessionLocal
from .facebook_crm_models import FacebookChatMessage
from .galancito_local import generate_training_text, last_timings
from .galancito_runtime import infer
from .galancito_memory import aware
from .galancito_training import (DETAIL_DAYS, HISTORY_DAYS, LEASE_SECONDS, LOCAL_CONTEXT_LIMIT,
                                  LOCAL_OUTPUT_LIMIT, ResourceSampler, eligible_at, resource_slots)
from .galancito_training_data import DATASET_VERSION, MESSENGER_FOCUS, scenario
from .galancito_real_learning import (LIVE_DATASET_VERSION, LIVE_EVALUATION_VERSION,
                                       LIVE_PROMPT, COACHING, evaluate_live,
                                       paired_holdout_metrics)
from .galancito_internal_training import (
    INTERNAL_DATASET_VERSION, INTERNAL_EVALUATION_VERSION,
    INTERNAL_PROMPT, internal_case, evaluate_internal,
)
from .galancito_training_eval import CORRECTOR_PROMPT, EVALUATION_VERSION, JUDGE_PROMPT, PROMPT, PROPOSALS, evaluate
from .galancito_training_model import TrainingModel
from .galancito_training_models import TERMINAL, TrainingCase, TrainingRound, TrainingWorker
from .models import uid, utcnow
from .version import SOURCE_COMMIT

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
LOCK_KEY = 2098001
CPU_THREADS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="training-case")


class BudgetReached(Exception):
    pass


class ProviderUnavailable(Exception):
    pass


class Deferred(Exception):
    pass


class ClaimGone(Exception):
    pass


@contextmanager
def worker_lock(factory):
    bind = factory.kw["bind"]
    if bind.dialect.name != "postgresql":
        yield True
        return
    with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        granted = conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY})
        try:
            yield granted
        finally:
            if granted and not conn.invalidated:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})


def heartbeat(db, snapshot, now):
    snapshot = {**snapshot, "worker_commit": SOURCE_COMMIT}
    row = db.get(TrainingWorker, 1)
    if row is None:
        db.add(TrainingWorker(id=1, updated_at=now, resources=snapshot))
    else:
        row.updated_at, row.resources = now, snapshot


def lock_round(db, round_id):
    return db.scalar(select(TrainingRound).where(TrainingRound.id == round_id).with_for_update())


def finish(row, state, reason, now):
    row.state, row.reason, row.finished_at = state, reason, now
    row.lease = row.lease_until = None


def collect_old(db, now):
    old_details = select(TrainingRound.id).where(TrainingRound.finished_at < now - timedelta(days=DETAIL_DAYS))
    db.execute(delete(TrainingCase).where(TrainingCase.round_id.in_(old_details)))
    old_rounds = select(TrainingRound.id).where(TrainingRound.finished_at < now - timedelta(days=HISTORY_DAYS))
    db.execute(delete(TrainingRound).where(TrainingRound.id.in_(old_rounds)))


def messenger_busy(db):
    # Only the presence of outstanding work. No lead, message body or token is read.
    return db.scalar(select(exists().where(FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.state.in_(("pending", "ai_pending", "drafting", "sending")),
        FacebookChatMessage.updated_at >= utcnow() - timedelta(minutes=2))))


def claim(factory, snapshot, *, maintenance=False, training_model=None):
    now = utcnow()
    with factory.begin() as db:
        heartbeat(db, snapshot, now)
        if maintenance:
            collect_old(db, now)
        rows = db.scalars(select(TrainingRound).where(
            TrainingRound.state.in_(("queued", "practicing", "evaluating", "correcting")),
            TrainingRound.next_at <= now,
        ).order_by(TrainingRound.next_at, TrainingRound.created_at).limit(8).with_for_update(skip_locked=True)).all()
        for row in rows:
            if row.lease and db.bind.dialect.name != "postgresql" and aware(row.lease_until) > now:
                continue
            if row.attempts >= MAX_ATTEMPTS:
                finish(row, "error", row.reason or "Se agotaron los reintentos del caso", now)
                continue
            internal = row.config.get("profile", "postulantes") == "interno"
            live = internal and row.config.get("suite") == "live"
            expected_dataset = (LIVE_DATASET_VERSION if live else
                                INTERNAL_DATASET_VERSION if internal else DATASET_VERSION)
            expected_evaluation = (LIVE_EVALUATION_VERSION if live else
                                   INTERNAL_EVALUATION_VERSION if internal else EVALUATION_VERSION)
            if row.config["dataset_version"] != expected_dataset:
                finish(row, "error", "Cambió la versión del generador durante la sesión", now)
                continue
            if row.config.get("evaluation_version", 1) != expected_evaluation:
                finish(row, "error", "Cambió la metodología de evaluación. Inicia una nueva ronda.", now)
                continue
            if row.metrics.get("elapsed_seconds", 0) >= row.config["minutes"] * 60:
                finish(row, "completed", "Se alcanzó la duración configurada", now)
                continue
            next_at = eligible_at(row.config, now)
            if next_at > now:
                row.state, row.next_at = "queued", next_at
                row.lease = row.lease_until = None
                row.reason = "Fuera de la ventana nocturna"
                continue
            slots, reason = resource_slots(row.config, snapshot, settings().galancito_memory_reserve_mb)
            if slots and messenger_busy(db):
                slots, reason = 0, "Messenger tiene prioridad"
            if slots and training_model is not None and any(
                row.config.get(role, {}).get("id") == "ollama" for role in ("model", "judge", "corrector")
            ):
                # The immutable round snapshot determines the actual model,
                # including old rounds created before the Qwen3.5 upgrade.
                targets = {row.config[role]["model"] for role in ("model", "judge", "corrector")
                           if row.config.get(role, {}).get("id") == "ollama"}
                if len(targets) != 1:
                    slots, reason = 0, "La ronda contiene versiones Ollama diferentes"
                else:
                    reason = training_model.waiting_reason(snapshot["disk_free_mb"], next(iter(targets)))
                if reason:
                    slots = 0
            if not slots:
                row.state, row.reason, row.next_at = "queued", reason, now + timedelta(seconds=20)
                row.lease = row.lease_until = None
                continue
            row.state, row.reason = "practicing", None
            row.lease, row.lease_until = uid(), now + timedelta(seconds=LEASE_SECONDS)
            row.attempts += 1
            # Specialized cycles must checkpoint the previous cycle's
            # corrections before the next case. Never parallelize across its boundary.
            if row.config.get("focus") in MESSENGER_FOCUS:
                slots = 1
            return row, min(slots, row.target - row.completed)
    return None


def active_claim(db, claim, *, allow_paused=True):
    row = lock_round(db, claim.id)
    if (row is None or row.lease != claim.lease or row.state in TERMINAL
            or (not allow_paused and row.state == "paused")):
        raise ClaimGone()
    return row


def _update_stage(factory, claim, state):
    with factory.begin() as db:
        row = active_claim(db, claim)
        if row.state != "paused":
            row.state = state
        row.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)


def _charge(factory, claim, spec, instructions, prompt, seed, *, role, sampler, thinking=False):
    provider = spec["id"]
    local = provider == "ollama"
    output_limit = (512 if thinking and role == "reply" else
                    {"reply": LOCAL_OUTPUT_LIMIT, "judge": 8, "correction": 96}[role])
    # Preflight by context size locally and conservative UTF-8 bounds externally.
    # An unsuccessful call with unknown usage keeps the reservation.
    reserve = LOCAL_CONTEXT_LIMIT if local else len((instructions + prompt).encode("utf-8")) + 640
    started = monotonic()
    reserved_cost = 0.0
    sent = False
    try:
        with factory.begin() as db:
            row = active_claim(db, claim)
            snapshot = sampler.sample()
            slots, reason = resource_slots(row.config, snapshot, settings().galancito_memory_reserve_mb)
            if not slots or messenger_busy(db):
                raise Deferred(reason or "Messenger tiene prioridad")
            now = utcnow()
            if eligible_at(row.config, now) > now:
                raise Deferred("Fuera de la ventana nocturna")
            heartbeat(db, snapshot, now)
            if not local:
                conn = db.get(AIConnection, provider)
                if not (conn and conn.org_id == row.org_id and conn.enabled and conn.encrypted_key
                        and conn.last_status == "verified" and conn.model == spec["model"]
                        and conn.provider == spec["provider"]
                        and conn.price_input_per_million is not None and conn.price_output_per_million is not None):
                    raise ProviderUnavailable("La conexión externa cambió o dejó de estar verificada")
                policy = db.get(AIOrchestration, row.org_id)
                if policy and policy.monthly_token_limit and monthly_tokens(db, row.org_id) + reserve > policy.monthly_token_limit:
                    raise BudgetReached("Se alcanzó la cuota mensual configurada")
                reserved_cost = (float(conn.price_input_per_million) * (reserve - output_limit)
                                 + float(conn.price_output_per_million) * output_limit) / 1_000_000
            metrics = dict(row.metrics)
            tokens = sum(metrics.get(key, 0) for key in ("input_tokens", "output_tokens", "reserved_tokens"))
            if tokens + reserve > row.config["token_budget"]:
                raise BudgetReached("Se alcanzó el presupuesto de tokens")
            if metrics.get("cost", 0) + metrics.get("reserved_cost_usd", 0) + reserved_cost > row.config["cost_budget"]:
                raise BudgetReached("Se alcanzó el presupuesto estimado de API")
            metrics["reserved_tokens"] = metrics.get("reserved_tokens", 0) + reserve
            metrics["reserved_cost_usd"] = metrics.get("reserved_cost_usd", 0) + reserved_cost
            row.metrics = metrics
            row.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
        sent = True
        if local:
            cfg = SimpleNamespace(galancito_num_ctx=LOCAL_CONTEXT_LIMIT, galancito_num_predict=output_limit,
                                  galancito_num_thread=1, galancito_keep_alive="2m",
                                  galancito_local_model=spec["model"])
            def invoke_local():
                return (generate_training_text(instructions, prompt, seed, cfg, thinking=True)
                        if thinking else generate_training_text(instructions, prompt, seed, cfg))
            if spec["model"] == "qwen3.5:4b-q4_K_M":
                # Same PostgreSQL gate as the authenticated GALANT chat and
                # Messenger. Training cannot monopolize the shared 4B model.
                try:
                    with factory.begin() as inference_db:
                        answer = infer(inference_db, invoke_local)
                except RuntimeError as exc:
                    if str(exc) == "Galancito está ocupado":
                        raise Deferred("Chat real usando Ollama; práctica reprogramada") from None
                    raise
            else:
                answer = invoke_local()
            measured = last_timings.get()
            counts = (measured.get("input_tokens"), measured.get("output_tokens"))
        else:
            answer, inp, out = invoke(conn, instructions=instructions, prompt=prompt, max_output_tokens=output_limit)
            counts = (inp, out) if inp or out else (None, None)
        with factory.begin() as db:
            row = lock_round(db, claim.id)
            cost = 0.0
            if not local:
                usage = record_usage(db, conn, "training_" + role, status="success",
                                     input_tokens=counts[0] or 0, output_tokens=counts[1] or 0,
                                     duration_ms=round((monotonic() - started) * 1000))
                cost = float(usage.estimated_cost_usd or 0)
            if row and None not in counts:
                metrics = dict(row.metrics)
                metrics["reserved_tokens"] = max(0, metrics["reserved_tokens"] - reserve)
                metrics["reserved_cost_usd"] = max(0, metrics["reserved_cost_usd"] - reserved_cost)
                metrics["input_tokens"] = metrics.get("input_tokens", 0) + counts[0]
                metrics["output_tokens"] = metrics.get("output_tokens", 0) + counts[1]
                metrics["cost"] = metrics.get("cost", 0) + cost
                row.metrics = metrics
        return answer
    except (AIServiceError, RuntimeError):
        if not local and sent:
            with factory.begin() as db:
                record_usage(db, conn, "training_" + role, status="error",
                             duration_ms=round((monotonic() - started) * 1000))
        raise ProviderUnavailable("El modelo de práctica no respondió") from None


def checkpoints(factory, claim, results, snapshot, elapsed):
    with factory.begin() as db:
        row = active_claim(db, claim)
        metrics = dict(row.metrics)
        dims, errors = dict(metrics.get("dimensions", {})), dict(metrics.get("errors", {}))
        sources = dict(metrics.get("reply_sources", {}))
        cycles = dict(metrics.get("cycles", {}))
        for result in results:
            if row.config.get("profile") == "interno" or row.config.get("focus") in MESSENGER_FOCUS:
                cycle = str(row.completed // row.config["cases"] + 1)
                item = dict(cycles.get(cycle, {"passed": 0, "failed": 0, "critical": 0, "errors": {}}))
                item["passed" if result["passed"] else "failed"] += 1
                item["critical"] += result["critical"]
                per_cycle_errors = dict(item.get("errors", {}))
                for error, amount in result["errors"].items():
                    per_cycle_errors[error] = per_cycle_errors.get(error, 0) + amount
                item["errors"] = per_cycle_errors
                cycles[cycle] = item
            db.add(TrainingCase(round_id=row.id, position=row.completed, case_id=result["id"],
                                passed=result["passed"], result=result))
            row.completed += 1
            for field in ("fields", "correct_fields", "repeated_turns", "questions", "repeated_questions",
                          "pending_repeats", "critical", "latency_ms"):
                metrics[field] = metrics.get(field, 0) + result[field]
            metrics["turns"] = metrics.get("turns", 0) + len(result["turns"])
            status = "passed" if result["passed"] else "failed"
            metrics[status] = metrics.get(status, 0) + 1
            if result["naturalness_review"] is not None:
                metrics["judged_cases"] = metrics.get("judged_cases", 0) + 1
                metrics["judged_turns"] = metrics.get("judged_turns", 0) + len(result["turns"])
            for key, value in result["reply_sources"].items():
                sources[key] = sources.get(key, 0) + value
            for key, value in result["dimensions"].items():
                dims[key] = dims.get(key, 0) + value
            for key, value in result["errors"].items():
                errors[key] = errors.get(key, 0) + value
        metrics.update(dimensions=dims, errors=errors, reply_sources=sources, cycles=cycles,
                       elapsed_seconds=metrics.get("elapsed_seconds", 0) + elapsed)
        # Focused Messenger loops can adjust bounded prompt instructions between
        # cycles. The last paired A/B cycles use independent synthetic holdout
        # fixtures; they are NEVER evidence of real-world learning or fine-tuning.
        focused = (row.config.get("profile") == "postulantes"
                   and row.config.get("focus") in MESSENGER_FOCUS)
        if focused and row.completed % row.config["cases"] == 0:
            cycle_no = row.completed // row.config["cases"]
            cycle = str(cycle_no)
            item = cycles[cycle]
            item["pass_rate"] = round(item["passed"] / max(1, item["passed"] + item["failed"]), 4)
            cycles_total = row.config.get("cycles", 1)
            reserved = cycles_total >= 4 and cycle_no >= cycles_total - 1
            item["holdout"] = reserved
            item["holdout_role"] = ("baseline" if cycle_no == cycles_total - 1 else
                                    "candidate" if cycle_no == cycles_total else None) if reserved else None
            cycles[cycle] = item
            if not reserved:
                coaching = list(metrics.get("messenger_coaching", []))
                for name in item.get("errors", {}):
                    proposal = PROPOSALS.get(name)
                    if proposal and proposal not in coaching:
                        coaching.append(proposal)
                metrics["messenger_coaching"] = coaching[:3]
            if reserved and cycle_no == cycles_total:
                size = row.config["cases"]
                db.flush()
                a = list(db.scalars(select(TrainingCase).where(
                    TrainingCase.round_id == row.id,
                    TrainingCase.position >= (cycles_total - 2) * size,
                    TrainingCase.position < (cycles_total - 1) * size,
                ).order_by(TrainingCase.position)))
                b = list(db.scalars(select(TrainingCase).where(
                    TrainingCase.round_id == row.id,
                    TrainingCase.position >= (cycles_total - 1) * size,
                    TrainingCase.position < cycles_total * size,
                ).order_by(TrainingCase.position)))
                if len(a) == len(b) == size:
                    comparison = paired_holdout_metrics(
                        [case.passed for case in a], [case.passed for case in b])
                    metrics["synthetic_holdout_baseline_rate"] = comparison["baseline_pass_rate"]
                    metrics["synthetic_holdout_candidate_rate"] = comparison["candidate_pass_rate"]
                    metrics["synthetic_holdout_gains"] = comparison["gain_cases"]
                    metrics["synthetic_holdout_regressions"] = comparison["regressions"]
                # A grade on the same reserved synthetic cases is ONLY a lab finding.
                metrics["synthetic_improvement_observed"] = bool(
                    metrics.get("messenger_coaching")
                    and metrics.get("synthetic_holdout_gains", 0) > 0
                    and metrics.get("synthetic_holdout_regressions", 1) == 0
                    and item["critical"] == 0)
            metrics["cycles"] = cycles
        if row.config.get("suite") == "live":
            metrics["evidence_type"] = "live_database"
        if row.config.get("suite") == "live" and row.completed % row.config["cases"] == 0:
            current = str(row.completed // row.config["cases"])
            item = cycles[current]
            # The final two cycles use exactly the SAME reserved real cases:
            # A = uncoached baseline, B = coached candidate with identical
            # Ollama seed. This avoids claiming learning from an easy holdout.
            item["pass_rate"] = round(item["passed"] / max(1, item["passed"] + item["failed"]), 4)
            last_cycle = row.config["cycles"]
            index = int(current)
            item["holdout"] = index >= last_cycle - 1
            item["holdout_role"] = ("baseline" if index == last_cycle - 1 else
                                    "candidate" if index == last_cycle else None)
            cycles[current] = item
            if not item["holdout"]:
                hints = list(metrics.get("real_coaching", []))
                for dimension in item.get("errors", {}):
                    if dimension in COACHING and COACHING[dimension] not in hints:
                        hints.append(COACHING[dimension])
                metrics["real_coaching"] = hints[:3]
            if index == last_cycle:
                cases = row.config["cases"]
                db.flush()
                baseline_start = (last_cycle - 2) * cases
                candidate_start = (last_cycle - 1) * cases
                baseline_rows = list(db.scalars(select(TrainingCase).where(
                    TrainingCase.round_id == row.id,
                    TrainingCase.position >= baseline_start,
                    TrainingCase.position < baseline_start + cases
                ).order_by(TrainingCase.position)))
                candidate_rows = list(db.scalars(select(TrainingCase).where(
                    TrainingCase.round_id == row.id,
                    TrainingCase.position >= candidate_start,
                    TrainingCase.position < candidate_start + cases
                ).order_by(TrainingCase.position)))
                if len(baseline_rows) == cases and len(candidate_rows) == cases:
                    comparison = paired_holdout_metrics(
                        [a.passed for a in baseline_rows],
                        [b.passed for b in candidate_rows])
                    gains, regressions = comparison["gain_cases"], comparison["regressions"]
                    metrics["real_holdout_gain_cases"] = gains
                    metrics["real_holdout_regressions"] = regressions
                    metrics["real_holdout_baseline_pass_rate"] = comparison["baseline_pass_rate"]
                    metrics["real_holdout_pass_rate"] = comparison["candidate_pass_rate"]
                    metrics["real_learning_demonstrated"] = bool(
                        metrics.get("real_coaching") and gains > 0
                        and regressions == 0 and item["critical"] == 0
                        and item["pass_rate"] >= 0.75)
                else:
                    metrics["real_learning_demonstrated"] = False
            else:
                metrics["real_learning_demonstrated"] = False
        for key, measured in (("peak_worker_ram_mb", "worker_ram_mb"), ("peak_host_cpu_percent", "host_cpu_percent")):
            if snapshot[measured] is not None:
                metrics[key] = max(metrics.get(key, 0), snapshot[measured])
        row.metrics = metrics
        row.lease = row.lease_until = None
        row.attempts = 0
        if row.completed == row.target:
            finish(row, "completed", None, utcnow())
        elif row.state != "paused":
            row.state, row.next_at = "queued", utcnow()


def defer(factory, claim, elapsed, error, *, budget=False, pressure=False):
    with factory.begin() as db:
        row = active_claim(db, claim)
        row.metrics = {**row.metrics, "elapsed_seconds": row.metrics.get("elapsed_seconds", 0) + elapsed}
        row.lease = row.lease_until = None
        row.reason = str(error)
        if pressure:
            row.attempts = max(0, row.attempts - 1)
        if row.state == "paused":
            return
        if budget or row.attempts >= MAX_ATTEMPTS:
            finish(row, "completed" if budget else "error", str(error), utcnow())
        else:
            retry = utcnow() + timedelta(seconds=20 if pressure else 10 * 2**row.attempts)
            row.state, row.next_at = "queued", eligible_at(row.config, retry)


def process_next(factory=SessionLocal, sampler=None, *, maintenance=False, training_model=None):
    sampler = sampler or ResourceSampler()
    with worker_lock(factory) as granted:
        if not granted:
            return False
        snapshot = sampler.sample()
        claimed = claim(factory, snapshot, maintenance=maintenance, training_model=training_model)
        if not claimed:
            return False
        row, count = claimed
        started = monotonic()
        model, judge = row.config["model"], row.config["judge"]
        corrector = row.config.get("corrector", {"id": "rules"})
        knowledge = row.knowledge if row.config["suite"] != "holdout" else [
            {**item, "phrase": None, "reply": None} for item in row.knowledge]
        def run(position):
            seed = int(row.dataset_hash[:8], 16) ^ position
            if row.config.get("suite") == "live":
                case_count = row.config["cases"]
                cycle_number = position // case_count + 1
                held_out = cycle_number >= row.config["cycles"] - 1
                baseline_holdout = cycle_number == row.config["cycles"] - 1
                case_index = position % case_count
                fixture = row.config["live_cases"][case_index +
                                                  (case_count if held_out else 0)]
                coach = [] if baseline_holdout else row.metrics.get("real_coaching", [])
                # Paired held-out cases use identical generation seeds.
                model_seed = (int(row.dataset_hash[:8], 16) ^ case_index ^
                              (314159 if held_out else cycle_number)) % (2**31)
                def real_answer(context, instructions):
                    system = LIVE_PROMPT + ("\nConsejos revisados tras errores anteriores:\n" +
                                            "\n".join(instructions) if instructions else "")
                    return _charge(factory, row, model, system, context,
                                   model_seed, role="reply", sampler=sampler, thinking=True)
                result = evaluate_live(fixture, answer=real_answer, coach=coach)
                result["id"] = fixture["id"] + "-c" + str(cycle_number)
                return result
            if row.config.get("profile", "postulantes") == "interno":
                fixture = internal_case(row.config, position)
                def internal_answer(context):
                    return _charge(factory, row, model, INTERNAL_PROMPT, context,
                                   seed % (2**31), role="reply", sampler=sampler)
                return evaluate_internal(
                    fixture, answer=internal_answer if model["id"] != "guided" else None,
                    stage=(lambda state: _update_stage(factory, row, state))
                          if count == 1 else (lambda _: None),
                )
            focused = (row.config.get("profile", "postulantes") == "postulantes"
                       and row.config.get("focus") in MESSENGER_FOCUS)
            cycle_number = position // row.config["cases"] + 1
            cycle_total = row.config.get("cycles", 1)
            reserved = focused and cycle_total >= 4 and cycle_number >= cycle_total - 1
            baseline = reserved and cycle_number == cycle_total - 1
            case_index = position % row.config["cases"]
            scenario_config = ({**row.config, "suite": "holdout"} if reserved else row.config)
            scenario_position = case_index if reserved else position
            case_seed = ((int(row.dataset_hash[:8], 16) ^ case_index ^ 48171) % (2**31)
                         if reserved else seed % (2**31))

            def ask(context):
                instructions = PROMPT
                if focused and not baseline:
                    approved_hints = row.metrics.get("messenger_coaching", [])
                    if approved_hints:
                        instructions += "\\nAjustes medidos en ciclos sintéticos anteriores (sin datos reales):\\n" + (
                            "\\n".join(approved_hints[:3])[:520])
                if model["id"] == "ollama" and knowledge:
                    instructions += "\nCriterios revisados del laboratorio:\n" + "\n".join(
                        item["instruction"] for item in knowledge)[:500]
                return _charge(factory, row, model, instructions, context, case_seed, role="reply", sampler=sampler)

            def score(context):
                return _charge(factory, row, judge, JUDGE_PROMPT, context, case_seed, role="judge", sampler=sampler)

            def suggest(context):
                return _charge(factory, row, corrector, CORRECTOR_PROMPT, context, case_seed,
                               role="correction", sampler=sampler)

            result = evaluate(scenario(scenario_config, scenario_position), row.aliases, knowledge,
                            answer=ask if model["id"] != "guided" else None,
                            judge=score if judge["id"] != "rules" else None,
                            corrector=suggest if corrector["id"] != "rules" else None,
                            stage=(lambda state: _update_stage(factory, row, state)) if count == 1 else (lambda _: None),
                            profile_review=row.config.get("profile_review", False))
            if focused and reserved:
                result["id"] += "-c" + str(cycle_number)
            return result

        try:
            positions = range(row.completed, row.completed + count)
            results = [run(row.completed)] if count == 1 else list(CPU_THREADS.map(run, positions))
            checkpoints(factory, row, results, sampler.sample(), monotonic() - started)
        except ClaimGone:
            pass
        except (BudgetReached, ProviderUnavailable, Deferred) as exc:
            try:
                defer(factory, row, monotonic() - started, exc, budget=isinstance(exc, BudgetReached),
                      pressure=isinstance(exc, Deferred))
            except ClaimGone:
                pass
        except Exception as exc:
            logger.error("Falló un caso del laboratorio (%s)", type(exc).__name__)
            try:
                defer(factory, row, monotonic() - started, "Error interno durante la simulación")
            except ClaimGone:
                pass
        return True


def main():
    from . import main as _application  # Load related models before resolving SQLAlchemy FKs.

    logging.basicConfig(level=logging.INFO)
    sampler = ResourceSampler()
    next_cleanup = 0
    training_model = TrainingModel()
    while True:
        try:
            maintenance = monotonic() >= next_cleanup
            processed = process_next(sampler=sampler, maintenance=maintenance, training_model=training_model)
            if maintenance:
                next_cleanup = monotonic() + 3600
            sleep(0.15 if processed else 3)
        except SQLAlchemyError as exc:
            logger.warning("Base de datos del entrenador en espera (%s)", type(exc).__name__)
            sleep(5)


if __name__ == "__main__":
    main()
