"""Admin-only AI connection center. No endpoint returns plaintext credentials."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ai_gateway import (
    AIServiceError, MODEL_RE, PROVIDERS, TASKS, encrypt_key, encryption_ready, monthly_tokens,
    run_connection,
)
from .ai_models import AIConnection, AIOrchestration, AIUsage
from .ai_model_recovery import recover_gemini
from .ai_provider_recovery import recover_provider
from .galancito_knowledge_models import Knowledge, AssistantRun
from .db import get_db
from .models import AuditEvent, User, utcnow
from .security import administrator

router = APIRouter(prefix="/api/v1/admin/ai", tags=["Centro de IA"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectionCreate(Strict):
    name: str = Field(min_length=2, max_length=80)
    provider: str
    model: str = Field(min_length=2, max_length=160)
    api_key: str | None = Field(default=None, max_length=4096)
    enabled: bool = False
    price_input_per_million: Decimal | None = Field(default=None, ge=0, le=100000)
    price_output_per_million: Decimal | None = Field(default=None, ge=0, le=100000)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Ingresa un nombre para identificar la conexión")
        return value

    @field_validator("provider")
    @classmethod
    def supported_provider(cls, value):
        if value not in PROVIDERS:
            raise ValueError("Proveedor no admitido")
        return value

    @field_validator("model")
    @classmethod
    def clean_model(cls, value):
        if not MODEL_RE.fullmatch(value):
            raise ValueError("Identificador de modelo inválido")
        return value


class ConnectionPatch(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    model: str | None = Field(default=None, min_length=2, max_length=160)
    api_key: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None
    price_input_per_million: Decimal | None = Field(default=None, ge=0, le=100000)
    price_output_per_million: Decimal | None = Field(default=None, ge=0, le=100000)

    @field_validator("model")
    @classmethod
    def clean_model(cls, value):
        if value is not None and not MODEL_RE.fullmatch(value):
            raise ValueError("Identificador de modelo inválido")
        return value


class PolicyPatch(Strict):
    enabled: bool = False
    fallback_enabled: bool = False
    review_enabled: bool = False
    monthly_token_limit: int = Field(default=0, ge=0, le=1000000000)
    task_routes: dict[str, str] = Field(default_factory=dict)


def connection_view(record: AIConnection) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "provider": record.provider,
        "model": record.model,
        "enabled": record.enabled,
        "has_key": bool(record.encrypted_key),
        "status": "disconnected" if not record.encrypted_key else record.last_status,
        "last_checked_at": record.last_checked_at,
        "price_input_per_million": float(record.price_input_per_million) if record.price_input_per_million is not None else None,
        "price_output_per_million": float(record.price_output_per_million) if record.price_output_per_million is not None else None,
        "updated_at": record.updated_at,
    }


def policy_view(record: AIOrchestration | None) -> dict:
    return {
        "enabled": bool(record and record.enabled),
        "fallback_enabled": bool(record and record.fallback_enabled),
        "review_enabled": bool(record and record.review_enabled),
        "monthly_token_limit": record.monthly_token_limit if record else 0,
        "task_routes": (record.task_routes or {}) if record else {},
    }


def log_change(db: Session, user: User, action: str, resource_id: str | None = None):
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="ai." + action, resource_id=resource_id))


def existing(db: Session, user: User, connection_id: str) -> AIConnection:
    record = db.get(AIConnection, connection_id)
    if not record or record.org_id != user.org_id:
        raise HTTPException(404, "Conexión IA no encontrada")
    return record


@router.get("/bootstrap")
def bootstrap(user: User = Depends(administrator), db: Session = Depends(get_db)):
    connections = list(db.scalars(select(AIConnection).where(
        AIConnection.org_id == user.org_id).order_by(AIConnection.name)))
    policy = db.get(AIOrchestration, user.org_id)
    knowledge_counts = dict(db.execute(select(Knowledge.status, func.count(Knowledge.id)).where(
        Knowledge.org_id == user.org_id).group_by(Knowledge.status)).all())
    feedback_rows = db.execute(select(AssistantRun.feedback, func.count(AssistantRun.id)).where(
        AssistantRun.org_id == user.org_id, AssistantRun.feedback.is_not(None))
        .group_by(AssistantRun.feedback)).all()
    return {
        "learning": {
            "approved": knowledge_counts.get("approved", 0),
            "pending": knowledge_counts.get("pending", 0),
            "disabled": knowledge_counts.get("disabled", 0),
            "feedback": dict(feedback_rows),
            "method": "curated_retrieval_no_weight_training",
        },
        "providers": [{"id": key, **value} for key, value in PROVIDERS.items()],
        "tasks": [{"id": key, "name": value, "active": key in {"red_obras", "messenger", "review"}} for key, value in TASKS.items()],
        "connections": [connection_view(c) for c in connections],
        "policy": policy_view(policy),
        "monthly_tokens": monthly_tokens(db, user.org_id),
        "server_ready": encryption_ready(),
    }


@router.post("/connections", status_code=201)
def create_connection(body: ConnectionCreate, user: User = Depends(administrator),
                      db: Session = Depends(get_db)):
    try:
        encrypted = encrypt_key(body.api_key) if body.api_key else None
    except AIServiceError as exc:
        raise HTTPException(503, str(exc)) from None
    if body.enabled and not encrypted:
        raise HTTPException(422, "Guarda una API Key antes de activar la conexión")
    conn = AIConnection(
        org_id=user.org_id, updated_by=user.id, name=body.name, provider=body.provider,
        model=body.model, enabled=body.enabled, encrypted_key=encrypted,
        price_input_per_million=body.price_input_per_million,
        price_output_per_million=body.price_output_per_million,
    )
    db.add(conn)
    try:
        db.flush()
        log_change(db, user, "connection.create", conn.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe una conexión con ese nombre") from None
    return connection_view(conn)


@router.patch("/connections/{connection_id}")
def edit_connection(connection_id: str, body: ConnectionPatch,
                    user: User = Depends(administrator), db: Session = Depends(get_db)):
    conn = existing(db, user, connection_id)
    fields = body.model_fields_set
    if "name" in fields:
        if not body.name or not body.name.strip():
            raise HTTPException(422, "El nombre no puede quedar vacío")
        conn.name = " ".join(body.name.split())
    if "model" in fields:
        if not body.model:
            raise HTTPException(422, "El modelo no puede quedar vacío")
        if conn.model != body.model:
            conn.model = body.model
            conn.last_status = "not_tested"
    if "api_key" in fields and body.api_key:
        try:
            conn.encrypted_key = encrypt_key(body.api_key)
        except AIServiceError as exc:
            raise HTTPException(503, str(exc)) from None
        conn.last_status = "not_tested"
        conn.last_checked_at = None
    if "enabled" in fields:
        if body.enabled and not conn.encrypted_key:
            raise HTTPException(422, "Configura primero la API Key")
        conn.enabled = bool(body.enabled)
    if "price_input_per_million" in fields:
        conn.price_input_per_million = body.price_input_per_million
    if "price_output_per_million" in fields:
        conn.price_output_per_million = body.price_output_per_million
    conn.updated_by, conn.updated_at = user.id, utcnow()
    log_change(db, user, "connection.update", conn.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "El nombre ya está en uso") from None
    return connection_view(conn)


@router.post("/connections/{connection_id}/disconnect")
def disconnect(connection_id: str, user: User = Depends(administrator),
               db: Session = Depends(get_db)):
    conn = existing(db, user, connection_id)
    conn.encrypted_key, conn.enabled = None, False
    conn.last_status, conn.last_checked_at = "not_tested", None
    conn.updated_by, conn.updated_at = user.id, utcnow()
    policy = db.get(AIOrchestration, user.org_id)
    if policy:
        policy.task_routes = {task: ident for task, ident in (policy.task_routes or {}).items()
                              if ident != conn.id}
        if not policy.task_routes.get("red_obras"):
            policy.enabled = False
        if not policy.task_routes.get("review"):
            policy.review_enabled = False
        policy.updated_by, policy.updated_at = user.id, utcnow()
    log_change(db, user, "connection.disconnect", conn.id)
    db.commit()
    return connection_view(conn)


@router.post("/connections/{connection_id}/test")
def test_connection(connection_id: str, user: User = Depends(administrator),
                    db: Session = Depends(get_db)):
    conn = existing(db, user, connection_id)
    if not conn.encrypted_key:
        raise HTTPException(422, "Ingresa primero la API Key")
    try:
        answer = run_connection(db, conn, task="connection_test",
                                instructions="Responde brevemente en español.",
                                prompt="Prueba de conexión. Responde OK.",
                                max_output_tokens=(512 if (conn.provider == "zai" or "gpt-oss" in conn.model) else 128))
        log_change(db, user, "connection.test", conn.id)
        db.commit()
    except AIServiceError as exc:
        log_change(db, user, "connection.test_failed", conn.id)
        db.commit()
        return {"ok": False, "message": str(exc), "connection": connection_view(conn)}
    return {"ok": True, "message": "Conexión verificada: " + answer[:60],
            "connection": connection_view(conn)}


@router.post("/connections/{connection_id}/recover")
def recover_connection(connection_id: str, user: User = Depends(administrator),
                       db: Session = Depends(get_db)):
    """One-click repair for supported providers; never returns a key."""
    conn = existing(db, user, connection_id)
    if conn.provider not in ("gemini", "groq", "nvidia", "zai"):
        raise HTTPException(422, "La recuperación automática no está disponible para este proveedor")
    if not conn.encrypted_key:
        raise HTTPException(422, "Primero guarda una API Key de este proveedor")
    try:
        outcome = recover_gemini(db, conn) if conn.provider == "gemini" else recover_provider(db, conn)
    except AIServiceError as exc:
        # Credential, network or listing errors are safe to display, not the API body.
        outcome = {"ok": False, "message": str(exc), "attempts": 0}
    log_change(db, user, "connection.auto_recover" if outcome["ok"] else "connection.auto_recover_failed", conn.id)
    db.commit()
    return {**outcome, "connection": connection_view(conn)}


@router.get("/usage")
def usage(days: int = Query(default=30, ge=1, le=365),
          user: User = Depends(administrator), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(select(
        AIUsage.connection_id, AIUsage.task, AIUsage.status,
        func.count(AIUsage.id), func.sum(AIUsage.input_tokens),
        func.sum(AIUsage.output_tokens), func.sum(AIUsage.total_tokens),
        func.sum(AIUsage.estimated_cost_usd),
        func.count(AIUsage.estimated_cost_usd),
    ).where(AIUsage.org_id == user.org_id, AIUsage.created_at >= since)
     .group_by(AIUsage.connection_id, AIUsage.task, AIUsage.status)).all()
    connections = {c.id: c for c in db.scalars(select(AIConnection).where(
        AIConnection.org_id == user.org_id))}
    groups = []
    for id_, task, status, calls, inp, out, total, cost, priced in rows:
        conn = connections.get(id_)
        groups.append({
            "connection_id": id_, "provider": conn.provider if conn else "unknown",
            "name": conn.name if conn else "Conexión anterior", "task": task,
            "status": status, "calls": int(calls), "input_tokens": int(inp or 0),
            "output_tokens": int(out or 0), "total_tokens": int(total or 0),
            "estimated_cost_usd": round(float(cost), 6) if cost is not None else None,
            "priced_calls": int(priced),
        })
    return {
        "days": days,
        "groups": groups,
        "total_calls": sum(g["calls"] for g in groups),
        "total_tokens": sum(g["total_tokens"] for g in groups),
        "input_tokens": sum(g["input_tokens"] for g in groups),
        "output_tokens": sum(g["output_tokens"] for g in groups),
        "estimated_cost_usd": round(sum(g["estimated_cost_usd"] or 0 for g in groups), 6),
        "unpriced_calls": sum(g["calls"] - g["priced_calls"] for g in groups),
    }


@router.put("/policy")
def update_policy(body: PolicyPatch, user: User = Depends(administrator),
                  db: Session = Depends(get_db)):
    if any(task not in TASKS for task in body.task_routes):
        raise HTTPException(422, "Función IA desconocida")
    for task, connection_id in body.task_routes.items():
        record = db.get(AIConnection, connection_id)
        if not record or record.org_id != user.org_id or not record.encrypted_key:
            raise HTTPException(422, "La IA asignada a " + task + " no está vinculada")
        if body.enabled and (not record.enabled or record.last_status != "verified"):
            raise HTTPException(422, "Primero habilita y verifica la conexión asignada a " + task)
    if body.enabled and not body.task_routes.get("red_obras"):
        raise HTTPException(422, "Asigna la IA de Consultas de Red de Obras antes de activar el equipo")
    if body.enabled and body.review_enabled:
        primary = body.task_routes.get("red_obras")
        reviewer = body.task_routes.get("review")
        if not reviewer or reviewer == primary:
            raise HTTPException(422, "Asigna una segunda IA distinta para revisar las respuestas")
        first, second = db.get(AIConnection, primary), db.get(AIConnection, reviewer)
        if first and second and (first.provider, first.model) == (second.provider, second.model):
            raise HTTPException(422, "El revisor debe utilizar un modelo diferente al principal")
        messenger = body.task_routes.get("messenger")
        if messenger:
            reply_model = db.get(AIConnection, messenger)
            if messenger == reviewer or (reply_model and second and
                                         (reply_model.provider, reply_model.model) ==
                                         (second.provider, second.model)):
                raise HTTPException(422, "El revisor de Messenger debe utilizar un modelo diferente")
    policy = db.get(AIOrchestration, user.org_id)
    if policy is None:
        policy = AIOrchestration(org_id=user.org_id)
        db.add(policy)
    policy.enabled = body.enabled
    policy.fallback_enabled = body.fallback_enabled
    policy.review_enabled = body.review_enabled
    policy.monthly_token_limit = body.monthly_token_limit
    policy.task_routes = body.task_routes
    policy.updated_by, policy.updated_at = user.id, utcnow()
    log_change(db, user, "policy.update")
    db.commit()
    return policy_view(policy)
