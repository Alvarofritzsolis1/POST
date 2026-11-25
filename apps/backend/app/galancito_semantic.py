"""Optional semantic confirmation protocol for consented local Qwen.

The model selects an interpretation; a user-visible confirmation bound to the
delivered message is required before persisting uncertain professional facts.
"""
import json
import re
from .galancito_communes import find_communes
from .galancito_links import canonical_trade
from .galancito_triage import plain, private_data

KEY = "_semantic_confirmation"
QUESTIONS = {
    ("interest_type", "employment"): "¿Te refieres a que buscas empleo con contrato?",
    ("interest_type", "service_offer"): "¿Te refieres a que tomas trabajos por tu cuenta como contratista?",
    ("interest_type", "both"): "¿Te interesan tanto el empleo como los trabajos por tu cuenta?",
    ("team_available", True): "¿Puedes llevar a otras personas a trabajar contigo?",
    ("team_available", False): "¿Irías a trabajar tú solo?",
}
FIELDS = {"interest_type", "team_available", "workers", "entity_type", "has_employees", "employee_count", "specialty", "work_communes", "experience", "availability", "display_name"}
CORRECTION = re.compile(r"\b(?:corrijo|me equivoque|quise decir|en realidad|ya no|ahora|correccion)\b")
YES = {"si", "sipo", "si po", "claro", "exacto", "asi es", "de una", "correcto", "si claro"}
PROTOCOL = ('Si detectas una interpretación profesional nueva e incierta, puedes proponer confirmación: '
    'devuelve JSON {"reply":"respuesta breve sin pregunta","confirm":{"field":"interest_type",'
    '"value":"service_offer","evidence":"cita literal del mensaje"}}. '
    'Campos: interest_type (employment/service_offer/both), team_available, workers (total), entity_type (individual/company), has_employees, employee_count, specialty, work_communes, experience, availability, display_name. Usa booleanos o cantidades enteras cuando corresponda. '
    'Verifica intención, contexto, contradicciones y dudas; no deduzcas empleados del equipo. Evidencia literal del mensaje. Si no necesitas confirmar, responde en texto normal.')


def _known(value):
    return value is not None and value != [] and value not in ("", "unknown", "Interesado de Facebook", "Contacto sin nombre")


def _available(facts, field, correction=False):
    states = facts.get("field_states") or {}
    if states.get(field) == "rechazado_por_usuario" or field in (facts.get("manual_fields") or []):
        return False
    if field == "display_name" and facts.get("name_opt_out"):
        return False
    return correction or not _known(facts.get(field))


def has_semantic_opportunity(facts):
    return any(_available(facts, field) for field in FIELDS)


def _typed_question(field, value, evidence):
    if field == "team_available":
        return (value, QUESTIONS.get((field, value))) if type(value) is bool else (None, None)
    if field == "interest_type":
        return (value, QUESTIONS.get((field, value))) if isinstance(value, str) else (None, None)
    if field == "entity_type":
        if value == "individual":
            return value, "¿Ofreces tus servicios a tu propio nombre?"
        if value == "company":
            return value, "¿Ofreces tus servicios mediante una empresa?"
        return None, None
    if field == "has_employees" and type(value) is bool:
        return value, ("¿Tienes trabajadores contratados por ti?" if value else "¿Confirmas que no tienes trabajadores contratados?")
    if field in {"workers", "employee_count"}:
        if type(value) is not int or not (1 if field == "workers" else 0) <= value <= 5000:
            return None, None
        return value, (f"¿Serían {value} personas en total, incluyéndote?" if field == "workers" else f"¿Tienes {value} trabajadores contratados por ti?")
    if not isinstance(value, str) or not value.strip() or len(value) > 120 or private_data(value):
        return None, None
    value = value.strip()
    if not re.fullmatch(r"[\w ,./'()\-]+", value) or "http" in value.casefold():
        return None, None
    if field == "work_communes":
        communes = find_communes(value)
        if communes and len(", ".join(communes)) <= 120:
            return communes, "¿Puedes trabajar en " + ", ".join(communes) + "?"
    if field == "specialty":
        value = canonical_trade(value)[:100]
        return value, "¿Tu oficio es " + value + "?"
    if field == "experience":
        return value, "¿Tu experiencia es de " + value + "?"
    if field == "availability":
        return value, "¿Tu disponibilidad sería " + value + "?"
    if field == "display_name" and len(value) <= 70 and plain(value) and plain(value) in plain(evidence) and not any(c.isdigit() for c in value):
        return value, "¿Prefieres que te llamemos " + value + "?"
    return None, None


def decode_local_reply(draft, latest, facts):
    """Plain output still works; malformed structured output stays out of chat."""
    if not isinstance(draft, str):
        return None, None
    if not draft.lstrip().startswith("{"):
        return draft, None
    try:
        data = json.loads(draft)
    except (ValueError, TypeError):
        return None, None
    if not isinstance(data, dict) or not isinstance(data.get("reply"), str):
        return None, None
    reply = data["reply"].strip()
    claim = data.get("confirm")
    if not isinstance(claim, dict):
        return reply or None, None
    field, value, evidence = claim.get("field"), claim.get("value"), claim.get("evidence")
    if not isinstance(field, str) or field not in FIELDS or not isinstance(evidence, str):
        return reply or None, None
    correction = bool(CORRECTION.search(plain(latest)))
    value, question = _typed_question(field, value, evidence)
    if (not question or not _available(facts, field, correction) or value == facts.get(field)
            or not plain(evidence) or plain(evidence) not in plain(latest)
            or private_data(evidence) or private_data(reply) or "?" in reply or "?" in latest):
        return reply or None, None
    return (reply + " " + question).strip(), {"field": field, "value": value, "question": question,
        "previous": facts.get(field), "correction": correction}


def remember_confirmation(lead, proposal, delivered_body, outbound_id):
    if not proposal or not delivered_body.endswith(proposal["question"]):
        return
    field = proposal["field"]
    origins = dict(lead.profile_sources or {})
    if origins.get(field, {}).get("source") == "manual":
        return
    if getattr(lead, field, None) != proposal.get("previous") or (field == "display_name" and getattr(lead, "name_opt_out", False)):
        return
    if not _available({field: getattr(lead, field, None), "field_states": {
            field: origins.get(field, {}).get("state")}}, field, proposal.get("correction", False)):
        return
    origins[KEY] = {**proposal, "body": delivered_body, "outbound_id": outbound_id}
    lead.profile_sources = origins


def consume_confirmation(lead, message, prior):
    """Consume once, only on a matching explicit yes."""
    origins = dict(lead.profile_sources or {})
    pending = origins.pop(KEY, None)
    if not pending:
        return {}
    lead.profile_sources = origins
    if plain(message) not in YES or not prior or plain(prior) != plain(pending.get("body", "")):
        return {}
    field, value = pending.get("field"), pending.get("value")
    if field not in FIELDS or origins.get(field, {}).get("source") == "manual":
        return {}
    if getattr(lead, field, None) != pending.get("previous") or (field == "display_name" and getattr(lead, "name_opt_out", False)):
        return {}
    if not _available({field: getattr(lead, field, None), "field_states": {
            field: origins.get(field, {}).get("state")}}, field, pending.get("correction", False)):
        return {}
    changes = {field: value}
    if field == "workers":
        changes["team_available"] = value > 1
    elif field == "team_available":
        workers = getattr(lead, "workers", None)
        if not value:
            changes["workers"] = 1
        elif workers == 1:
            changes["workers"] = None
    elif field == "employee_count":
        changes["has_employees"] = value > 0
    elif field == "has_employees":
        count = getattr(lead, "employee_count", None)
        if not value:
            changes["employee_count"] = 0
        elif count == 0:
            changes["employee_count"] = None
    elif field == "work_communes":
        changes["work_area"] = ", ".join(value)
    for key, val in changes.items():
        old = getattr(lead, key, None)
        if key != field and old != val and (origins.get(key, {}).get("source") == "manual"
                or (_known(old) and not pending.get("correction", False))):
            return {}
    return changes
