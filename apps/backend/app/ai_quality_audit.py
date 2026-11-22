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
    ratings: dict[str, StrictBool]
    source_reviewed: Literal[True]  # human attests reading the linked real exchange


def observed_run(db: Session, user: User, run_id: str) -> AssistantRun:
    record = db.scalar(select(AssistantRun).where(
        AssistantRun.id == run_id, AssistantRun.org_id == user.org_id,
    ))
    if not record or record.channel not in {"messenger", "galant_internal"}:
        raise HTTPException(404, "Interacción de producción no encontrada")
    if record.created_at < utcnow() - timedelta(days=30):
        raise HTTPException(409, "La interacción está fuera de la ventana de revisión")
    return record


def linked_evidence(db: Session, user: User, record: AssistantRun) -> dict | None:
    """Read in scope only; never persist or return without admin authorization."""
    if record.channel == "messenger":
        message_id = (record.timings or {}).get("outbound_message_id")
        if not isinstance(message_id, str) or len(message_id) != 36:
            return None
        message = db.scalar(select(FacebookChatMessage).where(
            FacebookChatMessage.id == message_id,
            FacebookChatMessage.org_id == user.org_id,
            FacebookChatMessage.ai_generated.is_(True),
            FacebookChatMessage.direction == "outbound",
            FacebookChatMessage.state == "sent",
        ))
        if message is None or not message.body.strip():
            return None
        inbound = list(db.scalars(select(FacebookChatMessage).where(
            FacebookChatMessage.org_id == user.org_id,
            FacebookChatMessage.lead_id == message.lead_id,
            FacebookChatMessage.direction == "inbound",
            FacebookChatMessage.created_at <= message.updated_at,
        ).order_by(FacebookChatMessage.created_at.desc()).limit(3)))
        if not inbound:
            return None  # No original user question to check
        return {
            "channel": "messenger", "kind": "messenger_message",
            "source_id": message.id,
            "question": "\n".join(msg.body[:650] for msg in reversed(inbound)),
            "answer": message.body[:1800],
        }

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
                    "source_id": conversation.id,
                    "question": question[:800], "answer": answer[:1600],
                }
    return None


@router.get("/queue")
def review_queue(channel: Literal["messenger", "general"] = Query(default="messenger"),
                 user: User = Depends(administrator), db: Session = Depends(get_db)):
    """List only auditable runs with real evidence, never message contents."""
    original_channel = "messenger" if channel == "messenger" else "galant_internal"
    recent = list(db.scalars(select(AssistantRun).where(
        AssistantRun.org_id == user.org_id, AssistantRun.channel == original_channel,
        AssistantRun.created_at >= utcnow() - timedelta(days=30),
    ).order_by(AssistantRun.created_at.desc()).limit(200)))
    reviewed_ids = set(db.scalars(select(AIResponseReview.run_id).where(
        AIResponseReview.org_id == user.org_id,
        AIResponseReview.run_id.in_([row.id for row in recent]),
    ))) if recent else set()
    items = []
    for row in recent:
        if row.id in reviewed_ids:
            continue
        evidence = linked_evidence(db, user, row)
        if evidence:
            items.append({
                "run_id": row.id, "created_at": row.created_at,
                "channel": channel, "source": row.source,
            })
        if len(items) >= 40:
            break
    return {"channel": channel, "rubric_version": RUBRIC_VERSION,
            "criteria": list(CRITERIA[channel]), "items": items}


@router.get("/cases/{run_id}")
def review_case(run_id: str, user: User = Depends(administrator),
                db: Session = Depends(get_db)):
    record = observed_run(db, user, run_id)
    evidence = linked_evidence(db, user, record)
    if not evidence:
        raise HTTPException(404, "No hay intercambio original verificable y autorizado")
    channel = evidence["channel"]
    return {"run_id": record.id, "created_at": record.created_at,
            "rubric_version": RUBRIC_VERSION, "criteria": list(CRITERIA[channel]),
            **{k: evidence[k] for k in ("channel", "question", "answer")}}


@router.post("/reviews", status_code=201)
def save_review(body: ReviewInput, user: User = Depends(administrator),
                db: Session = Depends(get_db)):
    record = observed_run(db, user, body.run_id)
    evidence = linked_evidence(db, user, record)
    if evidence is None:
        raise HTTPException(409, "Falta conversación original revisable, entrega confirmada o permiso")
    channel = evidence["channel"]
    if set(body.ratings) != set(CRITERIA[channel]):
        raise HTTPException(422, "Evalúa todos los criterios de esta versión sin agregar otros")
    if db.scalar(select(AIResponseReview.id).where(
        AIResponseReview.org_id == user.org_id, AIResponseReview.run_id == record.id,
    )):
        raise HTTPException(409, "La interacción ya fue auditada; no se admiten puntuaciones duplicadas")
    review = AIResponseReview(
        org_id=user.org_id, run_id=record.id, reviewer_id=user.id,
        channel=channel, rubric_version=RUBRIC_VERSION,
        evidence_kind=evidence["kind"], evidence_id=evidence["source_id"],
        ratings=dict(body.ratings),
    )
    db.add(review)
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="ai.response_review.created", resource_id=record.id))
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
    rows = list(db.scalars(select(AIResponseReview).join(
        AssistantRun, AIResponseReview.run_id == AssistantRun.id
    ).where(
        AIResponseReview.org_id == org_id,
        AssistantRun.org_id == org_id,
        AIResponseReview.channel == channel,
        AssistantRun.created_at >= since,
        AIResponseReview.rubric_version == RUBRIC_VERSION,
    )))
    count = len(rows)
    criteria = CRITERIA[channel]
    per_dimension = {name: round(100 * sum(bool(item.ratings.get(name)) for item in rows) / count, 1)
                     if count else None for name in criteria}
    score = round(sum(value for value in per_dimension.values() if value is not None)
                  / len(criteria), 1) if count >= MIN_REVIEWED_SAMPLE else None
    return {"quality_score": score, "reviewed_cases": count,
            "minimum_cases": MIN_REVIEWED_SAMPLE, "rubric_version": RUBRIC_VERSION,
            "dimension_scores": per_dimension,
            "quality_source": ("human_reviewed_production_sample" if score is not None
                               else "insufficient_verified_human_reviews"),
            "limitation": "Muestra de respuestas revisadas, no estimación representativa de toda la producción."}
