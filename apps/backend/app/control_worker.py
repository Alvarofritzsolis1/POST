"""Worker administrativo liviano para QA, independiente del procesamiento OCR."""
from __future__ import annotations

import logging
import signal
import time

from .control_scheduler import calendar_tick
from .db import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("galant.post.control_worker")
stopping = False


def stop(*_):
    global stopping
    stopping = True


def main() -> None:
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    logger.info("Worker de solicitudes automáticas iniciado")
    while not stopping:
        try:
            with SessionLocal.begin() as db:
                created = calendar_tick(db)
            if created:
                logger.info("%d solicitudes mensuales generadas", created)
        except Exception:
            logger.exception("Error administrativo; no se modifican los estados manuales")
        for _ in range(60):
            if stopping:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
