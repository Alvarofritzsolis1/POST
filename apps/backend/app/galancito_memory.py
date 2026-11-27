"""Transactional conversational memory shared by Messenger ingestion paths."""
from datetime import datetime, timedelta, timezone
import json
import re
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, or_, select

from .facebook_crm_models import FacebookChatMessage, FacebookTradeGuide, FacebookLeadTrade
from .galancito_intake import (
    UNKNOWN_NAMES, apply_intake, conversation_context, intake_question_fields, needs_deeper_response,
    requested_relative_start, unanswered_intake_question,
    unresolved_declarations,
)
from .galancito_knowledge import evidence_context, conversation_example
from .galancito_flow import retired_permission_prompt
from .galancito_evidence import REPORTED, declaration_segments, location_mentions, personal_statements
from .galancito_semantic import consume_confirmation
from .galancito_communes import find_communes
from .galancito_contact_email import redact_email_for_intake, remember_shared_email, email_shared_by_sender, REFUSAL
from .galancito_phone import (
    labeled_whatsapp_phone, phone_declined, phone_shared_by_sender, redact_mobile_for_intake, remember_shared_phone,
)
from .galancito_links import advertised_trade, audit_event, canonical_trade, record_declared_trades, trade_declarations, trade_terms
from .galancito_triage import (ASK_APPLICATION_OWN, application_role, application_role_question,
                              analyze, asks_about_application, declaration_text, plain, private_data, referring_to_application,
                              ambiguous_application_role, TRADE_CONFIRMATIONS, contractor_trade_question)

FIELDS = (
    "display_name", "name_opt_out", "specialty", "entity_type", "interest_type",
    "team_available", "workers", "has_employees", "employee_count", "experience", "work_area", "work_communes", "availability",
)
CHILE = ZoneInfo("America/Santiago")
_PERSONAL_DECLARATION = re.compile(
    r"^(?:corrijo |aclaro |yo )*(?:soy|soi|me llamo|mi nombre es|trabajo|trabajamos|hago|ofrezco|ofresco|busco|"
    r"puedo|estoy disponible|tengo|somos|llevo|voy con|me dedico|realizo|realizamos|vivo|resido|me muevo|"
    r"mi cuadrilla|mi equipo|cuento con|contamos con)\b"
)


def aware(timestamp):
    return timestamp.replace(tzinfo=timezone.utc) if timestamp and timestamp.tzinfo is None else timestamp


def profile_facts(lead, *, changed=False) -> dict:
    context = (lead.profile_sources or {}).get("_declared_context") or {}
    return {**{field: getattr(lead, field) for field in FIELDS},
            "field_states": {field: evidence.get("state") for field, evidence in (lead.profile_sources or {}).items()
                             if field in FIELDS and evidence.get("state")},
            "manual_fields": [field for field, origin in (lead.profile_sources or {}).items()
                              if field in FIELDS and origin.get("source") == "manual"],
            "turn_changed": changed,
            "declared_context": {key: item.get("value") for key, item in context.items() if isinstance(item, dict)
                                 and key in {"crew_expandable", "declared_origin", "crew_size",
                                             "preferred_contact", "worked_at_galilea", "notice_trade",
                                             "additional_services_pending"}},
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


def remember_whatsapp_channel(lead, message, *, at, remote_id):
    if not labeled_whatsapp_phone(message) or phone_shared_by_sender(message) != lead.contact_phone:
        return
    sources = lead.profile_sources or {}
    context = sources.get("_declared_context") or {}
    previous = context.get("preferred_contact") or {}
    if (previous.get("source") == "manual" or
            previous.get("at") and aware(datetime.fromisoformat(previous["at"])) >= aware(at)):
        return
    lead.profile_sources = {**sources, "_declared_context": {**context, "preferred_contact": {
        "value": "whatsapp", "source": "message", "state": "confirmado_por_declaracion",
        "at": at.isoformat(), "message_id": remote_id,
    }}}


def capture_voluntary_contact(db, lead, message, prior, *, at, remote_id):
    """Store only channels volunteered by the sender, with independent source evidence."""
    before = (lead.contact_phone, lead.contact_email, lead.phone_opt_out, lead.email_opt_out)
    phone_saved = remember_shared_phone(lead, message, prior, at=at)
    remember_whatsapp_channel(lead, message, at=at, remote_id=remote_id)
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


def iter_recovery_messages(db, lead, *, newest_first=False, inbound_only=False, full_history=True):
    """Page the persisted conversation in a stable order, scoped to tenant/page/contact."""
    stamp = (FacebookChatMessage.created_at if inbound_only else case(
        (and_(FacebookChatMessage.direction == "outbound", FacebookChatMessage.state == "sent"),
         FacebookChatMessage.updated_at), else_=FacebookChatMessage.created_at))
    criteria = [FacebookChatMessage.org_id == lead.org_id,
                FacebookChatMessage.lead_id == lead.id,
                FacebookChatMessage.page_id == lead.page_id]
    if inbound_only:
        criteria.append(FacebookChatMessage.direction == "inbound")
    order = (stamp.desc(), FacebookChatMessage.id.desc()) if newest_first else (stamp.asc(), FacebookChatMessage.id.asc())
    cursor = None
    while True:
        query = select(FacebookChatMessage, stamp).where(*criteria)
        if cursor is not None:
            at, ident = cursor
            advance = stamp < at if newest_first else stamp > at
            next_id = FacebookChatMessage.id < ident if newest_first else FacebookChatMessage.id > ident
            query = query.where(or_(advance, and_(stamp == at, next_id)))
        rows = db.execute(query.order_by(*order).limit(200)).all()
        if not rows:
            break
        for item, timestamp in rows:
            yield item
        if len(rows) < 200 or not full_history:
            break
        item, timestamp = rows[-1]
        cursor = (timestamp, item.id)


def recovery_scope(db, lead):
    """Freeze valid pre-existing facts; only replay-created facts may be corrected."""
    sources = lead.profile_sources or {}
    protected = set()
    for field in FIELDS:
        value = getattr(lead, field)
        origin = sources.get(field) or {}
        if field == "display_name" and value in UNKNOWN_NAMES and not lead.name_opt_out and origin.get("state") != "rechazado_por_usuario":
            continue  # Explicit refresh may restore a cleared name.
        if ((field != "name_opt_out" and _known(field, value)) or
                (field == "name_opt_out" and value) or origin.get("source") == "manual" or
                origin.get("state") == "rechazado_por_usuario"):
            protected.add(field)
    rows = db.scalars(select(FacebookLeadTrade).where(
        FacebookLeadTrade.org_id == lead.org_id, FacebookLeadTrade.lead_id == lead.id)).all()
    return {"fields": protected, "context": set(sources.get("_declared_context") or {}),
            "trades": {plain(canonical_trade(row.trade)) for row in rows},
            "inactive_trades": {plain(canonical_trade(row.trade)) for row in rows if not row.active}}


def recover_missing_contact(db, lead, *, full_history=False):
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
    rows = iter_recovery_messages(db, lead, newest_first=True, inbound_only=True,
                                  full_history=full_history)
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
                remember_whatsapp_channel(lead, body, at=at, remote_id=item.remote_id)
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


def messenger_prompt_text(message: str) -> str:
    return "" if retired_permission_prompt(message) else professional_message(message)


def messenger_context(message, facts, prior, turns, evidence, guide=None, *, limit=3000):
    """One bounded, contact-redacted prompt for automatic and operator drafts.

    Keep the current question and declared facts first. Include complete reference
    records, never a JSON fragment chopped at the Ollama context boundary.
    Input turns are newest first. No raw phone, email, or name field is exported.
    """
    public = {k: v for k, v in facts.items()
              if k not in {"display_name", "name_opt_out", "turn_changed", "contact_phone", "contact_email", "manual_fields"}
              and v is not None and v != "" and v != []}
    prior = messenger_prompt_text(prior or "")
    parts = [
        "Consulta actual: " + messenger_prompt_text(message)[:600],
        conversation_context(facts),
        "La procedencia declarada no confirma dónde puede trabajar. Una cuadrilla ampliable no confirma más integrantes ni personal contratado. Usa estos datos para no repetir preguntas.",
        "Datos profesionales declarados: " + json.dumps(public, ensure_ascii=False),
    ]
    if public.get("declared_context", {}).get("notice_trade"):
        parts.append("notice_trade describe el aviso consultado. El oficio propio requiere declaración del contacto.")
    if prior:
        parts.append("Última pregunta entregada: " + prior[:220])
    def add(section):
        if len("\n".join(parts)) + len(section) + 1 <= limit:
            parts.append(section)
            return True
        return False

    # Retrieve bounded older evidence from actual messages rather than inventing a summary.
    if evidence:
        reference = messenger_prompt_text(evidence_context(evidence[:1]))
        if reference and not private_data(reference):
            add("Referencia prioritaria: " + reference)
    tokens = {token for token in plain(message + " " + (prior or "")).split() if len(token) > 3}
    older = [item for item in turns[8:60] if item.direction == "inbound"
             and getattr(item, "consent_decision", None) is None and not private_data(item.body)]
    ranked = sorted(older, key=lambda item: len(tokens.intersection(plain(item.body).split())), reverse=True)
    for item in ranked[:2]:
        if tokens.intersection(plain(item.body).split()) and len("\n".join(parts)) + 650 < limit:
            if text := messenger_prompt_text(item.body):
                add("Mensaje anterior relevante (puede haber sido corregido): " + text[:140])
    # Keep the actual dialogue ahead of optional examples and reference guides.
    history = []
    for item in turns[:8]:
        if getattr(item, "consent_decision", None) is not None or private_data(item.body):
            continue
        if text := messenger_prompt_text(item.body):
            history.append(("Persona: " if item.direction == "inbound" else "Red de Obras: ") + text[:200])
    included = 0
    # Add recent turns first; render the final selection in chronological order.
    for n in range(len(history), 0, -1):
        if add("Historial reciente:\n" + "\n".join(reversed(history[:n]))):
            included = n
            break
    if guide:
        add("Guía administrativa validada: " + messenger_prompt_text(guide.explanation or "")[:600]
            + "\nOrientación documental: " + messenger_prompt_text("; ".join(guide.document_guidance or []))[:350])
    else:
        add("No hay guía documental validada. Deriva esas dudas al equipo.")
    for item in evidence[1:]:
        if (reference := messenger_prompt_text(evidence_context([item]))) and not add("Referencia aprobada: " + reference):
            break
    if example := messenger_prompt_text(conversation_example(message, prior)):
        add("Ejemplo didáctico (no es un hecho de la obra): " + example)
    return "\n".join(parts), included


def _known(field, value):
    if field == "display_name":
        return value not in UNKNOWN_NAMES
    return value is not None and value not in ("", "unknown", [])


def prior_delivered_prompt(db, lead, *, at, since=None) -> str:
    criteria = [
        FacebookChatMessage.lead_id == lead.id,
        FacebookChatMessage.org_id == lead.org_id,
        FacebookChatMessage.page_id == lead.page_id,
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


_GALILEA_WORK = re.compile(
    r"(?P<negative>(?:nunca |jamas |no )|(?:(?:aun|todavia) no ))?"
    r"(?:trabaje|trabajamos|he trabajado|hemos trabajado|trabajado) "
    r"(?:(?:antes|alguna vez) )?(?:en |para |con )(?:(?:una |alguna )?obras? de )?galilea\b"
)


def remember_declared_context(lead, message, prior, *, remote_id, at, historical=False, protected_context=None):
    """Persist bounded, evidence-linked declarations, not guesses or work coverage."""
    personal = ", ".join(personal_statements(message))
    value = plain(personal)
    previous = plain(prior)
    current = dict((lead.profile_sources or {}).get("_declared_context") or {})
    proposed = {}
    if trade := advertised_trade(message):
        proposed["notice_trade"] = trade
    statement = value
    asked_for_services = "additional_services" in intake_question_fields(prior)
    other_services = r"(?:de todo un poco|varios oficios|trabajos varios)"
    own_statement = re.sub(r"^(?:(?:yo|tambien|ademas|y) )+", "", statement)
    if (any(re.search(r"\b" + other_services + r"\b", clause) and
            not re.search(r"\b(?:no|nunca|quizas)\b", clause) for clause in declaration_segments(message))
            and (_PERSONAL_DECLARATION.match(own_statement) or
                 (getattr(lead, "specialty", "") and re.fullmatch(
                     r"(?:y |pero )?(?:tambien )?" + other_services, statement)))):
        proposed["additional_services_pending"] = True
    elif asked_for_services and (statement in {"paso", "prefiero no responder", "prefiero no decir"}
                                or any(trade_declarations(message, prior, allow_bare=True).values())):
        proposed["additional_services_pending"] = False
    answer = re.sub(r"^(?:yo |corrijo |aclaro |en realidad )", "", statement, count=1)
    if re.match(r"\s*(?:sí\b|si\s*,)", personal, re.I):
        answer = answer.removeprefix("si ")
    if work := _GALILEA_WORK.match(answer):
        proposed["worked_at_galilea"] = not bool(work["negative"])
    elif "worked_at_galilea" in intake_question_fields(prior) and "?" not in message and "¿" not in message:
        if statement in {"si", "si po", "sipo", "si ya", "si antes", "si claro", "claro que si", "si he trabajado"}:
            proposed["worked_at_galilea"] = True
        elif statement in {"no", "nop", "no po", "no nunca", "nunca", "aun no", "todavia no", "no todavia", "no he trabajado"}:
            proposed["worked_at_galilea"] = False
        elif statement in {"prefiero no responder", "prefiero no decir", "no quiero responder",
                           "prefiero dejarlo pendiente", "prefiero no contestar", "paso"}:
            proposed["worked_at_galilea"] = None
    if re.search(r"\b(?:no podemos|no puedo|no pueden) (?:ser|llevar|traer|sumar|contratar) mas\b", statement):
        proposed["crew_expandable"] = False
    elif re.search(r"\b(?:pueden|podemos|puedo) (?:ser|llevar|traer|sumar|contratar) mas\b", statement) or (
        getattr(lead, "team_available", False)
        and re.fullmatch(r"(?:(?:segun|depende (?:de)?) (?:el trabajo|la obra|el presupuesto)"
                         r"(?: y (?:de )?el presupuesto)? )?se puede contratar mas (?:personas|maestros|gente)",
                         statement)
    ):
        proposed["crew_expandable"] = True
    origin = re.fullmatch(r"(?:(?:hola|ola|buenas) )?(?:(?:soy|somos) )?de (.+)", value)
    if origin and re.search(r"\bde donde (?:es(?: usted)?|eres|son|viene[n]?)\b", previous):
        place = origin[1]
        if len(place) <= 60 and (place == "san pedro" or find_communes(place)) and re.fullmatch(r"[a-z ]+", place):
            proposed["declared_origin"] = place.title()
    elif origins := {commune for clause in declaration_segments(personal)
                     for _, commune, field in location_mentions(clause) if field == "origin"}:
        if len(origins) == 1:
            proposed["declared_origin"] = origins.pop()
    elif re.fullmatch(r"(?:(?:hola|ola|buenas) )?(?:soy|somos) de san pedro", value):
        proposed["declared_origin"] = "San Pedro"
    changed = False
    for field, fact in proposed.items():
        old = current.get(field) or {}
        if old.get("source") == "manual" or (protected_context is not None and field in protected_context):
            continue
        if protected_context is not None and old.get("at") and aware(datetime.fromisoformat(old["at"])) >= aware(at):
            continue
        if field in {"worked_at_galilea", "notice_trade", "additional_services_pending"}:
            if old.get("at") and aware(datetime.fromisoformat(old["at"])) >= aware(at):
                continue
        elif "value" in old and ((historical and protected_context is None) or old["value"] == fact):
            continue
        state = "rechazado_por_usuario" if fact is None else "confirmado_por_declaracion"
        if field == "worked_at_galilea" and fact is not None and old.get("value") is not None:
            state = old.get("state", state) if old["value"] == fact else "corregido"
        current[field] = {"value": fact, "source": "message", "state": state,
                          "at": at.isoformat(), "message_id": remote_id}
        changed = True
    if changed:
        lead.profile_sources = {**(lead.profile_sources or {}), "_declared_context": current}
    return changed


def apply_messenger_message(db, lead, message, prior, *, remote_id, at, historical=False,
                            replay=False, aliases=None, recovery=None) -> bool:
    if not message:
        return False
    # Contact details are captured separately. Do not discard unrelated
    # professional declarations simply because a message also contains a
    # phone number or email. Continue with contact-redacted text only.
    message = professional_message(message)
    if not message.strip() or private_data(message) or analyze(message).intent in {"human", "restricted"}:
        return False
    context_changed = remember_declared_context(lead, message, prior, remote_id=remote_id, at=at,
                                               historical=historical or replay,
                                               protected_context=recovery["context"] if recovery is not None else None)
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
    contractor_confirmation = contractor_trade_question(prior)
    if (prior.startswith(ASK_APPLICATION_OWN) or contractor_confirmation) and normalized in TRADE_CONFIRMATIONS:
        trade = trade_terms(prior)
        if len(trade) == 1:
            message = ("soy contratista y hago " if contractor_confirmation else "trabajo en ") + trade[0]
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
    if asking_about_notice := (REPORTED.search(plain(message)) or asks_about_application(message) or (
            referring_to_application(prior) and not application_role_question(prior))):
        # An oficio or comuna quoted from an advert belongs to that advert.
        # Preserve separate first-person declarations in the same message.
        message = ", ".join(part for part in personal_statements(message)
                            if _PERSONAL_DECLARATION.match(plain(part)) and not asks_about_application(part))
        if not message:
            return context_changed
    personal = ", ".join(personal_statements(message))
    # A tentative answer can describe why a field is pending without supplying a value.
    unresolved = unresolved_declarations(personal or message, prior) if not (historical or replay) else {}
    if not personal and not unresolved:
        return context_changed
    if plain(personal) != plain(declaration_text(message)):
        message = personal
    declarations = trade_declarations(message, prior, extra=aliases,
        allow_bare=not asking_about_notice and not application_role_question(prior))
    if recovery is not None:
        # An inactive trade already present before recovery must not be resurrected.
        declarations = {trade: present for trade, present in declarations.items()
                        if plain(canonical_trade(trade)) not in recovery["inactive_trades"]}
    before = {field: getattr(lead, field) for field in FIELDS}
    candidate = SimpleNamespace(**before, specialty_source=lead.specialty_source)
    apply_intake(candidate, message, prior, declarations=declarations,
                 on_date=aware(at).astimezone(CHILE).date())
    if application_role_question(prior) and ambiguous_application_role(message, prior):
        candidate.interest_type = before["interest_type"]
    prior_sources = lead.profile_sources or {}
    accepted = {}
    for field, old in before.items():
        value = getattr(candidate, field)
        if old == value or (field in unresolved and field != "experience"):
            continue
        origin = prior_sources.get(field, {})
        known = _known(field, old)
        # The explicit admin refresh may restore a cleared, unknown name;
        # preserve a real manual name, all other manual fields, and refusal.
        restore_cleared_name = (replay and field == "display_name" and not known
                                and not lead.name_opt_out
                                and origin.get("state") != "rechazado_por_usuario"
                                and _known(field, value))
        if recovery is not None:
            if field in recovery["fields"] or (origin.get("source") == "manual" and not restore_cleared_name):
                continue
            if field == "display_name" and lead.name_opt_out and not candidate.name_opt_out:
                continue
        else:
            if ((origin.get("source") == "manual" and not restore_cleared_name) or
                    ((historical or replay) and known and field not in {"work_communes", "work_area"})):
                continue
            if (historical or replay) and field in {"work_area", "work_communes"} and known:
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
    if recovery is not None and accepted.get("name_opt_out") is True and "display_name" not in recovery["fields"]:
        # Do not restore a name when a later message refuses it.
        accepted["display_name"] = "Interesado de Facebook"
    for field, value in accepted.items():
        setattr(lead, field, value)
    changed = list(accepted)
    active, trades_changed = record_declared_trades(db, lead, message, remote_id=remote_id,
                                     declarations=declarations, historical=historical or replay, at=at,
                                     recovery_protected=recovery["trades"] if recovery is not None else None)
    if "specialty" in changed:
        lead.specialty_source = candidate.specialty_source
    elif (((not historical and not replay) or
           (recovery is not None and "specialty" not in recovery["fields"])) and
          lead.specialty and lead.specialty_source == "message"
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
