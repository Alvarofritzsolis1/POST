"""Local, progressive professional intake for small contractors and job-seekers.

Ask one short question at a time. Understand spelling mistakes, very short
answers, independent tradespeople and small crews without judging literacy.
Collect voluntary professional declarations only, never determine eligibility,
legal employment, suitability, or award work. No external model is required.
"""
import re
from .galancito_triage import analyze, plain, private_data

_INTEREST_QUESTION = "ofreces trabajos por tu cuenta"
_TEAM_QUESTION = "trabajas solo"
_TRADE_QUESTION = "que trabajo realizas"
_EXPERIENCE_QUESTION = "cuanto tiempo llevas"
_COMMUNE_QUESTION = "en que comuna"
_AVAILABILITY_QUESTION = "desde cuando podrias"

_PROMPTS = (
    _INTEREST_QUESTION, _TEAM_QUESTION, _TRADE_QUESTION,
    _EXPERIENCE_QUESTION, _COMMUNE_QUESTION, _AVAILABILITY_QUESTION,
    "que oficio", "que servicio", "a que oficio", "cuantas personas",
    "cuantos anos", "desde cuando puedes", "puedes venir con", "representas una empresa",
    "buscas empleo como trabajador",
)


def is_intake_prompt(prompt: str) -> bool:
    normalized = plain(prompt)
    return any(key in normalized for key in _PROMPTS)


def _is_word_or_option(message: str, prior_prompt: str, option: str) -> bool:
    norm = plain(message)
    return norm == option and is_intake_prompt(prior_prompt)


def _intent_from_message(text: str, previous: str) -> str | None:
    norm, prompt = plain(text), plain(previous)
    if norm in {"1", "uno"} and _INTEREST_QUESTION in prompt:
        return "service_offer"
    if norm in {"2", "dos"} and _INTEREST_QUESTION in prompt:
        return "employment"
    if any(phrase in norm for phrase in (
        "ofrezco servicios", "ofresco servicios", "mis servicios", "trabajo por mi cuenta",
        "tengo un emprendimiento", "somos contratistas", "soy contratista",
        "hago trabajos por mi cuenta", "quiero ofrecer mis servicios",
        "somos una empresa", "tengo empresa",
    )):
        return "service_offer"
    if any(phrase in norm for phrase in (
        "busco pega", "busco empleo", "busco trabajo como trabajador",
        "quiero empleo", "busco trabajo de empleado", "quiero trabajar contratado",
        "postulo como trabajador", "postular a un empleo",
    )):
        return "employment"
    if _INTEREST_QUESTION in prompt:
        if norm in {"servicios", "contratista", "independiente", "por mi cuenta",
                    "ofrezco trabajo", "tengo cuadrilla", "maestro independiente"}:
            return "service_offer"
        if norm in {"empleo", "pega", "trabajador", "busco empleo", "busco pega"}:
            return "employment"
    return None


def _team_from_message(text: str, previous: str) -> bool | None:
    norm, prompt = plain(text), plain(previous)
    if any(s in norm for s in ("trabajo solo", "trabajo sola", "voy solo", "voy sola",
                             "yo solo", "yo sola", "no puedo llevar gente",
                             "sin equipo", "no tengo gente", "no tengo cuadrilla")):
        return False
    if any(s in norm for s in ("puedo traer gente", "puedo llevar gente", "tengo cuadrilla",
                             "con equipo", "somos un equipo", "tengo ayudantes",
                             "trabajamos varios", "con trabajadores", "puedo ir con gente")):
        return True
    if _TEAM_QUESTION in prompt or "puedes venir con" in prompt:
        if norm in {"1", "uno", "solito", "solo", "sola", "sin gente", "sin equipo", "no"}:
            return False
        if norm in {"2", "dos", "con gente", "con equipo", "con personas", "si", "si puedo"}:
            return True
    return None


def apply_intake(lead, message: str, prior_prompt: str = "") -> None:
    """Store only volunteered operational facts; never overwrite a manually verified trade."""
    if private_data(message) or len(message) > 400:
        return
    value, prev = plain(message), plain(prior_prompt)
    if not value:
        return
    declares_own_work = bool(re.search(
        r"\b(?:soy|soi|trabajo|trabajamos|hago|hacemos|tengo|tenemos|somos|"
        r"ofrezco|ofresco|busco|postulo|me dedico|puedo empezar|puedo ir)\b", value))
    # A question about painters does not make the sender a painter. However,
    # 'soy pintor, ¿hay pega?' still supplies a useful explicit declaration.
    if ("?" in message or "¿" in message) and not declares_own_work:
        return
    intent = _intent_from_message(message, prior_prompt)
    if intent and getattr(lead, "interest_type", "unknown") == "unknown":
        lead.interest_type = intent
    facts = analyze(message)
    if facts.entity_type != "unknown":
        lead.entity_type = facts.entity_type
    if intent == "employment" or "soy trabajador" in value:
        lead.entity_type = "individual"
    if "empresa" in value and any(phrase in value for phrase in (
        "tengo empresa", "tengo una empresa", "somos una empresa", "represento una empresa"
    )):
        lead.entity_type = "company"
    declared_trade = declares_own_work or (
        len(value.split()) <= 2 and "?" not in message) or (
        is_intake_prompt(prior_prompt) and any(s in prev for s in
        (_TRADE_QUESTION, "que oficio", "que servicio", "a que oficio")))
    if facts.specialty and declared_trade and (
        not lead.specialty or lead.specialty_source == "message"):
        lead.specialty, lead.specialty_source = facts.specialty, "message"
    # An unfamiliar trade may still be self-declared. Keep it marked as
    # unverified; never treat it as an approved official specialty.
    if not lead.specialty and any(s in prev for s in (_TRADE_QUESTION, "que oficio",
                                                       "que servicio", "a que oficio")):
        if (2 <= len(message.strip()) <= 80 and
                not re.search(r"\d|@|https?://|\b(?:rut|clave|contrasena|telefono|calle|pasaje|direccion|numero)\b", value)
                and value not in {"no se", "no tengo", "nada", "si", "no", "1", "2"}
                and len(value.split()) <= 8):
            lead.specialty, lead.specialty_source = message.strip(), "message"
    team = _team_from_message(message, prior_prompt)
    if team is not None:
        lead.team_available = team
        if not team and lead.workers is None:
            lead.workers = 1
    if facts.workers is not None:
        lead.workers = facts.workers
        if facts.workers > 1:
            lead.team_available = True
        elif lead.team_available is None:
            lead.team_available = False
    if lead.team_available is True and lead.workers is None:
        m = re.search(r"\b(?:somos|equipo de|en total somos|iremos|tengo)\s+(\d{1,3})\b", value)
        if not m and ("cuantas personas" in prev or "con cuantas" in prev):
            m = re.fullmatch(r"(\d{1,3})\s*(?:personas|maestros|trabajadores|gente)?", value)
        if m and 1 <= int(m.group(1)) <= 500:
            lead.workers = int(m.group(1))
    if not lead.experience and (any(s in prev for s in (
        _EXPERIENCE_QUESTION, "cuanta experiencia", "cuantos anos")) or
        ("experiencia" in value and re.search(r"\b\d{1,2}\s+(?:anos?|mes(?:es)?)\b", value))):
        if value in {"ninguna", "no tengo", "sin experiencia", "no tengo experiencia",
                     "recién comienzo", "recien comienzo", "nuevo", "nuevo en esto"}:
            lead.experience = "Sin experiencia declarada"
        elif value in {"prefiero no decir", "prefiero no indicar"}:
            lead.experience = "No informado por el interesado"
        elif re.fullmatch(r"\d{1,2}", value):
            lead.experience = value + " años declarados"
        elif re.search(r"\b\d{1,2}\s+anos?\b|\b\d{1,2}\s+mes(?:es)?\b", value):
            lead.experience = message.strip()[:180]
    if not lead.work_area and _COMMUNE_QUESTION in prev:
        commune = message.strip()
        commune = re.sub(r"^(?:en|puedo trabajar en|soy de|vivo en)\s+", "", commune, flags=re.I)
        if (2 <= len(commune) <= 80 and len(commune.split()) <= 5
                and not re.search(r"\d|@|http|\b(?:calle|pasaje|avenida|direccion|numero|rut)\b", plain(commune))
                and plain(commune) not in {"no se", "no", "si"}):
            lead.work_area = commune
    if not lead.availability and facts.availability:
        lead.availability = facts.availability
    if not lead.availability and (_AVAILABILITY_QUESTION in prev or
                                  value in {"desde hoy", "desde manana", "inmediato", "inmediata"}):
        common = {"hoy", "desde hoy", "manana", "desde manana", "inmediata",
                  "inmediato", "proxima semana", "la proxima semana", "en dos semanas",
                  "despues de dos semanas", "cuando me necesiten"}
        if value in common or (
            len(value) < 65 and re.search(
                r"\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo|semana|mes)\b", value)
        ):
            lead.availability = message.strip()[:100]


def _friendly_ack(message: str, facts: dict, question: str) -> str:
    """Brief, grounded acknowledgement, not a repetitive scripted self-introduction."""
    norm = plain(message)
    trade = (facts.get("specialty") or "").strip()
    if norm in {"hola", "ola", "buenas", "buen dia", "buenos dias", "buenas tardes"}:
        return "¡Hola! Cuéntame un poquito."
    if "trabajas solo" in plain(question) and facts.get("interest_type") == "service_offer":
        return "Perfecto, entonces ofreces tus servicios."
    if "cuantas personas" in plain(question):
        return "Ya, entiendo que puedes venir con otras personas."
    if "cuanto tiempo llevas" in plain(question) and facts.get("workers") is not None:
        return "Gracias, me queda clara la cantidad de personas."
    if "en que comuna" in plain(question) and facts.get("experience"):
        return "Gracias, también tengo anotada tu experiencia."
    if "desde cuando" in plain(question) and facts.get("work_area"):
        return "Bien, ya sé en qué comuna puedes trabajar."
    if "ofreces trabajos" in plain(question) and trade:
        return "Entiendo que trabajas en " + trade.lower() + "."
    if "que trabajo realizas" in plain(question):
        return "Cuéntame a qué te dedicas."
    return "Gracias por contarme."


def next_intake_reply(message: str, facts: dict, prior_prompt: str = "") -> str | None:
    """Respond conversationally, then ask one relevant missing question.

    No fake thinking delay, and no guessed work, hiring, wages or promises.
    """
    info = analyze(message)
    if info.intent in {"human", "restricted", "documents", "requirements", "about",
                       "contractor_request", "publish"} or private_data(message):
        return None
    norm = plain(message)
    engaged = (
        info.intent in {"greeting", "job_seeker", "company_offer", "capacity", "trade_offer", "apply"} or
        is_intake_prompt(prior_prompt) or
        any(p in norm for p in ("ofrezco servicios", "ofresco servicios", "soy contratista",
                               "busco pega", "busco trabajo", "hago trabajos",
                               "trabajo por mi cuenta", "tengo una cuadrilla", "quiero postular"))
    )
    if not engaged:
        return None
    intent = facts.get("interest_type", "unknown")
    if not facts.get("specialty"):
        question = "¿Qué trabajo realizas? Por ejemplo, pintura o carpintería."
    elif intent == "unknown":
        question = "¿Ofreces trabajos por tu cuenta (1) o buscas empleo (2)?"
    elif facts.get("team_available") is None:
        question = "¿Trabajas solo (1) o puedes venir con otras personas (2)?"
    elif facts.get("team_available") is True and facts.get("workers") is None:
        question = "¿Cuántas personas pueden trabajar contigo en total?"
    elif not facts.get("experience"):
        question = "¿Cuánto tiempo llevas haciendo este trabajo? Puedes decir 2 años o recién comienzo."
    elif not facts.get("work_area"):
        question = "¿En qué comuna puedes trabajar?"
    elif not facts.get("availability"):
        question = "¿Desde cuándo podrías comenzar?"
    elif facts.get("display_name") in {"", "Interesado de Facebook", "Contacto sin nombre", None} and not facts.get("name_opt_out"):
        question = "¿Cómo prefieres que te llamemos? Si prefieres no decirlo, escribe paso."
    else:
        return ("Gracias por contarme sobre tu trabajo. Ya quedó registrada la información "
                "que me diste para que administración pueda revisarla si corresponde. "
                "Esto todavía no significa que exista una contratación confirmada.")
    return (_friendly_ack(message, facts, question) + " " + question)[:540]


def natural_messenger_reply(text: str, prior_ai_replies: int = 0) -> str:
    """Identify as the virtual assistant initially, then avoid repeated bot branding."""
    clean = text.strip()
    if prior_ai_replies <= 0:
        # Keep the first reply unmistakably from an assistant.
        if not plain(clean).startswith("soy galancito"):
            clean = "Soy Galancito, el asistente virtual de GALANT. " + clean
        return clean[:550]
    # Every conversation started with the separate, explicit virtual-assistant
    # disclosure/consent prompt. Dropping repeated branding does not impersonate
    # a human or conceal the use of automation.
    for beginning in (
        "Soy Galancito, asistente virtual de GALANT. ",
        "Soy Galancito, el asistente virtual de GALANT. ",
        "Soy Galancito. ",
    ):
        if clean.lower().startswith(beginning.lower()):
            clean = clean[len(beginning):]
            break
    return clean[:550]
