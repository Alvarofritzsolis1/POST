"""Optional semantic confirmation protocol for consented local Qwen.

The model selects an interpretation; a user-visible confirmation bound to the
delivered message is required before persisting uncertain professional facts.
"""
import json
from .galancito_triage import plain, private_data

KEY = "_semantic_confirmation"
QUESTIONS = {
    ("interest_type", "employment"): "¿Te refieres a que buscas empleo con contrato?",
    ("interest_type", "service_offer"): "¿Te refieres a que tomas trabajos por tu cuenta como contratista?",
    ("interest_type", "both"): "¿Te interesan tanto el empleo como los trabajos por tu cuenta?",
    ("team_available", True): "¿Puedes llevar a otras personas a trabajar contigo?",
    ("team_available", False): "¿Irías a trabajar tú solo?",
}
YES = {"si", "sipo", "si po", "claro", "exacto", "asi es", "de una", "correcto", "si claro"}
PROTOCOL = ('Si detectas una interpretación profesional nueva e incierta, puedes proponer confirmación: '
    'devuelve JSON {"reply":"respuesta breve sin pregunta","confirm":{"field":"interest_type",'
    '"value":"service_offer","evidence":"cita literal del mensaje"}}. '
    'Campos: interest_type (employment, service_offer, both), team_available (true/false). '
    'La evidencia debe estar en el mensaje actual. Si no necesitas confirmar, responde en texto normal.')


def _available(facts, field):
    states = facts.get("field_states") or {}
    if states.get(field) == "rechazado_por_usuario":
        return False
    value = facts.get(field)
    return value in (None, "", "unknown") if field == "interest_type" else value is None


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
    if not isinstance(field, str) or field not in {"interest_type", "team_available"}:
        return reply or None, None
    if field == "team_available" and type(value) is not bool:
        return reply or None, None
    if field == "interest_type" and not isinstance(value, str):
        return reply or None, None
    question = QUESTIONS.get((field, value))
    if (not question or not _available(facts, field) or not isinstance(evidence, str)
            or not plain(evidence) or plain(evidence) not in plain(latest)
            or private_data(evidence) or private_data(reply) or "?" in reply or "?" in latest):
        return reply or None, None
    return (reply + " " + question).strip(), {"field": field, "value": value, "question": question}


def remember_confirmation(lead, proposal, delivered_body, outbound_id):
    if not proposal or not delivered_body.endswith(proposal["question"]):
        return
    field = proposal["field"]
    origins = dict(lead.profile_sources or {})
    if origins.get(field, {}).get("source") == "manual":
        return
    if not _available({field: getattr(lead, field), "field_states": {
            field: origins.get(field, {}).get("state")}}, field):
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
    if field not in {"interest_type", "team_available"}:
        return {}
    if origins.get(field, {}).get("source") == "manual" or not _available({
            field: getattr(lead, field), "field_states": {field: origins.get(field, {}).get("state")}}, field):
        return {}
    if field == "interest_type" and value in {"employment", "service_offer", "both"}:
        return {field: value}
    if field == "team_available" and type(value) is bool:
        workers = lead.workers
        if (value and workers == 1) or (not value and workers is not None and workers > 1):
            return {}
        if not value and workers is None and origins.get("workers", {}).get("source") != "manual":
            return {field: False, "workers": 1}
        return {field: value}
    return {}
