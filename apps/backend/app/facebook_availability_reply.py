"""Acknowledge a declared date in context of a schedule sent by an operator."""
from datetime import timedelta

from sqlalchemy import select

from .facebook_crm_models import FacebookChatMessage
from .galancito_intake import declared_relative_start, requested_relative_start, work_date_answer
from .galancito_memory import CHILE, aware
from .galancito_triage import analyze, private_data

_CONFUSION = "La persona expresó dificultades con la explicación o el trámite"


def availability_reply(db, lead, message: str, previous: str, at) -> str | None:
    if (at is None or not previous or lead.ai_consent_state == "declined"
            or (lead.needs_support and lead.support_reason != _CONFUSION)
            or private_data(message) or analyze(message).intent in {"human", "restricted"}):
        return None
    if confirmation := work_date_answer(message, previous):
        confirmed, day = confirmation
        if confirmed:
            return f"Perfecto, me dices que puedes el {day:%d/%m}. El equipo tiene que confirmar el trabajo."
        return "Entiendo. Dejo la fecha que ya me diste para que el equipo la pueda revisar."
    declared = declared_relative_start(message)
    if declared is None:
        return None
    requested = requested_relative_start(previous)
    if requested is None:
        return None
    sent_at = db.scalar(select(FacebookChatMessage.updated_at).where(
        FacebookChatMessage.org_id == lead.org_id,
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.state == "sent",
        FacebookChatMessage.operator_id.is_not(None),
        FacebookChatMessage.body == previous,
        FacebookChatMessage.updated_at <= at,
        FacebookChatMessage.updated_at >= aware(at) - timedelta(hours=24),
    ).order_by(FacebookChatMessage.updated_at.desc()).limit(1))
    if not sent_at:
        return None
    available_date = aware(at).astimezone(CHILE).date() + timedelta(days=declared)
    requested_date = aware(sent_at).astimezone(CHILE).date() + timedelta(days=requested)
    if available_date == requested_date:
        return f"Perfecto, me dices que puedes el {available_date:%d/%m}. Queda por coordinar con el equipo."
    return (f"Ya, puedes el {available_date:%d/%m}. Te comentamos que el trabajo sería el "
            f"{requested_date:%d/%m/%Y}. ¿También puedes ese día?")
