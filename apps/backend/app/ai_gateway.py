"""Vetted outbound AI endpoints. Secrets never leave the backend or appear in logs."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai_models import AIConnection, AIOrchestration, AIUsage
from .models import utcnow

# Adding a provider means registering a known HTTPS host, not accepting arbitrary URLs.
PROVIDERS = {
    "gemini": {"name": "Google Gemini", "mode": "gemini", "url": None, "docs": "https://aistudio.google.com/apikey"},
    "groq": {"name": "Groq", "mode": "chat", "url": "https://api.groq.com/openai/v1/chat/completions", "docs": "https://console.groq.com/keys"},
    "nvidia": {"name": "NVIDIA Build", "mode": "chat", "url": "https://integrate.api.nvidia.com/v1/chat/completions", "docs": "https://build.nvidia.com/settings/api-keys"},
    "openai": {"name": "OpenAI", "mode": "chat", "url": "https://api.openai.com/v1/chat/completions", "docs": "https://platform.openai.com/api-keys"},
    "mistral": {"name": "Mistral", "mode": "chat", "url": "https://api.mistral.ai/v1/chat/completions", "docs": "https://console.mistral.ai/"},
    "openrouter": {"name": "OpenRouter", "mode": "chat", "url": "https://openrouter.ai/api/v1/chat/completions", "docs": "https://openrouter.ai/settings/keys"},
}
TASKS = {
    "red_obras": "Consultas de Red de Obras",
    "ads": "Redacción de anuncios",
    "classification": "Clasificación y especialidades",
    "followup": "Seguimiento de interesados",
    "review": "Segunda opinión / calidad",
}
MODEL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{1,159}$")


class AIServiceError(Exception):
    """Safe-to-display provider error; no HTTP bodies, credentials or prompts."""


def _cipher() -> Fernet:
    value = os.environ.get("AI_CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if not value:
        raise AIServiceError("Configura AI_CREDENTIAL_ENCRYPTION_KEY en el servidor antes de guardar claves.")
    try:
        return Fernet(value.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        raise AIServiceError("La clave de cifrado del servidor es inválida.") from None


def encryption_ready() -> bool:
    try:
        _cipher()
        return True
    except AIServiceError:
        return False


def encrypt_key(value: str) -> str:
    if not value or not value.strip() or len(value) > 4096 or any(c in value for c in "\r\n\x00"):
        raise AIServiceError("La clave API es inválida.")
    return _cipher().encrypt(value.strip().encode()).decode("ascii")


def decrypt_key(value: str) -> str:
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        raise AIServiceError("No se puede descifrar la credencial; revisa la clave de cifrado del servidor.") from None


def invoke(connection: AIConnection, *, instructions: str, prompt: str,
           max_output_tokens: int = 300, timeout: float = 10) -> tuple[str, int, int]:
    """One request only; validated host and model, bounded payload, exact reported usage."""
    provider = PROVIDERS.get(connection.provider)
    if not provider or not MODEL_RE.fullmatch(connection.model):
        raise AIServiceError("Proveedor o modelo no admitido.")
    if not connection.encrypted_key:
        raise AIServiceError("Falta configurar la clave API.")
    token = decrypt_key(connection.encrypted_key)
    max_output_tokens = max(8, min(600, max_output_tokens))
    if provider["mode"] == "gemini":
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + quote(connection.model, safe="") + ":generateContent")
        body = {
            "systemInstruction": {"parts": [{"text": instructions[:4000]}]},
            "contents": [{"role": "user", "parts": [{"text": prompt[:7000]}]}],
            "generationConfig": {"maxOutputTokens": max_output_tokens, "temperature": 0.2},
        }
        headers = {"x-goog-api-key": token}
    else:
        url = provider["url"]
        body = {
            "model": connection.model,
            "messages": [
                {"role": "system", "content": instructions[:4000]},
                {"role": "user", "content": prompt[:7000]},
            ],
            "max_tokens": max_output_tokens,
            "temperature": 0.2,
            "stream": False,
        }
        headers = {"Authorization": "Bearer " + token}
    headers["Content-Type"] = "application/json"
    request = Request(url, data=json.dumps(body).encode("utf-8"),
                      headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read(250000).decode("utf-8"))
    except HTTPError as exc:
        # Never include the remote error body, headers or full exception message.
        raise AIServiceError("Proveedor rechazó la solicitud (HTTP " + str(exc.code) + ").") from None
    except (URLError, TimeoutError, OSError, ValueError, UnicodeError):
        raise AIServiceError("No se pudo contactar al proveedor de IA.") from None
    if provider["mode"] == "gemini":
        text = "\n".join(str(part.get("text", "")) for candidate in result.get("candidates", [])
                         for part in candidate.get("content", {}).get("parts", []) if isinstance(part, dict))
        usage = result.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount") or 0)
        output_tokens = int(usage.get("candidatesTokenCount") or 0)
    else:
        choices = result.get("choices") or []
        text = str((choices[0].get("message") or {}).get("content") or "") if choices else ""
        usage = result.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
    if not text.strip():
        raise AIServiceError("El proveedor respondió sin texto utilizable.")
    return text.strip(), max(0, input_tokens), max(0, output_tokens)


def record_usage(db: Session, conn: AIConnection, task: str, *, status: str,
                 input_tokens: int = 0, output_tokens: int = 0, duration_ms: int = 0) -> AIUsage:
    cost = None
    if (conn.price_input_per_million is not None and
            conn.price_output_per_million is not None):
        cost = ((Decimal(input_tokens) * Decimal(conn.price_input_per_million)
                + Decimal(output_tokens) * Decimal(conn.price_output_per_million)) / Decimal(1000000))
    row = AIUsage(org_id=conn.org_id, connection_id=conn.id, task=task,
                  status=status, input_tokens=input_tokens, output_tokens=output_tokens,
                  total_tokens=input_tokens + output_tokens,
                  estimated_cost_usd=cost, duration_ms=duration_ms)
    db.add(row)
    db.flush()
    return row


def run_connection(db: Session, conn: AIConnection, *, task: str, instructions: str,
                   prompt: str, max_output_tokens: int = 300, timeout: float = 10) -> str:
    started = time.perf_counter()
    try:
        generated, inp, out = invoke(conn, instructions=instructions, prompt=prompt,
                                    max_output_tokens=max_output_tokens, timeout=timeout)
    except AIServiceError:
        record_usage(db, conn, task, status="error",
                     duration_ms=round((time.perf_counter() - started) * 1000))
        conn.last_status = "error"
        conn.last_checked_at = utcnow()
        raise
    record_usage(db, conn, task, status="success", input_tokens=inp, output_tokens=out,
                 duration_ms=round((time.perf_counter() - started) * 1000))
    conn.last_status = "verified"
    conn.last_checked_at = utcnow()
    return generated


def monthly_tokens(db: Session, org_id: str) -> int:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(db.scalar(select(func.coalesce(func.sum(AIUsage.total_tokens), 0)).where(
        AIUsage.org_id == org_id, AIUsage.created_at >= start)) or 0)


def orchestration_available(db: Session, org_id: str, task: str) -> bool:
    policy = db.get(AIOrchestration, org_id)
    if not policy or not policy.enabled or task not in TASKS:
        return False
    conn = db.get(AIConnection, (policy.task_routes or {}).get(task, ""))
    return bool(conn and conn.org_id == org_id and conn.enabled and conn.encrypted_key
                and conn.last_status == "verified")


def orchestrated_text(db: Session, org_id: str, *, task: str, instructions: str,
                      prompt: str, max_output_tokens: int = 300) -> str | None:
    """Opt-in sequential routing; no fan-out or autonomous training."""
    policy = db.get(AIOrchestration, org_id)
    if not policy or not policy.enabled or task not in TASKS:
        return None
    if policy.monthly_token_limit and monthly_tokens(db, org_id) >= policy.monthly_token_limit:
        return None
    started = time.perf_counter()
    connections = list(db.scalars(select(AIConnection).where(
        AIConnection.org_id == org_id, AIConnection.enabled.is_(True))))
    primary_id = (policy.task_routes or {}).get(task)
    ordered = [c for c in connections if c.id == primary_id and c.last_status == "verified"]
    if policy.fallback_enabled and ordered:
        ordered += [c for c in connections if c.id != primary_id and c.last_status == "verified"]
    for conn in ordered:
        if not conn.encrypted_key:
            continue
        # Bound the whole attempt chain to the chat timeout.
        remaining = 7.5 - (time.perf_counter() - started)
        if remaining < 1:
            break
        try:
            return run_connection(db, conn, task=task, instructions=instructions,
                                  prompt=prompt, max_output_tokens=max_output_tokens,
                                  timeout=min(remaining, 6.0))
        except AIServiceError:
            continue
    return None
