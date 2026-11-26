"""Administrator-only Messenger simulation using the real inbound and reply flow."""
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .db import Base, get_db
from .facebook_chat_worker import process_chat_next
from .facebook_crm import ingest_facebook_payload
from .facebook_crm_models import FacebookChatMessage, FacebookLead, FacebookLeadTrade
from .facebook_worksite_reply import published_notices
from .galancito_contact_profile import contact_profile
from .galancito_intake import UNKNOWN_NAMES
from .galancito_knowledge_models import AssistantRun
from .galancito_triage import analyze
from .max_power_messenger import objective_checks
from .models import Organization, User, utcnow
from .security import administrator

router = APIRouter(prefix="/api/v1/admin/ai/messenger-simulator", tags=["Simulador Messenger"])
PAGE = "190000000000001"
SENDER = "190000000000002"
MAX_TURNS = 24
LIFETIME = timedelta(hours=1)
MODELS = (FacebookLead, FacebookChatMessage, FacebookLeadTrade)


class TurnInput(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    mode: Literal["rules", "local"] = "rules"
    state: str | None = Field(default=None, max_length=180000)


def _key(secret):
    # A simulation token cannot authenticate to the ordinary GALANT API.
    return sha256(("galant-messenger-simulation-v1:" + secret).encode()).digest()


def _decode(token, key, user, mode):
    if token is None:
        return {"turn": 0, "rows": {}}
    try:
        state = jwt.decode(token, key, algorithms=["HS256"], options={"require": ["exp", "sub", "org", "mode"]})
    except jwt.InvalidTokenError:
        raise HTTPException(400, "La conversación de prueba venció o cambió. Inicia una nueva.") from None
    if state["sub"] != user.id or state["org"] != user.org_id or state["mode"] != mode:
        raise HTTPException(403, "La conversación de prueba pertenece a otra sesión")
    return state


def _dump(model, row):
    values = {}
    for column in model.__table__.columns:
        value = getattr(row, column.key)
        values[column.key] = value.isoformat() if isinstance(value, datetime) else value
    return values


def _restore(model, record):
    values = {}
    for column in model.__table__.columns:
        value = record.get(column.key)
        values[column.key] = datetime.fromisoformat(value) if isinstance(column.type, DateTime) and value else value
    return model(**values)


def _profile(db, lead):
    if not lead:
        return {}, {}
    view = contact_profile(lead)
    trades = list(db.scalars(select(FacebookLeadTrade.trade).where(
        FacebookLeadTrade.lead_id == lead.id, FacebookLeadTrade.active.is_(True)
    ).order_by(FacebookLeadTrade.trade)))
    fields = {
        field: getattr(lead, field) for field in (
            "display_name", "specialty", "interest_type", "entity_type", "team_available", "workers",
            "employee_count", "has_employees", "experience", "work_communes", "availability",
            "contact_phone", "contact_email",
        )
    }
    if fields["display_name"] in UNKNOWN_NAMES:
        fields["display_name"] = None
    declared = {field: data["value"] for field, data in view["declared_context"].items()}
    return {**fields, "trades": trades, **declared}, view["field_states"]


@router.get("")
def configuration(user: User = Depends(administrator)):
    cfg = settings()
    return {"local_model": cfg.galancito_local_model if cfg.galancito_local_ai_enabled else None,
            "max_turns": MAX_TURNS}


@router.post("/turn")
def turn(body: TurnInput, response: Response, user: User = Depends(administrator), database: Session = Depends(get_db)):
    original = settings()
    if body.mode == "local" and not original.galancito_local_ai_enabled:
        raise HTTPException(409, "El modelo local no está habilitado en esta instalación")
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "Escribe un mensaje para probar")
    key = _key(original.app_secret)
    state = _decode(body.state, key, user, body.mode)
    if state["turn"] >= MAX_TURNS:
        raise HTTPException(409, "Esta conversación de prueba llegó a su límite. Inicia una nueva.")

    notices = (published_notices(database, user.org_id, original.facebook_page_id)
               if original.facebook_page_id and original.facebook_org_id == user.org_id else [])

    cfg = original.model_copy(update={
        "facebook_messaging_enabled": True, "facebook_org_id": user.org_id,
        "facebook_page_id": PAGE, "facebook_page_token": "isolation-only",
        "facebook_ai_enabled": True,
        "facebook_ai_provider": "ollama", "facebook_ai_api_key": "",
        "galancito_local_ai_enabled": body.mode == "local",
    })
    engine = create_engine("sqlite://")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    remote_id = "simulation-" + uuid4().hex
    try:
        Base.metadata.create_all(engine)
        with sessions() as db:
            db.add(Organization(id=user.org_id, name="Organización de prueba"))
            db.flush()
            for model in MODELS:
                db.add_all(_restore(model, row) for row in state["rows"].get(model.__tablename__, []))
                db.flush()
            lead = db.scalar(select(FacebookLead))
            if lead is None and body.mode == "local":
                # The operator explicitly chose local inference for this isolated conversation.
                lead = FacebookLead(org_id=user.org_id, page_id=PAGE, psid=SENDER,
                                    ai_consent=True, ai_consent_state="accepted", ai_consent_provider="ollama")
                db.add(lead)
                db.flush()
            before, _ = _profile(db, lead)
            history = [{"role": item.direction, "text": item.body} for item in db.scalars(
                select(FacebookChatMessage).order_by(FacebookChatMessage.created_at, FacebookChatMessage.id))]
            ingest_facebook_payload(db, {
                "object": "page", "entry": [{"id": PAGE, "messaging": [
                    {"sender": {"id": SENDER}, "message": {"mid": remote_id, "text": message}}
                ]}],
            }, cfg, notices=notices)
        process_chat_next(sessions, simulation_config=cfg, notices=notices)
        with sessions() as db:
            lead = db.scalar(select(FacebookLead))
            run = db.scalar(select(AssistantRun))
            outbound_id = (run.timings or {}).get("outbound_message_id") if run else None
            outbound = db.get(FacebookChatMessage, outbound_id) if outbound_id else None
            reply = outbound.body if outbound and outbound.state == "sent" else None
            fields, statuses = _profile(db, lead)
            known = {field for field, value in fields.items() if value not in (None, "", "unknown", [])}
            checks = objective_checks({"question": message, "history": history}, reply, known_fields=known) if reply else None
            rows = {model.__tablename__: [_dump(model, row) for row in db.scalars(select(model))] for model in MODELS}
            response.headers["Cache-Control"] = "private, no-store"
            return {
                "state": jwt.encode({"sub": user.id, "org": user.org_id, "mode": body.mode, "exp": utcnow() + LIFETIME,
                                     "turn": state["turn"] + 1, "rows": rows}, key, algorithm="HS256"),
                "reply": reply,
                "source": run.source if run else None,
                "intent": run.intent if run and (run.timings or {}).get("contextual_turn") else analyze(message).intent,
                "elapsed_ms": run.elapsed_ms if run else None,
                "profile": fields,
                "field_states": statuses,
                "changed_fields": [field for field, value in fields.items() if value != before.get(field)
                                   and (field in before or value not in (None, "", "unknown", []))],
                "checks": checks,
                "review_required": lead.needs_support if lead else False,
            }
    finally:
        engine.dispose()
