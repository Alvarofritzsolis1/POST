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
from .galancito_semantic import consume_confirmation
from .galancito_communes import find_communes
from .galancito_contact_email import redact_email_for_intake, remember_shared_email, email_shared_by_sender, REFUSAL
from .galancito_phone import redact_mobile_for_intake, remember_shared_phone, phone_shared_by_sender, phone_declined
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
            "manual_fields": [field for field, origin in (lead.profile_sources or {}).items()
                              if field in FIELDS and origin.get("source") == "manual"],
            "turn_changed": changed,
            "declared_context": {k: v.get("value") for k, v in ((lead.profile_sources or {}).get("_declared_context") or {}).items() if isinstance(v, dict) and k in {"crew_expandable", "declared_origin", "crew_size", "preferred_contact"}},
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


def recover_missing_contact(db, lead):
    """Restore missing contact fields from the newest explicit inbound evidence.

    No inference, no external calls, no reply, no override of manual edits or
    later refusal. Read only this contact's bounded, persisted conversation.
    """
    sources = lead.profile_sources or {}
    phone_pending = not (lead.contact_phone or lead.phone_opt_out or
                         sources.get("contact_phone", {}).get("source") == "manual")
    email_pending = not (lead.contact_email or lead.email_opt_out or
                         sources.get("contact_email", {}).get("source") == "manual")
    if not (phone_pending or email_pending):
        return False
    rows = db.scalars(select(FacebookChatMessage).where(
        FacebookChatMessage.org_id == lead.org_id,
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.direction == "inbound",
    ).order_by(FacebookChatMessage.created_at.desc(), FacebookChatMessage.id.desc()).limit(200))
    recovered = False
    for item in rows:
        if not (phone_pending or email_pending):
            break
        if item.consent_decision is not None:
            continue
        body, at = item.body or "", aware(item.created_at)
        if not at:
            continue
        prior = prior_delivered_prompt(db, lead, at=at)
        if phone_pending and phone_declined(body, prior):
            phone_pending = False
        if email_pending and REFUSAL.search(body):
            email_pending = False
        states = {}
        if phone_pending and phone_shared_by_sender(body, prior):
            if remember_shared_phone(lead, body, prior, at=at):
                states["contact_phone"] = "confirmado_por_declaracion"
            phone_pending = False
        if email_pending and email_shared_by_sender(body, prior):
            if remember_shared_email(lead, body, prior, at=at):
                states["contact_email"] = "confirmado_por_declaracion"
            email_pending = False
        if states:
            note_profile_sources(lead, states, source="message", at=at,
                                 remote_id=item.remote_id, states=states)
            for field in states:
                audit_event(db, lead, "field_" + field, source="message", remote_id=item.remote_id)
            recovered = True
    return recovered


def professional_message(message):
    return redact_email_for_intake(redact_mobile_for_intake(message))


def messenger_context(message, facts, prior, turns, evidence, guide=None, *, limit=3000):
    """One bounded, contact-redacted prompt for automatic and operator drafts.

    Keep the current question and declared facts first. Include complete reference
    records, never a JSON fragment chopped at the Ollama context boundary.
    Input turns are newest first. No raw phone, email, or name field is exported.
    """
    public = {k: v for k, v in facts.items()
              if k not in {"display_name", "name_opt_out", "turn_changed", "contact_phone", "contact_email", "manual_fields"}
              and v is not None and v != "" and v != []}
    parts = [
        "Consulta actual: " + professional_message(message)[:600],
        conversation_context(facts),
        "La procedencia declarada no confirma dónde puede trabajar. Una cuadrilla ampliable no confirma más integrantes ni personal contratado. Usa estos datos para no repetir preguntas.",
        "Datos profesionales declarados: " + json.dumps(public, ensure_ascii=False),
        "Última pregunta entregada: " + professional_message(prior or "")[:220],
    ]
    def add(section):
        if len("\n".join(parts)) + len(section) + 1 <= limit:
            parts.append(section)
            return True
        return False

    # Retrieve bounded older evidence from actual messages rather than inventing a summary.
    if evidence:
        reference = professional_message(evidence_context(evidence[:1]))
        if not private_data(reference):
            add("Referencia prioritaria: " + reference)
    tokens = {token for token in plain(message + " " + (prior or "")).split() if len(token) > 3}
    older = [item for item in turns[8:60] if item.direction == "inbound"
             and getattr(item, "consent_decision", None) is None and not private_data(item.body)]
    ranked = sorted(older, key=lambda item: len(tokens.intersection(plain(item.body).split())), reverse=True)
    for item in ranked[:2]:
        if tokens.intersection(plain(item.body).split()) and len("\n".join(parts)) + 650 < limit:
            add("Mensaje anterior relevante (puede haber sido corregido): " + professional_message(item.body)[:140])
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
    for item in evidence[1:]:
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


def remember_declared_context(lead, message, prior, *, remote_id, at, historical=False):
    """Persist bounded, evidence-linked declarations, not guesses or work coverage."""
    value = plain(message)
    previous = plain(prior)
    current = dict((lead.profile_sources or {}).get("_declared_context") or {})
    proposed = {}
    if re.search(r"\b(?:no podemos|no puedo|no pueden) (?:ser|llevar|traer|sumar) mas\b", value):
        proposed["crew_expandable"] = False
    elif re.search(r"\b(?:pueden|podemos|puedo) (?:ser|llevar|traer|sumar) mas\b", value):
        proposed["crew_expandable"] = True
    origin = re.fullmatch(r"(?:(?:hola|ola|buenas) )?(?:(?:soy|somos) )?de (.+)", value)
    if origin and re.search(r"\bde donde (?:es(?: usted)?|eres|son|viene[n]?)\b", previous):
        place = origin[1]
        if len(place) <= 60 and (place == "san pedro" or find_communes(place)) and re.fullmatch(r"[a-z ]+", place):
            proposed["declared_origin"] = place.title()
    elif (origin := re.fullmatch(r"(?:(?:hola|ola|buenas) )?(?:soy|somos) de (.+)", value)):
        place = origin[1]
        if len(place) <= 60 and (place == "san pedro" or find_communes(place)) and re.fullmatch(r"[a-z ]+", place):
            proposed["declared_origin"] = place.title()
    changed = False
    for field, fact in proposed.items():
        old = current.get(field) or {}
        if old.get("source") == "manual" or (historical and "value" in old) or old.get("value") == fact:
            continue
        current[field] = {"value": fact, "source": "message", "state": "confirmado_por_declaracion",
                          "at": at.isoformat(), "message_id": remote_id}
        changed = True
    if changed:
        lead.profile_sources = {**(lead.profile_sources or {}), "_declared_context": current}
    return changed


def apply_messenger_message(db, lead, message, prior, *, remote_id, at, historical=False,
                            replay=False, aliases=None) -> bool:
    if not message or private_data(message) or analyze(message).intent in {"human", "restricted"}:
        return False
    context_changed = remember_declared_context(lead, message, prior, remote_id=remote_id, at=at, historical=historical or replay)
    if not historical and not replay:
        confirmed = consume_confirmation(lead, message, prior)
        if confirmed:
            before = {field: getattr(lead, field, None) for field in confirmed}
            for field, value in confirmed.items():
                setattr(lead, field, value)
                audit_event(db, lead, "field_" + field, source="message", remote_id=remote_id)
            if "specialty" in confirmed:
                lead.specialty_source = "message"
                record_declared_trades(db, lead, message, remote_id=remote_id,
                    declarations={confirmed["specialty"]: True}, at=at)
            states = {field: "corregido" if _known(field, before[field]) else "confirmado_por_declaracion"
                      for field in confirmed}
            note_profile_sources(lead, confirmed, source="message", at=at, remote_id=remote_id, states=states)
            return True
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
        fragments = re.split(r"(?<=[,.!?;])\s+|\n+|\by\s+(?=soy\b|soi\b|hago\b|ofrezco\b)", message, flags=re.I)
        message = " ".join(part for part in fragments if _PERSONAL_DECLARATION.match(plain(part))
                           and not asks_about_application(part)).strip()
        if not message:
            return context_changed
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
    return bool(changed or trades_changed or context_changed)


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
