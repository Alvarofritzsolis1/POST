"""Facebook CRM: signed Messenger webhook, human review, explainable contractor matching.
Nothing in this module automatically awards work, creates a contractor master record,
or sends unsolicited messages. AI automation requires separate opt-in flags.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from uuid import uuid4
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request as HTTPRequest, build_opener

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text as sql_text
from sqlalchemy.orm import Session

from .config import settings
from . import galancito_contextual as contextual
from .db import get_db, SessionLocal
from .facebook_ai import (AD_INSTRUCTIONS, REPLY_INSTRUCTIONS, generate_text,
                          messenger_ai_source, messenger_contact_ai_source, verified_ad_copy, local_first_messenger, messenger_external_fallback_enabled,
                          generate_triage_note)
from .ai_gateway import orchestrated_text, AIServiceError
from .galancito_hybrid import select_response
from .facebook_availability_reply import availability_reply
from .facebook_worksite_reply import application_reply, digital_help_reply, is_worksite_question, worksite_reply
from .facebook_onboarding import assistance_signal, reply_for_support, onboarding_guide
from .galancito_flow import (
    AI_PERMISSION_DECLINED, apply_permission_reply, consented_for, messenger_model_authorized, explain_permission, wants_human,
)
from .facebook_crm_models import (FacebookLead, FacebookChatMessage, FacebookTradeGuide,
                                  FacebookLeadTrade, FacebookNeedAssociation, FacebookLeadTrace)
from .models import Organization, User, utcnow
from .network_facebook import public_message
from .network_models import NetworkFacebookPost, NetworkFacebookManual, NetworkRequirement
from .facebook_publication_models import FacebookPostSnapshot, FacebookPostJob
from .facebook_refresh_policy import automatic_refresh_allowed
from .network_service import key, today
from .galancito_triage import classify_lead, dashboard
from .security import administrator
from .galancito_triage import (analyze, plain, private_data, quick_reply, everyday_question_reply,
                              application_ai_candidate, payment_guidance, worksite_payment_terms_question,
                              contextual_payment_question)
from .galancito_intake import (
    GALILEA_QUESTION, acceptable_intake_draft, declared_relative_start, identity_reply, model_intake_candidate, needs_deeper_response, next_intake_reply, small_talk_reply,
    natural_messenger_reply, contact_followup_reply, contact_pending_questions,
)
from .galancito_memory import (
    apply_messenger_message, approved_trade_aliases, aware, capture_voluntary_contact, note_profile_sources,
    prior_delivered_prompt, professional_message, profile_facts, messenger_context, recover_missing_contact,
    iter_recovery_messages, recovery_scope,
)
from .galancito_contact_profile import contact_profile
from .galancito_conversation_summary import (
    summarize_conversation, safe_model_input, validate_ai_brief, brief_contains_private_data,
)
from .galancito_phone import (
    QUESTION as CONTACT_PHONE_QUESTION, confirmed_phone_reply, introducing_phone_number,
    normalize_mobile, phone_question_when_agreed,
)
from .galancito_communes import find_communes
from .galancito_links import (record_manual_trade,
                              suggest_requirements, link_requirement,
                              unlink_requirement, audit_event, canonical_trade, trade_terms)
from .galancito_escalation import flag_for_human
from .facebook_lead_insights import active_trades, ranked_needs, suggestions_for_lead, trace_unique_requirement
from .ops_models import Worksite
from .galancito_knowledge import retrieve, exact_answer
from .galancito_runtime import infer
from .galancito_flow import grounded_reply

router = APIRouter(prefix="/api/v1/network/facebook", tags=["Facebook CRM"])


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _in_window(lead: FacebookLead) -> bool:
    return bool(lead.last_inbound_at and
                _aware(lead.last_inbound_at) >= utcnow() - timedelta(hours=24))


def _lead(db: Session, user: User, lead_id: str, *, lock=False) -> FacebookLead:
    query = select(FacebookLead).where(FacebookLead.id == lead_id, FacebookLead.org_id == user.org_id)
    lead = db.scalar(query.with_for_update() if lock else query)
    if not lead:
        raise HTTPException(404, "Contacto no encontrado")
    return lead


def _match(db: Session, lead: FacebookLead) -> dict:
    if not lead.requirement_id:
        return {"label": "Sin necesidad asociada", "state": "unlinked",
                "checks": [], "missing": ["Seleccionar necesidad de obra"],
                "human_review_required": True}
    req = db.scalar(select(NetworkRequirement).where(
        NetworkRequirement.id == lead.requirement_id,
        NetworkRequirement.org_id == lead.org_id))
    if not req:
        return {"label": "Necesidad no disponible", "state": "unlinked",
                "checks": [], "missing": [], "human_review_required": True}
    checks, missing = [], []
    trades = active_trades(db, lead)
    if not trades:
        missing.append("Oficio declarado")
    else:
        possible = {key(canonical_trade(trade)) for trade in (trade_terms(req.specialty) or [req.specialty])}
        compatible = any(key(canonical_trade(trade)) in possible for trade in trades)
        checks.append({"criterion": "Especialidad",
                       "state": "match" if compatible else "verify",
                       "detail": ", ".join(trades) + " / requerida: " + req.specialty})
    if lead.workers is None:
        missing.append("Cantidad de trabajadores disponibles")
    else:
        compatible = lead.workers >= req.workers
        checks.append({"criterion": "Dotación declarada",
                       "state": "match" if compatible else "verify",
                       "detail": str(lead.workers) + " / requeridos: " + str(req.workers)})
    try:
        available = date.fromisoformat(lead.availability)
    except ValueError:
        available = None
    if not available:
        missing.append("Disponibilidad confirmada (AAAA-MM-DD)")
    else:
        checks.append({"criterion": "Inicio",
                       "state": "match" if available <= req.start_date else "verify",
                       "detail": "Disponible: " + available.isoformat()
                                 + " / inicio: " + req.start_date.isoformat()})
    if not lead.experience.strip():
        missing.append("Experiencia y referencias comerciales")
    if lead.documents_state != "verified":
        missing.append("Verificación documental por administración")
    facts_ok = bool(checks) and all(c["state"] == "match" for c in checks)
    state = "possible_match" if facts_ok and not missing else "needs_review"
    return {"label": "Posible coincidencia" if state == "possible_match" else
            "Pendiente de revisión", "state": state,
            "requirement": req.title, "checks": checks, "missing": missing,
            "human_review_required": True}


def _lead_view(db: Session, lead: FacebookLead) -> dict:
    return {
        "id": lead.id, "name": lead.display_name, "name_opt_out": lead.name_opt_out, "company": lead.company,
        "specialty": lead.specialty, "specialty_source": lead.specialty_source, "workers": lead.workers,
        "availability": lead.availability, "experience": lead.experience,
        "documents_state": lead.documents_state, "status": lead.status,
        "requirement_id": lead.requirement_id, "unread": lead.unread,
        "ai_consent": lead.ai_consent,
        "ai_consent_state": lead.ai_consent_state,
        "ai_paused": lead.ai_paused,
        "needs_support": lead.needs_support,
        "support_reason": lead.support_reason,
        "entity_type": lead.entity_type,
        "has_employees": lead.has_employees,
        "employee_count": lead.employee_count,
        "team_available": lead.team_available,
        "interest_type": lead.interest_type,
        "work_area": lead.work_area, "work_communes": lead.work_communes,
        "contact_phone": lead.contact_phone, "phone_source": lead.phone_source,
        "contact_email": lead.contact_email, "email_source": lead.email_source,
        "email_opt_out": lead.email_opt_out,
        "phone_requested_at": lead.phone_requested_at.isoformat() if lead.phone_requested_at else None,
        "phone_opt_out": lead.phone_opt_out,
        "profile": contact_profile(lead),
        "follow_up_on": lead.follow_up_on.isoformat() if lead.follow_up_on else None,
        "follow_up_note": lead.follow_up_note or "",
        "last_inbound_at": lead.last_inbound_at.isoformat() if lead.last_inbound_at else None,
        "can_reply": _in_window(lead), "analysis": _match(db, lead),
    }


def _message_view(m: FacebookChatMessage) -> dict:
    return {"id": m.id, "direction": m.direction, "state": m.state,
            "source_message_id": m.remote_id if m.direction == "inbound" else None,
            "body": m.body, "ai_generated": m.ai_generated,
            "automated": m.direction == "outbound" and m.operator_id is None,
            "error": m.error, "created_at": m.created_at.isoformat(),
            "updated_at": m.updated_at.isoformat() if m.updated_at else m.created_at.isoformat()}


class LeadEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=160)
    name_opt_out: bool = False
    company: str = Field(default="", max_length=180)
    specialty: str = Field(default="", max_length=100)
    workers: int | None = Field(default=None, ge=1, le=5000)
    availability: str = Field(default="", max_length=120)
    experience: str = Field(default="", max_length=1200)
    documents_state: str = Field(default="unverified", pattern=r"^(unverified|declared|verified)$")
    status: str = Field(default="new", pattern=r"^(new|contacting|pending_review|shortlisted|archived)$")
    requirement_id: str | None = None
    ai_paused: bool = False
    needs_support: bool = False
    entity_type: str = Field(default="unknown", pattern=r"^(unknown|company|individual)$")
    has_employees: bool | None = None
    employee_count: int | None = Field(default=None, ge=0, le=5000)
    team_available: bool | None = None
    interest_type: str = Field(default="unknown", pattern="^(unknown|service_offer|employment|both)$")
    work_area: str = Field(default="", max_length=120)
    follow_up_on: date | None = None
    follow_up_note: str = Field(default="", max_length=240)
    contact_phone: str = Field(default="", max_length=26)
    contact_email: str = Field(default="", max_length=254)


class TradeGuideInput(BaseModel):
    trade: str = Field(min_length=2, max_length=140)
    aliases: list[str] = Field(default_factory=list, max_length=15)
    explanation: str = Field(default="", max_length=1500)
    document_guidance: list[str] = Field(default_factory=list, max_length=20)
    approved: bool = False


def _guide_for(db: Session, lead: FacebookLead) -> FacebookTradeGuide | None:
    term = key(lead.specialty)
    if not term:
        return None
    guides = db.scalars(select(FacebookTradeGuide).where(
        FacebookTradeGuide.org_id == lead.org_id,
        FacebookTradeGuide.approved.is_(True))).all()
    return next((guide for guide in guides if
        term in {key(guide.trade), *(key(alias) for alias in (guide.aliases or []))}), None)


@router.get("/guides")
def list_trade_guides(user: User = Depends(administrator), db: Session = Depends(get_db)):
    guides = list(db.scalars(select(FacebookTradeGuide).where(
        FacebookTradeGuide.org_id == user.org_id).order_by(FacebookTradeGuide.trade)))
    return [{"id": g.id, "slug": g.slug, "trade": g.trade, "aliases": g.aliases or [],
             "explanation": g.explanation, "document_guidance": g.document_guidance or [],
             "approved": g.approved} for g in guides]


@router.put("/guides/{slug}")
def update_trade_guide(slug: str, body: TradeGuideInput,
                       user: User = Depends(administrator),
                       db: Session = Depends(get_db)):
    if not re.fullmatch(r"[a-z0-9-]{2,100}", slug):
        raise HTTPException(422, "Identificador de especialidad inválido")
    row = db.scalar(select(FacebookTradeGuide).where(
        FacebookTradeGuide.org_id == user.org_id, FacebookTradeGuide.slug == slug))
    if row is None:
        row = FacebookTradeGuide(org_id=user.org_id, slug=slug)
        db.add(row)
    row.trade, row.aliases = body.trade.strip(), [x.strip() for x in body.aliases if x.strip()]
    row.explanation = body.explanation.strip()
    row.document_guidance = [x.strip() for x in body.document_guidance if x.strip()]
    row.approved = body.approved
    row.updated_by, row.updated_at = user.id, utcnow()
    db.commit()
    return {"id": row.id, "trade": row.trade, "approved": row.approved}


class ReplyInput(BaseModel):
    message: str = Field(min_length=2, max_length=1800)


@router.get("/webhook", response_class=PlainTextResponse)
def verify_webhook(
    mode: str = Query(default="", alias="hub.mode"),
    token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
):
    cfg = settings()
    if not (cfg.facebook_messaging_enabled and cfg.facebook_webhook_verify_token and
            mode == "subscribe" and hmac.compare_digest(token, cfg.facebook_webhook_verify_token)):
        raise HTTPException(403, "Webhook no autorizado")
    return challenge


def _event_time(value, received_at):
    if isinstance(value, (int, float)) and 0 < value <= received_at.timestamp() * 1000:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    return received_at


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    cfg = settings()
    if not (cfg.facebook_messaging_enabled and cfg.facebook_org_id and
            cfg.facebook_page_id and cfg.facebook_app_secret):
        raise HTTPException(503, "Mensajería no configurada")
    data = await request.body()
    if len(data) > 131072:
        raise HTTPException(413, "Evento demasiado grande")
    supplied = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(
        cfg.facebook_app_secret.encode("utf-8"), data, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(403, "Firma de Meta inválida")
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Evento inválido") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "Evento inválido")
    # SQLAlchemy and intake rules are synchronous. Keep the ASGI event loop
    # responsive while persisting the signed event. Acknowledge only after commit.
    return await run_in_threadpool(ingest_facebook_payload, db, payload, cfg)


def ingest_facebook_payload(db, payload, cfg, *, notices=None):
    """Process a verified webhook, or an event generated by the isolated simulator."""
    if payload.get("object") != "page":
        return {"received": True}
    if not db.get(Organization, cfg.facebook_org_id):
        raise HTTPException(503, "Organización de Facebook no configurada")
    if db.bind.dialect.name == "postgresql":
        db.execute(sql_text("SELECT pg_advisory_xact_lock(2075003)"))
    received_at = utcnow()
    events = []
    reply_turns = {}
    aliases = None
    entries = payload.get("entry")
    changed_post_ids = set()
    for entry in entries[:20] if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("id")) != cfg.facebook_page_id:
            continue
        # Feed webhooks notify about post comments. Do not trust actor IDs,
        # create Messenger contacts or send messages for a public comment:
        # just schedule a safe refresh of GALANT-owned post snapshots.
        changes = entry.get("changes")
        for change in changes[:30] if isinstance(changes, list) else []:
            if not isinstance(change, dict) or change.get("field") != "feed":
                continue
            value = change.get("value")
            if not isinstance(value, dict) or value.get("item") != "comment":
                continue
            remote_post_id = str(value.get("post_id") or "")
            if re.fullmatch(r"[0-9]{5,30}_[0-9]{1,40}", remote_post_id):
                if remote_post_id.startswith(cfg.facebook_page_id + "_"):
                    changed_post_ids.add(remote_post_id)
        messaging = entry.get("messaging")
        for event in messaging[:30] if isinstance(messaging, list) else []:
            if isinstance(event, dict):
                event_at = _event_time(event.get("timestamp"), received_at)
                events.append((event_at + timedelta(microseconds=len(events)), event))
    if changed_post_ids:
        posts = list(db.scalars(select(NetworkFacebookPost).where(
            NetworkFacebookPost.org_id == cfg.facebook_org_id,
            NetworkFacebookPost.page_id == cfg.facebook_page_id,
            NetworkFacebookPost.post_id.in_(changed_post_ids),
            NetworkFacebookPost.state == "published")))
        for post in posts:
            already_queued = db.scalar(select(FacebookPostJob.id).where(
                FacebookPostJob.post_record_id == post.id,
                FacebookPostJob.action == "refresh",
                FacebookPostJob.state.in_(["pending", "sending"])).limit(1))
            if not already_queued and automatic_refresh_allowed(
                    db, post.id, post.org_id, post.page_id, received_at):
                db.add(FacebookPostJob(
                    org_id=cfg.facebook_org_id, post_record_id=post.id,
                    page_id=post.page_id,
                    created_by=post.created_by if hasattr(post, "created_by") else (
                        db.scalar(select(NetworkRequirement.created_by).where(
                            NetworkRequirement.id == post.requirement_id,
                            NetworkRequirement.org_id == post.org_id))
                    ),
                    action="refresh", state="pending"))
    for event_at, event in sorted(events, key=lambda item: item[0]):
        meta_message = event.get("message") or {}
        if not isinstance(meta_message, dict) or meta_message.get("is_echo"):
            continue
        sender = event.get("sender")
        psid = str(sender.get("id") or "") if isinstance(sender, dict) else ""
        mid = str(meta_message.get("mid") or "")
        body = meta_message.get("text")
        attachments = meta_message.get("attachments") or []
        audio_received = any(isinstance(part, dict) and part.get("type") == "audio"
                             for part in attachments[:10]) if isinstance(attachments, list) else False
        if audio_received and not (isinstance(body, str) and body.strip()):
            # No almacenar URLs de adjuntos sin un mecanismo privado de audio;
            # el humano puede escuchar el audio en la bandeja de Meta.
            body = "[Mensaje de voz recibido: revisar audio en Meta Business Suite]"
        if not (re.fullmatch(r"[0-9]{5,90}", psid) and
                3 <= len(mid) <= 180 and isinstance(body, str) and body.strip()):
            continue
        already = db.scalar(select(FacebookChatMessage.id).where(
            FacebookChatMessage.page_id == cfg.facebook_page_id,
            FacebookChatMessage.remote_id == mid))
        if already:
            continue
        lead = db.scalar(select(FacebookLead).where(
            FacebookLead.org_id == cfg.facebook_org_id,
            FacebookLead.page_id == cfg.facebook_page_id,
            FacebookLead.psid == psid).with_for_update())
        if lead is None:
            lead = FacebookLead(org_id=cfg.facebook_org_id,
                                page_id=cfg.facebook_page_id, psid=psid)
            db.add(lead)
            db.flush()
        prior_inbound = aware(lead.last_inbound_at)
        historical = prior_inbound is not None and event_at < prior_inbound
        previous_question = (prior_delivered_prompt(
            db, lead, at=event_at, since=None if historical else prior_inbound
        ) if not audio_received else "")
        consent = (apply_permission_reply(lead, body, previous_question)
                   if not historical and not audio_received else None)
        phone_saved = False
        if not historical and not audio_received:
            phone_saved, _ = capture_voluntary_contact(db, lead, body, previous_question, at=event_at, remote_id=mid)
        phone_ack = confirmed_phone_reply(lead, body, previous_question) if not historical and not audio_received else None
        changed = False
        intake_body = professional_message(body)
        if consent is None and not audio_received and not private_data(intake_body):
            if aliases is None:
                aliases = approved_trade_aliases(db, lead.org_id)
            changed = apply_messenger_message(
                db, lead, intake_body, previous_question, remote_id=mid, at=event_at,
                historical=historical, aliases=aliases,
            )
        lead.updated_at, lead.unread = received_at, True
        if not historical:
            lead.last_inbound_at = event_at
        db.add(FacebookChatMessage(
            org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
            remote_id=mid, direction="inbound", state="received",
            body=body.strip()[:3500], created_at=event_at, updated_at=event_at,
            consent_decision=consent,
        ))
        if historical or event_at < received_at - timedelta(hours=24):
            if not audio_received:
                recover_missing_contact(db, lead)
            continue
        signal = ("Solicitó atención humana" if wants_human(body) else
                  assistance_signal(body, is_audio=audio_received,
                                    prior_prompt=previous_question)
                  if consent is None and not explain_permission(lead, body, previous_question) else None)
        if consent is False:
            signal = "Prefirió atención humana y rechazó el uso de IA"
        if (signal and not audio_received and not wants_human(body) and consent is not False
                and not lead.ai_paused and not lead.needs_support and local_first_messenger(cfg)
                and messenger_model_authorized(cfg, lead, messenger_contact_ai_source(db, lead, cfg))):
            signal = None  # Authorized Qwen gets a chance to explain before handoff.
        if signal:
            flag_for_human(db, lead, signal)
        earlier = reply_turns.get(lead.id)
        if (earlier and consent is None and not signal and not phone_ack and not identity_reply(body)
                and (needs_deeper_response(earlier[1]) or is_worksite_question(earlier[1]))
                and not (needs_deeper_response(body) or is_worksite_question(body))
                and declared_relative_start(body) is None):
            intake_body, previous_question = earlier[1], earlier[2]
        reply_turns[lead.id] = (lead, intake_body, previous_question, changed or bool(earlier and earlier[3]),
                               signal or (earlier[4] if earlier else None), mid,
                               consent is True or bool(earlier and earlier[6]),
                               phone_saved or bool(earlier and earlier[7]), phone_ack)

    for lead, body, previous_question, changed, signal, mid, consent_reply, phone_saved, phone_ack in reply_turns.values():
        if changed and not signal:
            trace_unique_requirement(db, lead, today=today(), remote_id=mid)
        # El mensaje entrante más reciente desplaza cualquier respuesta
        # automática aún no enviada, incluidas las reglas locales.
        waiting_for_ai = False
        coalesced = None
        contextual_allowed = contextual.authorized(cfg, lead)
        for previous in db.scalars(select(FacebookChatMessage).where(
            FacebookChatMessage.lead_id == lead.id,
            FacebookChatMessage.operator_id.is_(None),
            FacebookChatMessage.direction == "outbound",
            FacebookChatMessage.state.in_(["pending", "ai_pending", "drafting"]),
        )):
            waiting_for_ai |= previous.ai_generated
            if (contextual_allowed and not coalesced and previous.state == "ai_pending"
                    and aware(previous.updated_at) >= received_at - timedelta(seconds=3)):
                coalesced = previous
            previous.state = "cancelled"
        # The first human-handoff turn still needs a brief acknowledgement,
        # even though flag_for_human has already paused automation.
        if cfg.facebook_ai_enabled and (not lead.ai_paused or bool(signal)):
            location = (worksite_reply(db, lead, body, previous_question, notices=notices)
                        if not (signal or lead.needs_support or lead.ai_consent_state == "declined") else None)
            application = (application_reply(db, lead, body, previous_question, notices=notices)
                           if not (location or signal or lead.needs_support or lead.ai_consent_state == "declined") else None)
            digital_help = (digital_help_reply(body, previous_question)
                            if not (location or application or signal or lead.needs_support) else None)
            direct = location or application or digital_help or (explain_permission(lead, body, previous_question) or
                                  availability_reply(db, lead, body, previous_question, lead.last_inbound_at)
                                  if not signal and lead.ai_consent_state != "declined" else None)
            if not signal and not direct and not lead.needs_support:
                direct = everyday_question_reply(body)
            if not signal and not direct and not lead.needs_support:
                phone_prompt = phone_question_when_agreed(lead, body)
                if phone_prompt:
                    direct = phone_prompt
                    lead.phone_requested_at = utcnow()
            if phone_ack and not signal and not lead.needs_support and lead.ai_consent_state != "declined":
                direct = contact_followup_reply(phone_ack, profile_facts(lead, changed=changed), previous_question)
            configured_source = messenger_contact_ai_source(db, lead, cfg)
            # Generic questions should reach the consented model; confirmed
            # worksite facts and consent operations keep their verified path.
            if (direct and not (location or application or digital_help or phone_saved or phone_ack)
                    and direct == everyday_question_reply(body)
                    and messenger_model_authorized(cfg, lead, configured_source)):
                direct = None
            # Let Qwen choose the next conversational question when authorized.
            application_model = bool(application and direct == application and not phone_saved and not phone_ack
                                     and not signal and not lead.needs_support
                                     and local_first_messenger(cfg)
                                     and application_ai_candidate(body, previous_question))
            if (digital_help and direct == digital_help and not phone_ack and not signal
                    and local_first_messenger(cfg) and messenger_model_authorized(cfg, lead, configured_source)):
                direct = None
            if application_model and messenger_model_authorized(cfg, lead, configured_source):
                direct = None
            else:
                application_model = False
            contact_model = bool(phone_ack and direct and not signal and not lead.needs_support
                and local_first_messenger(cfg) and messenger_model_authorized(cfg, lead, configured_source)
                and contact_pending_questions(profile_facts(lead, changed=changed), previous_question))
            contact_fallback = direct if contact_model else None
            if contact_model:
                direct = None
            contextual_turn = bool(contextual_allowed and not (signal or direct or lead.needs_support)
                                   and contextual.conversational_message(body))
            ai_source = "disabled" if direct else configured_source
            facts = profile_facts(lead, changed=changed)
            intake = (next_intake_reply(body, facts, previous_question)
                      if not (direct or signal or lead.needs_support or lead.ai_consent_state == "declined") else None)
            recent = db.scalar(select(func.count(FacebookChatMessage.id)).where(
                FacebookChatMessage.lead_id == lead.id,
                FacebookChatMessage.direction == "outbound",
                FacebookChatMessage.created_at >= utcnow() - timedelta(hours=24),
                FacebookChatMessage.state != "cancelled",
            )) or 0
            reply, use_ai = None, False
            local = small_talk_reply(body, previous_question)
            if signal:
                if recent < 3 or wants_human(body):
                    reply = (("Ya avisé al equipo para que te atienda una persona. "
                              "No necesitas enviar documentos por aquí.") if wants_human(body) else
                             AI_PERMISSION_DECLINED if lead.ai_consent_state == "declined" else
                             ("Dejé tu consulta para que la revise una persona del equipo. "
                              "Te pueden ayudar por este chat; no necesitas enviar documentos."))
            elif introducing_phone_number(body) and not (phone_ack or direct):
                continue
            elif (not lead.needs_support and lead.ai_consent_state != "declined"
                    and not private_data(body) and worksite_payment_terms_question(body)):
                reply = exact_answer(retrieve(db, lead.org_id, body, "messenger"))
                if not reply and contextual_allowed and contextual_payment_question(body):
                    # Understand the objective with Qwen, but never invent payment terms.
                    use_ai = True
            elif intake == GALILEA_QUESTION:
                reply = intake
            elif contextual_turn:
                # A busy model queue must not send a profile question as an answer to a different topic.
                reply, use_ai = contact_fallback, True
            elif direct:
                reply = direct
            elif contact_model:
                reply, use_ai = contact_fallback, True
            elif application_model:
                reply, use_ai = application, True
            elif local and identity_reply(body):
                reply = local
            elif local and not waiting_for_ai and not lead.needs_support:
                # Courtesy replies must sound conversational from the first turn.
                # Never insert a canned self-introduction into an ordinary hello.
                # Explicit identity questions are answered honestly by identity_reply().
                # AI provider consent is still required before any model processing.
                reply = local
            elif lead.ai_consent_state == "declined":
                # No insistir con IA a quien ya la rechazó.
                reply = None
            elif lead.needs_support:
                # Conversaciones difíciles pasan a revisión humana.
                reply = None
            elif messenger_model_authorized(cfg, lead, ai_source):
                if not (waiting_for_ai or consent_reply):
                    reply = intake
                use_ai = not reply or model_intake_candidate(body, facts, previous_question, reply)
            else:
                if needs_deeper_response(body):
                    if not private_data(body):
                        reply = exact_answer(retrieve(db, lead.org_id, body, "messenger")) or payment_guidance(body)
                else:
                    reply = intake or quick_reply(body, known=facts)
            if not use_ai and not reply and not lead.needs_support and lead.ai_consent_state != "declined":
                # A declaration about trades or an existing team is not a
                # request for human support. The local, non-model intake path
                # is permitted when Qwen is not authorized; never send the
                # unconsented contact's messages to an external provider.
                normalized = plain(body)
                professional = (
                    not signal and not private_data(body) and not needs_deeper_response(body)
                    and (changed or bool(trade_terms(body))
                         or ("equipo" in normalized and
                             any(word in normalized for word in ("cuento con", "contamos con", "tenemos"))))
                )
                if professional:
                    if lead.interest_type in (None, "", "unknown"):
                        reply = ("Gracias por escribir. ¿Quieres ofrecer estos servicios "
                                 "como contratista o buscas empleo?")
                    elif not lead.work_communes:
                        reply = "Gracias por contarme. ¿En qué comuna puedes trabajar?"
                    else:
                        reply = "Gracias, recibí la información y podemos continuar por aquí."
                else:
                    flag_for_human(db, lead,
                                   "Galancito no encontró una respuesta confirmada; revisión humana pendiente")
            if use_ai and recent < 30 and ai_source != "disabled":
                # Persist one queued model turn per contact. The worker owns
                # execution capacity; a full *temporary* queue is not a reason
                # to transfer a normal contractor conversation to a person.
                # New inbound messages cancel/coalesce previous unsent jobs above.
                if coalesced is not None:
                    coalesced.state, coalesced.updated_at = "ai_pending", received_at
                else:
                    db.add(FacebookChatMessage(
                        org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
                        direction="outbound", state="ai_pending",
                        body="", ai_generated=True, updated_at=received_at,
                    ))
            elif reply and recent < 30:
                db.add(FacebookChatMessage(
                    org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
                    direction="outbound", state="pending", body=reply[:550],
                    ai_generated=False,
                ))
            elif recent >= 30 and (use_ai or reply):
                flag_for_human(db, lead,
                               "Límite de respuestas automáticas alcanzado; revisión humana pendiente")
                if recent == 30:
                    db.add(FacebookChatMessage(org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
                        direction="outbound", state="pending", ai_generated=False,
                        body="Ya avisé al equipo para que te atienda una persona. Podemos retomar por aquí."))
    db.commit()
    return {"received": True}


@router.get("/galancito/seguimiento")
def galancito_seguimiento(user: User = Depends(administrator),
                          db: Session = Depends(get_db)):
    """Transparent categories and priority work queue; not hiring decisions."""
    total = db.scalar(select(func.count(FacebookLead.id)).where(
        FacebookLead.org_id == user.org_id)) or 0
    leads = list(db.scalars(select(FacebookLead).where(
        FacebookLead.org_id == user.org_id,
    ).order_by(FacebookLead.last_inbound_at.desc(), FacebookLead.id).limit(200)))
    reqs = list(db.scalars(select(NetworkRequirement).where(
        NetworkRequirement.org_id == user.org_id,
        NetworkRequirement.state == "published",
    ).order_by(NetworkRequirement.created_at.desc()).limit(200)))
    guides = list(db.scalars(select(FacebookTradeGuide).where(
        FacebookTradeGuide.org_id == user.org_id,
        FacebookTradeGuide.approved.is_(True),
    ).limit(60)))
    by_id = {lead.id: [] for lead in leads}
    if by_id:
        msgs = db.scalars(select(FacebookChatMessage).where(
            FacebookChatMessage.org_id == user.org_id,
            FacebookChatMessage.lead_id.in_(list(by_id)),
            FacebookChatMessage.direction == "inbound",
        ).order_by(FacebookChatMessage.created_at.desc()).limit(1000))
        for msg in msgs:
            if len(by_id[msg.lead_id]) < 4:
                by_id[msg.lead_id].append(msg)
    result = dashboard([
        classify_lead(lead, guides, reqs, by_id[lead.id], today=today())
        for lead in leads
    ])
    # Load all trade, association and trace rows in bounded batches; avoid N+1 queries.
    ids = [lead.id for lead in leads]
    trades_by = {lead_id: [] for lead_id in ids}
    linked_by = {lead_id: [] for lead_id in ids}
    history_by = {lead_id: [] for lead_id in ids}
    if ids:
        for item in db.scalars(select(FacebookLeadTrade).where(
            FacebookLeadTrade.org_id == user.org_id,
            FacebookLeadTrade.lead_id.in_(ids),
            FacebookLeadTrade.active.is_(True),
        )):
            trades_by[item.lead_id].append(item.trade)
        for item in db.scalars(select(FacebookNeedAssociation).where(
            FacebookNeedAssociation.org_id == user.org_id,
            FacebookNeedAssociation.lead_id.in_(ids),
            FacebookNeedAssociation.state == "linked",
        )):
            linked_by[item.lead_id].append(item.requirement_id)
        for event in db.scalars(select(FacebookLeadTrace).where(
            FacebookLeadTrace.org_id == user.org_id,
            FacebookLeadTrace.lead_id.in_(ids),
        ).order_by(FacebookLeadTrace.created_at.desc(),
                   FacebookLeadTrace.id.desc()).limit(800)):
            if len(history_by[event.lead_id]) < 3:
                history_by[event.lead_id].append({
                    "event": event.event, "trade": event.trade,
                    "requirement_id": event.requirement_id,
                    "source": event.source,
                    "at": event.created_at.isoformat(),
                })
    req_by_id = {need.id: need for need in reqs}
    by_lead_id = {lead.id: lead for lead in leads}
    by_specialty = {}
    by_need = {}
    for row in result["rows"]:
        lead = by_lead_id[row["id"]]
        trades = list(dict.fromkeys(trades_by[lead.id] or
                                    ([lead.specialty] if lead.specialty else [])))
        linked_ids = set(linked_by[lead.id] +
                         ([lead.requirement_id] if lead.requirement_id else []))
        row["trades"] = trades
        row["links"] = [
            {"id": req_id, "title": req_by_id[req_id].title,
             "specialty": req_by_id[req_id].specialty}
            for req_id in linked_ids if req_id in req_by_id
        ]
        row["matches"] = suggest_requirements(
            lead, trades, reqs, linked_ids, limit=5
        )
        row["recent_trace"] = history_by[lead.id]
        profile = contact_profile(lead)
        row["profile_state"] = "Perfil básico" if trades else "Oficio por conocer"
        row["profile_pending"] = profile["missing"]
        for trade in trades or ["Por confirmar"]:
            by_specialty[trade] = by_specialty.get(trade, 0) + 1
        for label in [x["title"] for x in row["links"]] or ["Sin necesidad asignada"]:
            by_need[label] = by_need.get(label, 0) + 1
    result["by_category"] = by_specialty
    result["by_requirement"] = by_need
    result["unlinked"] = sum(not row["links"] for row in result["rows"])
    result["limited"] = total > len(leads)
    return result


@router.post("/leads/{lead_id}/galancito/analyze")
def galancito_analyze_lead(lead_id: str, user: User = Depends(administrator),
                          db: Session = Depends(get_db)):
    """Local advisory note, consent-gated; never modifies classification fields."""
    lead = _lead(db, user, lead_id)
    reqs = list(db.scalars(select(NetworkRequirement).where(
        NetworkRequirement.org_id == user.org_id,
        NetworkRequirement.state == "published",
    ).limit(200)))
    guides = list(db.scalars(select(FacebookTradeGuide).where(
        FacebookTradeGuide.org_id == user.org_id,
        FacebookTradeGuide.approved.is_(True),
    ).limit(60)))
    recent = list(db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "inbound",
    ).order_by(FacebookChatMessage.created_at.desc()).limit(4)))
    summary = classify_lead(lead, guides, reqs, recent, today=today())
    note, source = "", "reglas"
    if consented_for(lead, "ollama") and not lead.ai_paused and not lead.needs_support:
        context = ("Oficio: " + lead.specialty[:100] +
                   "\nTrabajadores declarados: " + str(lead.workers or "sin informar") +
                   "\nNecesidad vinculada: " + (summary["requirement_title"] or "ninguna")[:150] +
                   "\nEtapa: " + summary["stage"] +
                   "\nMensajes: " + " | ".join(m.body[:220] for m in reversed(recent)))
        try:
            note = infer(db, lambda: generate_triage_note(context)) or ""
        except RuntimeError:
            pass
        if note:
            source = "ia_local"
    return {"triage": summary, "ai_note": note[:360],
            "source": source, "human_review_required": True,
            "changes_applied": False}


@router.get("/inbox/revision")
def inbox_revision(user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Cheap organization-scoped signal for inbound changes, no model or Meta calls."""
    count, latest = db.execute(select(
        func.count(FacebookLead.id), func.max(FacebookLead.updated_at),
    ).where(FacebookLead.org_id == user.org_id)).one()
    return {"revision": f"{count}:{latest.isoformat() if latest else ''}"}


@router.get("/center")
def center(user: User = Depends(administrator), db: Session = Depends(get_db)):
    cfg = settings()
    # Historial de TODOS los envíos (no solo errores). Mostrar la confirmación
    # real de Meta cuando existe un ID remoto; no confundirlo con el estado GALANT.
    rows = list(db.scalars(select(NetworkFacebookPost).where(
        NetworkFacebookPost.org_id == user.org_id,
    ).order_by(NetworkFacebookPost.updated_at.desc(), NetworkFacebookPost.id.desc()).limit(200)))
    known_ids = {row.requirement_id for row in rows}
    publications = []
    ads = []
    # Un requerimiento que ya tiene publicación confirmada nunca debe reaparecer
    # como "sin sincronizar" (error anterior de la bandeja).
    selected_needs = list(db.scalars(select(NetworkRequirement).where(
        NetworkRequirement.org_id == user.org_id,
        NetworkRequirement.publish_to_facebook.is_(True),
        NetworkRequirement.state == "published",
    ).order_by(NetworkRequirement.created_at.desc()).limit(100)))
    for req in selected_needs:
        if req.id not in known_ids:
            pending = {"id": "not-queued-" + req.id, "requirement_id": req.id,
                       "title": req.title, "specialty": req.specialty,
                       "state": "not_queued" if cfg.facebook_autopublish_enabled else "disabled",
                       "error": ("La conexión debe activarse en el VPS."
                                 if not cfg.facebook_autopublish_enabled else
                                 "La solicitud todavía no está en cola."),
                       "post_url": None, "updated_at": req.updated_at.isoformat(),
                       "attempts": 0}
            publications.append(pending)
            ads.append(pending)
    # Resolve publication targets in one query, never one SELECT per post.
    # With 200 publications the old pattern produced up to 200 DB roundtrips
    # on every Facebook dashboard refresh.
    requirement_ids = {row.requirement_id for row in rows if row.requirement_id}
    requirements_by_id = {
        req.id: req for req in db.scalars(select(NetworkRequirement).where(
            NetworkRequirement.org_id == user.org_id,
            NetworkRequirement.id.in_(requirement_ids),
        ))
    } if requirement_ids else {}
    # Resumen de interacción en una única consulta: sin llamadas a Meta
    # ni consultas por publicación en el GET del panel.
    snapshots_by_post = {
        snap.post_record_id: snap for snap in db.scalars(select(FacebookPostSnapshot).where(
            FacebookPostSnapshot.org_id == user.org_id,
            FacebookPostSnapshot.post_record_id.in_([row.id for row in rows])))
    } if rows else {}
    for row in rows:
        req = requirements_by_id.get(row.requirement_id)
        if req:
            item = {"id": row.id, "requirement_id": req.id, "title": req.title,
                    "specialty": req.specialty, "state": row.state,
                    "error": row.last_error,
                    "post_url": ("https://www.facebook.com/" + row.post_id
                                 if row.post_id and re.fullmatch(r"[0-9]+_[0-9]+", row.post_id) else None),
                    "updated_at": row.updated_at.isoformat(),
                    "attempts": row.attempts}
            snap = snapshots_by_post.get(row.id)
            item["comment_count"] = snap.comment_count if snap else None
            item["reaction_count"] = snap.reaction_count if snap else None
            item["share_count"] = snap.share_count if snap else None
            publications.append(item)
            if row.state in ("pending", "sending", "failed", "uncertain"):
                ads.append(item)
    # Último resultado REAL de Messenger. Un modelo activo NO significa que
    # Meta aceptó su respuesta: el operador debe verlo sin abrir cada chat.
    last_outbound = db.scalar(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.page_id == cfg.facebook_page_id,
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.state.in_(["sent", "failed", "uncertain"]),
    ).order_by(FacebookChatMessage.updated_at.desc(),
               FacebookChatMessage.id.desc()).limit(1))
    messenger_delivery = {
        "state": last_outbound.state if last_outbound else "untested",
        "error": last_outbound.error if last_outbound and
                 last_outbound.state in ("failed", "uncertain") else None,
        "updated_at": last_outbound.updated_at.isoformat() if last_outbound else None,
    }
    # Comprobación REAL del token por el worker, independiente del historial de posts.
    # La API no recibe ni devuelve el Page Access Token.
    verify = db.scalar(select(NetworkFacebookManual).where(
        NetworkFacebookManual.org_id == user.org_id,
        NetworkFacebookManual.page_id == cfg.facebook_page_id,
        NetworkFacebookManual.action == "verify",
    ).order_by(NetworkFacebookManual.updated_at.desc(),
               NetworkFacebookManual.id.desc()).limit(1))
    connection = {
        "state": verify.state if verify else "unchecked",
        "checked_at": verify.updated_at.isoformat() if verify else None,
        "error": verify.last_error if verify else None,
        "page_name": verify.page_name if verify and verify.state == "verified" else None,
    }
    # Evitar mezclar el éxito confirmado por Meta con los envíos aún en cola.
    published_count = sum(item["state"] == "published" for item in publications)
    failed_count = sum(item["state"] == "failed" for item in publications)
    last_sync = db.scalar(select(NetworkFacebookManual).where(
        NetworkFacebookManual.org_id == user.org_id,
        NetworkFacebookManual.page_id == cfg.facebook_page_id,
        NetworkFacebookManual.action == "sync_inbox",
    ).order_by(NetworkFacebookManual.updated_at.desc(),
               NetworkFacebookManual.id.desc()).limit(1))
    inbox_sync = {
        "state": last_sync.state if last_sync else "not_checked",
        "checked_at": last_sync.updated_at.isoformat() if last_sync else None,
        "error": last_sync.last_error if last_sync and last_sync.state == "failed" else None,
        "summary": last_sync.message if last_sync and last_sync.state == "synced" else None,
    }
    leads = list(db.scalars(select(FacebookLead).where(
        FacebookLead.org_id == user.org_id).order_by(
        FacebookLead.last_inbound_at.desc(), FacebookLead.id).limit(100)))
    # Single window-function query, not one query per contact. Makes multiple
    # anonymous contacts distinguishable without guessing a person's name.
    last_previews = {}
    if leads:
        latest = select(
            FacebookChatMessage.lead_id.label("lead_id"),
            FacebookChatMessage.body.label("body"),
            FacebookChatMessage.direction.label("direction"),
            func.row_number().over(
                partition_by=FacebookChatMessage.lead_id,
                order_by=(FacebookChatMessage.created_at.desc(),
                          FacebookChatMessage.id.desc()),
            ).label("row_number"),
        ).where(
            FacebookChatMessage.org_id == user.org_id,
            FacebookChatMessage.lead_id.in_([lead.id for lead in leads]),
        ).subquery()
        for lead_id, body, direction in db.execute(select(
            latest.c.lead_id, latest.c.body, latest.c.direction,
        ).where(latest.c.row_number == 1)):
            last_previews[lead_id] = {
                "text": (body or "")[:115], "direction": direction,
            }
    ai_source = messenger_ai_source(db, user.org_id, cfg)
    # This reports *configuration*, never fabricates a confirmed Meta delivery.
    reply_blockers = []
    if not cfg.facebook_messaging_enabled:
        reply_blockers.append("Mensajería de Facebook deshabilitada en el VPS")
    if not cfg.facebook_page_id or cfg.facebook_org_id != user.org_id:
        reply_blockers.append("Página u organización de Messenger sin asociar")
    if not cfg.facebook_app_secret or not cfg.facebook_webhook_verify_token:
        reply_blockers.append("Webhook de Meta incompleto")
    if not cfg.facebook_ai_enabled:
        reply_blockers.append("Asistente de Facebook deshabilitado en el VPS")
    # Token is only exposed to the sender container. Its actual permission
    # and delivery must still be verified against Meta from an external account.
    auto_reply = {
        "configured": not reply_blockers,
        "missing": reply_blockers,
        "verification": ("Comprobar enviando un mensaje desde una cuenta externa. "
                         "Las respuestas de IA requieren consentimiento; todo envío requiere "
                         "confirmación de Meta."),
        "last_delivery": messenger_delivery["state"],
    }
    return {"automatic_enabled": cfg.facebook_autopublish_enabled,
            "manual_enabled": cfg.facebook_manual_testing_enabled,
            "messaging_enabled": cfg.facebook_messaging_enabled,
            "ai_enabled": ai_source != "disabled",
            "ai_provider": ai_source,
            "auto_reply_enabled": cfg.facebook_ai_enabled,
            "auto_reply": auto_reply,
            "page_id": cfg.facebook_page_id,
            "pending_ads": ads, "publications": publications,
            "connection": connection,
            "messenger_delivery": messenger_delivery,
            "inbox_sync": inbox_sync,
            "leads": [{**_lead_view(db, lead),
                       "last_message": last_previews.get(lead.id)} for lead in leads],
            "guides_approved": db.scalar(select(func.count(FacebookTradeGuide.id)).where(
                FacebookTradeGuide.org_id == user.org_id,
                FacebookTradeGuide.approved.is_(True))) or 0,
            "counts": {"pending_ads": len(ads), "published_ads": published_count,
                       "failed_ads": failed_count, "total_ads": len(publications),
                       "contacts": len(leads),
                       "unread": sum(bool(lead.unread) for lead in leads),
                       "review": sum(lead.status == "pending_review" for lead in leads),
                       "support": sum(bool(lead.needs_support) for lead in leads)}}


@router.post("/inbox/sync", status_code=202)
def request_inbox_sync(user: User = Depends(administrator),
                       db: Session = Depends(get_db)):
    """Queue a bounded Page API recovery; never handles or exposes page tokens."""
    cfg = settings()
    if not (cfg.facebook_messaging_enabled and cfg.facebook_page_id and
            cfg.facebook_org_id == user.org_id):
        raise HTTPException(409, "Configura Messenger y su organización antes de recuperar mensajes")
    in_progress = db.scalar(select(NetworkFacebookManual).where(
        NetworkFacebookManual.org_id == user.org_id,
        NetworkFacebookManual.page_id == cfg.facebook_page_id,
        NetworkFacebookManual.action == "sync_inbox",
        NetworkFacebookManual.state.in_(["pending", "sending"]),
    ).order_by(NetworkFacebookManual.created_at).limit(1))
    if in_progress:
        return {"state": in_progress.state, "queued": False}
    previous = db.scalar(select(NetworkFacebookManual).where(
        NetworkFacebookManual.org_id == user.org_id,
        NetworkFacebookManual.page_id == cfg.facebook_page_id,
        NetworkFacebookManual.action == "sync_inbox",
    ).order_by(NetworkFacebookManual.updated_at.desc()).limit(1))
    if previous and _aware(previous.updated_at) >= utcnow() - timedelta(seconds=30):
        return {"state": previous.state, "queued": False}
    db.add(NetworkFacebookManual(
        org_id=user.org_id, created_by=user.id, page_id=cfg.facebook_page_id,
        client_key=str(uuid4()), action="sync_inbox", state="pending",
        title="Recuperación de mensajes de Messenger", message="",
    ))
    db.commit()
    return {"state": "pending", "queued": True}



@router.get("/leads/{lead_id}/trace")
def lead_trace(lead_id: str, user: User = Depends(administrator),
               db: Session = Depends(get_db)):
    lead = _lead(db, user, lead_id)
    events = db.scalars(select(FacebookLeadTrace).where(
        FacebookLeadTrace.org_id == lead.org_id,
        FacebookLeadTrace.lead_id == lead.id,
    ).order_by(FacebookLeadTrace.created_at.desc(),
               FacebookLeadTrace.id.desc()).limit(100))
    return [{
        "event": item.event, "trade": item.trade,
        "requirement_id": item.requirement_id,
        "source": item.source, "actor_id": item.actor_id,
        "message_id": item.source_remote_id,
        "at": item.created_at.isoformat(),
    } for item in events]


@router.post("/leads/{lead_id}/needs/{requirement_id}/link")
def link_contact_need(lead_id: str, requirement_id: str,
                      user: User = Depends(administrator),
                      db: Session = Depends(get_db)):
    """Explicit human link; no selection, award, or contact message."""
    lead = _lead(db, user, lead_id)
    need = db.scalar(select(NetworkRequirement).where(
        NetworkRequirement.id == requirement_id,
        NetworkRequirement.org_id == user.org_id,
        NetworkRequirement.state == "published",
    ))
    if not need:
        raise HTTPException(404, "Necesidad vigente no encontrada")
    changed = link_requirement(db, lead, need.id, user.id)
    if changed:
        lead.updated_at = utcnow()
        db.commit()
    return {"linked": True, "changed": changed}


@router.post("/leads/{lead_id}/needs/{requirement_id}/unlink")
def unlink_contact_need(lead_id: str, requirement_id: str,
                        user: User = Depends(administrator),
                        db: Session = Depends(get_db)):
    """Keep historical event and soft-delete only the requested association."""
    lead = _lead(db, user, lead_id)
    changed = unlink_requirement(db, lead, requirement_id, user.id)
    if changed:
        lead.updated_at = utcnow()
        db.commit()
    return {"linked": False, "changed": changed}


@router.get("/leads/{lead_id}")
def get_lead(lead_id: str, user: User = Depends(administrator),
             db: Session = Depends(get_db),
             include_messages: bool = Query(default=True)):
    lead = _lead(db, user, lead_id)
    # The contact sheet needs professional facts, not a 200-message chat
    # transcript. Inbox calls keep the default and receive all chat messages.
    msgs = []
    if include_messages:
        msgs = list(db.scalars(select(FacebookChatMessage).where(
            FacebookChatMessage.org_id == user.org_id,
            FacebookChatMessage.lead_id == lead.id,
        ).order_by(FacebookChatMessage.created_at.desc(), FacebookChatMessage.id.desc()).limit(200)))
        msgs.reverse()
    view = _lead_view(db, lead)
    trade_rows = list(db.scalars(select(FacebookLeadTrade).where(
        FacebookLeadTrade.org_id == user.org_id,
        FacebookLeadTrade.lead_id == lead.id,
        FacebookLeadTrade.active.is_(True),
    ).order_by(FacebookLeadTrade.first_seen_at, FacebookLeadTrade.id)))
    view["trades"] = list(dict.fromkeys([*(row.trade for row in trade_rows), *(
        [lead.specialty] if lead.specialty and not trade_rows else [])]))
    view["trade_sources"] = [
        {"trade": row.trade, "source": row.source, "message_id": row.source_remote_id,
         "at": row.updated_at.isoformat()} for row in trade_rows
    ]
    view["linked_needs"] = [row.requirement_id for row in db.scalars(
        select(FacebookNeedAssociation).where(
            FacebookNeedAssociation.org_id == user.org_id,
            FacebookNeedAssociation.lead_id == lead.id,
            FacebookNeedAssociation.state == "linked",
        )
    )]
    return {"lead": view, "messages": [_message_view(m) for m in msgs]}


# Namespaced summary cache in existing profile_sources JSON to avoid a schema change.
# The cache contains only a short narrative + evidence IDs, never raw messages.
_BRIEF_CACHE_KEY = "_galancito_conversation_brief_v1"
_BRIEF_INSTRUCTIONS = """Redacta una síntesis interna breve en español chileno, en dos frases.
Lee SOLO los hechos y mensajes aportados; nunca inventes datos, contratos,
ubicaciones, acuerdos, sueldos, validaciones ni promesas.
Usa expresiones como 'declara' o 'comenta'; no supongas que se contrató.
No incluyas nombres completos, teléfonos, direcciones, RUT ni datos sensibles.
Contesta SOLO un JSON válido, sin formato Markdown:
{"summary":"Qué dice la persona y qué falta para coordinar.","evidence_ids":["ID_RELEVANTE"]}
Los IDs deben existir en messages. La síntesis requiere al menos un mensaje real.
"""
def _conversation_brief(db: Session, lead: FacebookLead) -> dict:
    messages = list(db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == lead.org_id,
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "inbound",
    ).order_by(FacebookChatMessage.created_at.desc(), FacebookChatMessage.id.desc()).limit(75)))
    messages.reverse()
    brief = summarize_conversation(lead, messages)
    trades = active_trades(db, lead)
    brief["trades"] = trades
    source = messenger_contact_ai_source(db, lead)
    allowed = source != "disabled" and consented_for(lead, source) and not lead.ai_paused
    brief["ai_eligible"] = bool(allowed)
    cache = (lead.profile_sources or {}).get(_BRIEF_CACHE_KEY, {})
    if (allowed and isinstance(cache, dict) and cache.get("fingerprint") == brief["fingerprint"]
            and isinstance(cache.get("result"), dict) and
            cache["result"].get("source") == "ia_con_evidencia"):
        brief["ai"] = cache["result"]
    brief["messages_reviewed"] = len(messages)
    brief["limited"] = len(messages) == 75
    return brief


@router.get("/leads/{lead_id}/conversation-brief")
def conversation_brief(lead_id: str, user: User = Depends(administrator),
                       db: Session = Depends(get_db)):
    """Instant, truthful synthesis; no AI calls or side effects on a GET."""
    lead = _lead(db, user, lead_id)
    return _conversation_brief(db, lead)


@router.post("/leads/{lead_id}/conversation-brief")
def generate_conversation_brief(lead_id: str, user: User = Depends(administrator),
                                db: Session = Depends(get_db)):
    """Opted-in summary. Cached by real message+fact fingerprint to save tokens."""
    lead = _lead(db, user, lead_id, lock=True)
    brief = _conversation_brief(db, lead)
    if brief["ai"] or not brief["ai_eligible"] or not brief["evidence"]:
        return brief
    source = messenger_contact_ai_source(db, lead)
    # Check only human-readable content. Internal IDs may look like RUT/phone numbers.
    if brief_contains_private_data(brief):
        return brief
    data = safe_model_input(brief)
    try:
        if source == "team":
            raw = infer(db, lambda: orchestrated_text(
                db, lead.org_id, task="messenger",
                instructions=_BRIEF_INSTRUCTIONS, prompt=data,
                max_output_tokens=260,
            ), org_id=lead.org_id)
        elif source == "ollama":
            from .galancito_local import generate_local_text
            raw = infer(db, lambda: generate_local_text(_BRIEF_INSTRUCTIONS, data, 650))
        else:
            raw = infer(db, lambda: generate_text(_BRIEF_INSTRUCTIONS, data, 650))
    except (RuntimeError, ValueError, TimeoutError, OSError, HTTPError, URLError, AIServiceError):
        raw = None
    accepted = validate_ai_brief(raw, brief) if raw else None
    if accepted:
        lead.profile_sources = {
            **(lead.profile_sources or {}),
            _BRIEF_CACHE_KEY: {"fingerprint": brief["fingerprint"], "result": accepted},
        }
        db.commit()
        brief["ai"] = accepted
    return brief


@router.post("/leads/{lead_id}/recover-contact")
def recover_contact_fields(lead_id: str, user: User = Depends(administrator),
                           db: Session = Depends(get_db)):
    lead = _lead(db, user, lead_id, lock=True)
    if recover_missing_contact(db, lead):
        lead.updated_at = utcnow()
    db.commit()
    return _lead_view(db, lead)


def _replay_declared_profile(db, lead):
    """Recover all persisted messages in bounded pages, without replies or external calls."""
    recovery = recovery_scope(db, lead)
    recover_missing_contact(db, lead, full_history=True)
    previous_question, question_at = "", None
    aliases = approved_trade_aliases(db, lead.org_id)
    count = 0
    for item in iter_recovery_messages(db, lead):
        count += 1
        if item.direction == "outbound":
            if item.state == "sent":
                previous_question, question_at = item.body or "", aware(item.updated_at)
        elif item.direction == "inbound":
            at = aware(item.created_at)
            prior = previous_question if question_at and timedelta(0) <= at - question_at <= timedelta(hours=24) else ""
            if item.consent_decision is None:
                apply_messenger_message(db, lead, item.body or "", prior,
                                        remote_id=item.remote_id, at=at,
                                        replay=True, aliases=aliases, recovery=recovery)
            previous_question, question_at = "", None
    return {"messages_examined": count, "history_truncated": False,
            "history_scope": "persisted_messenger_messages", "page_size": 200}


def _recovery_snapshot(db, lead):
    # Detach mutable JSON and keep raw contact values out of the diagnostic.
    from copy import deepcopy
    facts = profile_facts(lead)
    facts["trades"] = sorted(active_trades(db, lead))
    facts["phone_recorded"] = bool(lead.contact_phone)
    facts["email_recorded"] = bool(lead.contact_email)
    return deepcopy(facts)


@router.post("/leads/{lead_id}/refresh-profile")
def refresh_declared_profile(lead_id: str, dry_run: bool = False,
                             user: User = Depends(administrator),
                             db: Session = Depends(get_db)):
    """Preview or recover evidence-backed fields without sending any messages."""
    lead = _lead(db, user, lead_id, lock=True)
    if dry_run:
        before = _recovery_snapshot(db, lead)
        savepoint = db.begin_nested()
        try:
            coverage = _replay_declared_profile(db, lead)
            db.flush()
            after = _recovery_snapshot(db, lead)
            changed = {key: {"before": before.get(key), "after": after.get(key)}
                       for key in after if before.get(key) != after.get(key)}
            # Provide the persisted inbound evidence identifiers, not message text.
            sources = lead.profile_sources or {}
            evidence = {key: sources[key].get("message_id") for key in changed
                        if isinstance(sources.get(key), dict)}
            for key, field in (("phone_recorded", "contact_phone"), ("email_recorded", "contact_email")):
                if key in changed:
                    evidence[key] = (sources.get(field) or {}).get("message_id")
            trade_evidence = {row.trade: {"message_id": row.source_remote_id, "active": row.active,
                                          "source": row.source}
                              for row in db.scalars(select(FacebookLeadTrade).where(
                                  FacebookLeadTrade.org_id == lead.org_id,
                                  FacebookLeadTrade.lead_id == lead.id))}
            for trade in set(before["trades"]) ^ set(after["trades"]):
                evidence["trades." + trade] = (trade_evidence.get(trade) or {}).get("message_id")
            if "contact_available" in changed:
                evidence["contact_available"] = [evidence[key] for key in ("phone_recorded", "email_recorded")
                                                 if evidence.get(key)]
            evidence.update({"declared_context." + key: entry.get("message_id")
                             for key, entry in (sources.get("_declared_context") or {}).items()
                             if isinstance(entry, dict) and
                             before.get("declared_context", {}).get(key) !=
                             after.get("declared_context", {}).get(key)})
            result = {"dry_run": True, "lead_id": lead_id, **coverage,
                      "changes": changed, "evidence": evidence, "trade_evidence": trade_evidence}
        finally:
            savepoint.rollback()
        return result
    _replay_declared_profile(db, lead)
    lead.updated_at = utcnow()
    db.commit()
    return _lead_view(db, lead)


@router.get("/leads/{lead_id}/insights")
def lead_insights(lead_id: str, user: User = Depends(administrator),
                  db: Session = Depends(get_db)):
    """Resumen y sugerencias explicables, sin cambios ni adjudicaciones automáticas."""
    lead = _lead(db, user, lead_id)
    messages = list(db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "inbound",
    ).order_by(FacebookChatMessage.created_at.desc()).limit(8)))
    needs = list(db.scalars(select(NetworkRequirement).where(
        NetworkRequirement.org_id == user.org_id,
        NetworkRequirement.state == "published",
    ).order_by(NetworkRequirement.start_date, NetworkRequirement.id).limit(200)))
    sites = {site.id: site.name for site in db.scalars(select(Worksite).where(
        Worksite.org_id == user.org_id
    ))}
    suggestions = suggestions_for_lead(lead, messages)
    matches = ranked_needs(lead, needs, sites, trades=active_trades(db, lead))
    triage = classify_lead(lead, [], needs, messages, today=today())
    missing = []
    if lead.display_name == "Interesado de Facebook":
        missing.append("Confirmar nombre")
    if not lead.specialty:
        missing.append("Oficio")
    if lead.workers is None:
        missing.append("Personas disponibles")
    if not lead.availability:
        missing.append("Fecha de disponibilidad")
    return {
        "contact_id": lead.id,
        "summary": {
            "name": lead.display_name,
            "company": lead.company,
            "specialty": lead.specialty,
            "workers": lead.workers,
            "availability": lead.availability,
            "stage": triage["stage"],
        },
        "next_action": triage["next_action"],
        "missing": missing,
        "suggestions": suggestions,
        "matches": matches,
        "source": "reglas_locales",
        "review_required": True,
        "changes_applied": False,
    }


@router.post("/leads/{lead_id}/read")
def read_lead(lead_id: str, user: User = Depends(administrator),
              db: Session = Depends(get_db)):
    lead = _lead(db, user, lead_id)
    lead.unread = False
    db.commit()
    return {"ok": True}


@router.patch("/leads/{lead_id}")
def update_lead(lead_id: str, body: LeadEdit, user: User = Depends(administrator),
                db: Session = Depends(get_db)):
    lead = _lead(db, user, lead_id, lock=True)
    if body.requirement_id and not db.scalar(select(NetworkRequirement.id).where(
        NetworkRequirement.id == body.requirement_id,
        NetworkRequirement.org_id == user.org_id,
    )):
        raise HTTPException(422, "La necesidad no pertenece a tu organización")
    previous_requirement_id = lead.requirement_id
    manual_fields = set()
    tracked_fields = profile_facts(lead)
    edits = body.model_dump(exclude_unset=True)
    if (employee_count := edits.get("employee_count")) is not None:
        if "has_employees" in edits and edits["has_employees"] is not (employee_count > 0):
            raise HTTPException(422, "La cantidad declarada debe coincidir con el estado de contratación")
        edits["has_employees"] = employee_count > 0
    elif "has_employees" in edits:
        if edits["has_employees"] is False:
            edits["employee_count"] = 0
        elif edits["has_employees"] is None or lead.employee_count == 0:
            edits["employee_count"] = None
    for field, value in edits.items():
        tracked = "display_name" if field == "name" else field
        if tracked in tracked_fields and getattr(lead, tracked) != value:
            manual_fields.add(tracked)
        if field == "name":
            lead.display_name = value.strip() or "Interesado de Facebook"
        elif field == "company":
            lead.company = value.strip()
        elif field == "contact_phone":
            normalized = normalize_mobile(value) if value.strip() else ""
            if value.strip() and normalized is None:
                raise HTTPException(422, "Número de celular chileno inválido")
            if lead.contact_phone != normalized:
                lead.contact_phone = normalized
                lead.phone_source = "manual" if normalized else ""
                lead.phone_shared_at = utcnow() if normalized else None
                lead.phone_opt_out = False
                note_profile_sources(lead, ["contact_phone"], source="manual", at=utcnow())
                audit_event(db, lead, "field_contact_phone", source="manual", actor_id=user.id)
        elif field == "contact_email":
            normalized_email = value.strip().lower()
            from .galancito_contact_email import email_shared_by_sender
            if normalized_email and (email_shared_by_sender(normalized_email) != normalized_email):
                raise HTTPException(422, "Ingresa un correo electrónico válido")
            if lead.contact_email != normalized_email:
                lead.contact_email = normalized_email
                lead.email_source = "manual" if normalized_email else ""
                lead.email_shared_at = utcnow() if normalized_email else None
                lead.email_opt_out = False
                note_profile_sources(lead, ["contact_email"], source="manual", at=utcnow())
                audit_event(db, lead, "field_contact_email", source="manual", actor_id=user.id)
        elif field == "work_area" and value != lead.work_area:
            lead.work_area = value.strip()
            lead.work_communes = find_communes(value)
            manual_fields.add("work_communes")
        elif field in {"specialty", "experience", "availability"}:
            setattr(lead, field, value.strip())
            if field == "specialty":
                lead.specialty_source = "manual"
                if value.strip():
                    record_manual_trade(db, lead, value.strip(), user.id)
        else:
            setattr(lead, field, value)
    note_profile_sources(lead, manual_fields, source="manual", at=utcnow())
    for field in sorted(manual_fields - {"work_area"}):
        audit_event(db, lead, "field_" + field, source="manual", actor_id=user.id)
    if "requirement_id" in body.model_fields_set and previous_requirement_id != lead.requirement_id:
        # Legacy single-need editor remains usable; the link table is canonical
        # for the new multi-need view and retains an audit trail.
        new_requirement_id = lead.requirement_id
        if previous_requirement_id:
            unlink_requirement(db, lead, previous_requirement_id, user.id)
        if new_requirement_id:
            link_requirement(db, lead, new_requirement_id, user.id)
            lead.requirement_id = new_requirement_id
    elif "requirement_id" not in body.model_fields_set:
        trace_unique_requirement(db, lead, today=today())
    if body.model_fields_set.intersection({"follow_up_on", "follow_up_note"}):
        lead.follow_up_by = user.id
    if body.model_fields_set.intersection({"needs_support"}) and not lead.needs_support:
        # An operator can explicitly resume this conversation with both flags
        # cleared. This does NOT grant an AI provider permission.
        lead.support_reason = ""
    if ((body.model_fields_set.intersection({"ai_paused"}) and lead.ai_paused) or
            (body.model_fields_set.intersection({"needs_support"}) and lead.needs_support)):
        # El operador toma el control: cancelar respuestas del bot que no
        # hayan salido, sin tocar mensajes redactados por una persona.
        for pending in db.scalars(select(FacebookChatMessage).where(
            FacebookChatMessage.lead_id == lead.id,
            FacebookChatMessage.operator_id.is_(None),
            FacebookChatMessage.direction == "outbound",
            FacebookChatMessage.state.in_(["pending", "ai_pending", "drafting"]),
        )):
            pending.state = "cancelled"
    lead.updated_at = utcnow()
    db.commit()
    return _lead_view(db, lead)


@router.post("/leads/{lead_id}/request-phone", status_code=202)
def request_contact_phone(lead_id: str, user: User = Depends(administrator),
                          db: Session = Depends(get_db)):
    """Operator-confirmed, optional phone request. No automated offer or award."""
    lead = _lead(db, user, lead_id, lock=True)
    if not settings().facebook_messaging_enabled or not _in_window(lead):
        raise HTTPException(409, "Mensajería fuera de la ventana permitida")
    if lead.contact_phone:
        raise HTTPException(409, "El contacto ya compartió un teléfono")
    if lead.phone_opt_out:
        raise HTTPException(409, "La persona prefirió no compartir el número")
    last = _aware(lead.phone_requested_at)
    if last and last >= utcnow() - timedelta(days=7):
        raise HTTPException(409, "El número ya se solicitó recientemente")
    # The human request supersedes unfinished automated drafts.
    for old in db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.operator_id.is_(None),
        FacebookChatMessage.state.in_(["pending", "ai_pending", "drafting"]),
    )):
        old.state = "cancelled"
    message = FacebookChatMessage(
        org_id=user.org_id, lead_id=lead.id, page_id=lead.page_id,
        direction="outbound", state="pending",
        operator_id=user.id, body=CONTACT_PHONE_QUESTION,
    )
    db.add(message)
    lead.phone_requested_at = utcnow()
    lead.updated_at = utcnow()
    db.commit()
    return {"queued": True, "state": "pending", "phone_requested_at": lead.phone_requested_at.isoformat()}


@router.post("/leads/{lead_id}/reply", status_code=202)
def queue_reply(lead_id: str, body: ReplyInput, user: User = Depends(administrator),
                db: Session = Depends(get_db)):
    lead = _lead(db, user, lead_id, lock=True)
    if not settings().facebook_messaging_enabled:
        raise HTTPException(409, "Habilita y verifica Messenger en el servidor")
    if not _in_window(lead):
        raise HTTPException(409, "La ventana estándar de respuesta de 24 horas finalizó")
    # This reply takes precedence over an unfinished bot draft. Future inbound
    # turns still receive automatic help unless the operator explicitly pauses it.
    for old in db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.operator_id.is_(None),
        FacebookChatMessage.state.in_(["pending", "ai_pending", "drafting"]),
    )):
        old.state = "cancelled"
    message = FacebookChatMessage(org_id=user.org_id, lead_id=lead.id, page_id=lead.page_id,
                                  direction="outbound", state="pending",
                                  operator_id=user.id, body=body.message.strip())
    db.add(message)
    db.commit()
    return _message_view(message)


@router.post("/leads/{lead_id}/suggest")
def suggest_reply(lead_id: str, user: User = Depends(administrator),
                  db: Session = Depends(get_db)):
    lead = _lead(db, user, lead_id)
    messages = list(db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.org_id == user.org_id).order_by(
        FacebookChatMessage.created_at.desc()).limit(8)))
    if lead.needs_support:
        return {"draft": reply_for_support(lead.support_reason or "Solicitó ayuda",
                                           bool(lead.specialty)),
                "source": "help_first", "requires_review": True,
                "alert_admin": True}
    latest_inbound = next((m.body for m in messages if m.direction == "inbound"
                           and m.consent_decision is None), "")
    facts = profile_facts(lead)
    previous_question = next((m.body for m in messages if m.direction == "outbound"
                              and m.state == "sent"), "")
    if location := worksite_reply(db, lead, latest_inbound, previous_question):
        return {"draft": location, "source": "template", "requires_review": True}
    intake = next_intake_reply(latest_inbound, facts, previous_question)
    evidence = retrieve(db, lead.org_id, latest_inbound, "messenger") if not private_data(latest_inbound) else []
    fast = intake or quick_reply(latest_inbound, known=facts)
    ai_source = messenger_contact_ai_source(db, lead)
    model_allowed = (consented_for(lead, ai_source) and not lead.ai_paused
                     and model_intake_candidate(latest_inbound, facts, previous_question, intake))
    if not model_allowed:
        if analyze(latest_inbound).intent not in {"human", "restricted", "requirements"} and not private_data(latest_inbound):
            fast = exact_answer(evidence) or fast
        if fast:
            return {"draft": fast, "source": "template", "requires_review": True}
    if model_allowed:
        supplied, _ = messenger_context(latest_inbound, facts, previous_question, messages, evidence,
                                        _guide_for(db, lead))
        try:
            if private_data(supplied):
                raise RuntimeError("El contexto requiere revisión humana")
            if ai_source == "team" and local_first_messenger(settings()):
                drafted, _route = select_response(
                    lambda: infer(db, lambda: generate_text(REPLY_INSTRUCTIONS, supplied, 450)),
                    lambda: infer(db, lambda: orchestrated_text(db, lead.org_id, task="messenger",
                        instructions=REPLY_INSTRUCTIONS, prompt=supplied, max_output_tokens=160), org_id=lead.org_id),
                    supplied, allow_external=(consented_for(lead, "team") and
                        messenger_external_fallback_enabled(db, lead.org_id, settings())),
                )
            else:
                drafted = infer(db, lambda: (
                    orchestrated_text(db, lead.org_id, task="messenger",
                                  instructions=REPLY_INSTRUCTIONS, prompt=supplied,
                                  max_output_tokens=160)
                    if ai_source == "team" else generate_text(REPLY_INSTRUCTIONS, supplied, 450)),
                    org_id=lead.org_id if ai_source == "team" else None)
        except (RuntimeError, ValueError):
            drafted = None
        if drafted:
            drafted = grounded_reply(drafted, supplied)
        if drafted and acceptable_intake_draft(drafted, facts, intake or "", message=latest_inbound):
            return {"draft": natural_messenger_reply(drafted), "source": "ai", "requires_review": True}
    if fast:
        return {"draft": fast, "source": "template", "requires_review": True}
    if not lead.specialty:
        question = "¿Qué trabajo haces? Por ejemplo, gasfitería, carpintería o pintura."
    elif lead.team_available is None:
        question = "¿Trabajas solo o puedes venir con otras personas?"
    elif lead.team_available and lead.workers is None:
        question = "¿Con cuántas personas puedes venir en total?"
    elif not lead.availability:
        question = "¿Desde cuándo puedes empezar a trabajar?"
    else:
        question = "¿En qué comuna puedes trabajar?"
    return {"draft": ("Puedes escribir como te salga, sin preocuparte por la ortografía. "
                      "Si prefieres un audio, una persona lo puede revisar. " + question),
            "source": "template", "requires_review": True}


@router.get("/leads/{lead_id}/onboarding")
def lead_onboarding(lead_id: str, user: User = Depends(administrator),
                    db: Session = Depends(get_db)):
    lead = _lead(db, user, lead_id)
    # No publicar una lista al contacto: es herramienta interna y gradual.
    return onboarding_guide(
        entity_type=lead.entity_type,
        has_employees=lead.has_employees,
        trade=lead.specialty,
        needs_support=lead.needs_support,
    )


@router.post("/requirements/{requirement_id}/ad-draft")
def suggest_ad(requirement_id: str, user: User = Depends(administrator),
               db: Session = Depends(get_db)):
    req = db.scalar(select(NetworkRequirement).where(
        NetworkRequirement.id == requirement_id,
        NetworkRequirement.org_id == user.org_id))
    if not req:
        raise HTTPException(404, "Necesidad no encontrada")
    original = public_message(db, req)
    try:
        draft, generated = infer(db, lambda: verified_ad_copy(original, req.title, req.specialty))
    except RuntimeError:
        draft, generated = original, False
    if generated:
        return {"draft": draft, "source": "ia_local", "requires_review": True,
                "published": False}
    return {"draft": original, "source": "template",
            "requires_review": True, "published": False}
