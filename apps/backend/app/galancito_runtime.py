"""Shared, bounded inference gate and content-free measurements."""
from time import perf_counter
from zlib import crc32
from sqlalchemy import text
from .galancito_local import last_timings
from .galancito_knowledge_models import AssistantRun
from .version import VERSION, SOURCE_COMMIT


def infer(db, generate, *, org_id: str | None = None):
    last_timings.set({})
    # Shared by API and Messenger containers. No unbounded Python/DB queue.
    # Ollama remains limited to one inference and two queued requests as a
    # second boundary. A busy request uses the deterministic fallback.
    if db.bind.dialect.name == "postgresql":
        # Keep the original global local-Ollama gate, but isolate external AI
        # requests by organization so one tenant does not block another.
        if org_id:
            lane = crc32(org_id.encode("utf-8")) & 0x7fffffff
            query = text("SELECT pg_try_advisory_xact_lock(2075002, :lane)")
            acquired = db.scalar(query, {"lane": lane})
        else:
            acquired = db.scalar(text("SELECT pg_try_advisory_xact_lock(2075001)"))
        if not acquired:
            last_timings.set({"queue_ms": 0, "busy": True})
            raise RuntimeError("Galancito está ocupado")
    return generate()


def record_run(db, *, org_id, user_id=None, channel, source, intent, started, db_ms=0, timings=None):
    row = AssistantRun(org_id=org_id, user_id=user_id, channel=channel, source=source,
                       intent=intent, elapsed_ms=max(0, round((perf_counter() - started) * 1000)),
                       timings={"db_ms": round(db_ms, 3), "release": VERSION,
                                "revision": SOURCE_COMMIT, **(timings or {})})
    db.add(row)
    db.flush()
    return row
