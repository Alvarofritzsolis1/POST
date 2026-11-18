"""Discover AND probe actual Gemini generateContent access using an already stored key.

Google can list a model that nevertheless returns HTTP 404 on generation,
so listing alone is never considered a successful connection.
No API keys, prompts, Google response bodies, or credentials are returned.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ai_gateway
from .ai_gateway import AIServiceError, MODEL_RE, decrypt_key, run_connection
from .ai_models import AIConnection
from .models import utcnow

MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_PAGES = 3
MAX_PROBES = 3
SUPPORTED = "generatecontent"


def _score(model: str) -> tuple[int, str]:
    # Prefer current low-latency models. Never silently select a costly Pro.
    if model == "gemini-3.8-flash":
        return (0, model)
    if model == "gemini-3.5-flash-lite":
        return (1, model)
    if "flash-lite" in model and not model.startswith("gemini-2."):
        return (2, model)
    if "flash" in model and not model.startswith("gemini-2."):
        return (3, model)
    if "flash" in model:
        return (4, model)
    return (99, model)


def listed_models(conn: AIConnection) -> list[str]:
    """List with x-goog-api-key HEADER, never query string or redirect."""
    if conn.provider != "gemini" or not conn.encrypted_key:
        raise AIServiceError("Se necesita una conexión Gemini con clave protegida.")
    token = decrypt_key(conn.encrypted_key)
    models: set[str] = set()
    next_token = ""
    for _ in range(MAX_PAGES):
        query = {"pageSize": 100}
        if next_token:
            query["pageToken"] = next_token
        url = MODELS_URL + "?" + urlencode(query)
        request = Request(url, headers={"x-goog-api-key": token}, method="GET")
        try:
            with ai_gateway.urlopen(request, timeout=8) as result:
                payload = json.loads(result.read(500000).decode("utf-8"))
        except HTTPError as exc:
            messages = {
                401: "Google rechazó la API Key. Revisa la clave de Google AI Studio.",
                403: "La clave no tiene permisos para consultar modelos de Google.",
                429: "Google alcanzó el límite de consultas de modelos.",
            }
            raise AIServiceError(messages.get(
                exc.code, "Google no pudo entregar el catálogo de modelos."
            )) from None
        except (URLError, TimeoutError, OSError, UnicodeError, ValueError):
            raise AIServiceError("No se pudo consultar el catálogo de Gemini.") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise AIServiceError("Google devolvió un catálogo de modelos inválido.")
        for entry in payload["models"]:
            if not isinstance(entry, dict):
                continue
            raw_name = entry.get("name", "")
            methods = entry.get("supportedGenerationMethods", [])
            if not (isinstance(raw_name, str) and raw_name.startswith("models/")
                    and isinstance(methods, list)
                    and any(str(method).lower() == SUPPORTED for method in methods)):
                continue
            model = raw_name.removeprefix("models/")
            if (model.startswith("gemini-") and MODEL_RE.fullmatch(model)
                    and ("flash" in model or "pro" in model)):
                models.add(model)
        next_token = payload.get("nextPageToken", "")
        if not isinstance(next_token, str) or not next_token or len(next_token) > 600:
            break
    return sorted(models, key=_score)


def recover_gemini(db: Session, conn: AIConnection) -> dict:
    """Explicit admin-triggered, low-cost tests; never rotate or return the key.

    Existing model is preserved on error. Only a proven successful model is saved,
    with a connection_test usage row and an admin audit event by the API layer.
    """
    # A failed recovery must never leave an old unverified model enabled.
    conn.enabled = False
    conn.last_status = "error"
    models = listed_models(conn)
    candidates = [model for model in models if _score(model)[0] < 99]
    if not candidates:
        return {"ok": False, "message": "Google no informó modelos Flash compatibles. Revisa tu cuenta en AI Studio.",
                "attempts": 0}
    checked = 0
    final_error = ""
    for model in candidates[:MAX_PROBES]:
        checked += 1
        # A temporary object prevents overwriting the stored model until verified.
        attempt = SimpleNamespace(
            id=conn.id, org_id=conn.org_id, name=conn.name, provider="gemini",
            model=model, encrypted_key=conn.encrypted_key,
            price_input_per_million=conn.price_input_per_million,
            price_output_per_million=conn.price_output_per_million,
            last_status="not_tested", last_checked_at=None,
        )
        try:
            run_connection(db, attempt, task="connection_test",
                           instructions="Responde muy brevemente en español.",
                           prompt="Prueba de conexión. Responde OK.",
                           max_output_tokens=128, timeout=7)
        except AIServiceError as exc:
            # A missing model may be listed by Google; try the next one.
            final_error = str(exc)
            if "(HTTP 404)" in final_error:
                continue
            # Bad credentials, billing, permissions and quota should not be retried.
            break
        old_model = conn.model
        conn.model = model
        conn.last_status = "verified"
        conn.last_checked_at = utcnow()
        conn.enabled = True
        # Only adjust the generated automatic name, never override a custom name.
        if conn.name == "Google Gemini · " + old_model:
            preferred_name = "Google Gemini · " + model
            used = set(db.scalars(select(AIConnection.name).where(
                AIConnection.org_id == conn.org_id, AIConnection.id != conn.id)))
            if preferred_name not in used:
                conn.name = preferred_name
            else:
                conn.name = next(
                    (preferred_name[:69] + " #" + str(n) for n in range(2, 100)
                     if preferred_name[:69] + " #" + str(n) not in used),
                    conn.name,
                )
        return {"ok": True, "model": model,
                "message": "Gemini conectado con el modelo compatible " + model + ".",
                "attempts": checked}
    conn.last_status = "error"
    conn.last_checked_at = utcnow()
    return {"ok": False, "message": (
        "No se encontró un modelo que responda con esta clave. "
        + (final_error or "Revisa disponibilidad en Google AI Studio.")
    ), "attempts": checked}
