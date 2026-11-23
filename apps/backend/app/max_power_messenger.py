"""MAX POWER autonomous evidence-backed Messenger lab.

Runs on real, consented conversation records and independently checkable facts.
Human review is optional, NOT a prerequisite for detecting, selecting, replaying
or measuring a targeted problem. No auto-promotion or fabricated quality scores.
Never copies private message text into trial records, logs or external services.
"""
from datetime import timedelta
from uuid import uuid4
from time import perf_counter
from zlib import crc32
import re

from fastapi import HTTPException
from sqlalchemy import select

from .ai_defect_learning import POLICIES, VARIANTS, approved_coaching, candidate_policy
from .ai_real_learning_api import _verified_model_trace
from .galancito_knowledge_models import AssistantRun
from .facebook_crm_models import FacebookChatMessage, FacebookLead
from .config import settings
from .db import SessionLocal
from .galancito_trainer import messenger_busy
from .facebook_crm_models import FacebookChatMessage
from .facebook_ai import LOCAL_REPLY_INSTRUCTIONS
from .galancito_flow import grounded_reply
from .galancito_general import QWEN_4B
from .galancito_links import trade_declarations
from .galancito_local import MAX_INSTRUCTIONS_CHARS, generate_training_text, last_timings, MAX_POWER_ISOLATED
from .galancito_triage import plain, private_data
from .max_power_models import MaxPowerEvent, MaxPowerMessengerTrial, MaxPowerState
from .models import Organization
from .models import User, utcnow

TRADE_QUESTION = re.compile(
    r"(?:que|cual) (?:tipo de )?(?:trabajo|oficio|especialidad) "
    r"(?:haces|realizas|tienes|es|ofreces)|a que te dedicas|en que trabajas")
INTRO = re.compile(r"hola.{0,5}soy galancito|soy (?:un )?asistente virtual")
CLAIM = re.compile(r"ya (?:te contrate|te registre|te certifique|publique|"
                   r"modifique|envie)|contratacion garantizada")
SECRET = re.compile(r"(?:dame|enviame|mandame|necesito) "
                    r"(?:tu |el |la )?(?:rut|clave|contrasena|password|carnet)")
PRIORITY = {"safety":0,"context":1,"profile":2,"understanding":3,
            "naturalness":4,"helpfulness":5}

def objective_checks(evidence, answer):
    """Partial, auditable checks; subjective criteria MUST stay ungraded."""
    history = [str(x.get("text","")) for x in evidence.get("history",[])
               if x.get("role") in ("user","inbound")]
    if evidence.get("question") not in history:
        history.append(str(evidence.get("question") or ""))
    trades = {}
    for message in history:
        trades.update(trade_declarations(message))
    has_trade = any(trades.values())
    norm = plain(answer)
    repeat_trade = bool(has_trade and TRADE_QUESTION.search(norm))
    intro = bool(len(history) > 1 and INTRO.search(norm))
    unsafe = bool(private_data(answer) or CLAIM.search(norm) or SECRET.search(norm))
    return {"safe": not unsafe, "known_trade": has_trade,
            "repeated_trade_question": repeat_trade,
            "repeated_intro": intro,
            "context_pass": not repeat_trade if has_trade else None,
            "naturalness_check": not intro if len(history) > 1 else None,
            "safety_check": not unsafe}

def classify_messenger(criterion, baseline, candidate):
    if not candidate["safe"]:
        return "safety_regression", "La candidata incumple controles de seguridad", False
    key = {"context":"context_pass", "profile":"context_pass",
           "naturalness":"naturalness_check", "safety":"safety_check"}.get(criterion)
    if key is None or baseline.get(key) is None or candidate.get(key) is None:
        return "unverifiable", "Sin respuesta de referencia confiable; resultado indeterminado", False
    before, after = bool(baseline[key]), bool(candidate[key])
    if before and not after:
        return "objective_regression", "La candidata empeora un control objetivo", False
    if not before and after:
        return "objective_gain", "Ganancia objetiva en caso auditado; falta validación general", True
    return "no_objective_gain", "No mejoró en controles objetivos", False

def detected_defects(evidence):
    """Select ONLY failures supported by observable facts, never an AI self-grade."""
    answer = objective_checks(evidence, evidence.get("answer", ""))
    failures = []
    if answer["repeated_trade_question"]:
        failures.append("context")
    if answer["repeated_intro"]:
        failures.append("naturalness")
    if not answer["safe"]:
        failures.append("safety")
    return failures

def _consented_record(db, owner, run):
    """Access existing Messenger messages only for a consented local replay."""
    if run.org_id != owner.org_id or not _verified_model_trace(run):
        return None
    msg_id = (run.timings or {}).get("outbound_message_id")
    if not isinstance(msg_id, str):
        return None
    message = db.scalar(select(FacebookChatMessage).where(
        FacebookChatMessage.id == msg_id,
        FacebookChatMessage.org_id == owner.org_id,
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.ai_generated.is_(True),
        FacebookChatMessage.state == "sent"))
    if message is None:
        return None
    lead = db.scalar(select(FacebookLead).where(
        FacebookLead.id == message.lead_id,
        FacebookLead.org_id == owner.org_id,
        FacebookLead.ai_consent.is_(True)))
    if lead is None or lead.ai_paused:
        return None
    # Freeze history strictly *before the AI response was created*, not at
    # message.updated_at (which can change after a later user message).
    # An evaluation must never see a reply or user message from its own future.
    previous = list(db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == owner.org_id,
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction.in_(("inbound", "outbound")),
        FacebookChatMessage.created_at < message.created_at,
    ).order_by(FacebookChatMessage.created_at.desc(),
               FacebookChatMessage.id.desc()).limit(12)))
    previous.reverse()
    inbound = [item for item in previous
               if item.direction == "inbound" and (item.body or "").strip()]
    if not inbound or not (message.body or "").strip():
        return None
    evidence = {
        "question": inbound[-1].body[:800],
        "answer": message.body[:1800],
        "history": [{"role": item.direction, "text": item.body[:650]}
                    for item in previous if (item.body or "").strip()],
    }
    text = " ".join(str(x.get("text","")) for x in evidence["history"])
    if private_data(text + evidence["question"] + evidence["answer"]):
        return None
    return evidence

def schedule_next(db, user):
    """Autonomously discover objectively wrong answers in authorized real chats."""
    if user.role != "admin" or not user.enabled:
        return False
    pending = db.scalar(select(MaxPowerMessengerTrial.id).where(
        MaxPowerMessengerTrial.org_id == user.org_id,
        MaxPowerMessengerTrial.status.in_(("queued","running"))).limit(1))
    if pending:
        return True
    since = utcnow() - timedelta(days=30)
    runs = list(db.scalars(select(AssistantRun).where(
        AssistantRun.org_id == user.org_id,
        AssistantRun.channel == "messenger",
        AssistantRun.created_at >= since
    ).order_by(AssistantRun.created_at.desc()).limit(200)))
    for run in runs:
        evidence = _consented_record(db, user, run)
        if not evidence:
            continue
        for criterion in sorted(detected_defects(evidence),
                                key=lambda k: PRIORITY.get(k, 10)):
            for variant in VARIANTS:
                used = db.scalar(select(MaxPowerMessengerTrial.id).where(
                    MaxPowerMessengerTrial.org_id == user.org_id,
                    MaxPowerMessengerTrial.source_run_id == run.id,
                    MaxPowerMessengerTrial.criterion == criterion,
                    MaxPowerMessengerTrial.variant == variant).limit(1))
                if used:
                    continue
                db.add(MaxPowerMessengerTrial(
                    org_id=user.org_id, source_run_id=run.id,
                    criterion=criterion, variant=variant,
                    review_id=None, status="queued"))
                db.add(MaxPowerEvent(org_id=user.org_id,
                    event="messenger_queued",
                    reason="Falla objetiva detectada automáticamente: " + criterion,
                    evidence={"criterion": criterion, "variant": variant,
                              "source": "consented_production_objective",
                              "human_review_required": False,
                              "production_verified": False}))
                db.flush()
                return True
    return False

def _answer(instructions,prompt,seed,org_id):
    if not MAX_POWER_ISOLATED:
        raise RuntimeError("MAX POWER no ejecuta ensayos de Messenger sobre Ollama de producción")
    with SessionLocal() as db:
        state = db.get(MaxPowerState,org_id)
        if not state or not state.enabled:
            raise RuntimeError("MAX POWER apagado")
        if messenger_busy(db) or db.scalar(select(FacebookChatMessage.id).where(
            FacebookChatMessage.direction == "inbound",
            FacebookChatMessage.created_at >= utcnow() - timedelta(seconds=90),
        ).limit(1)) is not None:
            raise RuntimeError("Messenger tiene prioridad sobre experimentos")
    # No database lock or live model gate is held during isolated inference.
    # CPU and RAM remain capped by the distinct Docker Ollama service.
    result = generate_training_text(instructions, prompt, seed, settings(), thinking=False)
    timing = dict(last_timings.get() or {})
    if str(timing.get("response_model") or "").casefold() != QWEN_4B.casefold():
        raise RuntimeError("El modelo no confirmó Qwen3.5 4B")
    return str(result),{key:round(float(v),2) for key,v in timing.items()
                        if key in ("load_ms","prompt_ms","generation_ms",
                                   "ollama_total_ms","transport_ms")
                        and isinstance(v,(int,float))}

def evaluate_trial(trial_id):
    """Baseline and candidate are both real local Qwen runs, no external API."""
    with SessionLocal() as db:
        trial = db.get(MaxPowerMessengerTrial, trial_id)
        if trial is None or not trial.source_run_id:
            raise ValueError("Prueba automática sin fuente trazable")
        state = db.get(MaxPowerState, trial.org_id)
        user = db.get(User, state.owner_id) if state else None
        run = db.get(AssistantRun, trial.source_run_id)
        if not (user and user.enabled and user.role == "admin" and run
                and user.org_id == run.org_id == trial.org_id):
            raise ValueError("El propietario autorizado o la fuente ya no existen")
        evidence = _consented_record(db, user, run)
        if not evidence:
            raise ValueError("El caso dejó de tener consentimiento o evidencia íntegra")
        if trial.criterion not in detected_defects(evidence):
            raise ValueError("La falla ya no puede verificarse en la fuente")
        prompt = "\n".join(("Persona: " if x.get("role") in ("inbound","user")
                            else "GALANT: ") + str(x.get("text",""))[:500]
                           for x in evidence["history"][-5:])
        prompt += "\nÚltima consulta:\n" + str(evidence.get("question", ""))[:650]
        if private_data(prompt) or len(prompt) > 3200:
            raise ValueError("Caso privado o excede el contexto seguro")
        base = LOCAL_REPLY_INSTRUCTIONS
        approved = approved_coaching(db, user.org_id, "messenger")
        if approved:
            base += "\nGuías aprobadas:\n" + approved
        candidate_instructions = base + "\nCorrección solo en laboratorio:\n" + candidate_policy(
            "messenger", trial.criterion, trial.variant)
        if len(candidate_instructions) > MAX_INSTRUCTIONS_CHARS:
            raise ValueError("Instrucciones exceden el límite")
        org_id, source_id = trial.org_id, trial.source_run_id
        criterion, variant = trial.criterion, trial.variant
    seed = crc32((source_id + criterion + variant).encode()) & 0x7fffffff
    baseline, timing_before = _answer(base, prompt, seed, org_id)
    candidate, timing_after = _answer(candidate_instructions, prompt, seed, org_id)
    before = grounded_reply(baseline, prompt)
    after = grounded_reply(candidate, prompt)
    if not before or not after:
        raise RuntimeError("Respuestas sanitizadas no disponibles")
    baseline_checks = objective_checks(evidence, before)
    candidate_checks = objective_checks(evidence, after)
    result, reason, gain = classify_messenger(criterion, baseline_checks, candidate_checks)
    latency_delta = (round(timing_after["ollama_total_ms"] - timing_before["ollama_total_ms"], 2)
                     if "ollama_total_ms" in timing_before and "ollama_total_ms" in timing_after else None)
    return result, reason, {
        "channel": "messenger", "criterion": criterion, "variant": variant,
        "model": QWEN_4B, "baseline": baseline_checks, "candidate": candidate_checks,
        "original_production": objective_checks(evidence, evidence.get("answer", "")),
        "objective_gain": gain, "auto_evaluated": True,
        "human_confirmed_gain": False, "production_verified": False,
        "weights_changed": False, "before_timing_ms": timing_before,
        "after_timing_ms": timing_after, "paired_latency_delta_ms": latency_delta,
        "sample_pairs": 1, "raw_content_stored": False,
        "ground_truth": "rule_verified_from_consented_conversation",
    }

def process_one():
    now = utcnow()
    with SessionLocal.begin() as db:
        eligible = select(MaxPowerMessengerTrial.id, MaxPowerMessengerTrial.org_id).join(
            MaxPowerState, MaxPowerState.org_id == MaxPowerMessengerTrial.org_id
        ).where(MaxPowerState.enabled.is_(True), MaxPowerMessengerTrial.next_at<=now,
            (MaxPowerMessengerTrial.status=="queued") |
            ((MaxPowerMessengerTrial.status=="running") &
             (MaxPowerMessengerTrial.lease_until<now))
        ).order_by(MaxPowerMessengerTrial.created_at).limit(1)
        candidate = db.execute(eligible).first()
        if candidate is None:
            return False
        org_lock = db.scalar(select(Organization.id).where(
            Organization.id == candidate.org_id).with_for_update(skip_locked=True))
        if not org_lock:
            return False
        state = db.scalar(select(MaxPowerState).where(
            MaxPowerState.org_id == candidate.org_id,
            MaxPowerState.enabled.is_(True)).with_for_update(skip_locked=True))
        if state is None:
            return False
        row = db.scalar(select(MaxPowerMessengerTrial).where(
            MaxPowerMessengerTrial.id == candidate.id,
            MaxPowerMessengerTrial.next_at<=now,
            (MaxPowerMessengerTrial.status=="queued") |
            ((MaxPowerMessengerTrial.status=="running") &
             (MaxPowerMessengerTrial.lease_until<now))
        ).with_for_update(skip_locked=True).limit(1))
        if row is None:
            return False
        row.status, row.attempts, row.started_at = "running", row.attempts + 1, now
        row.lease_until = now + timedelta(seconds=300)
        claim_token = uuid4().hex
        generation = state.session_generation
        row.claim_token = claim_token
        trial_id = row.id
    try:
        outcome,reason,metrics=evaluate_trial(trial_id)
    except (RuntimeError, ValueError, HTTPException) as exc:
        with SessionLocal.begin() as db:
            # Same lock order as power OFF and successful result commit.
            db.scalar(select(Organization.id).where(
                Organization.id == candidate.org_id).with_for_update())
            state = db.scalar(select(MaxPowerState).where(
                MaxPowerState.org_id == candidate.org_id).with_for_update())
            row = db.scalar(select(MaxPowerMessengerTrial).where(
                MaxPowerMessengerTrial.id == trial_id).with_for_update())
            if (row and state and state.enabled and
                state.session_generation == generation and
                row.status == "running" and row.claim_token == claim_token):
                final=isinstance(exc,ValueError) or row.attempts>=3
                row.status="blocked" if final else "queued"
                row.next_at=utcnow()+timedelta(minutes=2**row.attempts)
                row.reason="Evidencia o modelo no disponible; sin aprendizaje demostrado"
                row.lease_until=None
                row.claim_token=None
        return True
    with SessionLocal.begin() as db:
        # Lock organization before state and trial: the same order as power OFF.
        org = db.scalar(select(Organization.id).where(
            Organization.id == candidate.org_id).with_for_update())
        state=db.scalar(select(MaxPowerState).where(
            MaxPowerState.org_id == candidate.org_id).with_for_update())
        row=db.scalar(select(MaxPowerMessengerTrial).where(
            MaxPowerMessengerTrial.id == trial_id).with_for_update())
        if not (org and state and state.enabled and
                state.session_generation == generation and
                row and row.status == "running" and row.claim_token == claim_token):
            return True  # The run was switched off or reclaimed; discard stale output.
        row.status,row.outcome,row.reason="completed",outcome,reason
        row.completed_at,row.lease_until=utcnow(),None
        row.claim_token=None
        row.metrics=metrics
        if state:
            state.experiments+=1
            state.examined_cases+=1
            state.latest_result={**metrics,"code":outcome,"reason":reason,
                "next":"Validar varios casos independientes antes de atribuir mejora"}
            state.last_status="messenger_"+outcome
            state.last_reason=reason
            db.add(MaxPowerEvent(org_id=row.org_id,event="messenger_experiment",
                reason=reason,evidence={"criterion":row.criterion,"variant":row.variant,
                "outcome":outcome,"objective_gain":metrics["objective_gain"],
                "production_verified":False,"model":QWEN_4B,
                "paired_latency_delta_ms":metrics["paired_latency_delta_ms"]}))
    return True
