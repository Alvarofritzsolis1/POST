"""Transactional conversational memory shared by Messenger ingestion paths."""
from datetime import timedelta, timezone
import json
import re
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .facebook_crm_models import FacebookChatMessage, FacebookTradeGuide
from .galancito_intake import (
    UNKNOWN_NAMES, apply_intake, conversation_context, needs_deeper_response, requested_relative_start, unanswered_intake_question,
    unresolved_declarations,
)
from .galancito_knowledge import evidence_context, conversation_example
from .galancito_contact_email import redact_email_for_intake, remember_shared_email
from .galancito_phone import redact_mobile_for_intake, remember_shared_phone
from .galancito_links import audit_event, record_declared_trades, trade_declarations, trade_terms
from .galancito_triage import (ASK_APPLICATION_OWN, application_role, application_role_question,
                              analyze, asks_about_application, plain, private_data, referring_to_application, ambiguous_application_role)

FIELDS = (
    "display_name", "name_opt_out", "specialty", "entity_type", "interest_type",
    "team_available", "workers", "has_employees", "employee_count", "experience", "work_area", "work_communes", "availability",
)
CHILE = ZoneInfo("America/Santiago")
_PERSONAL_DECLARATION = re.compile(
    r"^(?:corrijo |aclaro )?(?:soy|soi|me llamo|mi nombre es|trabajo|trabajamos|hago|ofrezco|ofresco|busco|"
    r"puedo|estoy disponible|tengo|somos|llevo|voy con|me dedico)\b"
)


def aware(timestamp):
    return timestamp.replace(tzinfo=timezone.utc) if timestamp and timestamp.tzinfo is None else timestamp


def profile_facts(lead, *, changed=False) -> dict:
    return {**{field: getattr(lead, field) for field in FIELDS},
            "field_states": {field: evidence.get("state") for field, evidence in (lead.profile_sources or {}).items()
                             if field in FIELDS and evidence.get("state")},
            "turn_changed": changed,
            # Only contact availability flags, never the phone or email itself.
            "contact_available": bool(getattr(lead, "contact_phone", "") or getattr(lead, "contact_email", "")),
            "contact_declined": bool(getattr(lead, "phone_opt_out", False) or getattr(lead, "email_opt_out", False)),
            "contact_offered": bool(getattr(lead, "phone_requested_at", None))}


def note_profile_sources(lead, fields, *, source, at, remote_id=None, states=None):
    if fields:
        lead.profile_sources = {
            **(lead.profile_sources or {}),
            **{field: {"source": source, "at": at.isoformat(),
                       "message_id": remote_id, "state": (states or {}).get(field, "confirmado_por_declaracion")}
               for field in fields},
        }


def capture_voluntary_contact(db, lead, message, prior, *, at, remote_id):
    """Store only channels volunteered by the sender, with independent source evidence."""
    before = (lead.contact_phone, lead.contact_email, lead.phone_opt_out, lead.email_opt_out)
    phone_saved = remember_shared_phone(lead, message, prior, at=at)
    email_saved = remember_shared_email(lead, message, prior, at=at)
    states = {}
    for field, saved, old, opted_out, old_opt_out in (
        ("contact_phone", phone_saved, before[0], lead.phone_opt_out, before[2]),
        ("contact_email", email_saved, before[1], lead.email_opt_out, before[3]),
    ):
        if saved:
            states[field] = "corregido" if old else "confirmado_por_declaracion"
            audit_event(db, lead, "field_" + field, source="message", remote_id=remote_id)
        elif opted_out and not old_opt_out and not old:
            states[field] = "rechazado_por_usuario"
    note_profile_sources(lead, states, source="message", at=at, remote_id=remote_id, states=states)
    return phone_saved, email_saved


def professional_message(message):
    return redact_email_for_intake(redact_mobile_for_intake(message))


def messenger_context(message, facts, prior, turns, evidence, guide=None, *, limit=3000):
    """One bounded, contact-redacted prompt for automatic and operator drafts.

    Keep the current question and declared facts first. Include complete reference
    records, never a JSON fragment chopped at the Ollama context boundary.
    Input turns are newest first. No raw phone, email, or name field is exported.
    """
    public = {k: v for k, v in facts.items()
              if k not in {"display_name", "name_opt_out", "turn_changed", "contact_phone", "contact_email"}
              and v is not None and v != "" and v != []}
    parts = [
        "Consulta actual: " + professional_message(message)[:600],
        conversation_context(facts),
        "Datos profesionales declarados: " + json.dumps(public, ensure_ascii=False),
        "Última pregunta entregada: " + professional_message(prior or "")[:220],
    ]
    def add(section):
        if len("\n".join(parts)) + len(section) + 1 <= limit:
            parts.append(section)
            return True
        return False

    # Keep the actual dialogue ahead of optional examples and reference guides.
    history = []
    for item in turns[:8]:
        if (getattr(item, "consent_decision", None) is not None
                or private_data(item.body) or "autorizas" in item.body.casefold()):
            continue
        history.append(("Persona: " if item.direction == "inbound" else "Red de Obras: ")
                       + professional_message(item.body)[:200])
    included = 0
    # Add recent turns first; render the final selection in chronological order.
    for n in range(len(history), 0, -1):
        if add("Historial reciente:\n" + "\n".join(reversed(history[:n]))):
            included = n
            break
    if guide:
        add("Guía administrativa validada: " + professional_message(guide.explanation or "")[:600]
            + "\nOrientación documental: " + professional_message("; ".join(guide.document_guidance or []))[:350])
    else:
        add("No hay guía documental validada. Deriva esas dudas al equipo.")
    for item in evidence:
        if not add("Referencia aprobada: " + professional_message(evidence_context([item]))):
            break
    if example := conversation_example(message, prior or ""):
        add("Ejemplo didáctico (no es un hecho de la obra): " + professional_message(example))
    return "\n".join(parts), included


def _known(field, value):
    if field == "display_name":
        return value not in UNKNOWN_NAMES
    return value is not None and value not in ("", "unknown", [])


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
            or referring_to_application(prompt)
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
    # Treat an answer to a specific, just-asked question as the person's own
    # declaration, while never turning the advertised trade into experience.
    normalized = plain(message)
    if prior.startswith(ASK_APPLICATION_OWN) and normalized in {
            "si", "si claro", "si ese es mi oficio", "si trabajo en eso",
            "claro", "exacto"}:
        trade = trade_terms(prior)
        if len(trade) == 1:
            message = "trabajo en " + trade[0]
            prior = ""
    elif application_role_question(prior):
        role = application_role(message, prior)
        if role == "employment":
            message, prior = "busco trabajo", ""
        elif role == "service_offer":
            # Preserve explicit team/company facts; don't turn a bare role into employees.
            extra = message if _PERSONAL_DECLARATION.match(normalized) else ""
            message, prior = ("ofrezco servicios. " + extra).strip(), ""
        elif role == "both":
            message, prior = "busco trabajo y ofrezco servicios", ""
    # A role confirmation is not a request for an advert. Do not discard
    # professional corrections and additional declarations in that context.
    if asking_about_notice := (asks_about_application(message) or (
            referring_to_application(prior) and not application_role_question(prior))):
        # An oficio or comuna quoted from an advert belongs to that advert.
        # Preserve separate first-person declarations in the same message.
        fragments = re.split(r"(?<=[,.!?;])\s+|\by\s+(?=soy\b|soi\b|hago\b|ofrezco\b)", message, flags=re.I)
        message = " ".join(part for part in fragments if _PERSONAL_DECLARATION.match(plain(part))
                           and not asks_about_application(part)).strip()
        if not message:
            return False
    declarations = trade_declarations(message, prior, extra=aliases,
        allow_bare=not asking_about_notice and not application_role_question(prior))
    before = {field: getattr(lead, field) for field in FIELDS}
    candidate = SimpleNamespace(**before, specialty_source=lead.specialty_source)
    apply_intake(candidate, message, prior, declarations=declarations,
                 on_date=aware(at).astimezone(CHILE).date())
    if application_role_question(prior) and ambiguous_application_role(message, prior):
        candidate.interest_type = before["interest_type"]
    prior_sources = lead.profile_sources or {}
    accepted = {}
    unresolved = unresolved_declarations(message, prior) if not (historical or replay) else {}
    for field, old in before.items():
        value = getattr(candidate, field)
        if old == value or (field in unresolved and field != "experience"):
            continue
        origin = prior_sources.get(field, {})
        known = _known(field, old)
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
    employees = accepted.get("has_employees", before["has_employees"])
    employee_count = accepted.get("employee_count", before["employee_count"])
    if employee_count is not None and employees is not (employee_count > 0):
        accepted.pop("has_employees", None)
        accepted.pop("employee_count", None)
    for field, value in accepted.items():
        setattr(lead, field, value)
    changed = list(accepted)
    active, trades_changed = record_declared_trades(db, lead, message, remote_id=remote_id,
                                     declarations=declarations, historical=historical or replay, at=at)
    if "specialty" in changed:
        lead.specialty_source = candidate.specialty_source
    elif (not historical and not replay and lead.specialty and lead.specialty_source == "message"
          and prior_sources.get("specialty", {}).get("source") != "manual"
          and declarations.get(lead.specialty) is False and lead.specialty not in active):
        lead.specialty = active[0][:100] if active else ""
        changed.append("specialty")
    states = {field: "corregido" if _known(field, before[field]) and field != "name_opt_out"
              else "confirmado_por_declaracion" for field in changed}
    if "name_opt_out" in changed and lead.name_opt_out:
        unresolved["display_name"] = "rechazado_por_usuario"
    for field, status in unresolved.items():
        if (field in before and not _known(field, before[field])
                and prior_sources.get(field, {}).get("source") != "manual"):
            states[field] = status
    note_profile_sources(lead, states, source="message", at=at, remote_id=remote_id, states=states)
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
