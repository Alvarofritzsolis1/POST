"""Evidence-backed human reviews for real GALANT responses.

Admins can audit only a response whose source is still accessible:
a confirmed Messenger delivery or their own opt-in saved internal chat.
No text is stored in the review record, exported to third parties or used for
training. Scores describe the REVIEWED SAMPLE, not all production traffic.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ai_quality_models import AIResponseReview
from .db import get_db
from .facebook_crm_models import FacebookChatMessage
from .galancito_knowledge_models import AssistantRun, InternalConversation
from .models import AuditEvent, User, utcnow
from .galancito_memory import aware
from .security import administrator

router = APIRouter(prefix="/api/v1/admin/ai/audit", tags=["Auditoría humana de IA"])

RUBRIC_VERSION = 1
MIN_REVIEWED_SAMPLE = 30
CRITERIA = {
    "messenger": ("understanding", "profile", "context", "naturalness", "safety", "helpfulness"),
    "general": ("accuracy", "grounding", "context", "reasoning", "safety", "helpfulness"),
}


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=36, max_length=36)
    ratings: dict[str, StrictBool | None]
    source_reviewed: Literal[True]  # human attests reading the linked real exchange


def observed_run(db: Session, user: User, run_id: str) -> AssistantRun:
    record = db.scalar(select(AssistantRun).where(
        AssistantRun.id == run_id, AssistantRun.org_id == user.org_id,
    ))
    if not record or record.channel not in {"messenger", "galant_internal"}:
        raise HTTPException(404, "Interacción de producción no encontrada")
    if aware(record.created_at) < utcnow() - timedelta(days=30):
        raise HTTPException(409, "La interacción está fuera de la ventana de revisión")
    return record


def messenger_evidence(db: Session, user: User, message_id: str) -> dict | None:
    """Verify a delivered AI message against the real on-platform conversation.

    Works for existing Messenger chats recorded before telemetry was linked.
    Never invent a run, response time, provider or inferred ground truth.
    """
    if not isinstance(message_id, str) or len(message_id) != 36:
        return None
    message = db.scalar(select(FacebookChatMessage).where(
        FacebookChatMessage.id == message_id,
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.ai_generated.is_(True),
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.state == "sent",
    ))
    if (message is None or not message.body.strip()
            or aware(message.created_at) < utcnow() - timedelta(days=30)):
        return None
    recent = list(db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == user.org_id,
        FacebookChatMessage.lead_id == message.lead_id,
        FacebookChatMessage.id != message.id,
        FacebookChatMessage.direction.in_(("inbound", "outbound")),
        FacebookChatMessage.created_at <= message.updated_at,
    ).order_by(FacebookChatMessage.created_at.desc()).limit(12)))
    conversation = list(reversed(recent))
    inbound = [item for item in conversation if item.direction == "inbound" and item.body.strip()]
    if not inbound:
        return None
    return {
        "channel": "messenger", "kind": "messenger_message",
        "source_id": message.id, "source_at": message.created_at,
        "question": inbound[-1].body[:800],
        "answer": message.body[:1800],
        "history": [{"role": item.direction, "text": item.body[:650]}
                    for item in conversation if item.body.strip()],
    }


def linked_evidence(db: Session, user: User, record: AssistantRun) -> dict | None:
    """Resolve evidence for a run while preserving opt-in internal history."""
    if record.channel == "messenger":
        return messenger_evidence(db, user, (record.timings or {}).get("outbound_message_id"))

    # Never read another user's opt-in private internal conversation,
    # even when requesting a review as an organization administrator.
    if record.user_id != user.id:
        return None
    conversations = db.scalars(select(InternalConversation).where(
        InternalConversation.org_id == user.org_id,
        InternalConversation.user_id == user.id,
        InternalConversation.expires_at >= utcnow(),
    ).order_by(InternalConversation.updated_at.desc()).limit(20))
    for conversation in conversations:
        for index, turn in enumerate(conversation.turns or []):
            if turn.get("role") != "assistant" or turn.get("run_id") != record.id:
                continue
            question = str(turn.get("question") or (
                conversation.turns[index - 1].get("text", "") if index else ""
            ))
            answer = str(turn.get("text", ""))
            if question.strip() and answer.strip():
                return {
                    "channel": "general", "kind": "saved_internal_chat",
                    "source_id": record.id, "source_at": record.created_at,
                    "question": question[:800], "answer": answer[:1600],
                    "history": [
                        {"role": str(item.get("role", "")), "text": str(item.get("text", ""))[:650]}
                        for item in (conversation.turns or [])[max(0, index - 10):index]
                        if item.get("role") in {"user", "assistant"}
                    ],
                }
    return None


@router.get("/queue")
def review_queue(channel: Literal["messenger", "general"] = Query(default="messenger"),
                 user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Review cases linked to actual chat text; never expose text in list."""
    since = utcnow() - timedelta(days=30)
    items = []
    if channel == "messenger":
        messages = list(db.scalars(select(FacebookChatMessage).where(
            FacebookChatMessage.org_id == user.org_id,
            FacebookChatMessage.ai_generated.is_(True),
            FacebookChatMessage.direction == "outbound",
            FacebookChatMessage.state == "sent",
            FacebookChatMessage.created_at >= since,
        ).order_by(FacebookChatMessage.created_at.desc()).limit(250)))
        reviewed = set(db.scalars(select(AIResponseReview.evidence_id).where(
            AIResponseReview.org_id == user.org_id,
            AIResponseReview.channel == "messenger",
            AIResponseReview.evidence_kind == "messenger_message",
            AIResponseReview.evidence_id.in_([row.id for row in messages]),
        ))) if messages else set()
        for message in messages:
            if message.id in reviewed or messenger_evidence(db, user, message.id) is None:
                continue
            items.append({"run_id": message.id, "created_at": message.created_at,
                          "channel": "messenger", "source": "Mensaje IA entregado"})
            if len(items) >= 40:
                break
    else:
        recent = list(db.scalars(select(AssistantRun).where(
            AssistantRun.org_id == user.org_id, AssistantRun.channel == "galant_internal",
            AssistantRun.created_at >= since,
            AssistantRun.user_id == user.id,
        ).order_by(AssistantRun.created_at.desc()).limit(200)))
        reviewed = set(db.scalars(select(AIResponseReview.evidence_id).where(
            AIResponseReview.org_id == user.org_id,
            AIResponseReview.channel == "general",
            AIResponseReview.evidence_kind == "saved_internal_chat",
            AIResponseReview.evidence_id.in_([row.id for row in recent]),
        ))) if recent else set()
        for record in recent:
            if record.id in reviewed or linked_evidence(db, user, record) is None:
                continue
            items.append({"run_id": record.id, "created_at": record.created_at,
                          "channel": "general", "source": record.source})
            if len(items) >= 40:
                break
    return {"channel": channel, "rubric_version": RUBRIC_VERSION,
            "criteria": list(CRITERIA[channel]), "items": items}


def _audit_source(db: Session, user: User, source_id: str):
    """Direct Messenger message IDs and AssistantRun IDs; no guessed linkage."""
    run = db.scalar(select(AssistantRun).where(
        AssistantRun.id == source_id, AssistantRun.org_id == user.org_id,
        AssistantRun.channel.in_(("messenger", "galant_internal")),
    ))
    if run is not None:
        if aware(run.created_at) < utcnow() - timedelta(days=30):
            raise HTTPException(409, "La interacción está fuera de la ventana de revisión")
        evidence = linked_evidence(db, user, run)
    else:
        evidence = messenger_evidence(db, user, source_id)
    if evidence is None:
        raise HTTPException(404, "No hay intercambio original verificable y autorizado")
    return run, evidence


@router.get("/cases/{run_id}")
def review_case(run_id: str, user: User = Depends(administrator),
                db: Session = Depends(get_db)):
    record, evidence = _audit_source(db, user, run_id)
    channel = evidence["channel"]
    return {"run_id": run_id, "created_at": evidence["source_at"],
            "rubric_version": RUBRIC_VERSION, "criteria": list(CRITERIA[channel]),
            "origin": "conversacion_real", "trace_available": record is not None,
            **{key: evidence[key] for key in ("channel", "question", "answer", "history")}}


@router.post("/reviews", status_code=201)
def save_review(body: ReviewInput, user: User = Depends(administrator),
                db: Session = Depends(get_db)):
    record, evidence = _audit_source(db, user, body.run_id)
    channel = evidence["channel"]
    if set(body.ratings) != set(CRITERIA[channel]):
        raise HTTPException(422, "Evalúa todos los criterios de esta versión sin agregar otros")
    if all(value is None for value in body.ratings.values()):
        raise HTTPException(422, "Revisa al menos un criterio; los demás pueden ser no comprobables")
    if db.scalar(select(AIResponseReview.id).where(
        AIResponseReview.org_id == user.org_id,
        AIResponseReview.channel == channel,
        AIResponseReview.evidence_kind == evidence["kind"],
        AIResponseReview.evidence_id == evidence["source_id"],
    )):
        raise HTTPException(409, "La interacción ya fue auditada; no se admiten notas duplicadas")
    review = AIResponseReview(
        org_id=user.org_id, run_id=record.id if record else None,
        reviewer_id=user.id, channel=channel,
        rubric_version=RUBRIC_VERSION, evidence_kind=evidence["kind"],
        evidence_id=evidence["source_id"], source_at=evidence["source_at"],
        ratings=dict(body.ratings),
    )
    db.add(review)
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="ai.response_review.created",
                      resource_id=evidence["source_id"]))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "La interacción ya fue auditada") from None
    return {"saved": True, "review_id": review.id, "source": evidence["kind"],
            "rubric_version": RUBRIC_VERSION}


def reviewed_sample(db: Session, org_id: str, channel: Literal["messenger", "general"],
                    since) -> dict:
    """Exactly observed and human-reviewed subset; no extrapolated population grade."""
    rows = list(db.scalars(select(AIResponseReview).where(
        AIResponseReview.org_id == org_id,
        AIResponseReview.channel == channel,
        AIResponseReview.source_at >= since,
        AIResponseReview.rubric_version == RUBRIC_VERSION,
    )))
    count = len(rows)
    criteria = CRITERIA[channel]
    assessed = {name: sum(row.ratings.get(name) is not None for row in rows) for name in criteria}
    per_dimension = {
        name: (round(100 * sum(row.ratings.get(name) is True for row in rows) /
                     assessed[name], 1) if assessed[name] else None)
        for name in criteria
    }
    # Unknown/no-evidence is neither correct nor incorrect.
    failures = {name: sum(row.ratings.get(name) is False for row in rows) for name in criteria}
    score = (round(sum(per_dimension.values()) / len(criteria), 1)
             if all(n >= MIN_REVIEWED_SAMPLE for n in assessed.values()) else None)
    return {"quality_score": score, "reviewed_cases": count,
            "minimum_cases": MIN_REVIEWED_SAMPLE, "rubric_version": RUBRIC_VERSION,
            "dimension_scores": per_dimension,
            "dimension_sample_counts": assessed,
            "failed_review_counts": failures,
            "quality_source": ("human_reviewed_production_sample" if score is not None
                               else "insufficient_verified_human_reviews"),
            "limitation": "Muestra de respuestas revisadas, no estimación representativa de toda la producción."}
