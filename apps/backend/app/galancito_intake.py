"""Local, progressive professional intake for small contractors and job-seekers.

Ask one short question at a time. Understand spelling mistakes, very short
answers, independent tradespeople and small crews without judging literacy.
Collect voluntary professional declarations only, never determine eligibility,
legal employment, suitability, or award work. No external model is required.
"""
import re
from datetime import date, timedelta
from .galancito_triage import analyze, declaration_text, plain, private_data
from .galancito_links import trade_declarations
from .galancito_communes import find_communes

UNKNOWN_NAMES = {"", None, "Interesado de Facebook", "Contacto sin nombre"}

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
    "buscas empleo como trabajador", "como prefieres que te llamemos",
    "cual es tu nombre", "como te llamas", "dime tu nombre",
    "me dices tu nombre", "me puedes decir tu nombre", "tu nombre por favor",
)


def is_intake_prompt(prompt: str) -> bool:
    normalized = plain(prompt)
    return any(key in normalized for key in _PROMPTS)


_ROLE_SERVICE = (
    "ofrezco servicios", "ofresco servicios", "mis servicios", "por mi cuenta",
    "tengo un emprendimiento", "somos contratistas", "soy contratista",
    "somos una empresa", "tengo empresa", "tengo una empresa", "represento una empresa",
    "tengo cuadrilla", "tengo una cuadrilla",
)
_ROLE_WORKER = (
    "busco pega", "busco empleo", "busco trabajo", "ando buscando pega",
    "ando en busca de pega", "quiero empleo", "quiero trabajar contratado",
    "postulo como trabajador", "postular a un empleo", "soy trabajador", "soy trabajadora",
)
_NAME_PROMPTS = (
    "como prefieres que te llamemos", "cual es tu nombre", "como te llamas",
    "dime tu nombre", "me dices tu nombre", "me puedes decir tu nombre", "tu nombre por favor",
)
_TRADE_PROMPTS = (_TRADE_QUESTION, "que oficio", "que servicio", "a que oficio")
_CORRECTION = re.compile(r"\b(?:corrijo|correccion|me equivoque|en realidad|quise decir|al final|ahora|ya no|cambio de fecha)\b")
_OFFERS = re.compile(r"\b(?:pega|trabaj|servici|contrat|postul|dispon|equipo|cuadrill|"
                     r"ofici|ayudant|empresa|experienc|person|comuna|maestr|habl|gracia)\w*\b|"
                     r"\b(?:si|no|dale|bueno|obvio|ok|listo|bien|paso)\b")
_DATE = r"(?:\d{1,2}/\d{1,2}/20\d{2}|20\d{2}-\d{2}-\d{2})"
_DAY = (r"(?:hoy|manana|lunes|martes|miercoles|jueves|viernes|sabado|domingo|"
        r"(?:la )?proxima semana|en dos semanas|fin de mes|cuando me necesiten|inmediat[oa])")
_AREA_CUE = re.compile(
    r"\b(?:me muevo|puedo trabajar|trabajo|trabajamos|atiendo|busco (?:pega|trabajo|empleo)) "
    r"(?:por|en)\b|\b(?:solo en|comunas? de trabajo)\b"
)


def unanswered_intake_question(lead, prompt: str) -> bool:
    """Keep a delivered question in context until its field has an answer."""
    value = plain(prompt)
    pending = (
        (_TRADE_PROMPTS, not lead.specialty),
        ((_INTEREST_QUESTION,), lead.interest_type == "unknown"),
        ((_TEAM_QUESTION, "puedes venir con"), lead.team_available is None),
        (("cuantas personas", "con cuantas"), lead.workers is None),
        ((_EXPERIENCE_QUESTION, "cuanta experiencia", "cuantos anos"), not lead.experience),
        ((_COMMUNE_QUESTION,), not lead.work_area),
        ((_AVAILABILITY_QUESTION, "desde cuando puedes"), not lead.availability),
        (_NAME_PROMPTS, lead.display_name in UNKNOWN_NAMES and not lead.name_opt_out),
    )
    return any(missing and any(match in value for match in phrases) for phrases, missing in pending)


def _affirmed(value: str, phrases: tuple[str, ...]) -> bool:
    for clause in value.split(" | "):
        for phrase in phrases:
            for match in re.finditer(r"\b" + re.escape(phrase) + r"\b", clause):
                prefix = clause[max(0, match.start() - 40):match.start()]
                if not re.search(r"\b(?:no|nunca) (?:\w+ ){0,4}$", prefix):
                    return True
    return False


def _role_update(lead, value: str, previous: str) -> None:
    service = _affirmed(value, _ROLE_SERVICE)
    worker = _affirmed(value, _ROLE_WORKER)
    if _INTEREST_QUESTION in previous:
        service |= value in {"1", "uno", "servicios", "contratista", "independiente", "ofrezco trabajo"}
        worker |= value in {"2", "dos", "empleo", "pega", "trabajador", "trabajadora"}
        if value in {"ambos", "ambas", "las dos", "los dos", "las dos cosas", "ambos roles"}:
            service = worker = True
    current = getattr(lead, "interest_type", "unknown")
    if service and worker:
        lead.interest_type = "both"
    elif service or worker:
        declared = "service_offer" if service else "employment"
        only = bool(_CORRECTION.search(value) or re.search(r"\bsolo (?:busco|ofrezco|tomo)\b", value))
        if only or current in {"unknown", declared}:
            lead.interest_type = declared
        else:
            lead.interest_type = "both"
    if _affirmed(value, ("tengo una empresa", "tengo empresa", "somos una empresa", "represento una empresa")):
        lead.entity_type = "company"
    elif _affirmed(value, ("no tengo empresa", "soy independiente", "a mi nombre")):
        lead.entity_type = "individual"
    elif getattr(lead, "entity_type", "unknown") == "unknown" and (
            worker or _affirmed(value, ("trabajo solo", "trabajo sola"))):
        lead.entity_type = "individual"


def _name_update(lead, message: str, previous: str) -> None:
    if not hasattr(lead, "display_name") or getattr(lead, "name_opt_out", False):
        return
    asked = any(question in previous for question in _NAME_PROMPTS)
    value = plain(message)
    if (asked and value in {"paso", "no", "prefiero no decir", "prefiero no", "no quiero"}
            or re.search(r"\b(?:prefiero no dar mi nombre|no quiero dar mi nombre)\b", value)):
        lead.name_opt_out = True
        return
    explicit = re.search(r"\b(?:me llamo|mi nombre es)\s+([^,;.!?¿¡\n]+)", message, re.I)
    informal = re.fullmatch(r"(?:hola[,!]?\s+)?[Ss]oy\s+([A-ZÁÉÍÓÚÜÑ][^,;.!?¿¡\n]+)[.!]?", message.strip())
    candidate = (explicit[1] if explicit else informal[1] if informal else message if asked else "").strip()
    candidate = re.split(r"\s+(?:y )?(?:trabajo|hago|busco|soy|tengo|vivo|puedo|ofrezco)\b",
                         candidate, maxsplit=1, flags=re.I)[0].strip(" .")
    norm = plain(candidate)
    if (not re.fullmatch(r"[^\W\d_]+(?:[ .’'-]+[^\W\d_]+){0,4}", candidate)
            or len(candidate) > 70 or "?" in candidate
            or norm.startswith(("de ", "en ", "tu ", "un ", "una ", "el ", "la ", "hola ", "me "))
            or _OFFERS.search(norm) or analyze(candidate).specialty):
        return
    known = lead.display_name not in UNKNOWN_NAMES
    if not known or (explicit and _CORRECTION.search(value)):
        lead.display_name = candidate


def _commune_update(lead, message: str, previous: str) -> None:
    value = plain(message)
    asked = _COMMUNE_QUESTION in previous
    found = []
    for fragment in re.split(r"[,;.!\n]+|\bpero\b", message, flags=re.I):
        clause = plain(fragment)
        cue = _AREA_CUE.search(clause)
        if re.search(r"\b(?:no trabajo en|no voy a|no puedo ir a|no puedo trabajar en)\b", clause):
            continue
        if not cue and not asked and not clause.startswith(("tambien en ", "y en ", "en ")):
            # "Hago aseo en Hualpén" relates the commune to the work.
            match = re.search(r"\b(?:hago|hacemos|instalo|reparo) (?:\w+ ){1,4}en\b", clause)
            if not match:
                continue
            cue = match
        found.extend(find_communes(clause[cue.end():] if cue else clause))
    if not found:
        return
    current = list(getattr(lead, "work_communes", None) or [])
    if not current and lead.work_area:
        current = find_communes(lead.work_area)
    replace = bool(_CORRECTION.search(value) and not value.startswith("tambien ")) or "solo en " in value
    communes = list(dict.fromkeys([*([] if replace else current), *found]))
    lead.work_communes = communes
    lead.work_area = ", ".join(communes)[:120]


def _team_update(lead, value: str, previous: str) -> None:
    capacity = _affirmed(value, ("puedo traer gente", "puedo llevar gente", "tengo cuadrilla",
                                 "tengo una cuadrilla", "somos un equipo",
                                 "tengo ayudantes", "trabajamos varios", "puedo ir con gente"))
    solo = _affirmed(value, ("trabajo solo", "trabajo sola", "voy solo", "voy sola",
                             "voy a ir solo", "voy a ir sola", "yo solo", "yo sola", "sin equipo"))
    if value in {"no puedo llevar gente", "no tengo gente", "no tengo cuadrilla"}:
        solo = True
    if _TEAM_QUESTION in previous or "puedes venir con" in previous:
        solo |= value in {"1", "uno", "solito", "solo", "sola", "sin gente", "sin equipo"}
        capacity |= value in {"2", "dos", "con gente", "con equipo", "con personas"}
    if solo and not capacity:
        lead.team_available, lead.workers = False, 1
    elif capacity:
        if lead.team_available is False:
            lead.workers = None
        lead.team_available = True

    count = r"([1-9]\d{0,3}|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)"
    total = re.search(r"\b(?:somos|equipo de|iremos) " + count + r"\b", value)
    if not total:
        total = re.search(r"\btengo " + count + r" (?:ayudantes?|trabajadores?|personas?|maestros?)\b", value)
    helpers = re.search(
        r"\b(?:puedo ir con|voy con|llevo|puedo llevar) " + count
        + r" (?:ayudantes?|personas?|maestros?|trabajadores?)\b", value)
    if not total and not helpers and ("cuantas personas" in previous or "con cuantas" in previous):
        total = re.fullmatch(r"(?:con |en total )?" + count + r"(?: personas| maestros| trabajadores| gente)?", value)
    if not total and not helpers:
        return
    matched = total or helpers
    if not _affirmed(value, (matched[0],)):
        return
    token = matched[1]
    numbers = {"uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
               "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
    number = (int(token) if token.isdecimal() else numbers[token]) + bool(helpers and not total)
    if 1 <= number <= 5000:
        lead.workers, lead.team_available = number, number > 1


def _availability_update(lead, message: str, previous: str, *, on_date=None) -> None:
    clean = message.strip()
    value = plain(clean)
    asked = _AVAILABILITY_QUESTION in previous or "desde cuando puedes" in previous
    if any(phrase in value for phrase in ("sin disponibilidad", "no puedo empezar aun")):
        lead.availability = "Sin disponibilidad"
        return
    cue = re.search(r"\b(?:disponibl[ea]s?|puedo (?:empezar|comenzar|partir|desde)|arranco|parto|"
                    r"comienzo|empiezo|puedo ir)\b|\bdesde (?:el )?(?=" + _DAY + r"\b)", value)
    literal = re.search(r"\b" + _DATE + r"\b", clean)
    if literal and (cue or asked or re.search(r"\bdesde (?:el )?" + _DATE + r"\b", clean, re.I)):
        if re.search(r"\bno (?:puedo|estoy|empiezo|parto)\b", value):
            return
        token = literal[0]
        try:
            if "/" in token:
                day, month, year = map(int, token.split("/"))
                lead.availability = date(year, month, day).isoformat()
            else:
                lead.availability = date.fromisoformat(token).isoformat()
        except ValueError:
            return
    elif (cue or asked or re.fullmatch(_DAY, value)) and not re.search(
            r"\b(?:no puedo|no estoy disponible|no desde|nunca)\b", value):
        relative = re.search(r"\b" + _DAY + r"\b", value)
        if relative:
            day = relative[0]
            if on_date and day in {"hoy", "manana"}:
                lead.availability = (on_date + timedelta(days=day == "manana")).isoformat()
            elif value in {day, "desde " + day}:
                lead.availability = clean[:100]
            else:
                day = day.replace("manana", "mañana").replace("proxima", "próxima")
                lead.availability = "Desde " + day


def apply_intake(lead, message: str, prior_prompt: str = "", *,
                 declarations: dict[str, bool] | None = None, on_date=None) -> None:
    """Update declared facts using the text and the last delivered question."""
    if private_data(message) or len(message) > 3500:
        return
    if analyze(message).intent in {"human", "restricted"} or identity_reply(message):
        return
    prev = plain(prior_prompt)
    statement = declaration_text(message)
    value = " | ".join(plain(part) for part in re.split(r"[,;.!\n]+|\bpero\b", statement, flags=re.I)
                       if plain(part))
    if declarations is None:
        declarations = trade_declarations(message, prior_prompt, allow_bare=True)
    positives = [trade for trade, present in declarations.items() if present]
    if positives and (not lead.specialty or
                      (lead.specialty_source == "message" and declarations.get(lead.specialty) is False)):
        lead.specialty, lead.specialty_source = positives[0][:100], "message"
    if not value:
        return
    _role_update(lead, value, prev)
    _name_update(lead, statement, prev)
    _team_update(lead, value, prev)
    _commune_update(lead, statement, prev)
    _availability_update(lead, statement, prev, on_date=on_date)
    if not lead.experience:
        experience = re.search(r"\b(\d{1,2})\s+(anos?|mes(?:es)?)\b", value)
        asked = any(s in prev for s in (_EXPERIENCE_QUESTION, "cuanta experiencia", "cuantos anos"))
        volunteered = bool(re.search(r"\b(?:experiencia|llevo|llevamos)\b", value))
        if value in {"sin experiencia", "no tengo experiencia", "recien comienzo"} or (
                asked and value in {"ninguna", "no tengo", "nuevo", "nuevo en esto"}):
            lead.experience = "Sin experiencia declarada"
        elif asked and value in {"prefiero no decir", "prefiero no indicar", "paso"}:
            lead.experience = "No informado por el interesado"
        elif asked and re.fullmatch(r"\d{1,2}", value):
            lead.experience = value + " años declarados"
        elif experience and (asked or volunteered):
            lead.experience = experience[0].replace("ano", "año")


def identity_reply(message: str) -> str | None:
    value = plain(message)
    if re.search(r"\b(?:eres|soi|er[ií]s|hablo con|me (?:responde|atiende)|estoy hablando con) "
                 r"(?:una? |el )?(?:bot|robot|ia|inteligencia artificial|persona|humano)\b", value):
        return "Soy Galancito, el asistente de IA de GALANT. Si quieres hablar con alguien del equipo, avísame."
    return None


def _friendly_ack(message: str, facts: dict, question: str, prior: str = "") -> str:
    """Brief, grounded acknowledgement, not a repetitive scripted self-introduction."""
    norm = plain(message)
    trade = (facts.get("specialty") or "").strip()
    if norm in {"hola", "ola", "buenas", "buen dia", "buenos dias", "buenas tardes"}:
        return "¡Hola, qué tal!"
    if not _CORRECTION.search(norm) and any(q in plain(prior) for q in ("cual es tu nombre", "como te llamas", "como prefieres que te llamemos")):
        if facts.get("display_name") not in (None, "", "Interesado de Facebook", "Contacto sin nombre"):
            return "Un gusto, " + facts["display_name"].split()[0].title() + "."
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
    if facts.get("turn_changed") and _CORRECTION.search(norm):
        return "Listo, actualicé ese dato."
    return ""


def next_intake_reply(message: str, facts: dict, prior_prompt: str = "") -> str | None:
    """Respond conversationally, then ask one relevant missing question.

    No fake thinking delay, and no guessed work, hiring, wages or promises.
    """
    identity = identity_reply(message)
    if identity:
        return identity
    info = analyze(message)
    capacity_statement = any(p in plain(message) for p in (
        "puedo traer gente", "puedo llevar gente", "tengo cuadrilla",
        "puedo ir con gente", "trabajamos varios"
    ))
    if (needs_deeper_response(message) or
            info.intent in {"human", "restricted", "documents", "requirements",
                        "about", "publish"} or private_data(message)
            or (info.intent == "contractor_request" and not capacity_statement)):
        return None
    norm = plain(message)
    if facts.get("turn_changed") is False and re.search(
            r"\b(?:corrijo|correccion|me equivoque|quise decir|cambio de fecha)\b", norm):
        return "¿Qué dato quieres corregir?"
    engaged = (
        info.intent in {"greeting", "job_seeker", "company_offer", "capacity", "trade_offer", "apply"} or
        capacity_statement or is_intake_prompt(prior_prompt) or _CORRECTION.search(norm) or
        bool(facts.get("turn_changed")) or
        any(p in norm for p in ("ofrezco servicios", "ofresco servicios", "soy contratista",
                               "busco pega", "busco trabajo", "hago trabajos",
                               "trabajo por mi cuenta", "tengo una cuadrilla", "quiero postular"))
    )
    if not engaged:
        return None
    intent = facts.get("interest_type", "unknown")
    if not (facts.get("specialty") or facts.get("trades")):
        question = "¿Qué trabajo realizas?"
    elif intent == "unknown":
        question = "¿Ofreces trabajos por tu cuenta (1), buscas empleo (2) o haces las dos cosas?"
    elif facts.get("team_available") is None:
        question = "¿Trabajas solo (1) o puedes venir con otras personas (2)?"
    elif facts.get("team_available") is True and facts.get("workers") is None:
        question = "¿Cuántas personas pueden trabajar contigo en total?"
    elif not facts.get("experience"):
        question = "¿Cuánto tiempo llevas en ese oficio?"
    elif not facts.get("work_area"):
        question = "¿En qué comuna puedes trabajar?"
    elif not facts.get("availability"):
        question = "¿Desde cuándo podrías comenzar?"
    elif ("display_name" in facts and facts.get("display_name") in {
        "", "Interesado de Facebook", "Contacto sin nombre", None
    } and not facts.get("name_opt_out")):
        question = "¿Cómo prefieres que te llamemos? Si prefieres no decirlo, escribe paso."
    else:
        return "Listo, registré tus datos para que el equipo pueda revisarlos."
    return (_friendly_ack(message, facts, question, prior_prompt) + " " + question).strip()[:540]


def needs_deeper_response(message: str) -> bool:
    """Prefer the configured AI for real questions; keep one-word replies local.

    Avoid wasting tokens or passing short yes/no or numbered choices to a model.
    This is about answer quality, never an artificial waiting timer.
    """
    if private_data(message):
        return False
    text = plain(message)
    if text in {"si", "no", "1", "2", "uno", "dos", "hola", "ola",
                "solito", "solo", "sola", "gracias"}:
        return False
    # A short, misspelled question still deserves an informed answer rather
    # than a form-like follow-up. This does not imply confirmed job openings.
    short_questions = (
        "hay pega", "tienen pega", "tienen trabajo", "tienen cupos",
        "buscan maestros", "necesitan maestros", "puedo postular",
        "como postulo", "cuanto pagan", "cuanto se paga", "hay obras",
        "que requisitos", "que papeles", "me sirve", "que hago ahora",
        "a que obra", "como funciona", "donde postulo",
    )
    if ("?" in message or "¿" in message) and any(
        phrase in text for phrase in short_questions
    ):
        return True
    if len(text.split()) >= 15 and ("?" in message or "¿" in message):
        return True
    questions = ("como puedo", "que necesito", "me explicas", "como funciona",
                 "tengo dudas", "que pasa si", "quiero saber", "me puedes contar",
                 "hay alguna obra", "que obras", "que papeles", "que documentos",
                 "puedo postular", "como postulo", "necesito orientacion")
    return any(q in text for q in questions) or (
        ("?" in message or "¿" in message) and len(text.split()) >= 6)


def small_talk_reply(message: str) -> str | None:
    """Respuestas locales inmediatas: no requieren modelo ni consentimiento de IA."""
    if answer := identity_reply(message):
        return answer
    norm = plain(message)
    if norm in {"hola", "ola", "buenas", "buen dia", "buenos dias", "buenas tardes", "hola galancito"}:
        return "¡Hola! Cuéntame, ¿en qué te puedo ayudar?"
    if norm in {"como estas", "hola como estas", "ola como estas", "como estai",
                "que tal", "hola que tal", "todo bien", "como va"}:
        return "¡Bien, gracias por preguntar! Cuéntame, ¿en qué te puedo ayudar?"
    if norm in {"gracias", "muchas gracias", "vale gracias", "te pasaste"}:
        return "¡De nada! Aquí estamos para ayudarte."
    return None


def natural_messenger_reply(text: str, prior_ai_replies: int = 0) -> str:
    """Evita la presentación robótica en cada mensaje, sin hacerse pasar por humano.

    El permiso explícito para usar IA se procesa de forma independiente.
    """
    clean = text.strip()
    if clean == identity_reply("eres IA"):
        return clean
    for beginning in (
        "Soy Galancito, asistente virtual de GALANT. ",
        "Soy Galancito, el asistente virtual de GALANT. ",
        "Soy Galancito. ",
    ):
        if clean.casefold().startswith(beginning.casefold()):
            clean = clean[len(beginning):].strip()
            break
    # Un proveedor podría ignorar la instrucción y presentarse como bot.
    clean = re.sub(r"^(?:¡?hola[,!.]?\s+)?soy\s+(?:Galancito(?:,\s*(?:el\s+)?asistente virtual(?: de (?:GALANT|Red de Obras))?)?|(?:el\s+|un\s+)?asistente virtual(?: de (?:GALANT|Red de Obras))?)[.!]?\s*", "", clean, flags=re.I)
    return clean[:550]
