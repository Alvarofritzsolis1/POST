"""Single general-chat implementation for GALANT's authenticated UI.

Fact questions never leave the authorized database. Public abstract analyses
may use approved external API connections only when user opts in, the prompt
has no organization/private identifiers, and the budget rules permit it.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_gateway import AIServiceError, orchestration_available, orchestrated_text
from .config import settings
from .galancito_model_config import QWEN_2B
from .galancito_general import (GENERAL_INSTRUCTIONS, advice_fallback,
                                external_safe, general_intent, is_complex, safe_generated,
                                social_reply)
from .galancito_internal_live import internal_reply
from .galancito_flow import grounded_reply
from .galancito_knowledge_models import Knowledge
from .galancito_real_learning import GENERAL_COACH_TITLE, GENERAL_COACH_SCOPE
from .galancito_local import generate_local_text
from .ai_defect_learning import approved_coaching
from .galancito_runtime import infer
from .galancito_triage import quick_reply
from .ops_models import Worksite, Contractor
from .models import Organization
from .facebook_crm_models import FacebookLead


def internal_names_for_privacy(db: Session, user) -> tuple[str, ...]:
    names = []
    for model in (Worksite, Contractor):
        names.extend(name for name in db.scalars(
            select(model.name).where(model.org_id == user.org_id).limit(1500)) if name)
    organization = db.get(Organization, user.org_id)
    if organization:
        names.append(organization.name)
    names.extend(name for name in db.scalars(
        select(FacebookLead.display_name).where(
            FacebookLead.org_id == user.org_id).limit(1500)) if name)
    return tuple(names)


def external_ready(db: Session, user) -> bool:
    return (user.role == "admin" and
            orchestration_available(db, user.org_id, "red_obras"))


def _verified_coach(db: Session, org_id: str) -> str:
    """Only explicitly approved operational coaching, never lab-only corrections."""
    row = db.scalar(select(Knowledge).where(
        Knowledge.org_id == org_id, Knowledge.scope == GENERAL_COACH_SCOPE,
        Knowledge.title == GENERAL_COACH_TITLE, Knowledge.status == "approved"))
    return ((row.content[:700] if row else "") + "\n" + approved_coaching(db, org_id, "general"))[:1600]


def general_answer(db: Session, user, message: str,
                   history: list[str] | None = None,
                   *, allow_external: bool = False):
    """Return answer, intent, source, external-used flag.

    Not an autonomous tool agent. All tool outputs come from allowed internal
    queries; never send these outputs to external APIs.
    """
    social = social_reply(message)
    if social is not None:
        return social, "social_context", "local", False
    intent = general_intent(message)
    if intent == "greeting":
        return quick_reply(message), "greeting", "local", False
    if intent == "verified":
        answer, subtype = internal_reply(db, user, message, history or [])
        if subtype != "help":
            if (is_complex(message) and subtype in {"documents", "contractors", "overview",
                                                    "followups", "publications"} and
                    settings().galancito_local_ai_enabled and
                    settings().galancito_local_model == QWEN_2B):
                instructions = GENERAL_INSTRUCTIONS + "\n" + _verified_coach(db, user.org_id)
                prompt = ("Consulta del usuario:\n" + message[:500] +
                          "\nDATOS REALES VERIFICADOS POR EL SERVIDOR (solo lectura):\n" + answer[:900] +
                          "\nAnaliza únicamente estos datos, explica limitaciones y no inventes nuevas cifras.")
                try:
                    generated = infer(db, lambda: generate_local_text(
                        instructions, prompt, max_chars=1100, thinking=True))
                    grounded = safe_generated(generated, question=message + "\n" + answer)
                    if grounded and grounded_reply(grounded, answer) is not None:
                        return (answer + "\n\nAnálisis orientativo de Qwen (sobre datos verificados):\n" + grounded,
                                subtype, "verified_reasoning", False)
                except (RuntimeError, TimeoutError, OSError, ValueError):
                    pass
            return answer, subtype, "verified_local", False
    # General advice never sees private database values. If there is no
    # verified result, the fallback acknowledges missing evidence.
    if (allow_external and is_complex(message) and external_safe(message)
            and external_ready(db, user)):
        if external_safe(message, internal_names=internal_names_for_privacy(db, user)):
            try:
                generated = infer(db, lambda: orchestrated_text(
                    db, user.org_id, task="red_obras",
                    instructions=GENERAL_INSTRUCTIONS,
                    prompt="Consulta general, no contiene datos de GALANT:\n" + message[:650],
                    max_output_tokens=300), org_id=user.org_id)
                answer = safe_generated(generated, question=message)
                if answer:
                    return answer, "general_advice", "external_api", True
            except (AIServiceError, RuntimeError, OSError, TimeoutError):
                pass
    cfg = settings()
    if cfg.galancito_local_ai_enabled and cfg.galancito_local_model == QWEN_2B:
        try:
            previous = "\n".join((history or [])[-3:])[:350]
            # Minimize prompt prefill latency when no useful prior context exists.
            prompt = (("Contexto previo del usuario:\n" + previous + "\n")
                      if previous else "") + "Consulta:\n" + message[:650]
            generated = infer(db, lambda: generate_local_text(
                GENERAL_INSTRUCTIONS + "\n" + _verified_coach(db, user.org_id),
                prompt, max_chars=1100, thinking=is_complex(message)))
            answer = safe_generated(generated, question=message)
            if answer:
                return answer, "general_advice", "ollama_2b", False
        except (RuntimeError, TimeoutError, OSError, ValueError):
            pass
    return advice_fallback(), "general_advice", "fallback", False
