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
from urllib.request import Request, HTTPRedirectHandler, build_opener

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai_models import AIConnection, AIOrchestration, AIUsage
from .ai_review import REVIEW_INSTRUCTIONS, review_prompt, accepted_review
from .galancito_triage import private_data
from .models import utcnow

# Adding a provider means registering a known HTTPS host, not accepting arbitrary URLs.
PROVIDERS = {
    "gemini": {"name": "Google Gemini", "mode": "gemini", "url": None, "docs": "https://aistudio.google.com/apikey"},
    "groq": {"name": "Groq", "mode": "chat", "url": "https://api.groq.com/openai/v1/chat/completions", "docs": "https://console.groq.com/keys"},
    # Coding Plan is licensed for supported development tools, not multi-user GALANT.
    "zai": {"name": "Z.ai · API estándar", "mode": "chat", "url": "https://api.z.ai/api/paas/v4/chat/completions", "docs": "https://z.ai/manage-apikey/apikey-list"},
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


class _NoExternalRedirects(HTTPRedirectHandler):
    """Prevent credential-bearing requests from following redirects to other hosts."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


# Endpoint hosts are allowlisted and redirects are never followed.
# Keep a replaceable module-local callable for deterministic synthetic tests.
urlopen = build_opener(_NoExternalRedirects).open


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
        # GLM-4.7 supports non-thinking mode, suitable for short connectivity checks.
        # GLM-5.3 Flash uses forced thinking: do NOT send thinking=disabled.
        if connection.provider == "zai":
            if connection.model.startswith(("glm-4.7", "glm-4.6", "glm-5.2")):
                body["thinking"] = {"type": "disabled"}
            if connection.model.startswith("glm-5.3"):
                body["temperature"] = 1.0
        headers = {"Authorization": "Bearer " + token}
    headers["Content-Type"] = "application/json"
    request = Request(url, data=json.dumps(body).encode("utf-8"),
                      headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read(250000).decode("utf-8"))
    except HTTPError as exc:
        # Never include the remote error body, headers or full exception message.
        help_text = {
            400: "El proveedor no acepta este modelo o sus parámetros.",
            401: "La API Key fue rechazada. Genera o copia una clave válida.",
            402: "La cuenta del proveedor requiere saldo o facturación.",
            403: "Esta cuenta no tiene permiso para utilizar el modelo.",
            404: "El modelo elegido no está disponible en esta cuenta.",
            422: "Revisa el modelo seleccionado y vuelve a probar.",
            429: "Se alcanzó el límite de uso del proveedor. Vuelve a probar luego.",
        }.get(exc.code, "El proveedor no pudo completar la prueba.")
        raise AIServiceError(help_text + " (HTTP " + str(exc.code) + ").") from None
    except (URLError, TimeoutError, OSError, ValueError, UnicodeError):
        raise AIServiceError("No se pudo contactar al proveedor de IA.") from None
    if not isinstance(result, dict):
        raise AIServiceError("El proveedor respondió con un formato inválido.")
    try:
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
    except (TypeError, ValueError, AttributeError, IndexError, OverflowError):
        raise AIServiceError("El proveedor respondió con un formato inválido.") from None
    if not text.strip():
        if provider["mode"] == "chat" and connection.provider in ("groq", "zai"):
            raise AIServiceError("El modelo respondió sin texto. Puede haber consumido los tokens de salida razonando; prueba otro modelo o aumenta el límite de tokens.")
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



def estimated_tokens(instructions: str, prompt: str, output_limit: int) -> int:
    """Conservative preflight, NOT an exact tokenizer or provider spending guarantee."""
    return max(1, (len(instructions) + len(prompt) + 2) // 3) + max(8, output_limit)


def within_budget(db: Session, policy: AIOrchestration, org_id: str,
                  instructions: str, prompt: str, max_output_tokens: int) -> bool:
    if not policy.monthly_token_limit:
        return True
    estimated = estimated_tokens(instructions, prompt, max_output_tokens)
    return monthly_tokens(db, org_id) + estimated <= policy.monthly_token_limit


def orchestration_available(db: Session, org_id: str, task: str) -> bool:
    policy = db.get(AIOrchestration, org_id)
    if not policy or not policy.enabled or task != "red_obras":
        return False
    conn = db.get(AIConnection, (policy.task_routes or {}).get(task, ""))
    if not (conn and conn.org_id == org_id and conn.enabled and conn.encrypted_key
            and conn.last_status == "verified"):
        return False
    if policy.monthly_token_limit and monthly_tokens(db, org_id) >= policy.monthly_token_limit:
        return False
    if policy.review_enabled:
        reviewer = db.get(AIConnection, (policy.task_routes or {}).get("review", ""))
        if not (reviewer and reviewer.id != conn.id and reviewer.org_id == org_id
                and (reviewer.provider, reviewer.model) != (conn.provider, conn.model)
                and reviewer.enabled and reviewer.encrypted_key
                and reviewer.last_status == "verified"):
            return False
    return True


def orchestrated_text(db: Session, org_id: str, *, task: str, instructions: str,
                      prompt: str, max_output_tokens: int = 300) -> str | None:
    """Opt-in multi-provider routing; optional independent review, not weight training.

    The transaction-level organizational inference lock is acquired by
    galancito_runtime.infer BEFORE this method to serialize budget checks.
    """
    policy = db.get(AIOrchestration, org_id)
    if not policy or not policy.enabled or task != "red_obras":
        return None
    if not within_budget(db, policy, org_id, instructions, prompt, max_output_tokens):
        return None
    started = time.perf_counter()
    routes = policy.task_routes or {}
    connections = list(db.scalars(select(AIConnection).where(
        AIConnection.org_id == org_id, AIConnection.enabled.is_(True))))
    primary_id = routes.get(task)
    review_id = routes.get("review") if policy.review_enabled else None
    reviewer = next((c for c in connections if c.id == review_id and
                     c.encrypted_key and c.last_status == "verified"), None) if review_id else None
    ordered = [c for c in connections if c.id == primary_id and
               c.encrypted_key and c.last_status == "verified"]
    if policy.review_enabled and (not reviewer or reviewer.id == primary_id or
                                  (ordered and (reviewer.provider, reviewer.model) ==
                                   (ordered[0].provider, ordered[0].model))):
        return None
    if policy.fallback_enabled and ordered:
        ordered += [c for c in connections if c.id not in {primary_id, review_id}
                    and c.encrypted_key and c.last_status == "verified"]
    for conn in ordered:
        # Bound the whole attempt chain to the browser's response deadline.
        remaining = 7.5 - (time.perf_counter() - started)
        if remaining < (3 if policy.review_enabled else 1):
            break
        timeout = min(remaining - 2.2, 4.8) if policy.review_enabled else min(remaining, 6.0)
        if timeout < 0.7:
            break
        if not within_budget(db, policy, org_id, instructions, prompt, max_output_tokens):
            break
        try:
            answer = run_connection(db, conn, task=task, instructions=instructions,
                                    prompt=prompt, max_output_tokens=max_output_tokens,
                                    timeout=timeout)
        except AIServiceError:
            continue
        # Even a generated response might accidentally include a private datum.
        # Do not forward it to another external model (or return it to the user).
        if private_data(answer):
            return None
        if not policy.review_enabled:
            return answer
        context = review_prompt(prompt, answer)
        review_output = 64
        if not within_budget(db, policy, org_id, REVIEW_INSTRUCTIONS, context, review_output):
            return None
        remaining = 7.5 - (time.perf_counter() - started)
        if remaining < 0.8:
            return None
        try:
            verdict = run_connection(db, reviewer, task="review",
                                     instructions=REVIEW_INSTRUCTIONS,
                                     prompt=context, max_output_tokens=review_output,
                                     timeout=min(remaining, 2.7))
        except AIServiceError:
            return None
        return answer if accepted_review(verdict) else None
    return None
