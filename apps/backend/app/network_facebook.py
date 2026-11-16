"""Cola de difusión a una página de Facebook. No admite grupos ni expone tokens."""
from __future__ import annotations

import json
import logging
import re
import signal
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import utcnow
from .network_models import NetworkFacebookPost, NetworkItem, NetworkRequirement
from .ops_models import Worksite

log = logging.getLogger("galant.facebook")
stopping = False


def enqueue(db: Session, req: NetworkRequirement, *, force=False) -> NetworkFacebookPost | None:
    """Anexa trabajo a la misma transacción del requerimiento; sin publicar aún."""
    cfg = settings()
    if not cfg.facebook_autopublish_enabled or not re.fullmatch(r"[0-9]{5,30}", cfg.facebook_page_id or ""):
        return None
    row = db.scalar(select(NetworkFacebookPost).where(
        NetworkFacebookPost.org_id == req.org_id,
        NetworkFacebookPost.requirement_id == req.id,
        NetworkFacebookPost.page_id == cfg.facebook_page_id,
    ))
    if row is None:
        if req.state != "published":
            return None
        row = NetworkFacebookPost(
            org_id=req.org_id, requirement_id=req.id, page_id=cfg.facebook_page_id,
            target_version=req.version, action="publish", state="pending",
        )
        db.add(row)
        return row
    if row.state == "uncertain":
        return row  # nunca duplicar ante resultado indeterminado
    if row.target_version == req.version and not force:
        return row
    row.target_version = req.version
    row.action = ("update" if row.post_id else "publish") if req.state == "published" else ("delete" if row.post_id else "cancel")
    if row.state != "sending":
        row.state = "pending" if row.action != "cancel" else "cancelled"
    row.last_error = None
    row.updated_at = utcnow()
    return row


def status_view(db: Session, req: NetworkRequirement) -> dict:
    cfg = settings()
    row = db.scalar(select(NetworkFacebookPost).where(
        NetworkFacebookPost.org_id == req.org_id,
        NetworkFacebookPost.requirement_id == req.id,
        NetworkFacebookPost.page_id == cfg.facebook_page_id,
    )) if cfg.facebook_autopublish_enabled and cfg.facebook_page_id else None
    return {
        "enabled": cfg.facebook_autopublish_enabled,
        "state": row.state if row else ("not_queued" if cfg.facebook_autopublish_enabled else "disabled"),
        "post_url": "https://www.facebook.com/" + row.post_id if row and row.post_id and re.fullmatch(r"[0-9]+_[0-9]+", row.post_id) else None,
        "error": row.last_error if row else None,
    }


def public_message(db: Session, req: NetworkRequirement) -> str:
    """Solo campos explícitamente seguros para publicación; no se envía req.description."""
    site = db.scalar(select(Worksite.name).where(Worksite.id == req.site_id, Worksite.org_id == req.org_id)) or "Obra"
    items = list(db.scalars(select(NetworkItem.name).where(
        NetworkItem.org_id == req.org_id, NetworkItem.requirement_id == req.id
    ).order_by(NetworkItem.position).limit(6)))
    lines = [
        "CONVOCATORIA PARA EMPRESAS CONTRATISTAS", "",
        req.title,
        "Obra: " + site,
        "Especialidad: " + req.specialty,
        "Dotación estimada: " + str(req.workers) + " trabajadores",
        "Inicio estimado: " + req.start_date.strftime("%d/%m/%Y"),
    ]
    if items:
        lines.extend(["", "Partidas: " + ", ".join(items)])
    lines.extend(["", "¿Tu empresa realiza estos trabajos?",
        "Envíanos un mensaje privado a esta página con los antecedentes de tu empresa.",
        "Convocatoria sujeta a evaluación y adjudicación."])
    return "\n".join(lines)[:3900]


def graph_request(method: str, path: str, token: str, message: str | None = None) -> dict:
    if not re.fullmatch(r"/[0-9_]+(?:/feed)?", path):
        raise ValueError("Ruta de Graph API no permitida")
    req = Request(
        "https://graph.facebook.com/v27.0" + path,
        method=method,
        data=urlencode({"message": message}).encode() if message is not None else None,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(req, timeout=15) as response:
        value = json.loads(response.read(16384).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Respuesta inesperada de Meta")
    return value


def process_next(session_factory=SessionLocal) -> bool:
    cfg = settings()
    if not (cfg.facebook_autopublish_enabled and cfg.facebook_page_id and cfg.facebook_page_token):
        return False
    with session_factory.begin() as db:
        row = db.scalar(select(NetworkFacebookPost).where(
            NetworkFacebookPost.page_id == cfg.facebook_page_id,
            NetworkFacebookPost.state == "pending",
        ).order_by(NetworkFacebookPost.created_at, NetworkFacebookPost.id).with_for_update(skip_locked=True))
        if row is None:
            return False
        req = db.get(NetworkRequirement, row.requirement_id)
        if req is None:
            row.state = "failed"
            row.last_error = "El requerimiento ya no existe."
            return True
        if req.state != "published":
            row.action = "delete" if row.post_id else "cancel"
        if row.action == "cancel":
            row.state = "cancelled"
            return True
        action, post_id, job_id, revision = row.action, row.post_id, row.id, row.target_version
        if action in ("update", "delete") and not post_id:
            row.state = "uncertain"
            row.last_error = "Falta el ID remoto; revisión manual requerida."
            return True
        message = public_message(db, req) if action != "delete" else None
        row.state = "sending"
        row.attempts += 1
        row.updated_at = utcnow()

    outcome_id, error, uncertain = None, None, False
    try:
        if action == "publish":
            response = graph_request("POST", "/" + cfg.facebook_page_id + "/feed", cfg.facebook_page_token, message)
            outcome_id = response.get("id")
            if not isinstance(outcome_id, str) or not re.fullmatch(r"[0-9]+_[0-9]+", outcome_id):
                error, uncertain = "Meta no confirmó el ID de publicación.", True
        elif action == "update":
            graph_request("POST", "/" + post_id, cfg.facebook_page_token, message)
        elif action == "delete":
            graph_request("DELETE", "/" + post_id, cfg.facebook_page_token)
        else:
            error = "Acción de publicación desconocida."
    except HTTPError as exc:
        error = "Meta rechazó la solicitud (HTTP " + str(exc.code) + "). Verifica permisos y token."
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        error, uncertain = "No se confirmó el envío (" + type(exc).__name__ + "); revisar Facebook.", True

    with session_factory.begin() as db:
        row = db.get(NetworkFacebookPost, job_id, with_for_update=True)
        if row is None:
            return True
        if outcome_id:
            row.post_id = outcome_id
        if action == "delete" and not error:
            row.post_id = None
        if uncertain:
            row.state = "uncertain"  # no reintentar automáticamente
        elif error:
            row.state = "failed"
        elif row.target_version != revision:
            current = db.get(NetworkRequirement, row.requirement_id)
            row.action = ("update" if row.post_id else "publish") if current and current.state == "published" else ("delete" if row.post_id else "cancel")
            row.state = "pending" if row.action != "cancel" else "cancelled"
        else:
            row.state = "deleted" if action == "delete" else "published"
        row.last_error, row.updated_at = error, utcnow()
    return True


def stop(*_):
    global stopping
    stopping = True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("Worker de Facebook iniciado; sin publicación retroactiva.")
    while not stopping:
        try:
            if process_next():
                continue
        except Exception:
            log.exception("Fallo de worker Facebook; credenciales no registradas.")
        for _ in range(20):
            if stopping:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
