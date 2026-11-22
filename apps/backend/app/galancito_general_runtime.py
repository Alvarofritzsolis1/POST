"""Single general-chat implementation for GALANT's authenticated UI.

Fact questions never leave the authorized database. Public abstract analyses
may use approved external API connections only when user opts in, the prompt
has no organization/private identifiers, and the budget rules permit it.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_gateway import AIServiceError, orchestration_available, orchestrated_text
from .config import settings
from .galancito_general import (QWEN_4B, GENERAL_INSTRUCTIONS, advice_fallback,
                                external_safe, general_intent, is_complex, safe_generated)
from .galancito_internal_live import internal_reply
from .galancito_local import generate_local_text
from .galancito_runtime import infer
from .galancito_triage import quick_reply
from .ops_models import Worksite, Contractor


def internal_names_for_privacy(db: Session, user) -> tuple[str, ...]:
    names = []
    for model in (Worksite, Contractor):
        names.extend(name for name in db.scalars(
            select(model.name).where(model.org_id == user.org_id).limit(1500)) if name)
    return tuple(names)


def external_ready(db: Session, user) -> bool:
    return (user.role == "admin" and
            orchestration_available(db, user.org_id, "red_obras"))


def general_answer(db: Session, user, message: str,
                   history: list[str] | None = None,
                   *, allow_external: bool = False):
    """Return answer, intent, source, external-used flag.

    Not an autonomous tool agent. All tool outputs come from allowed internal
    queries; never send these outputs to external APIs.
    """
    intent = general_intent(message)
    if intent == "greeting":
        return quick_reply(message), "greeting", "local", False
    if intent == "verified":
        answer, subtype = internal_reply(db, user, message, history or [])
        if subtype != "help":
            return answer, subtype, "verified_local", False
    # General advice never sees private database values. If there is no
    # verified result, the fallback acknowledges missing evidence.
    if allow_external and is_complex(message) and external_ready(db, user):
        if external_safe(message, internal_names=internal_names_for_privacy(db, user)):
            try:
                generated = infer(db, lambda: orchestrated_text(
                    db, user.org_id, task="red_obras",
                    instructions=GENERAL_INSTRUCTIONS,
                    prompt="Consulta general, no contiene datos de GALANT:\n" + message[:650],
                    max_output_tokens=300), org_id=user.org_id)
                answer = safe_generated(generated)
                if answer:
                    return answer, "general_advice", "external_api", True
            except (AIServiceError, RuntimeError, OSError, TimeoutError):
                pass
    cfg = settings()
    # Production's Qwen3.5 4B must be deliberately activated and tested.
    # Never silently downgrade the general assistant to the legacy 1.7B.
    if cfg.galancito_local_ai_enabled and cfg.galancito_local_model == QWEN_4B:
        try:
            generated = infer(db, lambda: generate_local_text(
                GENERAL_INSTRUCTIONS,
                "Pregunta del usuario (sin registros privados):\n" + message[:950],
                max_chars=1100))
            answer = safe_generated(generated)
            if answer:
                return answer, "general_advice", "ollama_4b", False
        except (RuntimeError, TimeoutError, OSError, ValueError):
            pass
    return advice_fallback(), "general_advice", "fallback", False
