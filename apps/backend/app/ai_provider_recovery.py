"""Recover Groq and Z.ai connections without ever returning or logging API Keys.

Groq: ask the official account model catalog, then test actual Chat Completions.
Z.ai: no assumption about a catalog endpoint; test a small documented allowlist
on the Standard API endpoint ONLY. Coding Plan is not supported for GALANT.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import Request

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ai_gateway
from .ai_gateway import AIServiceError, MODEL_RE, decrypt_key, run_connection
from .ai_models import AIConnection
from .models import utcnow

GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
MAX_PROBES = 3
ZAI_MODELS = ("glm-4.7", "glm-5.3-flash")


def _priority(model: str) -> tuple[int, str]:
    priority = {
        "llama-3.1-8b-instant": 0,
        "openai/gpt-oss-20b": 1,
        "llama-3.3-70b-versatile": 2,
        "openai/gpt-oss-120b": 3,
    }
    return priority.get(model, 20), model


def groq_models(conn: AIConnection) -> list[str]:
    """List active supported chat models for this key, not merely global docs."""
    token = decrypt_key(conn.encrypted_key)
    req = Request(GROQ_MODELS_URL, headers={
        "Authorization": "Bearer " + token, "Accept": "application/json",
    }, method="GET")
    try:
        with ai_gateway.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read(250000).decode("utf-8"))
    except HTTPError as exc:
        help_text = {
            401: "Groq rechazó esta API Key. Genera otra clave en Groq Console.",
            403: "Esta clave Groq no tiene permiso para consultar modelos.",
            429: "Groq limitó las consultas; vuelve a intentar más tarde.",
        }.get(exc.code, "Groq no pudo entregar la lista de modelos.")
        raise AIServiceError(help_text) from None
    except (URLError, TimeoutError, OSError, ValueError, UnicodeError):
        raise AIServiceError("No se pudo consultar la lista de modelos de Groq.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise AIServiceError("Groq devolvió un listado de modelos inválido.")
    ids = set()
    for value in payload["data"]:
        if not isinstance(value, dict):
            continue
        model = value.get("id", "")
        if (not isinstance(model, str) or not MODEL_RE.fullmatch(model)
                or value.get("active") is False):
            continue
        # Do not test speech, guard, embeddings, moderation or huge image models.
        if model.startswith(("llama-3.", "openai/gpt-oss-")):
            ids.add(model)
    return sorted(ids, key=_priority)


def recover_provider(db: Session, conn: AIConnection) -> dict:
    if not conn.encrypted_key or conn.provider not in ("groq", "zai"):
        raise AIServiceError("No hay una conexión Groq o Z.ai recuperable.")
    if conn.provider == "groq":
        candidates = groq_models(conn)[:MAX_PROBES]
        if not candidates:
            return {"ok": False, "attempts": 0,
                    "message": "Tu cuenta Groq no informa modelos compatibles. Revisa tus permisos en Groq Console."}
    else:
        # Never send a Standard API key to Coding Plan endpoints.
        candidates = list(dict.fromkeys(
            ([conn.model] if conn.model in ZAI_MODELS else []) + list(ZAI_MODELS)
        ))[:MAX_PROBES]
    attempted = 0
    last_error = ""
    for model in candidates:
        attempted += 1
        target = SimpleNamespace(
            id=conn.id, org_id=conn.org_id, provider=conn.provider,
            model=model, encrypted_key=conn.encrypted_key,
            price_input_per_million=conn.price_input_per_million,
            price_output_per_million=conn.price_output_per_million,
            last_status="not_tested", last_checked_at=None,
        )
        # Reasoning models may need more tokens to emit visible text.
        limit = 512 if (conn.provider == "zai" or "gpt-oss" in model) else 128
        try:
            run_connection(db, target, task="connection_test",
                           instructions="Responde solo OK.",
                           prompt="Comprueba la conexión. Responde OK.",
                           max_output_tokens=limit, timeout=11)
        except AIServiceError as exc:
            last_error = str(exc)
            # 401/403/402/429 and network failures do not justify spending
            # another call on a different model with the same credential.
            if any(code in last_error for code in (
                "HTTP 401", "HTTP 402", "HTTP 403", "HTTP 429",
                "rechazada", "permiso", "facturación",
                "límite de uso", "No se pudo contactar",
            )):
                break
            # Continue if model is unavailable, bad request or no visible text.
            continue
        old = conn.model
        conn.model = model
        conn.last_checked_at = utcnow()
        conn.last_status = "verified"
        conn.enabled = True
        provider_name = ai_gateway.PROVIDERS[conn.provider]["name"]
        if conn.name in (provider_name + " · " + old, provider_name + " - " + old):
            base_name = provider_name + " · " + model
            existing = set(db.scalars(select(AIConnection.name).where(
                AIConnection.org_id == conn.org_id, AIConnection.id != conn.id)))
            if base_name not in existing:
                conn.name = base_name
        return {
            "ok": True, "attempts": attempted, "model": model,
            "message": provider_name + " conectado con el modelo " + model + ".",
        }
    conn.last_checked_at = utcnow()
    conn.last_status = "error"
    hint = ("Revisa si tienes una clave del tipo correcto y saldo o plan activo."
            if conn.provider == "zai" else
            "Revisa los modelos habilitados en Groq Console.")
    return {
        "ok": False, "attempts": attempted,
        "message": ("No fue posible verificar un modelo con esta cuenta. "
                    + hint + (" " + last_error if last_error else "")),
    }
