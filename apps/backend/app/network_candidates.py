"""Scoped, explainable candidate workspace for a single Red de Obras requirement.

All suggestions are advisory. This module never hires, replies on Messenger,
modifies a Facebook lead or changes an adjudication.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import User, utcnow
from .security import authorized_user
from .network_service import requirement_for, capacity_view, event, today, lock_org
from .network_models import (
    NetworkCandidateFollowUp, NetworkMatch, NetworkCapacity,
    NetworkFacebookPost,
)
from .facebook_crm_models import (
    FacebookLead, FacebookLeadTrade, FacebookNeedAssociation,
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
    required = trade_terms(requirement.specialty) or [requirement.specialty]
    sought = {normalized_trade(v) for v in required if v}
    declared = {normalized_trade(v) for v in trades if v}
    if not sought.intersection(declared):
        return None
    earned, known = 65, 65
    missing, reasons = [], ["Oficio compatible con la necesidad"]
    if lead.interest_type == "employment":
        missing.append("Confirmar modalidad de contratación")
    elif lead.workers is not None:
        known += 20
        if lead.workers >= requirement.workers:
            earned += 20
            reasons.append("Dotación declarada suficiente")
        else:
            reasons.append("Dotación inferior a la solicitada")
    else:
        missing.append("Dotación por confirmar")
    available = _date(lead.availability)
    if available:
        known += 15
        if available <= requirement.start_date:
            earned += 15
            reasons.append("Disponibilidad declarada compatible")
        else:
            reasons.append("Fecha de disponibilidad por coordinar")
    else:
        missing.append("Disponibilidad por confirmar")
    return {
        "compatibility": round(100 * earned / known),
        "data_coverage": round(100 * known / (80 if lead.interest_type == "employment" else 100)),
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
