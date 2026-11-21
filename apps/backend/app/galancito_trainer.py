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
from .galancito_memory import aware
from .galancito_training import (DETAIL_DAYS, HISTORY_DAYS, LEASE_SECONDS, LOCAL_CONTEXT_LIMIT,
                                  LOCAL_OUTPUT_LIMIT, ResourceSampler, eligible_at, resource_slots)
from .galancito_training_data import DATASET_VERSION, scenario
from .galancito_training_eval import CORRECTOR_PROMPT, EVALUATION_VERSION, JUDGE_PROMPT, PROMPT, evaluate
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
            if row.config["dataset_version"] != DATASET_VERSION:
                finish(row, "error", "Cambió la versión del generador durante la sesión", now)
                continue
            if row.config.get("evaluation_version", 1) != EVALUATION_VERSION:
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


def _charge(factory, claim, spec, instructions, prompt, seed, *, role, sampler):
    provider = spec["id"]
    local = provider == "ollama"
    output_limit = {"reply": LOCAL_OUTPUT_LIMIT, "judge": 8, "correction": 96}[role]
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
            answer = generate_training_text(instructions, prompt, seed, cfg)
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
        for result in results:
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
        metrics.update(dimensions=dims, errors=errors, reply_sources=sources, elapsed_seconds=metrics.get("elapsed_seconds", 0) + elapsed)
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
            def ask(context):
                instructions = PROMPT
                if model["id"] == "ollama" and knowledge:
                    instructions += "\nCriterios revisados del laboratorio:\n" + "\n".join(
                        item["instruction"] for item in knowledge)[:500]
                return _charge(factory, row, model, instructions, context, seed % (2**31), role="reply", sampler=sampler)

            def score(context):
                return _charge(factory, row, judge, JUDGE_PROMPT, context, seed % (2**31), role="judge", sampler=sampler)

            def suggest(context):
                return _charge(factory, row, corrector, CORRECTOR_PROMPT, context, seed % (2**31),
                               role="correction", sampler=sampler)

            return evaluate(scenario(row.config, position), row.aliases, knowledge,
                            answer=ask if model["id"] != "guided" else None,
                            judge=score if judge["id"] != "rules" else None,
                            corrector=suggest if corrector["id"] != "rules" else None,
                            stage=(lambda state: _update_stage(factory, row, state)) if count == 1 else (lambda _: None),
                            profile_review=row.config.get("profile_review", False))

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
