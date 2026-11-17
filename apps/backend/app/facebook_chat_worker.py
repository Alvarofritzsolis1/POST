"""Private Messenger sender run by the existing Facebook worker.

The API/webhook never receives the Page token. A completed/uncertain send is not retried
automatically; an ambiguous network outcome must be checked in Meta first.
"""
from datetime import timedelta, timezone
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .facebook_ai import ASSISTANT_NAME, REPLY_INSTRUCTIONS, generate_text
from .galancito_flow import safe_ai_reply
from .facebook_crm_models import FacebookLead, FacebookChatMessage, FacebookTradeGuide
from .models import utcnow
from .network_service import key

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("La API de Meta redirigió el envío")

_opener = build_opener(NoRedirect)


def graph_send(page_id: str, psid: str, message: str, token: str) -> str:
    if not (re.fullmatch(r"[0-9]{5,30}", page_id) and
            re.fullmatch(r"[0-9]{5,90}", psid)):
        raise ValueError("Identificador de Meta no válido")
    payload = json.dumps({
        "recipient": {"id": psid},
        "messaging_type": "RESPONSE",
        "message": {"text": message[:1800]},
    }).encode("utf-8")
    request = Request(
        "https://graph.facebook.com/v27.0/" + page_id + "/messages",
        data=payload, method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with _opener.open(request, timeout=15) as response:
        obj = json.loads(response.read(16384).decode("utf-8"))
    mid = obj.get("message_id")
    if not isinstance(mid, str) or not mid:
        raise RuntimeError("Meta no confirmó un identificador de mensaje")
    return mid[:180]


def _within_24h(lead: FacebookLead) -> bool:
    incoming = lead.last_inbound_at
    if incoming and incoming.tzinfo is None:
        incoming = incoming.replace(tzinfo=timezone.utc)
    return bool(incoming and incoming >= utcnow() - timedelta(hours=24))


def process_chat_next(session_factory=SessionLocal) -> bool:
    cfg = settings()
    if not (cfg.facebook_messaging_enabled and cfg.facebook_page_token and
            cfg.facebook_page_id and cfg.facebook_org_id):
        return False
    with session_factory.begin() as db:
        job = db.scalar(select(FacebookChatMessage).where(
            FacebookChatMessage.org_id == cfg.facebook_org_id,
            FacebookChatMessage.page_id == cfg.facebook_page_id,
            FacebookChatMessage.direction == "outbound",
            FacebookChatMessage.state.in_(["pending", "ai_pending"]),
        ).order_by(FacebookChatMessage.created_at, FacebookChatMessage.id)
          .with_for_update(skip_locked=True))
        if job is None:
            return False
        lead = db.get(FacebookLead, job.lead_id)
        if (lead is None or lead.org_id != cfg.facebook_org_id or
                lead.page_id != cfg.facebook_page_id):
            job.state, job.error = "failed", "Contacto no disponible"
            return True
        if not _within_24h(lead):
            job.state, job.error = "failed", "Fuera de la ventana estándar de 24 horas"
            return True
        if job.state == "ai_pending" and lead.needs_support:
            job.state, job.error = "cancelled", "El contacto pidió apoyo: revisión humana prioritaria"
            return True
        if job.state == "ai_pending" and (lead.ai_paused or lead.ai_consent_state == "declined"):
            job.state, job.error = "cancelled", "Galancito pausado para este contacto"
            return True
        if job.state == "ai_pending" and not lead.ai_consent:
            job.state, job.error = "cancelled", "El contacto no autorizó el procesamiento con IA"
            return True
        if job.state == "ai_pending" and not (
            cfg.facebook_ai_enabled and cfg.facebook_ai_auto_reply_enabled and cfg.facebook_ai_api_key
        ):
            job.state, job.error = "cancelled", "El asistente automático está deshabilitado"
            return True
        job_id, psid, state, body = job.id, lead.psid, job.state, job.body
        if state == "ai_pending":
            recent = list(db.scalars(select(FacebookChatMessage).where(
                FacebookChatMessage.lead_id == lead.id,
                FacebookChatMessage.direction == "inbound",
            ).order_by(FacebookChatMessage.created_at.desc()).limit(5)))
            context = "\n".join("Contacto: " + msg.body[:500] for msg in reversed(recent))
            context = "Empresa: " + lead.company + "\nEspecialidad: " + lead.specialty + "\n" + context
            guides = list(db.scalars(select(FacebookTradeGuide).where(
                FacebookTradeGuide.org_id == lead.org_id,
                FacebookTradeGuide.approved.is_(True))))
            term = key(lead.specialty)
            guide = next((g for g in guides if term and
                term in {key(g.trade), *(key(a) for a in (g.aliases or []))}), None)
            if guide:
                context += ("\nGuía administrativa validada: " + guide.explanation[:1000]
                            + "\nDocumentos que se explican solo si pregunta: "
                            + "; ".join(guide.document_guidance or [])[:700])
            else:
                context += "\nNo hay guía documental validada: derivar esas dudas al administrador."
        else:
            context = ""
        job.state, job.updated_at = "sending", utcnow()

    uncertain = False
    result_id, problem = None, None
    try:
        if state == "ai_pending":
            generated = generate_text(REPLY_INSTRUCTIONS, context, 550)
            if not generated:
                raise ValueError("IA no conectada")
            body = safe_ai_reply(generated)
        result_id = graph_send(cfg.facebook_page_id, psid, body, cfg.facebook_page_token)
    except HTTPError as exc:
        problem = "Meta rechazó el mensaje (HTTP " + str(exc.code) + ")."
    except (URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
        problem = "No se confirmó el envío (" + type(exc).__name__ + "). Verifica Messenger."
        uncertain = isinstance(exc, (URLError, TimeoutError, OSError))
    with session_factory.begin() as db:
        row = db.get(FacebookChatMessage, job_id, with_for_update=True)
        if row is None:
            return True
        row.body = body[:1800]
        row.remote_id = result_id
        row.state = "sent" if result_id else ("uncertain" if uncertain else "failed")
        row.error, row.updated_at = problem, utcnow()
    return True
