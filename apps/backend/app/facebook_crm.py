"""Facebook CRM: signed Messenger webhook, human review, explainable contractor matching.
Nothing in this module automatically awards work, creates a contractor master record,
or sends unsolicited messages. AI automation requires separate opt-in flags.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request as HTTPRequest, build_opener

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, SessionLocal
from .facebook_ai import AD_INSTRUCTIONS, REPLY_INSTRUCTIONS, generate_text
from .facebook_crm_models import FacebookLead, FacebookChatMessage, FacebookTradeGuide
from .models import Organization, User, utcnow
from .network_facebook import public_message
from .network_models import NetworkFacebookPost, NetworkRequirement
from .network_service import key
from .security import administrator

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
        "id": lead.id, "name": lead.display_name, "company": lead.company,
        "specialty": lead.specialty, "workers": lead.workers,
        "availability": lead.availability, "experience": lead.experience,
        "documents_state": lead.documents_state, "status": lead.status,
        "requirement_id": lead.requirement_id, "unread": lead.unread,
        "ai_consent": lead.ai_consent,
        "last_inbound_at": lead.last_inbound_at.isoformat() if lead.last_inbound_at else None,
        "can_reply": _in_window(lead), "analysis": _match(db, lead),
    }


def _message_view(m: FacebookChatMessage) -> dict:
    return {"id": m.id, "direction": m.direction, "state": m.state,
            "body": m.body, "ai_generated": m.ai_generated,
            "error": m.error, "created_at": m.created_at.isoformat()}


class LeadEdit(BaseModel):
    name: str = Field(default="", max_length=160)
    company: str = Field(default="", max_length=180)
    specialty: str = Field(default="", max_length=100)
    workers: int | None = Field(default=None, ge=1, le=5000)
    availability: str = Field(default="", max_length=120)
    experience: str = Field(default="", max_length=1200)
    documents_state: str = Field(default="unverified", pattern=r"^(unverified|declared|verified)$")
    status: str = Field(default="new", pattern=r"^(new|contacting|pending_review|shortlisted|archived)$")
    requirement_id: str | None = None
    ai_consent: bool = False


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
    if payload.get("object") != "page":
        return {"received": True}
    if not db.get(Organization, cfg.facebook_org_id):
        raise HTTPException(503, "Organización de Facebook no configurada")
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
            db.add(FacebookChatMessage(
                org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
                remote_id=mid, direction="inbound", state="received", body=body.strip()[:3500],
            ))
            if cfg.facebook_ai_auto_reply_enabled:
                recent = db.scalar(select(func.count(FacebookChatMessage.id)).where(
                    FacebookChatMessage.lead_id == lead.id,
                    FacebookChatMessage.direction == "outbound",
                    FacebookChatMessage.created_at >= utcnow() - timedelta(hours=24),
                ))
                if not lead.ai_consent and (recent or 0) == 0:
                    # Mensaje local: ninguna conversación se envía a un proveedor externo.
                    intro = ("Hola, soy el asistente virtual de GALANT. "
                             "Puedes escribir como te salga, sin formularios. "
                             + ("Recibimos tu audio; una persona lo revisará. "
                                if audio_received else "")
                             + "¿Qué trabajo haces: gasfitería, carpintería, pintura u otro?")
                    db.add(FacebookChatMessage(
                        org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
                        direction="outbound", state="pending", body=intro[:450],
                        ai_generated=False,
                    ))
                elif lead.ai_consent and (recent or 0) < 5 and cfg.facebook_ai_enabled and cfg.facebook_ai_api_key:
                    db.add(FacebookChatMessage(
                        org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
                        direction="outbound", state="ai_pending", body="", ai_generated=True,
                    ))
    db.commit()
    return {"received": True}


@router.get("/center")
def center(user: User = Depends(administrator), db: Session = Depends(get_db)):
    cfg = settings()
    rows = list(db.scalars(select(NetworkFacebookPost).where(
        NetworkFacebookPost.org_id == user.org_id,
        NetworkFacebookPost.state.in_(["pending", "sending", "failed", "uncertain"]),
    ).order_by(NetworkFacebookPost.created_at.desc()).limit(100)))
    ads = []
    queued_ids = {row.requirement_id for row in rows}
    # Mostrar también requerimientos seleccionados antes de habilitar el VPS.
    selected_needs = list(db.scalars(select(NetworkRequirement).where(
        NetworkRequirement.org_id == user.org_id,
        NetworkRequirement.publish_to_facebook.is_(True),
        NetworkRequirement.state == "published",
    ).order_by(NetworkRequirement.created_at.desc()).limit(100)))
    for req in selected_needs:
        if req.id not in queued_ids:
            ads.append({"id": "not-queued-" + req.id, "requirement_id": req.id,
                        "title": req.title, "specialty": req.specialty,
                        "state": "not_queued" if cfg.facebook_autopublish_enabled else "disabled",
                        "error": ("La conexión debe activarse en el VPS."
                                  if not cfg.facebook_autopublish_enabled else
                                  "La solicitud todavía no está en cola."),
                        "post_url": None})
    for row in rows:
        req = db.scalar(select(NetworkRequirement).where(
            NetworkRequirement.id == row.requirement_id,
            NetworkRequirement.org_id == user.org_id))
        if req:
            ads.append({"id": row.id, "requirement_id": req.id, "title": req.title,
                        "specialty": req.specialty, "state": row.state,
                        "error": row.last_error, "post_url": (
                            "https://www.facebook.com/" + row.post_id if row.post_id else None)})
    leads = list(db.scalars(select(FacebookLead).where(
        FacebookLead.org_id == user.org_id).order_by(
        FacebookLead.last_inbound_at.desc(), FacebookLead.id).limit(100)))
    return {"automatic_enabled": cfg.facebook_autopublish_enabled,
            "messaging_enabled": cfg.facebook_messaging_enabled,
            "ai_enabled": cfg.facebook_ai_enabled and bool(cfg.facebook_ai_api_key),
            "auto_reply_enabled": cfg.facebook_ai_auto_reply_enabled,
            "page_id": cfg.facebook_page_id,
            "pending_ads": ads, "leads": [_lead_view(db, lead) for lead in leads],
            "guides_approved": db.scalar(select(func.count(FacebookTradeGuide.id)).where(
                FacebookTradeGuide.org_id == user.org_id,
                FacebookTradeGuide.approved.is_(True))) or 0,
            "counts": {"pending_ads": len(ads), "contacts": len(leads),
                       "unread": sum(bool(lead.unread) for lead in leads),
                       "review": sum(lead.status == "pending_review" for lead in leads)}}


@router.get("/leads/{lead_id}")
def get_lead(lead_id: str, user: User = Depends(administrator),
             db: Session = Depends(get_db)):
    lead = _lead(db, user, lead_id)
    msgs = list(db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.lead_id == lead.id,
    ).order_by(FacebookChatMessage.created_at, FacebookChatMessage.id).limit(200)))
    return {"lead": _lead_view(db, lead), "messages": [_message_view(m) for m in msgs]}


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
        else:
            setattr(lead, field, value)
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
    if settings().facebook_ai_enabled and lead.ai_consent:
        guide = _guide_for(db, lead)
        if guide:
            supplied += ("\nGuía aprobada para el oficio: " + guide.trade
                         + "\nExplicación simple: " + guide.explanation
                         + "\nDocumentación a orientar, no solicitar al inicio: "
                         + "; ".join(guide.document_guidance or []))
        else:
            supplied += "\nNo hay guía documental aprobada para esta especialidad."
        try:
            drafted = generate_text(REPLY_INSTRUCTIONS, supplied, 450)
        except RuntimeError as err:
            raise HTTPException(503, str(err)) from None
        if drafted:
            return {"draft": drafted, "source": "ai", "requires_review": True}
    if not lead.specialty:
        question = "¿Qué trabajo haces? Por ejemplo, gasfitería, carpintería o pintura."
    elif lead.workers is None:
        question = "¿Trabajas solo o con cuántas personas?"
    elif not lead.availability:
        question = "¿Desde cuándo puedes empezar a trabajar?"
    else:
        question = "¿En qué comuna puedes trabajar?"
    return {"draft": ("Hola, soy el asistente virtual de GALANT. No importa si escribes "
                      "con faltas: te entiendo. Si prefieres un audio, una persona lo "
                      "puede revisar. " + question),
            "source": "template", "requires_review": True}


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
        improvement = generate_text(AD_INSTRUCTIONS, original, 1200) if settings().facebook_ai_enabled else None
    except RuntimeError as err:
        raise HTTPException(503, str(err)) from None
    return {"draft": improvement or original, "source": "ai" if improvement else "template",
            "requires_review": True}
