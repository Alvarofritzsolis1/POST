"""Administrator-only management and exports for synthetic practice."""
from datetime import timedelta
import json
import re
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from .ai_models import AIConnection
from .db import get_db
from .galancito_flow import grounded_reply
from .galancito_knowledge_api import persist
from .galancito_knowledge_models import Knowledge, KnowledgeVersion
from .config import settings
from .galancito_general import QWEN_4B
from .galancito_local import MODEL
from .galancito_real_learning import (LIVE_DATASET_VERSION, LIVE_EVALUATION_VERSION,
                                      MAX_LIVE_CASES, GENERAL_COACH_TITLE, GENERAL_COACH_SCOPE,
                                      collect_live_cases, live_hash)
from .galancito_internal_training import (
    INTERNAL_CATEGORIES, INTERNAL_DATASET_VERSION, INTERNAL_EVALUATION_VERSION,
    INTERNAL_PROMPT, INTERNAL_PROPOSALS, INTERNAL_WEIGHTS, internal_case, internal_dataset_hash,
)
from .galancito_memory import approved_trade_aliases, aware
from .galancito_phone import redact_mobile_for_intake
from .galancito_training import DETAIL_DAYS, WORKER_STALE_SECONDS, eligible_at, round_view, summarize
from .galancito_training_data import DATASET_VERSION, MAX_CASES, MESSENGER_FOCUS, dataset_hash, digest, scenario
from .galancito_training_eval import CORRECTOR_PROMPT, CRITICAL, EVALUATION_VERSION, JUDGE_PROMPT, PROMPT, PROPOSALS, WEIGHTS, visible
from .galancito_training_models import ACTIVE, TERMINAL, TrainingCase, TrainingRound, TrainingWorker
from .galancito_triage import plain
from .models import AuditEvent, Organization, User, utcnow
from .security import administrator
from .version import SOURCE_COMMIT, VERSION

router = APIRouter(prefix="/api/v1/admin/ai/training", tags=["Galancito Evolution"])
PROMPT_VERSION = digest([PROMPT, JUDGE_PROMPT, CORRECTOR_PROMPT, WEIGHTS, EVALUATION_VERSION])
INTERNAL_PROMPT_VERSION = digest([INTERNAL_PROMPT, INTERNAL_WEIGHTS, INTERNAL_EVALUATION_VERSION])
SCOPE = "training"
REVIEW_COMMAND = "GALANT PRACTICA"


class RoundInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["postulantes", "interno"] = "postulantes"
    level: int = Field(default=1, ge=1, le=5)
    cases: int = Field(default=100, ge=1, le=MAX_CASES)
    cycles: int = Field(default=1, ge=1, le=40)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    suite: Literal["practice", "reference", "holdout", "live"] = "reference"
    focus: str = Field(default="", max_length=30)
    night: bool = False
    night_start: int = Field(default=23, ge=0, le=23)
    night_end: int = Field(default=7, ge=0, le=23)
    minutes: int = Field(default=480, ge=1, le=1440)
    concurrency: int = Field(default=0, ge=0, le=4)
    ram_limit_mb: int = Field(default=0, ge=0, le=384)
    cpu_limit_percent: int = Field(default=75, ge=10, le=90)
    token_budget: int = Field(default=6000000, ge=1, le=50000000)
    cost_budget: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    model: str = Field(default="ollama", max_length=36)
    profile_review: bool = False
    judge: str = Field(default="rules", max_length=36)
    corrector: str = Field(default="rules", max_length=36)

    @model_validator(mode="after")
    def validate_night(self):
        if self.night and self.night_start == self.night_end:
            raise ValueError("La hora inicial y final deben ser distintas")
        if self.suite == "live" and self.profile != "interno":
            raise ValueError("Los datos operativos reales solo corresponden a Galancito General")
        if self.suite == "live" and self.model != "ollama":
            raise ValueError("La evaluación operativa exige respuestas reales de Qwen, no reglas ni API externa")
        if self.suite == "live" and self.cases > MAX_LIVE_CASES:
            raise ValueError(f"Para datos reales admite como máximo {MAX_LIVE_CASES} casos por ciclo")
        if self.focus:
            allowed = INTERNAL_CATEGORIES if self.profile == "interno" else MESSENGER_FOCUS
            if self.suite == "live" or self.focus not in allowed:
                raise ValueError("Enfoque incompatible con este canal o con datos operativos reales")
        if self.profile == "postulantes" and self.focus and self.suite == "holdout" and self.cycles > 1:
            raise ValueError("La prueba reservada no admite épocas previas que reutilicen sus casos")
        if self.profile != "interno" and self.cycles != 1 and not self.focus:
            raise ValueError("En Messenger los ciclos especializados requieren una categoría enfocada")
        if self.cases * self.cycles > MAX_CASES:
            raise ValueError(f"El máximo es {MAX_CASES} evaluaciones totales por ejecución")
        if self.profile == "interno" and (self.profile_review or self.judge != "rules" or self.corrector != "rules"):
            raise ValueError("La práctica interna usa evaluación determinista; no aplica verificación de fichas ni juez externo")
        return self


class RepeatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_review: bool | None = None


class ApprovedCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    case_id: str = Field(min_length=1, max_length=100)
    turn: int = Field(ge=1, le=20)
    reply: str = Field(min_length=5, max_length=450)
    instruction: str = Field(min_length=5, max_length=300)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0)
    corrections: list[ApprovedCorrection] = Field(min_length=1, max_length=20)


class RollbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    restore_version: int = Field(ge=0)


def audit(db, user, action, resource):
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id, action="ai.training." + action, resource_id=resource))


def owned_round(db, org_id, round_id, *, lock=False):
    query = select(TrainingRound).where(TrainingRound.org_id == org_id, TrainingRound.id == round_id)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, "Ronda no encontrada")
    return row


def review_knowledge(db, org_id):
    return db.scalar(select(Knowledge).where(Knowledge.org_id == org_id, Knowledge.scope == SCOPE))


def knowledge_items(knowledge):
    return json.loads(knowledge.content) if knowledge and knowledge.status == "approved" else []


def model_info(db, user, identifier, role):
    if role == "model" and identifier == "guided":
        return {"id": identifier, "provider": "local", "model": "Reglas conversacionales"}
    if role in {"judge", "corrector"} and identifier == "rules":
        name = "Pruebas deterministas" if role == "judge" else "Correcciones por categoría"
        return {"id": identifier, "provider": "local", "model": name}
    if identifier == "ollama":
        # Snapshot the selected live model for new rounds. Existing rounds keep
        # their recorded model, instead of being silently relabeled.
        return {"id": identifier, "provider": "ollama",
                "model": settings().galancito_local_model}
    row = db.get(AIConnection, identifier)
    if not (row and row.org_id == user.org_id and row.enabled and row.encrypted_key and
            row.last_status == "verified" and row.price_input_per_million is not None and
            row.price_output_per_million is not None):
        raise HTTPException(422, "Elige una conexión verificada, habilitada y con tarifas registradas")
    return {"id": row.id, "provider": row.provider, "model": row.model,
            "priced": bool(row.price_input_per_million or row.price_output_per_million)}


@router.get("")
def overview(user: User = Depends(administrator), db: Session = Depends(get_db)):
    base = select(TrainingRound).where(TrainingRound.org_id == user.org_id)
    rows = list(db.scalars(base.order_by(TrainingRound.created_at.desc(), TrainingRound.id.desc()).limit(20)))
    active = next((row for row in rows if row.state in ACTIVE), None)
    if active is None:
        active = db.scalar(base.where(TrainingRound.state.in_(ACTIVE)))
    worker = db.get(TrainingWorker, 1)
    alive = bool(worker and aware(worker.updated_at) > utcnow() - timedelta(seconds=WORKER_STALE_SECONDS))
    review = review_knowledge(db, user.org_id)
    revisions = list(db.scalars(select(KnowledgeVersion.version).where(
        KnowledgeVersion.org_id == user.org_id, KnowledgeVersion.knowledge_id == review.id
    ).order_by(KnowledgeVersion.version.desc()).limit(15))) if review else []
    models = db.scalars(select(AIConnection).where(
        AIConnection.org_id == user.org_id, AIConnection.enabled.is_(True),
        AIConnection.encrypted_key.is_not(None), AIConnection.last_status == "verified",
        AIConnection.price_input_per_million.is_not(None), AIConnection.price_output_per_million.is_not(None),
    ).order_by(AIConnection.name).limit(50))
    return {"active_id": active.id if active else None, "rounds": [round_view(row) for row in rows],
            "worker": {"available": alive, "seen": aware(worker.updated_at) if worker else None,
                       "resources": worker.resources if worker else None},
            "knowledge": {"version": review.version if review else 0, "revisions": revisions,
                          "corrections": knowledge_items(review)},
            "providers": [{"id": row.id, "label": row.name, "model": row.model} for row in models],
            "weights": WEIGHTS, "internal_weights": INTERNAL_WEIGHTS,
            "internal_categories": INTERNAL_CATEGORIES, "detail_days": DETAIL_DAYS,
            "local_model": settings().galancito_local_model,
            "training_mode": "motor_principal_compartido" if settings().galancito_local_model != MODEL
                             else "ollama_entrenamiento_aislado"}


def start(db, user, body, *, previous=None, compare_profile=False):
    config = body.model_dump()
    config["seed"] = secrets.randbelow(2**31) if body.seed is None else body.seed
    internal = body.profile == "interno"
    if internal and body.model == "ollama" and settings().galancito_local_model != QWEN_4B:
        raise HTTPException(422, "Galancito General requiere activar y verificar Qwen3.5 4B antes de practicar con Ollama. Puedes usar reglas sintéticas.")
    live = internal and body.suite == "live"
    config["dataset_version"] = (LIVE_DATASET_VERSION if live else
                                 INTERNAL_DATASET_VERSION if internal else DATASET_VERSION)
    config["evaluation_version"] = (LIVE_EVALUATION_VERSION if live else
                                    INTERNAL_EVALUATION_VERSION if internal else EVALUATION_VERSION)
    if live:
        try:
            config["live_cases"] = (previous.config["live_cases"]
                                    if previous is not None and previous.config.get("suite") == "live"
                                    else collect_live_cases(db, user))
            config["snapshot_reused"] = previous is not None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if body.cases * 2 > len(config["live_cases"]):
            raise HTTPException(422, f"Hay {len(config['live_cases'])} escenarios reales. Reduce a {len(config['live_cases']) // 2} casos por ciclo para reservar otros tantos sin usar para validación")
        if body.cycles < 4 or body.cases < 4:
            raise HTTPException(422, "Se requieren al menos 4 casos y 4 ciclos: práctica, corrección y prueba reservada A/B")
    config["model"] = model_info(db, user, body.model, "model")
    config["judge"] = model_info(db, user, body.judge, "judge")
    config["corrector"] = model_info(db, user, body.corrector, "corrector")
    if any(config[role].get("priced") for role in ("model", "judge", "corrector")) and not body.cost_budget:
        raise HTTPException(422, "Indica un presupuesto en USD para la conexión seleccionada")
    fingerprint = (live_hash(config) if live else
                   internal_dataset_hash(config) if internal else dataset_hash(config))
    if previous is not None and fingerprint != previous.dataset_hash:
        raise HTTPException(409, "El generador cambió desde la ronda anterior. Inicia una nueva referencia.")
    # Serialize starts and approvals for a consistent knowledge snapshot.
    db.scalar(select(Organization.id).where(Organization.id == user.org_id).with_for_update())
    current = db.scalar(select(TrainingRound.id).where(
        TrainingRound.org_id == user.org_id, TrainingRound.state.in_(ACTIVE)))
    if current:
        raise HTTPException(409, "Ya existe una ronda activa para esta organización")
    comparable = previous or db.scalar(select(TrainingRound).where(
        TrainingRound.org_id == user.org_id, TrainingRound.dataset_hash == fingerprint,
        TrainingRound.state == "completed",
    ).order_by(TrainingRound.created_at.desc()).limit(1))
    external = any(config[role]["id"] not in {"guided", "rules", "ollama"}
                   for role in ("model", "judge", "corrector"))
    review = None if external or internal else review_knowledge(db, user.org_id)
    knowledge = [{**item, "id": review.id, "version": review.version} for item in knowledge_items(review)]
    aliases = {} if external or internal else approved_trade_aliases(db, user.org_id)
    if compare_profile and (previous.state != "completed" or previous.completed != previous.target):
        raise HTTPException(409, "Completa todos los casos de la ronda base antes de comparar.")
    if compare_profile and (
        previous.config.get("evaluation_version") != config["evaluation_version"]
        or previous.prompt_version != (digest(["operational", LIVE_DATASET_VERSION, LIVE_EVALUATION_VERSION]) if live
                                      else INTERNAL_PROMPT_VERSION if internal else PROMPT_VERSION)
        or previous.knowledge != knowledge or previous.aliases != aliases
        or any(previous.config.get(role) != config[role] for role in ("model", "judge", "corrector"))
    ):
        raise HTTPException(409, "La evaluación, la conexión o el conocimiento cambió. Repite primero la ronda base.")
    scheduled = eligible_at(config, utcnow())
    row = TrainingRound(org_id=user.org_id, created_by=user.id, target=body.cases * body.cycles, config=config,
                        dataset_hash=fingerprint, system_version=f"{VERSION}@{SOURCE_COMMIT}",
                        prompt_version=(digest(["operational", LIVE_DATASET_VERSION, LIVE_EVALUATION_VERSION]) if live else
                                        INTERNAL_PROMPT_VERSION if internal else PROMPT_VERSION),
                        previous_id=comparable.id if comparable else None,
                        aliases=aliases, knowledge=knowledge, next_at=scheduled)
    try:
        db.add(row)
        db.flush()
        audit(db, user, "queue", row.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe una ronda activa para esta organización") from None
    return round_view(row)


@router.post("/rounds", status_code=201)
def create_round(body: RoundInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    return start(db, user, body)


@router.post("/rounds/{round_id}/repeat", status_code=201)
def repeat_round(round_id: str, body: RepeatInput | None = None, user: User = Depends(administrator),
                 db: Session = Depends(get_db)):
    previous = owned_round(db, user.org_id, round_id)
    if previous.state not in TERMINAL:
        raise HTTPException(409, "Espera a que termine la ronda original")
    config = {key: value for key, value in previous.config.items() if key in RoundInput.model_fields}
    config.update(model=config["model"]["id"], judge=config["judge"]["id"],
                  corrector=config.get("corrector", {"id": "rules"})["id"], night=False)
    compare_profile = body is not None and body.profile_review is not None
    if compare_profile:
        config["profile_review"] = body.profile_review
    return start(db, user, RoundInput.model_validate(config), previous=previous, compare_profile=compare_profile)


@router.post("/rounds/{round_id}/control/{action}")
def control_round(round_id: str, action: Literal["pause", "resume", "stop"],
                  user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = owned_round(db, user.org_id, round_id, lock=True)
    if action == "pause" and row.state in ACTIVE:
        row.state, row.reason = "paused", "Pausado por administración"
    elif action == "resume" and row.state == "paused":
        row.state, row.reason, row.next_at, row.attempts = "queued", None, eligible_at(row.config, utcnow()), 0
    elif action == "stop" and row.state in ACTIVE:
        row.state, row.reason = "stopped", "Detenido por administración"
        row.lease = row.lease_until = None
        row.finished_at = utcnow()
    else:
        raise HTTPException(409, "La ronda cambió de estado. Actualiza la vista.")
    audit(db, user, action, row.id)
    db.commit()
    return round_view(row)


@router.get("/rounds/{round_id}/errors")
def errors(round_id: str, offset: int = Query(default=0, ge=0, le=MAX_CASES),
           user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = owned_round(db, user.org_id, round_id)
    items = list(db.scalars(select(TrainingCase).where(
        TrainingCase.round_id == row.id, TrainingCase.passed.is_(False),
    ).order_by(TrainingCase.position).offset(offset).limit(21)))
    cases = [item.result for item in items[:20]]
    if row.config["suite"] == "holdout":
        cases = [{key: case[key] for key in ("id", "errors", "critical")} for case in cases]
    return {"cases": cases, "more": len(items) > 20,
            "proposals": INTERNAL_PROPOSALS if row.config.get("profile") == "interno" else PROPOSALS}


@router.post("/rounds/{round_id}/corrections", status_code=201)
def approve(round_id: str, body: ReviewInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = owned_round(db, user.org_id, round_id)
    if row.config.get("profile") == "interno":
        raise HTTPException(422, "Las rondas internas se evalúan por separado y no modifican el conocimiento de postulantes")
    if row.state not in TERMINAL or row.config["suite"] == "holdout":
        raise HTTPException(409, "Usa una ronda finalizada de referencia o práctica para preparar correcciones")
    db.scalar(select(Organization.id).where(Organization.id == user.org_id).with_for_update())
    current = review_knowledge(db, user.org_id)
    if body.version != (current.version if current else 0):
        raise HTTPException(409, "El conocimiento cambió. Actualiza la vista y vuelve a revisar el lote.")
    by_phrase = {plain(item["phrase"]): item for item in knowledge_items(current)}
    for correction in body.corrections:
        item = db.scalar(select(TrainingCase).where(TrainingCase.round_id == row.id,
                         TrainingCase.case_id == correction.case_id, TrainingCase.passed.is_(False)))
        if item is None:
            raise HTTPException(422, "Cada corrección debe corresponder a un caso fallido de esta ronda")
        case = scenario(row.config, item.position) if row.config["dataset_version"] == DATASET_VERSION else None
        if case is None or case.id != correction.case_id or correction.turn > len(case.turns):
            raise HTTPException(422, "El turno o la versión del escenario no está disponible")
        phrase = case.turns[correction.turn - 1][0]
        supplied = " ".join(message for message, _ in case.turns[:correction.turn])
        if (any(visible(value) != value for value in (phrase, correction.reply, correction.instruction)) or
                grounded_reply(correction.reply, supplied) != correction.reply or
                any(re.search(rule, plain(correction.reply)) for rule in CRITICAL)):
            raise HTTPException(422, "La corrección contiene datos reservados, cifras nuevas o una afirmación no permitida")
        prior = [visible(redact_mobile_for_intake(message))
                 for message, _ in case.turns[max(0, correction.turn - 9):correction.turn - 1]]
        by_phrase[plain(phrase)] = {"phrase": phrase, "reply": correction.reply, "context": prior,
                                  "instruction": correction.instruction, "case_id": correction.case_id}
    if len(by_phrase) > 100:
        raise HTTPException(422, "El conocimiento activo admite 100 correcciones")
    if current is None:
        current = Knowledge(org_id=user.org_id, title="Correcciones aprobadas de Galancito Evolution",
                            category="Entrenamiento", kind="correction", scope=SCOPE,
                            updated_by=user.id, phrases=[])
        db.add(current)
    current.content = json.dumps(list(by_phrase.values()), ensure_ascii=False)
    current.status, current.approved_by = "approved", user.id
    audit(db, user, "approve", row.id)
    return {"version": persist(db, current, user)["version"], "count": len(by_phrase)}


@router.post("/rounds/{round_id}/promote-live")
def promote_live(round_id: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Human-approved promotion of measured coaching, never of raw model output.

    The isolated laboratory cannot silently modify production prompts. A
    promotion requires a full Qwen run, an improvement on repeated real data,
    and a clean minimum-quality result on unseen verified real aggregates.
    Only fixed, reviewed rules enter production; no case data is published.
    """
    row = owned_round(db, user.org_id, round_id)
    cycles = row.metrics.get("cycles", {})
    last = cycles.get(str(row.config.get("cycles", 1)), {})
    if not (row.config.get("profile") == "interno" and row.config.get("suite") == "live"
            and row.config.get("model", {}).get("id") == "ollama"
            and row.state == "completed" and row.completed == row.target
            and row.metrics.get("real_learning_demonstrated") is True
            and last.get("holdout_role") == "candidate" and last.get("critical") == 0
            and row.metrics.get("real_holdout_gain_cases", 0) >= 1
            and row.metrics.get("real_holdout_regressions", 1) == 0
            and row.metrics.get("real_holdout_pass_rate", 0) >= 0.75):
        raise HTTPException(409, "Sin aprendizaje verificable, ciclo completo y prueba reservada aprobada")
    from .galancito_real_learning import PRODUCTION_COACHING
    # Deterministic allowlist prevents model-produced or dataset-derived text
    # from entering prompts or leaking organization information.
    allowed = set(PRODUCTION_COACHING)
    instructions = [item for item in row.metrics.get("real_coaching", [])
                    if item in allowed][:3]
    if not instructions:
        raise HTTPException(409, "No hay cambios de comportamiento evaluados")
    applied = [PRODUCTION_COACHING[instruction] for instruction in instructions]
    content = ("Para análisis de datos internos, aplica únicamente estas reglas "
               "de razonamiento a información ya verificada por el servidor. "
               "Nunca inventes cifras, accesos, cambios ni acciones:\n" +
               "\n".join(applied))
    db.scalar(select(Organization.id).where(Organization.id == user.org_id).with_for_update())
    current = db.scalar(select(Knowledge).where(
        Knowledge.org_id == user.org_id,
        Knowledge.scope == GENERAL_COACH_SCOPE, Knowledge.title == GENERAL_COACH_TITLE
    ).with_for_update())
    if current and current.content == content and current.status == "approved":
        return {"status": "already_approved", "version": current.version,
                "knowledge_id": current.id}
    if current is None:
        current = Knowledge(org_id=user.org_id, title=GENERAL_COACH_TITLE,
                            category="Razonamiento operacional", kind="correction",
                            scope=GENERAL_COACH_SCOPE, phrases=[],
                            content=content, status="approved", updated_by=user.id,
                            approved_by=user.id)
        db.add(current)
    else:
        current.content, current.status, current.approved_by = content, "approved", user.id
    audit(db, user, "promote_live", row.id)
    return {"status": "approved", "version": persist(db, current, user)["version"],
            "knowledge_id": current.id}


@router.post("/knowledge/rollback")
def rollback(body: RollbackInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    db.scalar(select(Organization.id).where(Organization.id == user.org_id).with_for_update())
    current = review_knowledge(db, user.org_id)
    if current is None or current.version != body.version:
        raise HTTPException(409, "El conocimiento cambió. Actualiza la vista.")
    snapshot = db.scalar(select(KnowledgeVersion).where(
        KnowledgeVersion.org_id == user.org_id, KnowledgeVersion.knowledge_id == current.id,
        KnowledgeVersion.version == body.restore_version))
    if body.restore_version and snapshot is None:
        raise HTTPException(404, "Versión no encontrada")
    current.content = snapshot.snapshot["content"] if snapshot else "[]"
    current.status = "approved" if snapshot and snapshot.snapshot["status"] == "approved" else "disabled"
    current.approved_by = user.id if current.status == "approved" else None
    audit(db, user, "rollback", current.id)
    return {"version": persist(db, current, user)["version"]}


def attachment(body: str, content_type: str, filename: str):
    return Response(body, media_type=content_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store",
    })


@router.get("/rounds/{round_id}/export/{kind}")
def export_round(round_id: str, kind: Literal["json", "md"], user: User = Depends(administrator),
                 db: Session = Depends(get_db)):
    row = owned_round(db, user.org_id, round_id)
    profile = row.config.get("profile", "postulantes")
    internal = profile == "interno"
    weights = INTERNAL_WEIGHTS if internal else WEIGHTS
    proposals = INTERNAL_PROPOSALS if internal else PROPOSALS
    metrics = summarize(row.metrics, profile)
    examples = list(db.scalars(select(TrainingCase.result).where(
        TrainingCase.round_id == row.id, TrainingCase.passed.is_(False),
    ).order_by(TrainingCase.position).limit(12)))
    if row.config["suite"] == "holdout":
        examples = [{"id": case["id"], "errors": case["errors"], "critical": case["critical"]} for case in examples]
    elif row.knowledge or row.aliases:
        examples = [{**case, "evidence": {}, "turns": [{**turn, "reply": "[reservada por conocimiento de la organización]",
                                      "candidate_reply": None, "differences": dict.fromkeys(turn["differences"])}
                                     for turn in case["turns"]]} for case in examples]
    previous = db.scalar(select(TrainingRound).where(TrainingRound.org_id == user.org_id,
                         TrainingRound.id == row.previous_id)) if row.previous_id else None
    comparison = None
    if previous:
        old = summarize(previous.metrics, previous.config.get("profile", "postulantes"))
        before = aliased(TrainingCase)
        regressions = db.scalar(select(func.count()).select_from(TrainingCase).join(
            before, and_(before.round_id == previous.id, before.position == TrainingCase.position)).where(
            TrainingCase.round_id == row.id, TrainingCase.passed.is_(False), before.passed.is_(True)))
        retained = aware(previous.finished_at) and aware(previous.finished_at) >= utcnow() - timedelta(days=DETAIL_DAYS)
        same_evaluation = (row.config.get("evaluation_version", 1) == previous.config.get("evaluation_version", 1)
                           and row.config["judge"] == previous.config["judge"]
                           and (metrics["dimensions"].get("naturalness") is None)
                           == (old["dimensions"].get("naturalness") is None))
        comparison = {"id": previous.id, "metrics": old, "same_evaluation": same_evaluation,
                      "profile_review": previous.config.get("profile_review", False),
                      "regressions": regressions if retained and same_evaluation else None,
                      "score_difference": round(metrics["score"] - old["score"], 2)
                      if same_evaluation and metrics["score"] is not None and old["score"] is not None else None}
    info = {"command": REVIEW_COMMAND, "source": "agregados_reales_laboratorio" if row.config["suite"] == "live" else "simulacion_sintetica",
            "round_id": row.id,
            "system_version": row.system_version, "prompt_version": row.prompt_version,
            "dataset_hash": row.dataset_hash, "dataset_version": row.config["dataset_version"],
            "state": row.state, "processed": row.completed, "target": row.target,
            "evaluation_version": row.config.get("evaluation_version", 1),
            "profile_review": row.config.get("profile_review", False),
            "profile": profile, "suite": row.config["suite"], "level": row.config["level"], "metrics": metrics,
            "weights": weights, "targets": {"profile_accuracy": 0.95, "conversational_criteria": 0.9,
                                             "repetition_below": 0.03, "critical_max": 0},
            "confidence": {"cases": row.completed,
                "sample": ("Agregados operativos congelados; no equivalen a conversaciones de producción."
                           if row.config["suite"] == "live" else
                           "Casos sintéticos. Los turnos de una conversación no son independientes.")},
            "models": {role: {k: row.config[role][k] for k in ("provider", "model")}
                       for role in ("model", "judge", "corrector") if role in row.config},
            "knowledge_versions": sorted({item["version"] for item in row.knowledge}),
            "approved_corrections": len(row.knowledge), "comparison": comparison,
            "proposals": {code: proposals.get(code, "Revisar el caso") for code in metrics["error_counts"]}, "examples": examples}
    name = f"galant-practica-{row.id}.{kind}"
    if kind == "json":
        return attachment(json.dumps(info, ensure_ascii=False, indent=2), "application/json", name)
    lines = [f"# {REVIEW_COMMAND}", "", f"- Ronda `{row.id}`",
             f"- Sistema `{row.system_version}` y prompt `{row.prompt_version}`",
             f"- Dataset `{row.dataset_hash}` · perfil {profile} · nivel {row.config['level']} · {row.config['suite']}",
             f"- {row.completed} / {row.target} casos sintéticos procesados",
             f"- {metrics['passed']} correctos, {metrics['failed']} incorrectos y {metrics['critical']} alertas críticas",
             f"- Respuesta con {info['models']['model']['model']} y revisión con {info['models']['judge']['model']}.",
             f"- Verificación local de ficha {'activa' if info['profile_review'] else 'inactiva'}.",
             f"- {metrics['fields']} campos presentes evaluados en {metrics['turns']} turnos.",
             f"- {metrics['judged_turns']} turnos revisados por un modelo de naturalidad.",
             f"- Correcciones aprobadas incluidas en la ronda: {len(row.knowledge)}."]
    if metrics["reply_sources"] is not None:
        sources = metrics["reply_sources"]
        lines.append(f"- Respuestas por origen: {sources.get('model', 0)} de IA, {sources.get('rules', 0)} de reglas, "
                     f"{sources.get('approved_correction', 0)} revisadas y {sources.get('fallback', 0)} de respaldo.")
    lines += ["", "## Resultados por competencia", "", "| Competencia | Resultado | Peso |",
              "| --- | ---: | ---: |"]
    for dimension, weight in weights.items():
        value = metrics["dimensions"][dimension]
        formatted = f"{value:.1%}" if value is not None else "Sin muestra"
        lines.append(f"| {dimension} | {formatted} | {weight}% |")
    if metrics["questions"]:
        lines += ["", f"Preguntas que volvieron a pedir datos entregados: {metrics['repeated_questions']} "
                  f"de {metrics['questions']} ({metrics['repetition_rate']:.1%})."]
    if comparison:
        lines += ["", f"## Comparación con {previous.id}", ""]
        if comparison["same_evaluation"]:
            lines.append(f"Diferencia en puntuación: {comparison['score_difference']}. Regresiones: {comparison['regressions']}.")
        else:
            lines.append("La metodología o el evaluador cambió. Ejecuta las dos rondas con la misma evaluación para comparar.")
    lines += ["", "## Propuestas de revisión", ""]
    lines.extend(f"- {metrics['error_counts'][code]} alertas de {code}. {proposal}"
                 for code, proposal in info["proposals"].items())
    for example in examples:
        lines += ["", f"### Caso {example['id']}", ""]
        if example.get("ai_proposal"):
            lines.append("Propuesta del modelo para revisión: " + example["ai_proposal"])
        for turn in example.get("turns", []):
            lines += [f"- Persona: {turn['message']}", f"  Galancito: {turn['reply']}",
                      "  Fallas: " + ", ".join(turn.get("issues", [])),
                      "  Diferencias: " + json.dumps(turn["differences"], ensure_ascii=False),
                      "  Esperado: " + json.dumps(turn["expected"], ensure_ascii=False)]
    lines += ["", "Revisa primero las alertas críticas y prepara instrucciones para la siguiente ronda.",
              "La naturalidad es una estimación del modelo evaluador y se calcula sobre los turnos revisados. "
              "La puntuación global pondera solo las competencias medidas."]
    return attachment("\n".join(lines) + "\n", "text/markdown", name)


@router.get("/knowledge/dataset/{split}")
def export_dataset(split: Literal["train", "validation", "test"],
                   user: User = Depends(administrator), db: Session = Depends(get_db)):
    samples = []
    for item in knowledge_items(review_knowledge(db, user.org_id)):
        bucket = int(digest(plain(item["phrase"]))[:8], 16) % 10
        if split == ("train" if bucket < 8 else "validation" if bucket == 8 else "test"):
            samples.append(json.dumps({"messages": [
                {"role": "user", "content": "\n".join([*item.get("context", []), item["phrase"]])},
                {"role": "assistant", "content": item["reply"]},
            ]}, ensure_ascii=False))
    return attachment("".join(sample + "\n" for sample in samples),
                      "application/x-ndjson", f"galancito-{split}.jsonl")
