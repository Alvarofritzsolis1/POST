"""Private Messenger sender run by the existing Facebook worker.

The API/webhook never receives the Page token. A completed/uncertain send is not retried
automatically; an ambiguous network outcome must be checked in Meta first.
"""
from datetime import timedelta, timezone
import json
import re
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .facebook_ai import REPLY_INSTRUCTIONS, generate_text, messenger_ai_source
from .ai_gateway import orchestrated_text
from .galancito_flow import safe_ai_reply, consent_decision, grounded_reply
from .facebook_crm_models import FacebookLead, FacebookChatMessage, FacebookTradeGuide
from .models import utcnow
from .network_service import key
from .galancito_triage import analyze, quick_reply, private_data
from .galancito_intake import next_intake_reply
from .galancito_knowledge import retrieve, exact_answer, evidence_context
from .galancito_runtime import infer, record_run
from .galancito_local import last_timings

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


def meta_messenger_error(exc: HTTPError) -> str:
    """Conservar solo códigos estructurados; jamás el texto libre o credenciales de Meta.

    La respuesta puede contener URLs, PSID, tokens y parámetros privados.
    El código, subcódigo y fbtrace_id seguro bastan para diagnóstico.
    """
    code, subcode, trace = None, None, None
    try:
        response = json.loads(exc.read(8192).decode("utf-8"))
        details = response.get("error") if isinstance(response, dict) else None
        if isinstance(details, dict):
            raw_code = details.get("code")
            raw_subcode = details.get("error_subcode")
            if type(raw_code) is int and 0 < raw_code < 1000000:
                code = raw_code
            if type(raw_subcode) is int and 0 < raw_subcode < 10000000:
                subcode = raw_subcode
            raw_trace = details.get("fbtrace_id")
            if isinstance(raw_trace, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", raw_trace):
                trace = raw_trace
    except (OSError, UnicodeError, ValueError, TypeError):
        pass
    status = exc.code if type(exc.code) is int and 100 <= exc.code <= 599 else 0
    markers = [f"HTTP {status}"]
    if code is not None:
        markers.append(f"código Meta {code}")
    if subcode is not None:
        markers.append(f"subcódigo {subcode}")
    if trace:
        markers.append("referencia " + trace)
    if code in {190, 102}:
        hint = "Token rechazado. Renueva el token de página en el VPS y reinicia facebook-publisher."
    elif code in {10, 200, 230, 283}:
        hint = ("Permiso de Messenger denegado. Revisa pages_messaging, el acceso MESSAGING "
                "a la página, los roles de prueba y App Review de Meta.")
    elif code in {551, 613}:
        hint = ("Meta no permite entregar este mensaje. Revisa la disponibilidad del destinatario "
                "y las restricciones de mensajería de la página.")
    elif status == 401:
        hint = ("Meta rechazó la autorización de envío. Comprueba pages_messaging, "
                "rol MESSAGING del token, destinatario y estado de la aplicación.")
    else:
        hint = ("Meta rechazó el envío. Comprueba los permisos de Messenger, "
                "la suscripción de página y la ventana de respuesta.")
    return "Meta rechazó el mensaje (" + " · ".join(markers) + "). " + hint


def messenger_profile_name(psid: str, token: str) -> str | None:
    """Obtener el nombre permitido por el perfil PSID, sin exponer token o URL.

    Meta puede denegar datos del perfil incluso con pages_messaging. En ese caso
    el administrador puede confirmar el nombre declarado en el chat.
    """
    if not re.fullmatch(r"[0-9]{5,90}", psid):
        return None
    request = Request(
        "https://graph.facebook.com/v27.0/" + psid +
        "?fields=id%2Cname%2Cfirst_name%2Clast_name",
        headers={"Authorization": "Bearer " + token}, method="GET",
    )
    with _opener.open(request, timeout=5) as response:
        payload = json.loads(response.read(8192).decode("utf-8"))
    if not isinstance(payload, dict) or str(payload.get("id")) != psid:
        return None
    first, last = payload.get("first_name"), payload.get("last_name")
    full = payload.get("name")
    value = (full if isinstance(full, str) else
             (str(first or "") + " " + str(last or "")).strip())
    value = " ".join(value.split())[:155]
    if len(value) < 2 or not all(char.isprintable() for char in value):
        return None
    return value


# Cada instancia del worker intenta un perfil por contacto, no en cada sondeo.
# No hay credenciales ni nombres privados en logs o el frontend hasta que
# el servicio de Meta responde y se valida el ID de página.
_profile_attempted: set[str] = set()
_profile_auth_denied = False


def process_profile_next(session_factory=SessionLocal) -> bool:
    """Mejor esfuerzo, aislado de la cola de mensajes y sin migrar tablas."""
    global _profile_auth_denied
    cfg = settings()
    if _profile_auth_denied or not (cfg.facebook_messaging_enabled and
            cfg.facebook_page_token and cfg.facebook_page_id and cfg.facebook_org_id):
        return False
    with session_factory() as db:
        candidates = list(db.scalars(select(FacebookLead).where(
            FacebookLead.org_id == cfg.facebook_org_id,
            FacebookLead.page_id == cfg.facebook_page_id,
            FacebookLead.display_name == "Interesado de Facebook",
            FacebookLead.last_inbound_at.is_not(None),
        ).order_by(FacebookLead.last_inbound_at.desc()).limit(300)))
        lead = next((x for x in candidates if x.id not in _profile_attempted), None)
        if lead is None:
            return False
        lead_id, psid = lead.id, lead.psid
    _profile_attempted.add(lead_id)
    try:
        name = messenger_profile_name(psid, cfg.facebook_page_token)
    except HTTPError as exc:
        if exc.code in (401, 403):
            _profile_auth_denied = True
        return True
    except (URLError, TimeoutError, OSError, ValueError, TypeError):
        return True
    if name:
        with session_factory.begin() as db:
            lead = db.get(FacebookLead, lead_id, with_for_update=True)
            if (lead and lead.org_id == cfg.facebook_org_id and
                    lead.page_id == cfg.facebook_page_id and
                    lead.display_name == "Interesado de Facebook"):
                lead.display_name = name
                lead.updated_at = utcnow()
    return True


def _within_24h(lead: FacebookLead) -> bool:
    incoming = lead.last_inbound_at
    if incoming and incoming.tzinfo is None:
        incoming = incoming.replace(tzinfo=timezone.utc)
    return bool(incoming and incoming >= utcnow() - timedelta(hours=24))


def process_chat_next(session_factory=SessionLocal) -> bool:
    started = perf_counter()
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
        ai_source = messenger_ai_source(db, lead.org_id, cfg)
        if (job.state == "pending" and job.operator_id is None and
                "autorizas" in job.body.casefold() and
                (lead.ai_consent_state not in ("requested", "requested_team") or
                 ("proveedores de IA externos" in job.body) !=
                 (lead.ai_consent_state == "requested_team"))):
            job.state, job.error = "cancelled", "Solicitud de consentimiento superada"
            return True
        if job.state == "ai_pending" and lead.needs_support:
            job.state, job.error = "cancelled", "El contacto pidió apoyo: revisión humana prioritaria"
            return True
        if job.state == "ai_pending" and (lead.ai_paused or lead.ai_consent_state == "declined"):
            job.state, job.error = "cancelled", "Galancito pausado para este contacto"
            return True
        if job.state == "ai_pending" and (
                not lead.ai_consent or lead.ai_consent_state != (
                    "accepted_team" if ai_source == "team" else "accepted")):
            job.state, job.error = "cancelled", "El contacto no autorizó el procesamiento con IA"
            return True
        if job.state == "ai_pending" and not (
            cfg.facebook_ai_auto_reply_enabled and ai_source != "disabled"
        ):
            job.state, job.error = "cancelled", "El asistente automático está deshabilitado"
            return True
        job_id, lead_id, org_id, psid, state, body = job.id, lead.id, lead.org_id, lead.psid, job.state, job.body
        inbound_at = lead.last_inbound_at
        fast, intent, fast_source = None, "unknown", "local"
        if state == "ai_pending":
            recent = list(db.scalars(select(FacebookChatMessage).where(
                FacebookChatMessage.lead_id == lead.id,
                FacebookChatMessage.direction == "inbound",
            ).order_by(FacebookChatMessage.created_at.desc()).limit(5)))
            # Consent's "sí" is not a new business query; respond to the
            # preceding message without sending private fields to the model.
            latest = next((m.body for m in recent if consent_decision(m.body) is None), "")
            facts = {"specialty": lead.specialty, "entity_type": lead.entity_type,
                     "workers": lead.workers, "availability": lead.availability,
                     "has_employees": lead.has_employees,
                     "team_available": lead.team_available, "work_area": lead.work_area,
                     "experience": lead.experience}
            prior_question = db.scalar(select(FacebookChatMessage.body).where(
                FacebookChatMessage.lead_id == lead.id,
                FacebookChatMessage.direction == "outbound",
                FacebookChatMessage.state == "sent",
            ).order_by(FacebookChatMessage.created_at.desc(),
                       FacebookChatMessage.id.desc()).limit(1)) or ""
            intake = next_intake_reply(latest, facts, prior_question)
            intent = analyze(latest).intent
            evidence = retrieve(db, lead.org_id, latest, "messenger") if not private_data(latest) else []
            fast = intake or quick_reply(latest, known=facts)
            if not private_data(latest) and intent not in {"human", "restricted"}:
                learned = exact_answer(evidence)
                if learned and not intake:
                    fast, fast_source = learned, "knowledge"
            context = ("Consulta actual: " + latest[:800] + "\nHechos confirmados: " +
                       json.dumps(facts, ensure_ascii=False) + "\nReferencias aprobadas: " +
                       evidence_context(evidence))
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
        db_ms = (perf_counter() - started) * 1000
        job.state, job.updated_at = "sending", utcnow()

    uncertain = False
    result_id, problem = None, None
    source, timings, failed_ai = fast_source, {}, False
    try:
        if state == "ai_pending":
            generated = fast
            if not fast and not private_data(context):
                try:
                    with session_factory.begin() as db:
                        generated = infer(db, lambda: (
                            orchestrated_text(db, org_id, task="messenger",
                                              instructions=REPLY_INSTRUCTIONS, prompt=context,
                                              max_output_tokens=160)
                            if ai_source == "team" else
                            generate_text(REPLY_INSTRUCTIONS, context, 550)),
                            org_id=org_id if ai_source == "team" else None)
                        timings = last_timings.get()
                    if generated:
                        generated = grounded_reply(generated, context)
                    source = "ai" if generated else "fallback"
                except (RuntimeError, ValueError):
                    generated, source, timings = None, "fallback", last_timings.get()
            if generated:
                body = safe_ai_reply(generated)
            else:
                # Si Ollama está saturado o apagado, Messenger continúa
                # funcionando y la persona puede recibir apoyo humano.
                body = ("Soy Galancito, asistente virtual de GALANT. "
                        "Ahora no tengo una respuesta confirmada. "
                        "Tu consulta queda pendiente de revisión humana.")
                failed_ai = True
        # Re-check after slow inference: a human may have taken over or the
        # contact may have revoked permission/sent a newer question meanwhile.
        with session_factory.begin() as db:
            current = db.get(FacebookLead, lead_id)
            current_job = db.get(FacebookChatMessage, job_id)
            if (current is None or not _within_24h(current) or
                    current_job is None or current_job.state != "sending" or
                    (state == "ai_pending" and (current.ai_paused or current.needs_support or
                     not current.ai_consent or current.ai_consent_state != (
                         "accepted_team" if ai_source == "team" else "accepted") or
                     current.last_inbound_at != inbound_at or
                     messenger_ai_source(db, org_id, cfg) != ai_source))):
                if current_job:
                    current_job.state, current_job.error = "cancelled", "La conversación cambió antes del envío"
                return True
        result_id = graph_send(cfg.facebook_page_id, psid, body, cfg.facebook_page_token)
    except HTTPError as exc:
        problem = meta_messenger_error(exc)
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
        if state == "ai_pending":
            record_run(db, org_id=org_id, channel="messenger", source=source,
                       intent=intent, started=started, db_ms=db_ms, timings=timings)
            if failed_ai:
                contact = db.get(FacebookLead, lead_id)
                if contact:
                    contact.needs_support = True
                    contact.support_reason = "Galancito no obtuvo una respuesta confirmada; revisión pendiente"
    return True
