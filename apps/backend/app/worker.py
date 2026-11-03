"""Worker aislado con reserva transaccional y recuperación de trabajos atascados."""
import logging
import signal
import time
from datetime import timedelta
from sqlalchemy import or_, select
from .config import settings
from .db import SessionLocal
from .models import Document, utcnow
from .pipeline import process_document
from .control_scheduler import calendar_tick

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("galant.post.worker")
stopping = False


def stop(*_):
    global stopping
    stopping = True


def process_next() -> bool:
    with SessionLocal.begin() as db:
        query = (select(Document)
                 .where(or_(Document.status == "queued",
                            (Document.status == "processing") & (Document.updated_at < utcnow() - timedelta(minutes=25))))
                 .order_by(Document.created_at)
                 .with_for_update(skip_locked=True).limit(1))
        doc = db.scalar(query)
        if doc is None:
            return False
        doc.status = "processing"
        doc.page_count = 0
        doc.extracted = {"progreso": {"procesadas": 0, "total": None}}
        doc.updated_at = utcnow()
        doc_id, storage, category, digest = doc.id, doc.storage_path, doc.declared_type, doc.sha256
    try:
        def progress(done: int, total: int) -> None:
            with SessionLocal.begin() as db:
                current = db.get(Document, doc_id)
                if current and current.status == "processing":
                    current.page_count = done
                    current.extracted = {"progreso": {"procesadas": done, "total": total}}
                    current.updated_at = utcnow()

        outcome = process_document(storage, category, expected_sha256=digest, progress=progress)
        with SessionLocal.begin() as db:
            doc = db.get(Document, doc_id)
            if doc:
                doc.status = "complete"
                doc.detected_type = outcome["detected_type"]
                doc.payment_status = outcome["payment_status"]
                doc.page_count = outcome["page_count"]
                doc.extracted = outcome["extracted"]
                doc.evidence = outcome["evidence"]
                doc.warnings = outcome["warnings"]
                doc.updated_at = utcnow()
        logger.info("OCR terminado para identificador %s", doc_id)
    except Exception:
        logger.exception("Error al procesar trabajo %s", doc_id)
        with SessionLocal.begin() as db:
            doc = db.get(Document, doc_id)
            if doc:
                doc.status = "error"
                doc.error = "Falló el procesamiento; requiere revisión técnica"
                doc.updated_at = utcnow()
    return True


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    next_calendar_check = 0.0
    while not stopping:
        try:
            if time.monotonic() >= next_calendar_check:
                with SessionLocal.begin() as db:
                    created = calendar_tick(db)
                if created:
                    logger.info("Calendario: %d solicitudes generadas", created)
                next_calendar_check = time.monotonic() + 300
            if not process_next():
                time.sleep(settings().worker_poll_seconds)
        except Exception:
            logger.exception("Falla transitoria en worker")
            time.sleep(5)


if __name__ == "__main__":
    main()
