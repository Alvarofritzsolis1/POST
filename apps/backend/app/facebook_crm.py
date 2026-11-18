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
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text as sql_text
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, SessionLocal
from .facebook_ai import (AD_INSTRUCTIONS, REPLY_INSTRUCTIONS, generate_text,
                          messenger_ai_source, verified_ad_copy,
                          generate_triage_note)
from .ai_gateway import orchestrated_text
from .facebook_onboarding import assistance_signal, reply_for_support, onboarding_guide
from .galancito_flow import (AI_PERMISSION_QUESTION, AI_PERMISSION_REASK,
                             AI_PERMISSION_DECLINED, consent_decision, wants_human, permission_question)
from .facebook_crm_models import FacebookLead, FacebookChatMessage, FacebookTradeGuide
from .models import Organization, User, utcnow
from .network_facebook import public_message
from .network_models import NetworkFacebookPost, NetworkFacebookManual, NetworkRequirement, NetworkNotification
from .network_service import key, today
from .galancito_triage import classify_lead, dashboard
from .security import administrator
from .galancito_triage import analyze, private_data, quick_reply
from .galancito_intake import apply_intake, next_intake_reply
from .galancito_contact_profile import contact_profile
from .facebook_lead_insights import ranked_needs, suggestions_for_lead
from .ops_models import Worksite
from .galancito_knowledge import retrieve, exact_answer, evidence_context
from .galancito_runtime import infer
from .galancito_flow import grounded_reply

router = APIRouter(prefix="/api/v1/network/facebook", tags=["Facebook CRM"])


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _in_window(lead: FacebookLead) -> bool:
    return bool(lead.last_inbound_at and
                _aware(lead.last_inbound_at) >= utcnow() - timedelta(hours=24))


def _lead(db: Session, user: User, lead_id: str) -> FacebookLead:
    lead = db.scalar(select(FacebookLead).where(
        FacebookLead.id == lead_id, FacebookLead.org_id == user.org_id))
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
    if not lead.specialty.strip():
        missing.append("Especialidad de la empresa")
    else:
        compatible = key(lead.specialty) == key(req.specialty)
        checks.append({"criterion": "Especialidad",
                       "state": "match" if compatible else "verify",
                       "detail": lead.specialty + " / requerida: " + req.specialty})
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
        "team_available": lead.team_available,
        "interest_type": lead.interest_type,
        "work_area": lead.work_area,
        "profile": contact_profile(lead),
        "follow_up_on": lead.follow_up_on.isoformat() if lead.follow_up_on else None,
        "follow_up_note": lead.follow_up_note or "",
        "last_inbound_at": lead.last_inbound_at.isoformat() if lead.last_inbound_at else None,
        "can_reply": _in_window(lead), "analysis": _match(db, lead),
    }


def _message_view(m: FacebookChatMessage) -> dict:
    return {"id": m.id, "direction": m.direction, "state": m.state,
            "body": m.body, "ai_generated": m.ai_generated,
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
    team_available: bool | None = None
    interest_type: str = Field(default="unknown", pattern="^(unknown|service_offer|employment)$")
    work_area: str = Field(default="", max_length=120)
    follow_up_on: date | None = None
    follow_up_note: str = Field(default="", max_length=240)


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
    if payload.get("object") != "page":
        return {"received": True}
    if not db.get(Organization, cfg.facebook_org_id):
        raise HTTPException(503, "Organización de Facebook no configurada")
    if db.bind.dialect.name == "postgresql":
        db.execute(sql_text("SELECT pg_advisory_xact_lock(2075003)"))
    for entry in payload.get("entry", [])[:20]:
        if str(entry.get("id")) != cfg.facebook_page_id:
            continue
        for event in entry.get("messaging", [])[:30]:
            if not isinstance(event, dict):
                continue
            meta_message = event.get("message") or {}
            if not isinstance(meta_message, dict) or meta_message.get("is_echo"):
                continue
            psid = str((event.get("sender") or {}).get("id") or "")
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
                FacebookLead.psid == psid))
            if lead is None:
                lead = FacebookLead(org_id=cfg.facebook_org_id,
                                    page_id=cfg.facebook_page_id, psid=psid)
                db.add(lead)
                db.flush()
            lead.last_inbound_at, lead.updated_at, lead.unread = utcnow(), utcnow(), True
            consent = (False if (lead.ai_consent_state in ("accepted", "accepted_team") and
                                 wants_human(body)) else
                       consent_decision(body) if lead.ai_consent_state in ("requested", "requested_team")
                       and not audio_received else None)
            if consent is True:
                lead.ai_consent = True
                lead.ai_consent_state = ("accepted_team" if lead.ai_consent_state == "requested_team"
                                         else "accepted")
            elif consent is False:
                lead.ai_consent, lead.ai_consent_state = False, "declined"
                # A refusal can arrive before the permission question leaves
                # the durable queue. Do not send that obsolete question later.
                for pending in db.scalars(select(FacebookChatMessage).where(
                    FacebookChatMessage.lead_id == lead.id,
                    FacebookChatMessage.operator_id.is_(None),
                    FacebookChatMessage.direction == "outbound",
                    FacebookChatMessage.state.in_(["pending", "ai_pending"]),
                )):
                    pending.state = "cancelled"
            if consent is None and not audio_received and not private_data(body):
                previous_question = db.scalar(select(FacebookChatMessage.body).where(
                    FacebookChatMessage.lead_id == lead.id,
                    FacebookChatMessage.direction == "outbound",
                    FacebookChatMessage.state == "sent",
                ).order_by(FacebookChatMessage.created_at.desc(),
                           FacebookChatMessage.id.desc()).limit(1)) or ""
                # Only self-declared professional details, never an employment inference
                # from ability to bring people; no third-party model receives these fields.
                apply_intake(lead, body, previous_question)
                approved_trades = {g.trade: (g.trade, *(g.aliases or [])) for g in db.scalars(
                    select(FacebookTradeGuide).where(FacebookTradeGuide.org_id == lead.org_id,
                                                    FacebookTradeGuide.approved.is_(True)).limit(100))}
                facts = analyze(body, approved_trades)
                # Asking about a trade is NOT a declaration of doing that trade.
                # Allow short one-word answers because many small contractors
                # type only a word or two.
                casual = key(body)
                declares_trade = bool(re.search(
                    r"\b(?:soy|soi|trabajo|trabajamos|hago|hacemos|ofrezco|ofresco|"
                    r"tengo|tenemos|somos|me dedico|busco)\b", casual))
                declares_trade = declares_trade or (
                    len(casual.split()) <= 2 and "?" not in body and "¿" not in body)
                if facts.specialty and declares_trade and (
                    not lead.specialty or lead.specialty_source == "message"):
                    lead.specialty = facts.specialty
                    lead.specialty_source = "message"
                if facts.entity_type != "unknown":
                    lead.entity_type = facts.entity_type
                if facts.workers is not None:
                    lead.workers = facts.workers
                if facts.availability:
                    lead.availability = facts.availability
                # Trabajar solo no demuestra que no existan dependientes
                # formalmente contratados: nunca inferir has_employees.
            signal = (assistance_signal(body, is_audio=audio_received)
                      if consent is None else None)
            if consent is False:
                signal = "Prefirió atención humana y no autorizó IA externa"
            if signal:
                # No inferir escolaridad ni rechazar por errores ortográficos.
                first_alert = not lead.needs_support
                lead.needs_support = True
                lead.support_reason = signal
                if first_alert:
                    admin_ids = db.scalars(select(User.id).where(
                        User.org_id == lead.org_id, User.role == "admin",
                        User.enabled.is_(True))).all()
                    for admin_id in admin_ids:
                        event_key = "facebook_help:" + lead.id
                        if not db.scalar(select(NetworkNotification.id).where(
                            NetworkNotification.user_id == admin_id,
                            NetworkNotification.event_key == event_key)):
                            db.add(NetworkNotification(
                                org_id=lead.org_id, user_id=admin_id,
                                event_key=event_key,
                                title="Facebook: un interesado necesita ayuda para avanzar",
                                resource_type="facebook", resource_id=lead.id,
                            ))
            db.add(FacebookChatMessage(
                org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
                remote_id=mid, direction="inbound", state="received",
                body=body.strip()[:3500],
            ))
            # El mensaje entrante más reciente desplaza cualquier respuesta AI
            # que todavía no haya salido: nunca responder a una consulta antigua.
            for previous in db.scalars(select(FacebookChatMessage).where(
                FacebookChatMessage.lead_id == lead.id,
                FacebookChatMessage.direction == "outbound",
                FacebookChatMessage.state == "ai_pending",
            )):
                previous.state = "cancelled"
            if cfg.facebook_ai_auto_reply_enabled and not lead.ai_paused:
                ai_source = messenger_ai_source(db, lead.org_id, cfg)
                recent = db.scalar(select(func.count(FacebookChatMessage.id)).where(
                    FacebookChatMessage.lead_id == lead.id,
                    FacebookChatMessage.direction == "outbound",
                    FacebookChatMessage.created_at >= utcnow() - timedelta(hours=24),
                )) or 0
                reply, use_ai = None, False
                if signal:
                    if recent < 3:
                        reply = (AI_PERMISSION_DECLINED if consent is False else
                                 reply_for_support(signal, bool(lead.specialty)))
                elif (consent is True and not lead.needs_support and
                      lead.ai_consent_state == ("accepted_team" if ai_source == "team" else "accepted")):
                    use_ai = True
                elif lead.ai_consent_state == "declined":
                    # No insistir con IA a quien ya la rechazó.
                    reply = None
                elif lead.needs_support:
                    # Conversaciones difíciles pasan a revisión humana.
                    reply = None
                elif lead.ai_consent and lead.ai_consent_state == (
                        "accepted_team" if ai_source == "team" else "accepted"):
                    use_ai = True
                elif ai_source != "disabled" and lead.ai_consent_state in (
                        "not_requested", "accepted", "accepted_team"):
                    lead.ai_consent_state = "requested_team" if ai_source == "team" else "requested"
                    lead.ai_consent = False
                    reply = permission_question(ai_source)
                elif (ai_source != "disabled" and lead.ai_consent_state in
                      ("requested", "requested_team") and lead.ai_consent_state !=
                      ("requested_team" if ai_source == "team" else "requested")):
                    lead.ai_consent_state = "requested_team" if ai_source == "team" else "requested"
                    reply = permission_question(ai_source)
                elif (ai_source != "disabled" and lead.ai_consent_state in
                      ("requested", "requested_team") and recent < 2):
                    reply = permission_question(ai_source, repeat=True)
                elif recent == 0:
                    # Sin IA configurada: orientación básica, sin enviar
                    # datos personales a un servicio externo.
                    reply = ("Hola, soy Galancito, asistente virtual de GALANT. "
                             "Puedes escribir como te salga. ¿Qué trabajo haces?")
                if use_ai and recent < 30 and ai_source != "disabled":
                    queue_locked = (db.bind.dialect.name != "postgresql" or db.scalar(
                        sql_text("SELECT pg_try_advisory_xact_lock(2075002)")))
                    queued = db.scalar(select(func.count(FacebookChatMessage.id)).where(
                        FacebookChatMessage.org_id == lead.org_id,
                        FacebookChatMessage.state == "ai_pending")) or 0
                    if queue_locked and queued < 2:
                        db.add(FacebookChatMessage(
                            org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
                            direction="outbound", state="ai_pending",
                            body="", ai_generated=True,
                        ))
                    else:
                        lead.needs_support = True
                        lead.support_reason = "Cola del asistente ocupada; requiere revisión humana"
                elif reply and recent < 30:
                    db.add(FacebookChatMessage(
                        org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
                        direction="outbound", state="pending", body=reply[:550],
                        ai_generated=False,
                    ))
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
    if lead.ai_consent and not lead.ai_paused and not lead.needs_support:
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
    for row in rows:
        req = db.scalar(select(NetworkRequirement).where(
            NetworkRequirement.id == row.requirement_id,
            NetworkRequirement.org_id == user.org_id))
        if req:
            item = {"id": row.id, "requirement_id": req.id, "title": req.title,
                    "specialty": req.specialty, "state": row.state,
                    "error": row.last_error,
                    "post_url": ("https://www.facebook.com/" + row.post_id
                                 if row.post_id and re.fullmatch(r"[0-9]+_[0-9]+", row.post_id) else None),
                    "updated_at": row.updated_at.isoformat(),
                    "attempts": row.attempts}
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
    if not cfg.facebook_ai_auto_reply_enabled:
        reply_blockers.append("Respuestas automáticas deshabilitadas en el VPS")
    if not cfg.facebook_ai_enabled:
        reply_blockers.append("Asistente de Facebook deshabilitado en el VPS")
    if ai_source == "disabled":
        reply_blockers.append("No hay un modelo de IA verificado y asignado a Messenger")
    # Token is only exposed to the sender container. Its actual permission
    # and delivery must still be verified against Meta from an external account.
    auto_reply = {
        "configured": not reply_blockers,
        "missing": reply_blockers,
        "verification": ("Comprobar enviando un mensaje desde una cuenta externa. "
                         "Las respuestas requieren consentimiento y confirmación de Meta."),
        "last_delivery": messenger_delivery["state"],
    }
    return {"automatic_enabled": cfg.facebook_autopublish_enabled,
            "manual_enabled": cfg.facebook_manual_testing_enabled,
            "messaging_enabled": cfg.facebook_messaging_enabled,
            "ai_enabled": ai_source != "disabled",
            "ai_provider": ai_source,
            "auto_reply_enabled": cfg.facebook_ai_auto_reply_enabled,
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


@router.get("/leads/{lead_id}")
def get_lead(lead_id: str, user: User = Depends(administrator),
             db: Session = Depends(get_db)):
    lead = _lead(db, user, lead_id)
    msgs = list(db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.lead_id == lead.id,
    ).order_by(FacebookChatMessage.created_at, FacebookChatMessage.id).limit(200)))
    return {"lead": _lead_view(db, lead), "messages": [_message_view(m) for m in msgs]}


@router.post("/leads/{lead_id}/refresh-profile")
def refresh_declared_profile(lead_id: str, user: User = Depends(administrator),
                             db: Session = Depends(get_db)):
    """Idempotent, local replay of recorded declarations; no outside AI call.

    Recovers short names given to an older question like "¿Cuál es tu nombre?"
    while respecting names already set by an operator or Meta.
    """
    lead = _lead(db, user, lead_id)
    messages = list(db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.lead_id == lead.id,
    ).order_by(FacebookChatMessage.created_at, FacebookChatMessage.id).limit(200)))
    previous_question = ""
    for item in messages:
        if item.direction == "outbound":
            if item.state == "sent":
                previous_question = item.body or ""
        elif item.direction == "inbound":
            apply_intake(lead, item.body or "", previous_question)
            previous_question = ""
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
    matches = ranked_needs(lead, needs, sites)
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
    lead = _lead(db, user, lead_id)
    if body.requirement_id and not db.scalar(select(NetworkRequirement.id).where(
        NetworkRequirement.id == body.requirement_id,
        NetworkRequirement.org_id == user.org_id,
    )):
        raise HTTPException(422, "La necesidad no pertenece a tu organización")
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "name":
            lead.display_name = value.strip() or "Interesado de Facebook"
        elif field == "company":
            lead.company = value.strip()
        elif field in {"specialty", "experience", "availability"}:
            setattr(lead, field, value.strip())
            if field == "specialty":
                lead.specialty_source = "manual"
        else:
            setattr(lead, field, value)
    if body.model_fields_set.intersection({"follow_up_on", "follow_up_note"}):
        lead.follow_up_by = user.id
    if body.model_fields_set.intersection({"needs_support"}) and not lead.needs_support:
        lead.support_reason = ""
    if ((body.model_fields_set.intersection({"ai_paused"}) and lead.ai_paused) or
            (body.model_fields_set.intersection({"needs_support"}) and lead.needs_support)):
        # El operador toma el control: cancelar respuestas del bot que no
        # hayan salido, sin tocar mensajes redactados por una persona.
        for pending in db.scalars(select(FacebookChatMessage).where(
            FacebookChatMessage.lead_id == lead.id,
            FacebookChatMessage.operator_id.is_(None),
            FacebookChatMessage.direction == "outbound",
            FacebookChatMessage.state.in_(["pending", "ai_pending"]),
        )):
            pending.state = "cancelled"
    lead.updated_at = utcnow()
    db.commit()
    return _lead_view(db, lead)


@router.post("/leads/{lead_id}/reply", status_code=202)
def queue_reply(lead_id: str, body: ReplyInput, user: User = Depends(administrator),
                db: Session = Depends(get_db)):
    lead = _lead(db, user, lead_id)
    if not settings().facebook_messaging_enabled:
        raise HTTPException(409, "Habilita y verifica Messenger en el servidor")
    if not _in_window(lead):
        raise HTTPException(409, "La ventana estándar de respuesta de 24 horas finalizó")
    # When a person replies, Galancito pauses to prevent competing messages.
    lead.ai_paused = True
    for old in db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.state.in_(["pending", "ai_pending"]),
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
    latest = "\n".join(m.direction + ": " + m.body[:500] for m in reversed(messages))
    supplied = ("Empresa: " + lead.company[:150] +
                "\nEspecialidad declarada: " + lead.specialty[:100] +
                "\nDotación: " + str(lead.workers or "sin informar") +
                "\nDisponibilidad: " + lead.availability[:120] +
                "\nConversación reciente:\n" + latest)
    if lead.needs_support:
        return {"draft": reply_for_support(lead.support_reason or "Solicitó ayuda",
                                           bool(lead.specialty)),
                "source": "help_first", "requires_review": True,
                "alert_admin": True}
    latest_inbound = next((m.body for m in messages if m.direction == "inbound"
                           and consent_decision(m.body) is None), "")
    facts = {"specialty": lead.specialty, "workers": lead.workers,
             "availability": lead.availability, "entity_type": lead.entity_type,
             "has_employees": lead.has_employees, "team_available": lead.team_available,
             "interest_type": lead.interest_type, "work_area": lead.work_area, "experience": lead.experience,
             "display_name": lead.display_name, "name_opt_out": lead.name_opt_out}
    previous_question = next((m.body for m in messages if m.direction == "outbound"
                              and m.state == "sent"), "")
    intake = next_intake_reply(latest_inbound, facts, previous_question)
    evidence = retrieve(db, lead.org_id, latest_inbound, "messenger") if not private_data(latest_inbound) else []
    fast = intake or quick_reply(latest_inbound, known=facts)
    if analyze(latest_inbound).intent not in {"human", "restricted", "requirements"} and not private_data(latest_inbound):
        fast = exact_answer(evidence) or fast
    if fast:
        return {"draft": fast, "source": "template", "requires_review": True}
    supplied = "Consulta actual: " + latest_inbound[:800] + "\nHechos: " + json.dumps(facts, ensure_ascii=False) + "\nReferencias: " + evidence_context(evidence)
    ai_source = messenger_ai_source(db, lead.org_id)
    consent_state = "accepted_team" if ai_source == "team" else "accepted"
    if ai_source != "disabled" and lead.ai_consent and lead.ai_consent_state == consent_state and not private_data(supplied):
        guide = _guide_for(db, lead)
        if guide:
            supplied += ("\nGuía aprobada para el oficio: " + guide.trade
                         + "\nExplicación simple: " + guide.explanation
                         + "\nDocumentación a orientar, no solicitar al inicio: "
                         + "; ".join(guide.document_guidance or []))
        else:
            supplied += "\nNo hay guía documental aprobada para esta especialidad."
        try:
            if private_data(supplied):
                raise RuntimeError("El contexto requiere revisión humana")
            drafted = infer(db, lambda: (
                orchestrated_text(db, lead.org_id, task="messenger",
                                  instructions=REPLY_INSTRUCTIONS, prompt=supplied,
                                  max_output_tokens=160)
                if ai_source == "team" else generate_text(REPLY_INSTRUCTIONS, supplied, 450)),
                org_id=lead.org_id if ai_source == "team" else None)
        except RuntimeError:
            drafted = None
        if drafted:
            drafted = grounded_reply(drafted, supplied)
        if drafted:
            return {"draft": drafted, "source": "ai", "requires_review": True}
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
    return {"draft": ("Hola, soy Galancito, asistente virtual de GALANT. No importa si escribes "
                      "con faltas: te entiendo. Si prefieres un audio, una persona lo "
                      "puede revisar. " + question),
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
