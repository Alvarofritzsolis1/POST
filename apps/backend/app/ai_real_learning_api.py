"""Real conversation practice with Qwen; never publishes or persists chat text.

The observed reply is the production baseline. Local Qwen tests one fixed,
approved-for-trial instruction. The human verdict is a *case-specific* signal,
not a blinded A/B study or proof of general model improvement.
"""
from datetime import timedelta
from time import perf_counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_defect_learning import POLICIES, SCOPE, learning_plan, policy_title
from .ai_quality_audit import _audit_source
from .ai_quality_models import AIRealPracticeTrial, AIResponseReview
from .config import settings
from .db import get_db
from .facebook_ai import REPLY_INSTRUCTIONS
from .galancito_general import GENERAL_INSTRUCTIONS, QWEN_4B
from .galancito_knowledge_api import KnowledgeInput, create
from .galancito_knowledge_models import Knowledge
from .galancito_local import generate_local_text, last_timings
from .galancito_memory import aware
from .galancito_runtime import infer
from .galancito_triage import private_data
from .models import AuditEvent, User, utcnow
from .security import administrator

router = APIRouter(prefix="/api/v1/admin/ai/real-learning", tags=["Aprendizaje auditado"])


class ReplayInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=36, max_length=36)
    criterion: str = Field(min_length=3, max_length=30)


class TrialRating(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["better", "same", "worse"]
    source_reviewed: Literal[True]


class ProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Literal["messenger", "general"]
    criterion: str = Field(min_length=3, max_length=30)


def reviews_for(db, org_id, channel, since):
    return list(db.scalars(select(AIResponseReview).where(
        AIResponseReview.org_id == org_id, AIResponseReview.channel == channel,
        AIResponseReview.source_at >= since, AIResponseReview.rubric_version == 1)))


def trials_for(db, org_id, channel, criterion, since):
    return list(db.scalars(select(AIRealPracticeTrial).where(
        AIRealPracticeTrial.org_id == org_id,
        AIRealPracticeTrial.channel == channel,
        AIRealPracticeTrial.criterion == criterion,
        AIRealPracticeTrial.created_at >= since)))


@router.get("/plan")
def plan(days: int = Query(default=30, ge=1, le=90),
         user: User = Depends(administrator), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    channels = {}
    for channel in POLICIES:
        summary = learning_plan(reviews_for(db, user.org_id, channel, since), channel)
        for item in summary["items"]:
            trials = trials_for(db, user.org_id, channel, item["criterion"], since)
            outcome = {name: sum(t.outcome == name for t in trials)
                       for name in ("better", "same", "worse", "pending")}
            item["practice"] = outcome
            item["proposal_ready"] = (item["failed"] >= 2 and outcome["better"] >= 2
                                      and outcome["worse"] == 0)
            item["active_coaching"] = bool(db.scalar(select(Knowledge.id).where(
                Knowledge.org_id == user.org_id,
                Knowledge.title == policy_title(channel, item["criterion"]),
                Knowledge.scope == SCOPE[channel],
                Knowledge.status == "approved")))
        channels[channel] = summary
    return {"days": days, "source": "human_reviewed_production", "channels": channels,
            "disclaimer": "Resultados por casos reales revisados, no porcentaje representativo ni entrenamiento de pesos."}


@router.post("/replay")
def replay(body: ReplayInput, user: User = Depends(administrator),
           db: Session = Depends(get_db)):
    _, evidence = _audit_source(db, user, body.source_id)
    channel = evidence["channel"]
    if body.criterion not in POLICIES[channel]:
        raise HTTPException(422, "Criterio incompatible con la conversación")
    review = db.scalar(select(AIResponseReview).where(
        AIResponseReview.org_id == user.org_id,
        AIResponseReview.channel == channel,
        AIResponseReview.evidence_kind == evidence["kind"],
        AIResponseReview.evidence_id == evidence["source_id"],
        AIResponseReview.rubric_version == 1))
    if review is None or review.ratings.get(body.criterion) is not False:
        raise HTTPException(409, "Primero revisa una deficiencia real de este criterio")
    if db.scalar(select(AIRealPracticeTrial.id).where(
        AIRealPracticeTrial.review_id == review.id,
        AIRealPracticeTrial.criterion == body.criterion,
        AIRealPracticeTrial.policy_version == 1)):
        raise HTTPException(409, "Esta deficiencia ya se practicó; revisa su resultado")
    cfg = settings()
    if not cfg.galancito_local_ai_enabled or cfg.galancito_local_model != QWEN_4B:
        raise HTTPException(409, "Requiere Qwen3.5 4B local activo; sin simulaciones ni API externas")
    lines = [("Persona: " if x["role"] in ("user", "inbound") else "GALANT: ") +
             str(x["text"])[:500] for x in evidence["history"][-5:]]
    prompt = "\n".join(lines) + "\nÚltima consulta:\n" + evidence["question"][:650]
    if private_data(prompt) or len(prompt) > 3200:
        raise HTTPException(422, "Hay datos privados; esta conversación no se reproduce")
    instructions = (REPLY_INSTRUCTIONS if channel == "messenger" else GENERAL_INSTRUCTIONS)
    instructions = ("Corrección experimental de una falla revisada (no aprobada):\n" +
                    POLICIES[channel][body.criterion][1] + "\n\n" + instructions)
    started = perf_counter()
    try:
        candidate = infer(db, lambda: generate_local_text(
            instructions, prompt, max_chars=550, thinking=(channel == "general")))
    except (RuntimeError, TimeoutError, OSError, ValueError):
        raise HTTPException(503, "Qwen local no terminó; no se registró ninguna mejora") from None
    if not candidate or not str(candidate).strip():
        raise HTTPException(503, "Qwen no produjo una respuesta para comparar")
    # The actual model identity must be reported by Ollama, not merely configured.
    observed = last_timings.get()
    if (not isinstance(observed, dict) or not isinstance(observed.get("response_model"), str)
            or observed["response_model"].casefold() != QWEN_4B.casefold()):
        raise HTTPException(503, "Ollama no confirmó Qwen3.5 4B; no se registra aprendizaje")
    elapsed = round((perf_counter() - started) * 1000)
    trial = AIRealPracticeTrial(
        org_id=user.org_id, review_id=review.id, reviewer_id=user.id,
        channel=channel, criterion=body.criterion, model=QWEN_4B,
        elapsed_ms=elapsed, policy_version=1, outcome="pending")
    db.add(trial)
    db.commit()
    return {"trial_id": trial.id, "channel": channel, "criterion": body.criterion,
            "model": QWEN_4B, "source": "actual_local_qwen_on_audited_production_chat",
            "original": evidence["answer"], "candidate": str(candidate)[:1000],
            "elapsed_ms": elapsed,
            "ollama_timings_ms": {name: round(float(observed[name]), 1)
                                 for name in ("load_ms", "prompt_ms", "generation_ms")
                                 if isinstance(observed.get(name), (int, float))},
            "disclaimer": "Comparación exploratoria de un caso real; no es prueba reservada ni se envía a Messenger."}


@router.post("/trials/{trial_id}/review")
def review_trial(trial_id: str, body: TrialRating,
                 user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = db.scalar(select(AIRealPracticeTrial).where(
        AIRealPracticeTrial.id == trial_id,
        AIRealPracticeTrial.org_id == user.org_id,
        AIRealPracticeTrial.reviewer_id == user.id).with_for_update())
    if row is None:
        raise HTTPException(404, "Práctica no encontrada")
    if row.outcome != "pending":
        raise HTTPException(409, "Esta práctica ya fue evaluada")
    if aware(row.created_at) < utcnow() - timedelta(minutes=30):
        raise HTTPException(409, "Evaluación caducada; no se permite inventar un resultado")
    row.outcome, row.reviewed_at = body.outcome, utcnow()
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="ai.real_learning.trial_reviewed", resource_id=row.id))
    db.commit()
    return {"saved": True, "outcome": body.outcome, "overall_improvement_proven": False}


@router.post("/proposals", status_code=201)
def propose(body: ProposalInput, user: User = Depends(administrator),
            db: Session = Depends(get_db)):
    if body.criterion not in POLICIES[body.channel]:
        raise HTTPException(422, "Criterio no válido")
    since = utcnow() - timedelta(days=30)
    reviews = reviews_for(db, user.org_id, body.channel, since)
    failed = [r for r in reviews if r.ratings.get(body.criterion) is False]
    trials = trials_for(db, user.org_id, body.channel, body.criterion, since)
    better = {t.review_id for t in trials if t.outcome == "better"}
    if len(failed) < 2 or len(better) < 2 or any(t.outcome == "worse" for t in trials):
        raise HTTPException(409, "Se requieren al menos dos casos reales con mejora revisada y sin regresiones")
    title = policy_title(body.channel, body.criterion)
    existing = db.scalar(select(Knowledge).where(
        Knowledge.org_id == user.org_id, Knowledge.title == title))
    if existing:
        return {"id": existing.id, "status": existing.status,
                "message": "La propuesta ya existe. Revisa su estado en Conocimientos."}
    _, content, _ = POLICIES[body.channel][body.criterion]
    result = create(db, KnowledgeInput(
        title=title, category="Práctica real auditada", kind="procedure",
        scope=SCOPE[body.channel], content=content, phrases=[]), user)
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="ai.real_learning.proposed", resource_id=result["id"]))
    db.commit()
    return {"id": result["id"], "status": "pending",
            "message": "Pendiente de aprobación humana. No equivale a fine-tuning ni demuestra calidad global."}
