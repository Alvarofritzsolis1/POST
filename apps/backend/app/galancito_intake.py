"""Consent-aware, deterministic intake for Red de Obras interested people.

Collect only volunteered professional facts, one question at a time. No hiring score,
no inferred employer relationship, no automatic awarding or external AI required.
"""
import re

from .galancito_triage import analyze, plain, private_data

_PROMPT_MARKERS = (
    "buscas empleo como trabajador", "buscas trabajo como", "representas una empresa",
    "que oficio", "que trabajo", "que servicio", "puedes venir con", "trabajas solo",
    "cuantas personas", "cuanta experiencia", "cuantos anos", "en que comuna",
    "desde cuando puedes", "desde cuando podrias", "desde cuando tienen",
)


def is_intake_prompt(prompt: str) -> bool:
    return any(marker in plain(prompt) for marker in _PROMPT_MARKERS)


def _team_answer(text: str, prompt: str) -> bool | None:
    value = plain(text)
    if any(x in value for x in ("trabajo solo", "voy solo", "yo solo", "sin equipo",
                              "no puedo traer gente", "no tengo gente")):
        return False
    if any(x in value for x in ("puedo traer gente", "puedo llevar gente",
                              "con equipo", "somos un equipo", "tengo cuadrilla",
                              "con trabajadores", "puedo ir con")):
        return True
    if is_intake_prompt(prompt) and any(x in plain(prompt) for x in
                                         ("puedes venir con", "trabajas solo")):
        if value in {"si", "si puedo", "claro", "con gente", "con personas"}:
            return True
        if value in {"no", "solo", "solito", "sin gente"}:
            return False
    return None


def apply_intake(lead, message: str, prior_prompt: str = "") -> None:
    """Apply only explicit self-reported professional facts, never override admin choices."""
    if private_data(message) or len(message) > 400 or "?" in message:
        return
    norm = plain(message)
    info = analyze(message)
    if info.entity_type != "unknown":
        lead.entity_type = info.entity_type
    if any(p in norm for p in ("soy trabajador", "busco empleo", "busco pega", "busco trabajo",
                              "postulo como trabajador", "quiero postular")):
        lead.entity_type = "individual"
    if any(p in norm for p in ("somos una empresa", "tengo una empresa", "represento una empresa",
                              "mi empresa")) and "no tengo" not in norm:
        lead.entity_type = "company"
    if is_intake_prompt(prior_prompt) and (
        "representas una empresa" in plain(prior_prompt) or
        "buscas empleo como trabajador" in plain(prior_prompt)
    ):
        if norm in {"trabajador", "empleo", "persona", "busco trabajo", "busco empleo"}:
            lead.entity_type = "individual"
        if norm in {"empresa", "soy empresa", "tengo empresa", "ofrezco servicios"}:
            lead.entity_type = "company"
    if info.specialty and (not lead.specialty or lead.specialty_source == "message"):
        lead.specialty, lead.specialty_source = info.specialty, "message"
    if not lead.specialty and is_intake_prompt(prior_prompt) and "que oficio" in plain(prior_prompt):
        # Unknown trades require human confirmation; never store a free-form answer
        # that may contain contact details or unsolicited sensitive attributes.
        pass
    team = _team_answer(message, prior_prompt)
    if team is not None:
        lead.team_available = team
        if team is False and lead.workers is None:
            lead.workers = 1
    if info.workers is not None:
        lead.team_available = info.workers > 1
        lead.workers = info.workers
    if lead.team_available is True and lead.workers is None:
        m = re.search(r"\b(?:somos|equipo de|en total somos|iremos)\s+(\d{1,3})\b", norm)
        if m and int(m.group(1)) > 0:
            lead.workers = int(m.group(1))
    if not lead.experience and "experiencia" in plain(prior_prompt):
        if norm in {"ninguna", "no tengo", "sin experiencia", "no tengo experiencia"}:
            lead.experience = "Sin experiencia declarada"
        elif norm in {"prefiero no decir", "prefiero no indicar"}:
            lead.experience = "No informado por el interesado"
        elif re.search(r"\b\d{1,2}\s+anos?\b|\b\d{1,2}\s+mes(?:es)?\b", norm):
            lead.experience = message.strip()[:180]
    if not lead.work_area and "en que comuna" in plain(prior_prompt):
        locality = message.strip()
        locality = re.sub(r"^(?:en|puedo trabajar en|soy de|vivo en)\s+", "", locality, flags=re.I)
        if (2 <= len(locality) <= 80 and not re.search(r"\d|@|http|\b(?:calle|pasaje|avenida|direccion|numero)\b", plain(locality))):
            lead.work_area = locality
    if not lead.availability and ("desde cuando" in plain(prior_prompt) or
                                  norm in {"desde hoy", "desde manana", "inmediato", "inmediata"}):
        if norm in {"desde hoy", "hoy", "desde manana", "manana", "inmediata",
                    "inmediato", "proxima semana", "la proxima semana", "en dos semanas"} or (
                len(norm) < 65 and re.search(r"\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo|semana|mes)\b", norm)):
            lead.availability = message.strip()[:100]


def next_intake_reply(message: str, facts: dict, prior_prompt: str = "") -> str | None:
    """Ask one missing question; avoid turning unrelated support requests into intake."""
    info = analyze(message)
    if info.intent in {"human", "restricted", "documents", "requirements", "about",
                       "contractor_request", "publish"} or private_data(message):
        return None
    engaged = info.intent in {"job_seeker", "company_offer", "capacity", "trade_offer", "apply"} or is_intake_prompt(prior_prompt)
    if not engaged:
        return None
    kind = facts.get("entity_type") or info.entity_type
    if kind == "unknown":
        question = "¿Buscas empleo como trabajador o representas una empresa?"
    elif not facts.get("specialty"):
        question = ("¿A qué oficio o trabajo postulas?" if kind == "individual" else
                    "¿Qué oficio o servicio ofrece tu empresa?")
    elif facts.get("team_available") is None:
        question = "¿Trabajas solo o puedes venir con otras personas?"
    elif facts.get("team_available") is True and facts.get("workers") is None:
        question = "¿Cuántas personas podrían trabajar en total contigo?"
    elif not facts.get("experience"):
        question = "¿Cuántos años de experiencia tienes en ese oficio?"
    elif not facts.get("work_area"):
        question = "¿En qué comuna puedes trabajar?"
    elif not facts.get("availability"):
        question = "¿Desde cuándo podrías comenzar?"
    else:
        return ("Soy Galancito. Gracias, ya tengo tu oficio, modalidad de trabajo, "
                "experiencia, comuna y disponibilidad declaradas. "
                "El equipo puede revisar tu interés, sin garantizar contratación.")
    return "Soy Galancito. " + question
