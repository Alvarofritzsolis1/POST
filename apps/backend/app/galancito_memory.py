"""Transactional conversational memory shared by Messenger ingestion paths."""
from datetime import timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .facebook_crm_models import FacebookChatMessage, FacebookTradeGuide
from .galancito_intake import (
    UNKNOWN_NAMES, apply_intake, needs_deeper_response, requested_relative_start, unanswered_intake_question,
)
from .galancito_links import audit_event, record_declared_trades, trade_declarations
from .galancito_triage import analyze, private_data

FIELDS = (
    "display_name", "name_opt_out", "specialty", "entity_type", "interest_type",
    "team_available", "workers", "experience", "work_area", "work_communes", "availability",
)
CHILE = ZoneInfo("America/Santiago")


def aware(timestamp):
    return timestamp.replace(tzinfo=timezone.utc) if timestamp and timestamp.tzinfo is None else timestamp


def profile_facts(lead, *, changed=False) -> dict:
    return {**{field: getattr(lead, field) for field in FIELDS},
            "has_employees": lead.has_employees, "turn_changed": changed}


def note_profile_sources(lead, fields, *, source, at, remote_id=None):
    if fields:
        lead.profile_sources = {
            **(lead.profile_sources or {}),
            **{field: {"source": source, "at": at.isoformat(),
                       "message_id": remote_id} for field in fields},
        }


def prior_delivered_prompt(db, lead, *, at, since=None) -> str:
    criteria = [
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.state == "sent",
        FacebookChatMessage.updated_at <= at,
        FacebookChatMessage.updated_at >= at - timedelta(hours=24),
    ]
    latest = db.execute(select(FacebookChatMessage.body, FacebookChatMessage.updated_at, FacebookChatMessage.operator_id)
                        .where(*criteria).order_by(FacebookChatMessage.updated_at.desc(),
                                                  FacebookChatMessage.id.desc()).limit(1)).first()
    if not latest:
        return ""
    prompt, sent_at, operator_id = latest
    if (not since or aware(sent_at) >= since or unanswered_intake_question(lead, prompt)
            or (operator_id and requested_relative_start(prompt) is not None)):
        return prompt
    return ""


def approved_trade_aliases(db, org_id):
    return {guide.trade: guide.aliases or [] for guide in db.scalars(
        select(FacebookTradeGuide).where(FacebookTradeGuide.org_id == org_id,
                                         FacebookTradeGuide.approved.is_(True)).limit(100))}


def apply_messenger_message(db, lead, message, prior, *, remote_id, at, historical=False,
                            replay=False, aliases=None) -> bool:
    if not message or private_data(message) or analyze(message).intent in {"human", "restricted"}:
        return False
    declarations = trade_declarations(message, prior, extra=aliases, allow_bare=True)
    before = {field: getattr(lead, field) for field in FIELDS}
    candidate = SimpleNamespace(**before, specialty_source=lead.specialty_source)
    apply_intake(candidate, message, prior, declarations=declarations,
                 on_date=at.astimezone(CHILE).date())
    prior_sources = lead.profile_sources or {}
    accepted = {}
    for field, old in before.items():
        value = getattr(candidate, field)
        if old == value:
            continue
        origin = prior_sources.get(field, {})
        known = (old not in UNKNOWN_NAMES if field == "display_name" else
                 old is not None and old not in ("", "unknown", []))
        if ((origin.get("source") == "manual" and (known or not replay)) or
                ((historical or replay) and known and field not in {"work_communes", "work_area"})):
            continue
        if (historical or replay) and field in {"work_area", "work_communes"} and known:
            # An older declaration may supply a missing area, but cannot widen
            # or reverse a later destination correction.
            continue
        accepted[field] = value
    team = accepted.get("team_available", before["team_available"])
    workers = accepted.get("workers", before["workers"])
    if ((team is False and workers is not None and workers > 1) or
            (team is True and workers == 1)):
        # A declared correction cannot change one half of a conflicting manual
        # or newer record. Keep the original message available for review.
        accepted.pop("team_available", None)
        accepted.pop("workers", None)
    if "work_communes" in accepted and "work_area" not in accepted and candidate.work_area != before["work_area"]:
        accepted.pop("work_communes")
    for field, value in accepted.items():
        setattr(lead, field, value)
    changed = list(accepted)
    active, trades_changed = record_declared_trades(db, lead, message, remote_id=remote_id,
                                     declarations=declarations, historical=historical or replay, at=at)
    if "specialty" in changed:
        lead.specialty_source = candidate.specialty_source
    elif (not historical and not replay and lead.specialty and lead.specialty_source == "message"
          and declarations.get(lead.specialty) is False and lead.specialty not in active):
        lead.specialty = active[0][:100] if active else ""
        changed.append("specialty")
    note_profile_sources(lead, changed, source="message", at=at, remote_id=remote_id)
    for field in changed:
        if field != "work_area":  # The same evidence is recorded for work_communes.
            audit_event(db, lead, "field_" + field, source="message", remote_id=remote_id)
    return bool(changed or trades_changed)


def reply_focus(messages):
    """Choose the newest unanswered question, or the latest detail in the burst."""
    details = []
    for item in messages:
        if item.direction == "outbound":
            if details:
                break
            continue
        if item.consent_decision is not None:
            continue
        if not details and private_data(item.body):
            return item
        details.append(item)
    return next((item for item in details if needs_deeper_response(item.body)), None) or (
        details[0] if details else None)
