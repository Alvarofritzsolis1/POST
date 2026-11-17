"""Cola de difusión a una página de Facebook. No admite grupos ni expone tokens."""
from __future__ import annotations

import json
import logging
import re
import signal
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import utcnow
from .network_models import NetworkFacebookPost, NetworkFacebookManual, NetworkItem, NetworkRequirement
from .ops_models import Worksite
from .facebook_ai import generate_text, AD_INSTRUCTIONS, verified_ad_copy
from .galancito_runtime import infer

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
        if req.state != "published" or not req.publish_to_facebook:
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
    should_publish = req.state == "published" and req.publish_to_facebook
    row.action = ("update" if row.post_id else "publish") if should_publish else ("delete" if row.post_id else "cancel")
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
        "selected": req.publish_to_facebook,
        "state": row.state if row else ("disabled" if not cfg.facebook_autopublish_enabled else ("not_selected" if not req.publish_to_facebook else "not_queued")),
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


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("Meta intentó redirigir una petición autenticada")


_NO_REDIRECT = build_opener(_NoRedirect)


def graph_request(method: str, path: str, token: str, message: str | None = None) -> dict:
    if not re.fullmatch(r"/[0-9_]+(?:/feed)?", path):
        raise ValueError("Ruta de Graph API no permitida")
    if method not in {"POST", "GET", "DELETE"}:
        raise ValueError("Método no permitido")
    # Campos de verificación acotados; no permite URLs externas o arbitrarias.
    endpoint = path + ("?fields=id,name" if method == "GET" else "")
    req = Request(
        "https://graph.facebook.com/v27.0" + endpoint,
        method=method,
        data=urlencode({"message": message}).encode() if message is not None else None,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with _NO_REDIRECT.open(req, timeout=15) as response:
        value = json.loads(response.read(16384).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Respuesta inesperada de Meta")
    return value


def meta_http_error(exc: HTTPError) -> str:
    """Explain Meta failures using only structured, non-secret diagnostic codes.

    Never persist Meta's raw error.message: it can include request parameters.
    The Graph API's numeric code/subcode and sanitized trace are sufficient
    for an administrator to identify the next corrective step.
    """
    hints = {
        4: "Meta está limitando solicitudes; revisa cuotas antes de reintentar.",
        10: "La aplicación no tiene autorización para esta acción.",
        17: "Meta está limitando solicitudes; inténtalo más tarde.",
        32: "Meta está limitando solicitudes; inténtalo más tarde.",
        100: "Revisa el ID de página y los campos del anuncio.",
        102: "Token inválido o vencido. Genera un token de página nuevo.",
        190: "Token inválido o vencido. Genera un token de página nuevo.",
        200: "Faltan permisos para publicar. Revisa pages_manage_posts, pages_read_engagement, pages_show_list y CREATE_CONTENT.",
        283: "Faltan permisos de la aplicación o de la página.",
        368: "Meta restringió temporalmente esta acción en la página.",
        492: "La cuenta vinculada no tiene el rol necesario en la página.",
        506: "Meta detectó una publicación duplicada. Comprueba primero el muro de Facebook.",
        613: "Se alcanzó un límite de solicitudes de Meta.",
    }
    error_code = None
    error_subcode = None
    trace = None
    try:
        payload = json.loads(exc.read(8192).decode("utf-8"))
        details = payload.get("error", {}) if isinstance(payload, dict) else {}
        if isinstance(details, dict):
            if type(details.get("code")) is int and 0 < details["code"] < 1000000:
                error_code = details["code"]
            if type(details.get("error_subcode")) is int and 0 < details["error_subcode"] < 1000000:
                error_subcode = details["error_subcode"]
            identifier = details.get("fbtrace_id")
            if isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identifier):
                trace = identifier
    except (OSError, UnicodeError, ValueError, TypeError):
        pass
    code_part = (" · código Meta " + str(error_code)) if error_code is not None else ""
    if error_subcode is not None:
        code_part += " / subcódigo " + str(error_subcode)
    hint = hints.get(error_code, "Comprueba el ID de página, la autorización y los permisos en Meta.")
    if trace:
        code_part += " · referencia " + trace
    return "Meta rechazó la solicitud (HTTP " + str(exc.code) + code_part + "). " + hint


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
        if req.state != "published" or not req.publish_to_facebook:
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
    # Generar solo una introducción breve local; los datos oficiales nunca
    # se reemplazan. Esta opción requiere selección Facebook + permiso de anuncio.
    if (message and cfg.facebook_ai_provider == "ollama" and
            cfg.galancito_local_ai_enabled and cfg.facebook_ai_ad_enabled):
        try:
            with session_factory.begin() as db:
                message, _generated = infer(db, lambda: verified_ad_copy(message, req.title, req.specialty))
        except RuntimeError:
            pass  # Keep the verified original when the shared inference slot is busy.
    # Opt-in, solo desde datos comerciales públicos, sin demorar la transacción SQL.
    if (message and cfg.facebook_ai_provider == "openai" and cfg.facebook_ai_ad_enabled
            and cfg.facebook_ai_enabled and cfg.facebook_ai_api_key):
        try:
            message = generate_text(AD_INSTRUCTIONS, message, 1200) or message
        except RuntimeError:
            pass  # Mantener anuncio factual y seguro si falla el modelo.
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
        error = meta_http_error(exc)
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
            row.action = ("update" if row.post_id else "publish") if current and current.state == "published" and current.publish_to_facebook else ("delete" if row.post_id else "cancel")
            row.state = "pending" if row.action != "cancel" else "cancelled"
        else:
            row.state = "deleted" if action == "delete" else "published"
        row.last_error, row.updated_at = error, utcnow()
    return True


def process_manual_next(session_factory=SessionLocal) -> bool:
    """Ejecuta SOLO acciones manuales confirmadas y registradas por administrador."""
    cfg = settings()
    # La verificación de conexión es lectura segura aunque el modo de pruebas
    # esté apagado; publicar/eliminar manualmente sigue requiriendo permiso explícito.
    if not ((cfg.facebook_manual_testing_enabled or cfg.facebook_autopublish_enabled) and
            re.fullmatch(r"[0-9]{5,30}", cfg.facebook_page_id or "") and
            cfg.facebook_page_token):
        return False
    with session_factory.begin() as db:
        conditions = [
            NetworkFacebookManual.page_id == cfg.facebook_page_id,
            NetworkFacebookManual.state == "pending",
        ]
        if not cfg.facebook_manual_testing_enabled:
            conditions.append(NetworkFacebookManual.action == "verify")
        row = db.scalar(select(NetworkFacebookManual).where(*conditions)
            .order_by(NetworkFacebookManual.created_at, NetworkFacebookManual.id)
            .with_for_update(skip_locked=True))
        if not row:
            return False
        action, row_id, post_id, message = row.action, row.id, row.post_id, row.message
        if action in ("publish", "delete") and action == "delete" and not post_id:
            row.state, row.last_error = "failed", "No hay ID de Facebook para retirar la prueba"
            return True
        if action == "publish" and not message.startswith("🧪 PUBLICACIÓN DE PRUEBA"):
            row.state, row.last_error = "failed", "Contenido sin marca de prueba; envío bloqueado"
            return True
        row.state = "sending"
        row.attempts += 1
        row.updated_at = utcnow()

    confirmed_id, page_name, error, uncertain = None, None, None, False
    try:
        if action == "verify":
            result = graph_request("GET", "/" + cfg.facebook_page_id, cfg.facebook_page_token)
            if str(result.get("id")) != cfg.facebook_page_id:
                error = "El token no identifica la página configurada."
            else:
                page_name = str(result.get("name") or "Página de Facebook")[:180]
        elif action == "publish":
            result = graph_request("POST", "/" + cfg.facebook_page_id + "/feed", cfg.facebook_page_token, message)
            confirmed_id = result.get("id")
            if not isinstance(confirmed_id, str) or not re.fullmatch(r"[0-9]+_[0-9]+", confirmed_id):
                error, uncertain = "Meta no devolvió un ID válido; comprueba el muro antes de repetir.", True
            elif not confirmed_id.startswith(cfg.facebook_page_id + "_"):
                error, uncertain = "El ID recibido corresponde a otra página; revisión manual.", True
        elif action == "delete":
            result = graph_request("DELETE", "/" + post_id, cfg.facebook_page_token)
            if result.get("success") is not True:
                error, uncertain = "Meta no confirmó el retiro. Revisa la página.", True
        else:
            error = "Acción no permitida"
    except HTTPError as exc:
        error = meta_http_error(exc)
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        error = "No se confirmó la respuesta (" + type(exc).__name__ + "); revisa Facebook."
        uncertain = action in ("publish", "delete")

    with session_factory.begin() as db:
        row = db.get(NetworkFacebookManual, row_id, with_for_update=True)
        if row is None:
            return True
        if confirmed_id:
            row.post_id = confirmed_id
        if page_name:
            row.page_name = page_name
        if uncertain:
            row.state = "uncertain"  # No reintentar automáticamente.
        elif error:
            row.state = "failed"
        else:
            row.state = {"verify": "verified", "publish": "published", "delete": "deleted"}[action]
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
    from .facebook_chat_worker import process_chat_next
    while not stopping:
        try:
            if process_chat_next():
                continue
            if process_manual_next():
                continue
            if process_next():
                continue
        except Exception:
            log.exception("Fallo de worker Facebook; credenciales no registradas.")
        # A 20s idle sleep delayed greetings even without model inference.
        for _ in range(10):
            if stopping:
                break
            time.sleep(settings().facebook_worker_poll_seconds / 10)


if __name__ == "__main__":
    main()
