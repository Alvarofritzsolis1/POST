"""Shared, bounded inference gate and content-free measurements."""
from time import perf_counter
from sqlalchemy import text
from .galancito_local import last_timings
from .galancito_knowledge_models import AssistantRun


def infer(db, generate):
    last_timings.set({})
    # Shared by API and Messenger containers. No unbounded Python/DB queue.
    # Ollama remains limited to one inference and two queued requests as a
    # second boundary. A busy request uses the deterministic fallback.
    if db.bind.dialect.name == "postgresql" and not db.scalar(
        text("SELECT pg_try_advisory_xact_lock(2075001)")):
        last_timings.set({"queue_ms": 0, "busy": True})
        raise RuntimeError("Galancito está ocupado")
    return generate()


def record_run(db, *, org_id, user_id=None, channel, source, intent, started, db_ms=0, timings=None):
    row = AssistantRun(org_id=org_id, user_id=user_id, channel=channel, source=source,
                       intent=intent, elapsed_ms=max(0, round((perf_counter() - started) * 1000)),
                       timings={"db_ms": round(db_ms, 3), **(timings or {})})
    db.add(row)
    db.flush()
    return row
