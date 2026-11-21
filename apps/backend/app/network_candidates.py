"""Scoped, explainable candidate workspace for a single Red de Obras requirement.

All suggestions are advisory. This module never hires, replies on Messenger,
modifies a Facebook lead or changes an adjudication.
"""
from __future__ import annotations

from datetime import date, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User, utcnow
from .security import authorized_user
from .network_service import requirement_for, capacity_view, event, today, lock_org
from .network_models import (
    NetworkCandidateFollowUp, NetworkMatch, NetworkCapacity,
    NetworkFacebookPost,
)
from .facebook_crm_models import (
    FacebookLead, FacebookLeadTrade, FacebookNeedAssociation, FacebookChatMessage,
)
from .facebook_publication_models import FacebookPostComment
from .galancito_contact_profile import contact_profile
from .galancito_links import canonical_trade, trade_terms
from .galancito_triage import plain

router = APIRouter(prefix="/api/v1/network", tags=["Red de Obras - candidatos"])

STAGES = {"suggested", "interested", "contacted", "evaluating", "selected", "discarded"}


def normalized_trade(value: str) -> str:
    return plain(canonical_trade(value or ""))


def _date(value: str | None):
    try:
        return date.fromisoformat(value or "")
    except (TypeError, ValueError):
        return None


def _fit(lead, trades: list[str], requirement):
    """Fixed weights: missing evidence never becomes a perfect 100% match."""
    required = trade_terms(requirement.specialty) or [requirement.specialty]
    sought = {normalized_trade(v) for v in required if v}
    declared = {normalized_trade(v) for v in trades if v}
    if not sought.intersection(declared):
        return None
    # The sum of these independently verifiable criteria is exactly 100.
    score, coverage = 60, 60
    missing, reasons = [], ["Oficio relacionado con la necesidad"]
    workers = getattr(lead, "workers", None)
    if workers is not None:
        coverage += 20
        if workers >= requirement.workers:
            score += 20
            reasons.append("Cantidad de personas declarada compatible")
        else:
            reasons.append("Debe confirmar si puede cubrir toda la dotación")
    else:
        missing.append("Cantidad de personas por confirmar")
    available = _date(lead.availability)
    if available:
        coverage += 20
        if available <= requirement.start_date:
            score += 20
            reasons.append("Fecha de disponibilidad compatible")
        else:
            reasons.append("Fecha posterior al inicio solicitado")
    else:
        # 'mañana' or 'la próxima semana' is a declaration, not an exact
        # calendar date. It must not score as verified availability.
        missing.append("Confirmar fecha exacta de disponibilidad")
    return {
        "compatibility": score,
        "data_coverage": coverage,
        "reasons": reasons,
        "missing": missing,
    }


def _follow_up(record):
    return {
        "stage": record.stage if record else "suggested",
        "note": record.note if record else "",
        "follow_up_on": record.follow_up_on.isoformat() if record and record.follow_up_on else None,
        "version": record.version if record else 0,
        "updated_at": record.updated_at.isoformat() if record else None,
    }


@router.get("/requirements/{requirement_id}/candidates")
def requirement_candidates(
    requirement_id: str,
    limit: int = Query(80, ge=1, le=150),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    # The existing authorization boundary limits detailed information to the
    # corresponding site. Never use the admin-only Facebook CRM endpoints.
    requirement = requirement_for(db, user, requirement_id, detail=True)
    leads = list(db.scalars(
        select(FacebookLead)
        .where(FacebookLead.org_id == user.org_id)
        .order_by(FacebookLead.updated_at.desc(), FacebookLead.id)
        .limit(1501)
    ))
    limited_source = len(leads) > 1500
    leads = leads[:1500]
    # Explicit associations and saved follow-ups must remain visible even
    # when a very active organization has more than 1500 recent contacts.
    pinned_ids = set(db.scalars(
        select(FacebookNeedAssociation.lead_id).where(
            FacebookNeedAssociation.org_id == user.org_id,
            FacebookNeedAssociation.requirement_id == requirement.id,
            FacebookNeedAssociation.state == "linked",
        )
    ))
    pinned_ids.update(db.scalars(
        select(NetworkCandidateFollowUp.lead_id).where(
            NetworkCandidateFollowUp.org_id == user.org_id,
            NetworkCandidateFollowUp.requirement_id == requirement.id,
        )
    ))
    pinned_ids.update(db.scalars(
        select(FacebookLead.id).where(
            FacebookLead.org_id == user.org_id,
            FacebookLead.requirement_id == requirement.id,
        )
    ))
    recent_ids = {lead.id for lead in leads}
    missing_ids = pinned_ids - recent_ids
    if missing_ids:
        leads.extend(db.scalars(select(FacebookLead).where(
            FacebookLead.org_id == user.org_id,
            FacebookLead.id.in_(missing_ids),
        )).all())
    ids = [lead.id for lead in leads]
    trades_by_id: dict[str, list[str]] = {id: [] for id in ids}
    if ids:
        for trade in db.scalars(
            select(FacebookLeadTrade).where(
                FacebookLeadTrade.org_id == user.org_id,
                FacebookLeadTrade.lead_id.in_(ids),
                FacebookLeadTrade.active.is_(True),
            )
        ):
            trades_by_id[trade.lead_id].append(trade.trade)
    linked_ids = set(db.scalars(
        select(FacebookNeedAssociation.lead_id).where(
            FacebookNeedAssociation.org_id == user.org_id,
            FacebookNeedAssociation.requirement_id == requirement.id,
            FacebookNeedAssociation.state == "linked",
        )
    ))
    records = {row.lead_id: row for row in db.scalars(
        select(NetworkCandidateFollowUp).where(
            NetworkCandidateFollowUp.org_id == user.org_id,
            NetworkCandidateFollowUp.requirement_id == requirement.id,
        )
    )}
    suggestions = []
    for lead in leads:
        trades = list(dict.fromkeys([*trades_by_id[lead.id], *([lead.specialty] if lead.specialty else [])]))
        fit = _fit(lead, trades, requirement)
        linked = lead.id in linked_ids or lead.requirement_id == requirement.id
        tracked = records.get(lead.id)
        if not fit and not linked and not tracked:
            continue
        if fit is None:
            fit = {
                "compatibility": None, "data_coverage": 0,
                "reasons": ["Relación previa registrada; oficio pendiente de confirmar"],
                "missing": ["Confirmar oficio y compatibilidad"],
            }
        profile = contact_profile(lead)
        suggestions.append({
            "id": lead.id,
            "source": "messenger",
            "name": lead.display_name or "Contacto sin nombre",
            "company": lead.company or "",
            "trades": trades,
            "type": lead.interest_type,
            "entity_type": lead.entity_type,
            "workers": lead.workers,
            "availability": lead.availability or "",
            "work_area": lead.work_area or "",
            "experience": (lead.experience or "")[:600],
            "phone": lead.contact_phone or "",
            "email": lead.contact_email or "",
            "phone_opt_out": lead.phone_opt_out,
            "email_opt_out": lead.email_opt_out,
            "contact_source": {
                "phone": lead.phone_source or "",
                "email": lead.email_source or "",
            },
            "contact_action": (
                "Se puede coordinar por teléfono o correo."
                if lead.contact_phone or lead.contact_email else
                "Aún falta teléfono o correo. Conversar primero por Messenger y, si se acuerda coordinar, ofrecer compartir el medio que prefiera."
                if not (lead.phone_opt_out and lead.email_opt_out) else
                "Prefirió no facilitar teléfono ni correo; continuar por Messenger si está permitido."
            ),
            "last_inbound_at": lead.last_inbound_at.isoformat() if lead.last_inbound_at else None,
            "profile": {
                "summary": profile["summary"],
                "percent": profile["percent"],
                "missing": profile["missing"],
            },
            "linked": linked,
            "fit": fit,
            "tracking": _follow_up(tracked),
        })
    suggestions.sort(key=lambda row: (
        row["tracking"]["stage"] == "suggested",
        not row["linked"],
        -(row["fit"]["compatibility"] or 0),
        -(row["fit"]["data_coverage"] or 0),
        row["name"].lower(),
    ))

    matches = list(db.scalars(
        select(NetworkMatch).join(
            NetworkCapacity, NetworkMatch.capacity_id == NetworkCapacity.id
        ).where(
            NetworkMatch.org_id == user.org_id,
            NetworkMatch.requirement_id == requirement.id,
            NetworkMatch.active.is_(True),
            NetworkCapacity.expires_on >= today(),
        ).order_by(NetworkMatch.score.desc()).limit(60)
    ))
    capacities = []
    for match in matches:
        cap = db.get(NetworkCapacity, match.capacity_id)
        if cap:
            capacities.append({
                "id": match.id, "score": match.score,
                "reasons": match.reasons,
                "capacity": capacity_view(db, user, cap),
            })
    post_ids = list(db.scalars(
        select(NetworkFacebookPost.id).where(
            NetworkFacebookPost.org_id == user.org_id,
            NetworkFacebookPost.requirement_id == requirement.id,
        )
    ))
    comments = []
    if post_ids:
        for comment in db.scalars(
            select(FacebookPostComment).where(
                FacebookPostComment.org_id == user.org_id,
                FacebookPostComment.post_record_id.in_(post_ids),
                FacebookPostComment.is_deleted.is_(False),
                FacebookPostComment.is_hidden.is_(False),
                FacebookPostComment.classification.in_(["interested", "question", "human_review"]),
            ).order_by(FacebookPostComment.posted_at.desc()).limit(60)
        ):
            comments.append({
                "id": comment.id,
                "name": comment.author_name or "Persona en Facebook",
                "picture_url": comment.author_picture_url or None,
                "body": comment.body[:650],
                "classification": comment.classification,
                "review_state": comment.review_state,
                "posted_at": comment.posted_at.isoformat(),
                # No identity link: a public commenter is not automatically a lead.
                "identity_confirmed": False,
            })
    title_trades = {normalized_trade(t) for t in trade_terms(requirement.title)}
    specialty_trades = {normalized_trade(t) for t in (
        trade_terms(requirement.specialty) or [requirement.specialty]
    )}
    warning = (
        "El título parece indicar otro oficio; revisa la especialidad antes de evaluar coincidencias."
        if title_trades and not title_trades.intersection(specialty_trades) else None
    )
    return {
        "requirement_id": requirement.id,
        "candidates": suggestions[:limit],
        "candidate_total": len(suggestions),
        "source_limited": limited_source,
        "capacities": capacities,
        "comments": comments,
        "classification_warning": warning,
        "summary": {
            "suggested": sum(c["tracking"]["stage"] == "suggested" for c in suggestions),
            "interested": sum(c["tracking"]["stage"] == "interested" for c in suggestions),
            "contacted": sum(c["tracking"]["stage"] == "contacted" for c in suggestions),
            "evaluating": sum(c["tracking"]["stage"] == "evaluating" for c in suggestions),
            "selected": sum(c["tracking"]["stage"] == "selected" for c in suggestions),
            "discarded": sum(c["tracking"]["stage"] == "discarded" for c in suggestions),
        },
    }


class CandidateFollowUpInput(BaseModel):
    stage: Literal["suggested", "interested", "contacted", "evaluating", "selected", "discarded"]
    note: str = Field(default="", max_length=2000)
    follow_up_on: date | None = None
    version: int = Field(ge=0)


@router.put("/requirements/{requirement_id}/candidates/{lead_id}/follow-up")
def update_candidate_follow_up(
    requirement_id: str,
    lead_id: str,
    body: CandidateFollowUpInput,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    requirement = requirement_for(db, user, requirement_id, detail=True)
    if not requirement or user.role not in {"admin", "resident", "supervisor", "analyst"}:
        raise HTTPException(403, "Sin permisos de seguimiento")
    lead = db.scalar(select(FacebookLead).where(
        FacebookLead.id == lead_id, FacebookLead.org_id == user.org_id
    ))
    if not lead:
        raise HTTPException(404, "Contacto no encontrado")
    # Serialize first-time creation as well as updates. Without this lock two
    # reviewers saving a previously untracked profile could race to a 500.
    lock_org(db, user)
    record = db.scalar(select(NetworkCandidateFollowUp).where(
        NetworkCandidateFollowUp.org_id == user.org_id,
        NetworkCandidateFollowUp.requirement_id == requirement.id,
        NetworkCandidateFollowUp.lead_id == lead.id,
    ).with_for_update())
    if record is None:
        declared_trades = list(db.scalars(
            select(FacebookLeadTrade.trade).where(
                FacebookLeadTrade.org_id == user.org_id,
                FacebookLeadTrade.lead_id == lead.id,
                FacebookLeadTrade.active.is_(True),
            )
        ))
        if lead.specialty:
            declared_trades.append(lead.specialty)
        related = bool(db.scalar(select(FacebookNeedAssociation.id).where(
            FacebookNeedAssociation.org_id == user.org_id,
            FacebookNeedAssociation.lead_id == lead.id,
            FacebookNeedAssociation.requirement_id == requirement.id,
            FacebookNeedAssociation.state == "linked",
        ))) or lead.requirement_id == requirement.id
        if not related and _fit(lead, declared_trades, requirement) is None:
            raise HTTPException(403, "El contacto no está relacionado con esta necesidad")
    version = record.version if record else 0
    if body.version != version:
        raise HTTPException(409, "Esta ficha se actualizó en otra sesión. Recarga antes de guardar.")
    before = _follow_up(record)
    if record is None:
        record = NetworkCandidateFollowUp(
            org_id=user.org_id, requirement_id=requirement.id,
            lead_id=lead.id, created_by=user.id,
        )
        db.add(record)
    record.stage = body.stage
    record.note = body.note.strip()
    record.follow_up_on = body.follow_up_on
    record.updated_by = user.id
    record.updated_at = utcnow()
    record.version = version + 1
    db.flush()
    result = _follow_up(record)
    event(db, user, "candidate_follow_up", requirement.id,
          {"lead_id": lead.id, "candidate_stage": before["stage"],
           "candidate_follow_up_on": before["follow_up_on"], "tracking": before},
          {"lead_id": lead.id, "candidate_stage": result["stage"],
           "candidate_follow_up_on": result["follow_up_on"], "tracking": result},
          reason="Seguimiento del candidato actualizado")
    db.commit()
    return result


def _scoped_chat_lead(db: Session, user: User, requirement_id: str, lead_id: str):
    """Authorize BOTH the worksite and the candidate relationship on every call."""
    requirement = requirement_for(db, user, requirement_id, detail=True)
    lead = db.scalar(select(FacebookLead).where(
        FacebookLead.id == lead_id, FacebookLead.org_id == user.org_id
    ))
    if not lead:
        raise HTTPException(404, "Contacto no encontrado")
    linked = lead.requirement_id == requirement.id or bool(db.scalar(
        select(FacebookNeedAssociation.id).where(
            FacebookNeedAssociation.org_id == user.org_id,
            FacebookNeedAssociation.requirement_id == requirement.id,
            FacebookNeedAssociation.lead_id == lead.id,
            FacebookNeedAssociation.state == "linked",
        )
    ))
    tracked = bool(db.scalar(select(NetworkCandidateFollowUp.id).where(
        NetworkCandidateFollowUp.org_id == user.org_id,
        NetworkCandidateFollowUp.requirement_id == requirement.id,
        NetworkCandidateFollowUp.lead_id == lead.id,
    )))
    if not linked and not tracked:
        trades = list(db.scalars(select(FacebookLeadTrade.trade).where(
            FacebookLeadTrade.org_id == user.org_id,
            FacebookLeadTrade.lead_id == lead.id,
            FacebookLeadTrade.active.is_(True),
        )))
        if lead.specialty:
            trades.append(lead.specialty)
        if _fit(lead, trades, requirement) is None:
            raise HTTPException(403, "Esta persona no está relacionada con la solicitud")
    return lead


def _can_message(lead: FacebookLead) -> bool:
    last = lead.last_inbound_at
    if not last:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    config = settings()
    return (
        config.facebook_messaging_enabled
        and config.facebook_page_id == lead.page_id
        and config.facebook_org_id == lead.org_id
        and last >= utcnow() - timedelta(hours=24)
    )


def _chat_message(row: FacebookChatMessage) -> dict:
    return {
        "id": row.id,
        "direction": row.direction,
        "state": row.state,
        "body": row.body,
        "automated": row.direction == "outbound" and row.operator_id is None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat() if row.updated_at else row.created_at.isoformat(),
        "error": row.error if row.state in {"failed", "uncertain"} else None,
    }


@router.get("/requirements/{requirement_id}/candidates/{lead_id}/chat")
def candidate_chat(
    requirement_id: str,
    lead_id: str,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lead = _scoped_chat_lead(db, user, requirement_id, lead_id)
    recent = list(db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.lead_id == lead.id,
    ).order_by(FacebookChatMessage.created_at.desc(), FacebookChatMessage.id.desc()).limit(120)))
    return {
        "lead_id": lead.id,
        "name": lead.display_name,
        "messages": [_chat_message(row) for row in reversed(recent)],
        "can_reply": _can_message(lead),
        "reply_notice": (
            "Puedes responder por Messenger. Confirma el envío en el estado del mensaje."
            if _can_message(lead) else
            "Mensajería no habilitada para responder o la ventana de 24 horas finalizó. Puedes revisar el historial."
        ),
    }


class ResidentReply(BaseModel):
    message: str = Field(min_length=1, max_length=550)


@router.post("/requirements/{requirement_id}/candidates/{lead_id}/chat", status_code=202)
def candidate_reply(
    requirement_id: str,
    lead_id: str,
    body: ResidentReply,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    if user.role not in {"admin", "resident"}:
        raise HTTPException(403, "No tienes permiso para escribir por Messenger")
    lead = _scoped_chat_lead(db, user, requirement_id, lead_id)
    # Prevent concurrent manual and AI pending drafts for the same conversation.
    db.refresh(lead, with_for_update=True)
    if not _can_message(lead):
        raise HTTPException(409, "Messenger no permite responder ahora: verifica la conexión y la ventana de 24 horas")
    message_text = body.message.strip()
    if not message_text:
        raise HTTPException(422, "Escribe un mensaje")
    for earlier in db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.state == "pending",
        FacebookChatMessage.operator_id == user.id,
        FacebookChatMessage.created_at >= utcnow() - timedelta(seconds=20),
    )):
        if earlier.body.strip() == message_text:
            raise HTTPException(409, "Este mensaje ya está en cola de envío")
    for pending in db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.operator_id.is_(None),
        FacebookChatMessage.state.in_(["pending", "ai_pending", "drafting"]),
    )):
        pending.state = "cancelled"
    message = FacebookChatMessage(
        org_id=user.org_id, lead_id=lead.id, page_id=lead.page_id,
        direction="outbound", state="pending", operator_id=user.id,
        body=message_text,
    )
    db.add(message)
    db.commit()
    return _chat_message(message)
