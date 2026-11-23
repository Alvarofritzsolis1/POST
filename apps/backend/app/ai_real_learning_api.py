"""Real conversation practice with Qwen; never publishes or persists chat text.

The observed reply is the production baseline. Local Qwen tests one fixed,
approved-for-trial instruction. The human verdict is a *case-specific* signal,
not a blinded A/B study or proof of general model improvement.
"""
from datetime import timedelta
from zlib import crc32
from time import perf_counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_historical_learning import historical_overview
from .ai_defect_learning import (
    POLICIES, SCOPE, VARIANTS, REPLAY_LIMIT_PER_CRITERION, MIN_HOLDOUT_WINS,
    candidate_policy, diagnostic_route, eligible_for_proposal, learning_plan, policy_title,
)
from .ai_quality_audit import _audit_source
from .ai_quality_models import AIRealPracticeTrial, AIResponseReview
from .config import settings
from .db import get_db
from .facebook_ai import LOCAL_REPLY_INSTRUCTIONS
from .galancito_general import GENERAL_INSTRUCTIONS, QWEN_4B
from .galancito_knowledge_api import KnowledgeInput, create
from .galancito_knowledge_models import Knowledge, AssistantRun
from .galancito_local import generate_local_text, last_timings
from .galancito_memory import aware
from .galancito_runtime import infer
from .galancito_flow import grounded_reply
from .galancito_triage import private_data
from .galancito_general import safe_generated
from .models import AuditEvent, User, utcnow
from .security import administrator

router = APIRouter(prefix="/api/v1/admin/ai/real-learning", tags=["Aprendizaje auditado"])


class ReplayInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=36, max_length=36)
    criterion: str = Field(min_length=3, max_length=30)
    variant: Literal["focused", "alternative"] = "focused"


class TrialRating(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["better", "same", "worse"]
    verification_nonce: str = Field(min_length=36, max_length=36)
    criterion_resolved: bool = False
    safety_passed: bool = False
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


def _linked_original_run(db, user, evidence, candidate):
    """Resolve genuine source telemetry; do not guess by timestamp alone."""
    if candidate is not None:
        return candidate
    if evidence["channel"] != "messenger":
        return None
    since = utcnow() - timedelta(days=30)
    rows = db.scalars(select(AssistantRun).where(
        AssistantRun.org_id == user.org_id,
        AssistantRun.channel == "messenger",
        AssistantRun.created_at >= since,
    ).order_by(AssistantRun.created_at.desc()).limit(500))
    return next((r for r in rows
                 if isinstance(r.timings, dict) and
                 r.timings.get("outbound_message_id") == evidence["source_id"]), None)


def _verified_model_trace(record):
    if record is None:
        return False
    timings = getattr(record, "timings", {}) or {}
    return (isinstance(timings, dict)
            and isinstance(timings.get("response_model"), str)
            and timings["response_model"].casefold() == QWEN_4B.casefold()
            and record.source in {"ai", "ollama_4b", "verified_reasoning"})


def _successful_training(trials, variant):
    return len({t.review_id for t in trials if t.variant == variant and
                t.stage == "practice" and t.outcome == "better" and
                t.provenance == "model_verified" and
                t.criterion_resolved and t.safety_passed})


@router.get("/history")
def historical_inventory(
    months: int = Query(default=0, ge=0, le=60),
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    """All retained metadata; the endpoint never reads any conversation body."""
    return historical_overview(db, user.org_id, months=months)


@router.get("/cases")
def audited_cases(channel: Literal["messenger", "general"] = "messenger",
                  user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Cases with human-confirmed deficits; list without original/private text."""
    since = utcnow() - timedelta(days=30)
    rows = list(db.scalars(select(AIResponseReview).where(
        AIResponseReview.org_id == user.org_id,
        AIResponseReview.channel == channel,
        AIResponseReview.source_at >= since,
        AIResponseReview.rubric_version == 1,
    ).order_by(AIResponseReview.source_at.desc()).limit(80)))
    cases = []
    for review in rows:
        weak = [criterion for criterion in POLICIES[channel]
                if review.ratings.get(criterion) is False]
        if not weak:
            continue
        try:
            original_run, evidence = _audit_source(db, user, review.evidence_id)
        except HTTPException:
            continue
        original_run = _linked_original_run(db, user, evidence, original_run)
        cases.append({
            "source_id": review.evidence_id,
            "source_at": review.source_at,
            "failed_criteria": weak,
            "route": diagnostic_route(original_run, weak[0]),
            "model_verified": _verified_model_trace(original_run),
        })
        if len(cases) >= 25:
            break
    return {"channel": channel, "items": cases,
            "note": "Casos reales auditados, sin copiar las conversaciones ni afirmar causalidad."}


@router.get("/next")
def next_target(channel: Literal["messenger", "general"] = "messenger",
                user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Pick next verified deficiency deterministically. Never invent cases."""
    results = audited_cases(channel=channel, user=user, db=db)["items"]
    since = utcnow() - timedelta(days=30)
    counts = {}
    for row in reviews_for(db, user.org_id, channel, since):
        for key in POLICIES[channel]:
            if row.ratings.get(key) is False:
                counts[key] = counts.get(key, 0) + 1
    candidates = []
    for case in results:
        if not case["model_verified"]:
            continue
        original, evidence = _audit_source(db, user, case["source_id"])
        history = evidence["history"][-5:]
        context = "\n".join(str(item["text"])[:500] for item in history) + evidence["question"][:650]
        if private_data(context):
            continue
        for key in case["failed_criteria"]:
            previous = list(db.scalars(select(AIRealPracticeTrial).where(
                AIRealPracticeTrial.org_id == user.org_id,
                AIRealPracticeTrial.channel == channel,
                AIRealPracticeTrial.criterion == key,
            ).order_by(AIRealPracticeTrial.created_at.desc()).limit(300)))
            done = [x for x in previous if x.review_id ==
                    db.scalar(select(AIResponseReview.id).where(
                        AIResponseReview.org_id == user.org_id,
                        AIResponseReview.evidence_id == case["source_id"],
                        AIResponseReview.channel == channel))]
            if any(t.outcome == "pending" for t in done) or len(done) >= REPLAY_LIMIT_PER_CRITERION:
                continue
            # Select the strategy with strongest training evidence; explore the
            # alternate only after a first non-successful or cancelled attempt.
            strategies = []
            for variant in VARIANTS:
                seen = [x for x in previous if x.variant == variant]
                if any(x.outcome == "worse" for x in seen):
                    continue
                training_wins = _successful_training(seen, variant)
                prior_attempts = sum(x.variant == variant for x in done)
                if training_wins >= 2 and not done:
                    strategies.append((0, variant))
                elif not prior_attempts:
                    strategies.append((1 if variant == "focused" else 2, variant))
            if not strategies:
                continue
            _, variant = min(strategies)
            candidates.append((0 if key == "safety" else 1, -counts.get(key, 0),
                               case["source_at"], case["source_id"], key, variant))
    if not candidates:
        return {"available": False, "reason": "No hay casos reales auditados, autorizados y elegibles para práctica local."}
    _, minus_count, _, source_id, criterion, variant = min(candidates)
    return {"available": True, "source_id": source_id, "criterion": criterion,
            "variant": variant, "observed_defects": -minus_count,
            "reason": "Seleccionado por fallas humanas verificadas y estrategia sin regresiones observadas.",
            "model": QWEN_4B, "automatic_approval": False,
            "caution": "La hipótesis de fallo no prueba la causa ni el éxito de una corrección."}


@router.get("/pending")
def pending_trials(channel: Literal["messenger", "general"] = "messenger",
                   user: User = Depends(administrator), db: Session = Depends(get_db)):
    """No candidate text retained. Provide safe reset after tab refresh."""
    rows = list(db.scalars(select(AIRealPracticeTrial).where(
        AIRealPracticeTrial.org_id == user.org_id,
        AIRealPracticeTrial.reviewer_id == user.id,
        AIRealPracticeTrial.channel == channel,
        AIRealPracticeTrial.outcome == "pending",
    ).order_by(AIRealPracticeTrial.created_at.desc()).limit(25)))
    return {"items": [{
        "id": t.id, "criterion": t.criterion, "variant": t.variant, "created_at": t.created_at,
        "can_cancel": True,
    } for t in rows],
    "note": "No se guarda el texto generado. Cancela una prueba interrumpida antes de repetirla."}


@router.post("/trials/{trial_id}/cancel")
def cancel_trial(trial_id: str, user: User = Depends(administrator),
                 db: Session = Depends(get_db)):
    trial = db.scalar(select(AIRealPracticeTrial).where(
        AIRealPracticeTrial.id == trial_id,
        AIRealPracticeTrial.org_id == user.org_id,
        AIRealPracticeTrial.reviewer_id == user.id,
    ).with_for_update())
    if trial is None:
        raise HTTPException(404, "Práctica no encontrada")
    if trial.outcome != "pending":
        raise HTTPException(409, "No puedes cancelar una práctica ya evaluada")
    trial.outcome = "cancelled"
    trial.reviewed_at = utcnow()
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="ai.real_learning.trial_cancelled", resource_id=trial.id))
    db.commit()
    return {"cancelled": True, "quality_improvement_proven": False}


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
            eligibility = eligible_for_proposal(trials)
            item["proposal_ready"] = eligibility["ready"]
            item["holdout"] = eligibility
            item["analysis_status"] = "observed_fault_without_verified_cause" if item["failed"] else "no_fault_observed"
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
    original_run, evidence = _audit_source(db, user, body.source_id)
    original_run = _linked_original_run(db, user, evidence, original_run)
    diagnosis = diagnostic_route(original_run, body.criterion)
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
    previous = list(db.scalars(select(AIRealPracticeTrial).where(
        AIRealPracticeTrial.review_id == review.id,
        AIRealPracticeTrial.criterion == body.criterion,
    ).order_by(AIRealPracticeTrial.created_at.desc())))
    if any(t.outcome == "pending" for t in previous):
        raise HTTPException(409, "Existe una práctica sin calificar; revísala o cancélala")
    if len(previous) >= REPLAY_LIMIT_PER_CRITERION:
        raise HTTPException(409, "Límite de intentos alcanzado; revisa el diagnóstico")
    if body.variant not in VARIANTS:
        raise HTTPException(422, "Variante no permitida")
    cfg = settings()
    if not cfg.galancito_local_ai_enabled or cfg.galancito_local_model != QWEN_4B:
        raise HTTPException(409, "Requiere Qwen3.5 4B local activo; sin simulaciones ni API externas")
    lines = [("Persona: " if x["role"] in ("user", "inbound") else "GALANT: ") +
             str(x["text"])[:500] for x in evidence["history"][-5:]]
    prompt = "\n".join(lines) + "\nÚltima consulta:\n" + evidence["question"][:650]
    if private_data(prompt) or len(prompt) > 3200:
        raise HTTPException(422, "Hay datos privados; esta conversación no se reproduce")
    base_instructions = (LOCAL_REPLY_INSTRUCTIONS if channel == "messenger" else GENERAL_INSTRUCTIONS)
    from .ai_defect_learning import approved_coaching
    current_coaching = approved_coaching(db, user.org_id, channel)
    if current_coaching:
        base_instructions += "\nGuías ya aprobadas:\n" + current_coaching
    correction = candidate_policy(channel, body.criterion, body.variant)
    # Only the correction varies; both answers use the same model, context,
    # inference parameters and seed, not two unrelated historical runs.
    instructions = base_instructions + "\n\nCORRECCIÓN EN ENSAYO (no aprobada):\n" + correction
    from .galancito_local import MAX_INSTRUCTIONS_CHARS
    if len(instructions) > MAX_INSTRUCTIONS_CHARS:
        raise HTTPException(422, "La corrección excede las instrucciones seguras; se cancela la prueba")
    same_variant = trials_for(db, user.org_id, channel, body.criterion,
                              utcnow() - timedelta(days=30))
    variant_trials = [t for t in same_variant if t.variant == body.variant]
    trained = _successful_training(variant_trials, body.variant)
    if any(t.outcome == "worse" for t in variant_trials):
        raise HTTPException(409, "La estrategia tiene regresiones; requiere investigación")
    stage = "holdout" if trained >= 2 and not previous else "practice"
    started = perf_counter()
    seed = crc32((evidence["source_id"] + body.criterion + body.variant).encode("utf-8")) & 0x7fffffff
    outputs = []
    measures = []
    try:
        for instruction_set in (base_instructions, instructions):
            raw = infer(db, lambda current=instruction_set: generate_local_text(
                current, prompt, max_chars=550, thinking=(channel == "general"), seed=seed))
            observed = dict(last_timings.get() or {})
            if (not isinstance(observed.get("response_model"), str)
                    or observed["response_model"].casefold() != QWEN_4B.casefold()):
                raise HTTPException(503, "Ollama no confirmó Qwen3.5 4B en ambas ejecuciones")
            if not raw or not str(raw).strip():
                raise HTTPException(503, "Qwen no produjo ambas respuestas comparables")
            clean = (grounded_reply(raw, prompt) if channel == "messenger"
                     else safe_generated(raw, question=prompt))
            if not clean or private_data(clean):
                raise HTTPException(422, "La respuesta incumple seguridad; no puede contarse como mejora")
            outputs.append(clean)
            measures.append(observed)
    except (RuntimeError, TimeoutError, OSError, ValueError):
        raise HTTPException(503, "Qwen local no completó ambas pruebas; no se registró aprendizaje") from None
    if outputs[0].strip().casefold() == outputs[1].strip().casefold():
        raise HTTPException(409, "La corrección no cambió la respuesta de Qwen; no se atribuye mejora")
    observed = measures[1]
    baseline, validated = outputs
    elapsed = round((perf_counter() - started) * 1000)
    trial = AIRealPracticeTrial(
        org_id=user.org_id, review_id=review.id, reviewer_id=user.id,
        channel=channel, criterion=body.criterion, model=QWEN_4B,
        elapsed_ms=elapsed, policy_version=1, outcome="pending",
        variant=body.variant, stage=stage,
        provenance="model_verified" if _verified_model_trace(original_run) else "reconstructed")
    db.add(trial)
    db.commit()
    return {"trial_id": trial.id, "verification_nonce": trial.verification_nonce,
            "channel": channel, "criterion": body.criterion,
            "variant": body.variant, "stage": stage, "diagnosis": diagnosis,
            "provenance": trial.provenance,
            "model": QWEN_4B, "source": "actual_local_qwen_on_audited_production_chat",
            "original": evidence["answer"],
            "baseline": str(baseline)[:1000], "candidate": str(validated)[:1000],
            "seed": seed, "elapsed_ms": elapsed,
            "ollama_timings_ms": {name: round(float(observed[name]), 1)
                                 for name in ("load_ms", "prompt_ms", "generation_ms")
                                 if isinstance(observed.get(name), (int, float))},
            "disclaimer": "Dos inferencias locales con el mismo contexto y semilla; no reproduce todos los componentes ni prueba calidad general."}


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
    if row.verification_nonce != body.verification_nonce:
        raise HTTPException(409, "Falta el comprobante de la respuesta generada; vuelve a realizar el ensayo")
    if aware(row.created_at) < utcnow() - timedelta(minutes=30):
        raise HTTPException(409, "Evaluación caducada; no se permite inventar un resultado")
    if body.outcome == "better" and not (body.criterion_resolved and body.safety_passed):
        raise HTTPException(422,
            "No basta con ser mejor: confirma que resolvió la falla y conservó la seguridad")
    row.outcome, row.reviewed_at = body.outcome, utcnow()
    row.criterion_resolved = bool(body.criterion_resolved and body.outcome == "better")
    row.safety_passed = bool(body.safety_passed and body.outcome == "better")
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
    result = eligible_for_proposal(trials)
    if len(failed) < 2 or not result["ready"]:
        raise HTTPException(409,
            "Sin evidencia suficiente: se requieren dos prácticas y cuatro casos reservados "
            "distintos favorables, con ruta de Qwen verificable y sin regresiones")
    title = policy_title(body.channel, body.criterion)
    existing = db.scalar(select(Knowledge).where(
        Knowledge.org_id == user.org_id, Knowledge.title == title))
    if existing:
        return {"id": existing.id, "status": existing.status,
                "message": "La propuesta ya existe. Revisa su estado en Conocimientos."}
    content = candidate_policy(body.channel, body.criterion, result["variant"])
    result = create(db, KnowledgeInput(
        title=title, category="Práctica real auditada", kind="procedure",
        scope=SCOPE[body.channel], content=content, phrases=[]), user)
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="ai.real_learning.proposed", resource_id=result["id"]))
    db.commit()
    return {"id": result["id"], "status": "pending",
            "message": "Pendiente de aprobación humana. No equivale a fine-tuning ni demuestra calidad global."}
