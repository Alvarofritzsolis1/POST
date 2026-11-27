"""Local, progressive professional intake for small contractors and job-seekers.

Ask one short question at a time. Understand spelling mistakes, very short
answers, independent tradespeople and small crews without judging literacy.
Collect voluntary professional declarations only, never determine eligibility,
legal employment, suitability, or award work. No external model is required.
"""
import re
from datetime import date, timedelta
from .galancito_triage import (
    analyze, asks_about_application, declaration_text, is_pure_greeting, plain, private_data,
    worksite_details_question,
)
from .galancito_links import trade_declarations
from .galancito_phone import WHATSAPP_ACK
from .galancito_communes import find_communes
from .galancito_profile_review import declaration_for_review, JOB_ROLES

UNKNOWN_NAMES = {"", None, "Interesado de Facebook", "Contacto sin nombre"}
GALILEA_QUESTION = "¿Has trabajado antes en Galilea?"

_INTEREST_QUESTION = "ofreces trabajos por tu cuenta"
_TEAM_QUESTION = "trabajas solo"
_TRADE_QUESTION = "que trabajo realizas"
_EXPERIENCE_QUESTION = "cuanto tiempo llevas"
_COMMUNE_QUESTION = "en que comuna"
_AVAILABILITY_QUESTION = "desde cuando podrias"
# Occupational nouns describe people; equipment, materials and work quantities do not.
CREW_PERSON_UNIT = (r"personas?|maestros?|trabajadores?|ayudantes?|cabros?|compas?|integrantes?|"
                    r"pintor(?:es|as)?|pintora|yeser[oa]s?|carpinter[oa]s?|electricistas?|"
                    r"gasfiter(?:es|os)?|albanil(?:es)?|soldador(?:es|as)?|soldadora|"
                    r"ceramistas?|tabiquer[oa]s?|enfierrador(?:es|as)?|jardiner[oa]s?")

_PROMPTS = (
    _INTEREST_QUESTION, _TEAM_QUESTION, _TRADE_QUESTION,
    _EXPERIENCE_QUESTION, _COMMUNE_QUESTION, _AVAILABILITY_QUESTION,
    "que oficio", "que servicio", "a que oficio", "cuantas personas",
    "cuantos anos", "desde cuando puedes", "puedes venir con", "representas una empresa",
    "buscas empleo como trabajador", "como prefieres que te llamemos",
    "cual es tu nombre", "como te llamas", "dime tu nombre",
    "me dices tu nombre", "me puedes decir tu nombre", "tu nombre por favor",
    "anos o meses",
)


def is_intake_prompt(prompt: str) -> bool:
    normalized = plain(prompt)
    return bool(intake_question_fields(prompt)) or any(key in normalized for key in _PROMPTS)


def intake_question_fields(prompt: str) -> set[str]:
    """Identify the professional fields asked for in visible questions."""
    value = " ".join(plain(part.rsplit("¿", 1)[-1]) for part in prompt.split("?")[:-1])
    patterns = {
        "additional_services": ("que otros trabajos", "que otros servicios", "que otros oficios"),
        "display_name": _NAME_PROMPTS,
        "specialty": (*_TRADE_PROMPTS, "que trabajo hace", "que trabajo realiza", "que trabajos realiza", "que labores realizas", "que labores realiza", "que trabajo haces", "que trabajos haces", "a que te dedicas", "en que trabajas"),
        "interest_type": (_INTEREST_QUESTION, "buscas empleo o", "buscas empleo como trabajador", "buscas trabajo para ti", "buscas que te contraten", "ofreces tus servicios", "trabajo por tu cuenta o", "quieres trabajar por tu cuenta como contratista", "empleo con contrato o tomar trabajos", "como trabajador o", "como contratista", "tomas trabajos por tu cuenta", "tomar trabajos por tu cuenta", "ofreces servicios por tu cuenta", "buscas un empleo", "quieres un empleo"),
        "entity_type": ("representas una empresa", "con una empresa o a tu propio nombre"),
        "team_available": (_TEAM_QUESTION, "puedes venir con", "vas solo", "irias solo", "trabajas con alguien", "tienes cuadrilla", "puedes llevar gente", "puedes llevar otras personas", "puedes traer gente", "puedes trabajar con mas gente", "trabajas por tu cuenta solo", "trabajarias solo"),
        "workers": ("cuantas personas", "con cuantas", "cuantos puedes traer", "cuantos maestros", "cuantos son en total"),
        "has_employees": ("tienes trabajadores contratados", "tienes empleados"),
        "employee_count": ("cuantos trabajadores contratados", "cuantos empleados"),
        "experience": (_EXPERIENCE_QUESTION, "cuantos anos", "cuanta experiencia", "anos o meses"),
        "work_communes": (_COMMUNE_QUESTION, "en cuales comunas", "en que comunas", "donde puedes trabajar", "donde trabajas", "que comunas"),
        "availability": ("desde cuando", "cuando podrias comenzar", "cuando puedes empezar", "cuando puedes partir", "cuando podrias partir", "cuando podrias empezar", "cuando puedes comenzar", "cuando estas disponible"),
        "contact_phone": ("tu telefono", "tu celular", "numero de celular", "tu numero", "numero de telefono", "tu whatsapp"),
        "contact_email": ("tu correo", "tu email"),
    }
    fields = {field for field, phrases in patterns.items() if any(phrase in value for phrase in phrases)}
    if re.search(r"\b(?:hace cuanto|desde hace cuanto|cuanto tiempo) (?:que )?(?:trabajas?|trabajan|llevas?|llevan|ejerces?|ejercen|eres|son)\b", value):
        fields.add("experience")
        if not re.search(r"\b(?:buscas|ofreces|quieres|prefieres)\b", value):
            fields.discard("interest_type")
    if re.search(r"\b(?:(?:(?:has|ha|han|habias|habia) trabajado|trabajaste) (?:(?:antes|anteriormente|alguna vez) )?"
                 r"(?:en|para|con) (?:(?:una |alguna )?obras? de )?|tienes experiencia (?:previa )?en )galilea\b", value):
        fields.add("worked_at_galilea")
    return fields


def unresolved_declarations(message: str, prior: str) -> dict[str, str]:
    value = plain(declaration_text(message))
    fields = intake_question_fields(prior)
    if value in _REFUSAL:
        return dict.fromkeys(fields, "rechazado_por_usuario")
    if "experience" in fields and ambiguous_experience_number(value, prior):
        return {"experience": "ambiguo"}
    if re.search(r"\b(?:aun no se|no se todavia|no tengo claro|no estoy segur[ao])\b", value):
        return dict.fromkeys(fields, "ambiguo")
    if "specialty" in fields and re.search(r"\b(?:o|quizas|tal vez)\b", value):
        return {"specialty": "ambiguo"}
    if re.search(_COUNT + r" (?:o|a) " + _COUNT + r"\b", value) and (
        "workers" in fields or re.search(r"\b(?:somos|iremos|voy con|puedo ir con|puedo llevar)\b", value)
    ):
        return {"workers": "ambiguo"}
    if re.search(r"\b(?:quizas|tal vez|puede que|no se si)\b|\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo|hoy|manana) o (?:el )?\w+", value):
        if "availability" in fields or re.search(r"\b(?:puedo (?:empezar|partir|comenzar)|disponibilidad|disponible)\b", value):
            return {"availability": "ambiguo"}
    return {}


_ROLE_SERVICE = (
    "ofrezco servicios", "ofresco servicios", "mis servicios", "por mi cuenta", "por las mias", "por mi propia cuenta",
    "hago pitutos", "busco pitutos",
    "tengo un emprendimiento", "somos contratistas", "soy contratista",
    "somos una empresa", "tengo empresa", "tengo una empresa", "represento una empresa",

)
_ROLE_WORKER = (
    "busco pega", "busco empleo", "busco trabajo", "ando buscando pega",
    "ando en busca de pega", "quiero empleo", "quiero trabajar contratado",
    "nesesito pega", "necesito pega", "ando sin pega", "quiero pega",
    "postulo como trabajador", "postular a un empleo", "soy trabajador", "soy trabajadora",
    "trabajo apatronado", "quiero trabajar apatronado", "busco trabajo apatronado",
)

_ROLE_MENTION_PATTERNS = {
    "service_offer": re.compile(r"\b(?:" + "|".join(map(re.escape, _ROLE_SERVICE)) +
                                r"|contratistas?|ofrezco|ofresco|trabaj(?:o|amos|ar) a trato)\b"),
    "employment": re.compile(r"\b(?:" + "|".join(map(re.escape, _ROLE_WORKER)) +
                              r"|buscando (?:pega|(?:un )?contrato)|necesito empleo|"
                              r"quiero que me contraten|trabajar apatronad[oa])\b"),
}


def role_mentions(value: str):
    """Possible self-descriptions in normalized text, without inferring the actor."""
    for role, pattern in _ROLE_MENTION_PATTERNS.items():
        if match := pattern.search(value):
            yield match, role


_NAME_PROMPTS = (
    "como prefieres que te llamemos", "cual es tu nombre", "como te llamas",
    "dime tu nombre", "me dices tu nombre", "me puedes decir tu nombre", "tu nombre por favor",
)
_TRADE_PROMPTS = (_TRADE_QUESTION, "que oficio", "que servicio", "a que oficio")
_CORRECTION = re.compile(r"\b(?:corrijo|correccion|me equivoque|en realidad|quise decir|al final|ahora|ya no|cambio de fecha)\b")
_REFUSAL = {"paso", "prefiero no decir", "prefiero no indicar", "no quiero dar ese dato"}
_NUMBERS = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
            "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
_COUNT = r"([0-9]{1,4}|" + "|".join(_NUMBERS) + r")"
_OFFERS = re.compile(r"\b(?:pega|trabaj|servici|contrat|postul|dispon|equipo|cuadrill|"
                     r"ofici|ayudant|empresa|experienc|person|comuna|maestr|habl|gracia)\w*\b|"
                     r"\b(?:si|no|dale|bueno|obvio|ok|listo|bien|paso)\b")
_DATE = r"(?:\d{1,2}/\d{1,2}/20\d{2}|20\d{2}-\d{2}-\d{2})"
_DAY = (r"(?:hoy|manana|lunes|martes|miercoles|jueves|viernes|sabado|domingo|"
        r"(?:la )?proxima semana|en dos semanas|fin de mes|cuando me necesiten|inmediat[oa])")
WORK_AREA_CUE = re.compile(
    r"\b(?:(?:me muevo|nos movemos|me puedo mover|nos podemos mover|puedo ir|puedo trabajar|"
    r"trabajo|trabajamos|atiendo|atendemos|busco (?:pega|trabajo|empleo)) (?:solo )?(?:en|por|a)|"
    r"puedo hacer (?:la pega )?en|(?:las )?obras que tomo son en|"
    r"(?:hago|hacemos|instalo|reparo) (?:\w+ ){1,4}en|(?:tambien|solo) en|comunas? de trabajo)\b"
)


def unanswered_intake_question(lead, prompt: str) -> bool:
    """Keep a delivered question in context until its field has an answer."""
    value = plain(prompt)
    pending = (
        (_TRADE_PROMPTS, not lead.specialty),
        ((_INTEREST_QUESTION,), lead.interest_type == "unknown"),
        ((_TEAM_QUESTION, "puedes venir con"), lead.team_available is None),
        (("cuantas personas", "con cuantas"), lead.workers is None),
        ((_EXPERIENCE_QUESTION, "cuanta experiencia", "cuantos anos", "anos o meses"), not lead.experience),
        ((_COMMUNE_QUESTION,), not lead.work_area),
        ((_AVAILABILITY_QUESTION, "desde cuando puedes"), not lead.availability),
        (_NAME_PROMPTS, lead.display_name in UNKNOWN_NAMES and not lead.name_opt_out),
    )
    fields = intake_question_fields(prompt)
    facts = {field: getattr(lead, field, None) for field in (
        "display_name", "name_opt_out", "specialty", "interest_type", "entity_type",
        "team_available", "workers", "has_employees", "employee_count", "experience",
        "work_area", "work_communes", "availability")}
    known = conversation_fields(facts)
    professional = fields - {"contact_phone", "contact_email"}
    states = getattr(lead, "profile_sources", None) or {}
    return (any(not known.get(field) and states.get(field, {}).get("state") != "rechazado_por_usuario"
                for field in professional)
            or any(missing and any(match in value for match in phrases) for phrases, missing in pending))


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
    if "interest_type" in intake_question_fields(previous + "?") or _INTEREST_QUESTION in previous:
        service |= value in {"1", "uno", "servicios", "contratista", "independiente", "ofrezco trabajo", "por mi cuenta"}
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
    elif _affirmed(value, ("no tengo empresa", "soy independiente", "a mi nombre", "por mi cuenta")):
        lead.entity_type = "individual"


def _employment_update(lead, value: str) -> None:
    if not hasattr(lead, "has_employees"):
        return
    if re.search(r"\b(?:no tengo|no tenemos|no cuento con|sin|no hay) (?:trabajadores|personal|gente)(?: propios?)? (?:contratad[oa]s?|con contrato)\b", value):
        lead.has_employees = False
        lead.employee_count = 0
    elif match := re.search(r"\b(?:tengo|tenemos|cuento con) (?:" + _COUNT + r" )?"
                            r"(?:trabajador(?:es)?|personal|gente|personas?) (?:contratad[oa]s?|con contrato)\b", value):
        count = (int(match[1]) if match[1].isdecimal() else _NUMBERS[match[1]]) if match[1] else None
        lead.has_employees = count != 0
        if count is not None and count <= 5000:
            lead.employee_count = count
        elif getattr(lead, "employee_count", None) == 0:
            lead.employee_count = None


def _name_update(lead, message: str, previous: str) -> None:
    if not hasattr(lead, "display_name"):
        return
    asked = any(question in previous for question in _NAME_PROMPTS)
    value = plain(message)
    if (asked and value in {"paso", "no", "prefiero no decir", "prefiero no", "no quiero"}
            or re.search(r"\b(?:prefiero no dar mi nombre|no quiero dar mi nombre)\b", value)):
        lead.name_opt_out = True
        return
    explicit = re.search(r"\b(?:me llamo|mi nombre es)\s+([^,;.!?¿¡\n]+)", message, re.I)
    if getattr(lead, "name_opt_out", False) and not explicit:
        return
    introduction = declaration_for_review(message)
    informal = re.fullmatch(r"[Ss]oy\s+([A-ZÁÉÍÓÚÜÑ][^,;.!?¿¡\n]+)[.!]?", introduction.strip())
    candidate = (explicit[1] if explicit else informal[1] if informal else message if asked else "").strip()
    candidate = re.split(r"\s+(?:y )?(?:trabajo|hago|busco|soy|tengo|vivo|puedo|ofrezco)\b",
                         candidate, maxsplit=1, flags=re.I)[0].strip(" .")
    norm = plain(candidate)
    if (not re.fullmatch(r"[^\W\d_]+(?:[ .’'-]+[^\W\d_]+){0,4}", candidate)
            or len(candidate) > 70 or "?" in candidate
            or norm.startswith(("de ", "en ", "tu ", "un ", "una ", "el ", "la ", "hola ", "me "))
            or norm in {"no se", "no entiendo", "no cacho", "como", "que", "no entendi", "no comprendo", "no cache", "no tengo idea", "no se que decir"}
            or not norm or norm.split()[0] in JOB_ROLES or _OFFERS.search(norm) or analyze(candidate).specialty):
        return
    known = lead.display_name not in UNKNOWN_NAMES
    if not known or (explicit and _CORRECTION.search(value)):
        lead.display_name = candidate
        lead.name_opt_out = False


def _commune_update(lead, message: str, previous: str) -> None:
    value = plain(message)
    asked = "work_communes" in intake_question_fields(previous + "?") or _COMMUNE_QUESTION in previous
    found = []
    continues_area = False
    for fragment in re.split(r"[,;.!\n]+|\bpero\b", message, flags=re.I):
        clause = plain(fragment)
        cue = WORK_AREA_CUE.search(clause)
        if re.search(r"\b(?:vivo en|resido en|donde vivo es|soy de|somos de|no trabajo en|no voy a|"
                     r"no puedo ir a|no puedo trabajar en)\b", clause):
            continues_area = False
            continue
        if not cue and not asked and not continues_area and not clause.startswith(("tambien en ", "y en ", "en ")):
            continue
        communes = find_communes(clause[cue.end():] if cue else clause)
        found.extend(communes)
        continues_area = bool(communes)
    if not found:
        return
    current = list(getattr(lead, "work_communes", None) or [])
    if not current and lead.work_area:
        current = find_communes(lead.work_area)
    replace = bool(_CORRECTION.search(value) and not re.search(r"\b(?:tambien|ademas)\b", value)) or "solo en " in value
    communes = list(dict.fromkeys([*([] if replace else current), *found]))
    lead.work_communes = communes
    lead.work_area = ", ".join(communes)[:120]


def _team_update(lead, value: str, previous: str) -> None:
    capacity = _affirmed(value, ("cuento con equipo", "cuento con un equipo", "cuento con equipo de trabajo",
                                 "contamos con equipo", "tenemos equipo de trabajo", "tenemos un equipo",
                                 "puedo traer gente", "puedo llevar gente", "tengo cuadrilla",
                                 "tengo una cuadrilla", "somos un equipo",
                                 "tengo ayudantes", "trabajamos varios", "puedo ir con gente"))
    # In “trabajo solo en Ñuñoa”, solo limits the work area.
    team_statement = re.sub(r"\b(trabajo|trabajamos) solo en\b", r"\1 en", value)
    solo = _affirmed(team_statement, ("trabajo solo", "trabajo sola", "voy solo", "voy sola",
                             "voy a ir solo", "voy a ir sola", "yo solo", "yo sola", "sin equipo"))
    if value in {"no puedo llevar gente", "no tengo gente", "no tengo cuadrilla"}:
        solo = True
    if "team_available" in intake_question_fields(previous + "?") or _TEAM_QUESTION in previous or "puedes venir con" in previous:
        solo |= value in {"1", "uno", "solito", "solo", "sola", "sin gente", "sin equipo"}
        capacity |= value in {"2", "dos", "con gente", "con equipo", "con personas"}
    if any(p in previous for p in ("vas solo", "irias solo", "trabajas solo")) and value in {"si", "si po", "sipo", "si claro"}:
        solo = True
    if solo and not capacity:
        lead.team_available, lead.workers = False, 1
    elif capacity:
        if lead.team_available is False:
            lead.workers = None
        lead.team_available = True

    count = _COUNT
    total = re.search(r"\b(?:somos|(?:cuadrilla|equipo) (?:es )?de|iremos) " + count +
                      r"(?= (?:" + CREW_PERSON_UNIT + r"|en total|"
                      r"que (?:necesitan?|hay que) hacer|y (?:podemos|pueden|puedo|el resto))\b|\s*(?:\||$))", value)
    if not total:
        total = re.search(r"\btengo " + count + r" (?:ayudantes?|personas?|maestros?|trabajadores?) disponibles\b", value)
    helpers = re.search(
        r"\b(?:puedo ir con|voy con|llevo|puedo llevar) " + count
        + r" (?:ayudantes?|personas?|maestros?|trabajadores?|cabros?|compas?|companeros?)\b", value)
    if not helpers:
        helpers = re.fullmatch(r"yo y " + count + r" mas", value)
    if not total and not helpers and ("workers" in intake_question_fields(previous + "?") or "cuantas personas" in previous or "con cuantas" in previous):
        total = re.fullmatch(r"(?:con |en total )?" + count + r"(?: personas| maestros| trabajadores| gente)?", value)
    if not total and not helpers:
        return
    matched = total or helpers
    if not _affirmed(value, (matched[0],)):
        return
    token = matched[1]
    number = (int(token) if token.isdecimal() else _NUMBERS[token]) + bool(helpers and not total)
    if 1 <= number <= 5000:
        lead.workers, lead.team_available = number, number > 1


_SPAN = re.compile(r"\b(?:en|desde|para|dentro de|de aqui a) "
                   r"(\d{1,3}|un|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez) "
                   r"(dias?|semanas?)(?: mas)?\b")
_AVAILABILITY_STATEMENT = re.compile(
    r"\b(?:puedo(?: empezar| comenzar| partir| ir| trabajar)?|"
    r"(?:estoy|quedo) disponible|tengo disponibilidad) "
    r"(?=(?:en|desde|dentro de|de aqui a) )"
)


def relative_start_days(message: str) -> int | None:
    """Parse a start offset, excluding duration phrases such as 'por dos semanas'."""
    match = _SPAN.search(plain(message))
    if not match:
        return None
    number, unit = match.groups()
    words = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
             "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
    count = int(number) if number.isdigit() else words[number]
    days = count * (7 if unit.startswith("semana") else 1)
    return days if days <= 365 else None


def requested_relative_start(message: str) -> int | None:
    if re.search(r"\b(?:necesito|necesitamos|busco|buscamos)\b", plain(message)):
        return relative_start_days(message)
    return None


def declared_relative_start(message: str) -> int | None:
    value = plain(declaration_text(message))
    cue = _AVAILABILITY_STATEMENT.search(value)
    if not cue or re.search(r"\b(?:no|nunca|quizas|tal vez|no se si) (?:yo )?$", value[:cue.start()]):
        return None
    offset = value[cue.end():]
    if _SPAN.match(offset) and not re.search(r"\b(?:o|quizas|tal vez|depende)\b", offset):
        return relative_start_days(offset)
    return None


def work_date_answer(message: str, previous: str) -> tuple[bool, date] | None:
    reply = plain(message)
    if reply not in {"si", "si puedo", "ese dia si", "no", "no puedo", "ese dia no"}:
        return None
    match = re.search(r"\bseria el (\d{2}) (\d{2}) (20\d{2}) tambien puedes ese dia$", plain(previous))
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return "no" not in reply.split(), date(year, month, day)
    except ValueError:
        return None


def _availability_update(lead, message: str, previous: str, *, on_date=None) -> None:
    clean = message.strip()
    value = plain(clean)
    asked = "availability" in intake_question_fields(previous + "?") or _AVAILABILITY_QUESTION in previous or "desde cuando puedes" in previous
    if (asked or "disponib" in value or "puedo" in value) and re.search(
        r"\b(?:quizas|tal vez|puede que|no se si|depende)\b|\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo|hoy|manana) o\b", value
    ):
        return
    if confirmation := work_date_answer(message, previous):
        if confirmation[0]:
            lead.availability = confirmation[1].isoformat()
        return
    if any(phrase in value for phrase in ("sin disponibilidad", "no puedo empezar aun")):
        lead.availability = "Sin disponibilidad"
        return
    cue = re.search(r"\b(?:disponibl[ea]s?|puedo (?:empezar|comenzar|partir|desde)|arranco|parto|"
                    r"comienzo|empiezo|puedo ir)\b|\bdesde (?:el )?(?=" + _DAY + r"\b)", value)
    offset = declared_relative_start(message)
    if offset is not None and on_date:
        lead.availability = (on_date + timedelta(days=offset)).isoformat()
        return
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
    statement = declaration_text(message)
    if clarification_reply(message, prior_prompt) is not None and (not statement or "?" not in message):
        return  # A question, objection or bare ambiguous number is not a new fact.
    prev = plain(prior_prompt)
    value = " | ".join(plain(part) for part in re.split(r"[,;.!\n]+|\bpero\b", statement, flags=re.I)
                       if plain(part))
    if declarations is None:
        declarations = trade_declarations(message, prior_prompt, allow_bare=True)
    positives = [trade for trade, present in declarations.items() if present]
    explicit_main = re.search(r"\b(?:mi oficio (?:principal )?es|mi especialidad (?:principal )?es)\b", value)
    if positives and (not lead.specialty or (lead.specialty_source == "message" and
                      (explicit_main or declarations.get(lead.specialty) is False))):
        lead.specialty, lead.specialty_source = positives[0][:100], "message"
    if not value:
        return
    _role_update(lead, value, prev)
    _employment_update(lead, value)
    _name_update(lead, statement, prev)
    _team_update(lead, value, prev)
    _commune_update(lead, statement, prev)
    _availability_update(lead, statement, prev, on_date=on_date)
    if not lead.experience or lead.experience == "No informado por el interesado" or _CORRECTION.search(value):
        experience = re.search(r"\b(?:(mas de|casi|cerca de|alrededor de|aproximadamente|unos|unas) )?"
                               + _COUNT + r"\s*(anos?|mes(?:es)?)\b", value)
        asked = "experience" in intake_question_fields(prior_prompt) or any(s in prev for s in (_EXPERIENCE_QUESTION, "cuanta experiencia", "cuantos anos", "anos o meses"))
        volunteered = (bool(re.search(r"\b(?:experiencia|llevo|llevamos)\b", value)
                            or re.search(r"\b(?:soy|voy|trabajo|trabajamos) (?:\w+ ){0,3}(?:maestr[oa]|contratista|independiente)\b", value))
                       and not re.search(r"\b(?:edad|de vida|viviendo|residiendo)\b", value)
                       and not re.search(r"\b(?:no soy|no tengo|no llevo|no trabajo|no se si|quizas)\b", value))
        if value in {"sin experiencia", "no tengo experiencia", "recien comienzo"} or (
                asked and value in {"ninguna", "no tengo", "nuevo", "nuevo en esto"}):
            lead.experience = "Sin experiencia declarada"
        elif asked and value in _REFUSAL:
            lead.experience = "No informado por el interesado"
        elif asked and ambiguous_experience_number(value, prior_prompt):
            pass  # A bare number cannot distinguish months from years.
        elif asked and re.fullmatch(r"\d{1,2}", value) and "cuantos anos" in prev:
            lead.experience = value + " años declarados"
        elif experience and (asked or volunteered):
            # Preserve distinct kinds of declared experience without reducing them to the first number.
            if (re.search(r"\b(?:independiente|contratista|por mi cuenta)\b", value) and
                    re.search(r"\b(?:apatronado|contratado|con contrato|dependiente|maestr[oa])\b", value) and
                    len(re.findall(_COUNT + r"\s*(?:anos?|mes(?:es)?)\b", value)) >= 2):
                lead.experience = statement.strip()[:250]
                return
            qualifier, amount, unit = experience.groups()
            number = int(amount) if amount.isdecimal() else _NUMBERS[amount]
            if 0 <= number <= 99:
                prefix = (qualifier.replace("mas de", "más de") + " ") if qualifier else ""
                lead.experience = (prefix + f"{number} {unit}").replace("ano", "año")


def identity_reply(message: str) -> str | None:
    value = plain(message)
    if re.search(r"\b(?:eres|soi|er[ií]s|hablo con|me (?:responde|atiende)|estoy hablando con) "
                 r"(?:una? |el )?(?:bot|robot|ia|inteligencia artificial|persona|humano)\b", value):
        return "Este chat lo atiende un asistente de IA de GALANT. Si prefieres, te puede atender alguien del equipo."
    return None


def _friendly_ack(message: str, facts: dict, question: str, prior: str = "") -> str:
    """Brief, grounded acknowledgement, not a repetitive scripted self-introduction."""
    norm = plain(message)
    if is_pure_greeting(message):
        return "¡Hola, qué tal!"
    if not _CORRECTION.search(norm) and any(q in plain(prior) for q in ("cual es tu nombre", "como te llamas", "como prefieres que te llamemos")):
        if facts.get("display_name") not in (None, "", "Interesado de Facebook", "Contacto sin nombre"):
            return "Un gusto, " + facts["display_name"].split()[0].title() + "."
    # No narration of the extraction process. A direct question is often enough.
    if facts.get("turn_changed") and _CORRECTION.search(norm):
        return "Listo, actualicé ese dato."
    return ""


def ambiguous_experience_number(value: str, prior: str) -> bool:
    """Do not turn a bare number into years when the question never specified units."""
    prev = plain(prior)
    return bool(("experience" in intake_question_fields(prior) or _EXPERIENCE_QUESTION in prev)
                and "cuantos anos" not in prev
                and re.fullmatch(r"(?:\d{1,2}|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)", plain(value)))


def clarification_reply(message: str, prior: str = "") -> str | None:
    """Small, context-bound explanations before any new intake question.

    Never interpret confusion as a professional declaration, or impersonate a
    person. Questions needing actual project records remain on the normal path.
    """
    if private_data(message) or analyze(message).intent in {"human", "restricted"}:
        return None
    value = plain(message)
    if ambiguous_experience_number(value, prior):
        return "¿Te refieres a años o meses?"
    definitions = (
        (r"(?:que|ke|q) (?:es|significa|quiere decir) (?:una? )?postular(?:se)?", 
         "Postular es decir que te interesa un trabajo para que el equipo pueda considerarte. No significa que ya tengas el puesto."),
        (r"(?:que|ke|q) (?:es|significa|quiere decir) (?:ser )?(?:una? )?contratista(?: independiente)?",
         "Un contratista ofrece hacer un trabajo por su cuenta o mediante una empresa. Es distinto de buscar un empleo."),
        (r"(?:que|ke|q) (?:es|significa|quiere decir) (?:trabajar )?a trato",
         "Trabajar a trato significa acordar cuánto se paga por una tarea o resultado. Conviene dejar claro el monto y qué trabajo incluye."),
        (r"puedo ofrecer (?:mis )?servicios (?:aunque no tenga|sin) (?:una )?(?:cuadrilla|equipo)",
         "Puedes ofrecer los servicios que haces por tu cuenta. Si te interesa un aviso, revisa con quien contrata si ese trabajo requiere cuadrilla."),
        (r"(?:que|ke|q) (?:es|significa|quiere decir) (?:una? )?cuadrilla",
         "Una cuadrilla es un grupo de personas que trabaja junto. Eso no significa que sean trabajadores contratados por ti."),
        (r"(?:que|ke|q) (?:es|significa|quiere decir) (?:una? )?comuna",
         "La comuna es el lugar, por ejemplo Coronel o Concepción. Nos interesa dónde puedes trabajar, no tu dirección."),
        (r"no (?:tengo|uso|se usar) (?:el )?correo(?: electronico)?",
         "No necesitas correo para comenzar. Podemos conversar por este chat."),
        (r"no (?:se|puedo) (?:mandar|enviar|subir) (?:una )?(?:foto|fotos|audio|audios)",
         "No necesitas enviar fotos ni audios para una consulta inicial. Puedes contarnos por escrito lo que haces."),
        (r"no (?:cacho|entiendo|se usar) (?:la pagina|el celular|esta pagina|esto del celular|el formulario)",
         "Podemos avanzar por este chat, sin llenar todo de una vez. Cuéntame con tus palabras qué necesitas."),
        (r"(?:ya te dije|me preguntai lo mismo|me preguntas lo mismo|ya respondi)",
         "Disculpa la repetición. No hace falta que vuelvas a dar el dato. Podemos seguir con tu duda."),
        (r"(?:ya filo|me aburri|no quiero seguir|me canse de responder)",
         "Está bien, no hace falta responder más ahora. Si después quieres continuar, puedes escribir por aquí."),
    )
    question = plain(message.rsplit("¿", 1)[-1]) if message.count("?") == 1 and "¿" in message else value
    for pattern, answer in definitions:
        if re.fullmatch(pattern, question):
            return answer
    if value not in {"no entiendo", "no entendi", "no cacho", "no cache", "no comprendo",
                     "no entiendo la pregunta", "como asi", "que significa", "a que te refieres"}:
        return None
    fields = intake_question_fields(prior)
    if len(fields) == 1:
        field = next(iter(fields))
        explanations = {
            "interest_type": "Te pregunto si buscas un empleo donde te contraten o si quieres ofrecer trabajos por tu cuenta. También pueden ser las dos cosas.",
            "specialty": "Quiero saber qué sabes hacer. Por ejemplo, pintar, instalar cerámica o reparar techos. ¿Qué trabajo haces?",
            "team_available": "Quiero saber si irías tú solo o si podrías llevar a otras personas para trabajar.",
            "workers": "Cuenta a todas las personas que podrían trabajar, incluyéndote. ¿Cuántos serían?",
            "experience": "Quiero saber desde hace cuánto haces ese trabajo. Puede ser en meses o años; si no sabes, no pasa nada.",
            "worked_at_galilea": "¿Has trabajado alguna vez en una obra de Galilea? Si prefieres, podemos dejarlo pendiente.",
            "work_communes": "Quiero saber en qué lugar puedes trabajar, por ejemplo Coronel o Concepción. No necesito tu dirección.",
            "availability": "Quiero saber desde qué día podrías comenzar a trabajar. Si todavía no sabes, está bien.",
            "display_name": "Solo quiero saber cómo prefieres que te llamemos. No tienes que dar tu nombre si no quieres.",
            "contact_phone": "Es opcional dejar un teléfono para coordinar. Podemos seguir por este chat.",
            "contact_email": "Es opcional dejar un correo para coordinar. Podemos seguir por este chat.",
        }
        if field in explanations:
            return explanations[field]
    return "Te lo explico con otras palabras. ¿Qué parte te cuesta entender?"


def pending_professional_questions(facts: dict) -> dict[str, str]:
    """Applicable missing fields; their order is only the outage fallback."""
    known = conversation_fields(facts)
    states = facts.get("field_states") or {}
    intent = facts.get("interest_type", "unknown")
    candidates = {"specialty": "¿Qué trabajo realizas?"}
    if (facts.get("declared_context") or {}).get("additional_services_pending"):
        candidates["additional_services"] = "¿Qué otros trabajos realizas habitualmente?"
    candidates["interest_type"] = "¿Ofreces trabajos por tu cuenta, buscas empleo o haces las dos cosas?"
    if intent in {"service_offer", "both"}:
        if facts.get("team_available") is None:
            candidates["team_available"] = "¿Trabajas solo o puedes venir con otras personas?"
        elif facts.get("team_available") is True:
            candidates["workers"] = "¿Cuántas personas pueden trabajar contigo en total?"
    candidates.update({
        "experience": "¿Cuánto tiempo llevas en ese oficio?",
        "work_communes": "¿En qué comuna puedes trabajar?",
        "availability": "¿Desde cuándo podrías comenzar?",
    })
    if known["interest_type"] and known["specialty"]:
        candidates["worked_at_galilea"] = GALILEA_QUESTION
    if "display_name" in facts:
        candidates["display_name"] = "¿Cómo te llamas?"
    return {field: question for field, question in candidates.items()
            if not known.get(field) and states.get(field) not in {"rechazado_por_usuario", "ambiguo"}}


CONTACT_RECEIVED_CONTEXT = ("La persona acaba de entregar voluntariamente su teléfono y el sistema lo guardó. "
    "No se necesita otro contacto. Continúa según la conversación y los campos profesionales aplicables pendientes. "
    "Devuelve una sola pregunta natural sobre un dato pendiente; no cierres la conversación.")


def contact_pending_questions(facts: dict, prior: str = "") -> dict[str, str]:
    known = conversation_fields(facts)
    active = (any(known[field] for field in ("specialty", "interest_type", "experience",
                                            "work_communes", "availability", "team_available"))
              or bool(intake_question_fields(prior) & {"contact_phone", "contact_email"}))
    return pending_professional_questions(facts) if active else {}


def contact_followup_reply(ack: str, facts: dict, prior: str = "") -> str:
    pending = contact_pending_questions(facts, prior)
    question = next(iter(pending.values()), None)
    if ack == WHATSAPP_ACK and not facts.get("specialty"):
        return ack + " ¿De qué aviso o trabajo necesitas más información?"
    return compose_contact_followup(question) if question else ack


def compose_contact_followup(question: str) -> str:
    return ("Gracias, ya tengo tu número de contacto. " + question)[:550]


def model_contact_question(draft: str, facts: dict, prior: str = "") -> str | None:
    """Keep only a useful model-generated question; never let inference suppress receipt."""
    pending = contact_pending_questions(facts, prior)
    if not draft or draft.count("?") != 1 or private_data(draft):
        return None
    question = draft[draft.rfind("¿"):].strip() if "¿" in draft else draft.strip()
    if not question.endswith("?") or len(question) > 220:
        return None
    fields = intake_question_fields(question)
    if len(fields) != 1 or not fields.issubset(pending):
        return None
    if not acceptable_intake_draft(question, facts):
        return None
    return question


def next_intake_reply(message: str, facts: dict, prior_prompt: str = "") -> str | None:
    """Respond conversationally, then ask one relevant missing question.

    No fake thinking delay, and no guessed work, hiring, wages or promises.
    """
    identity = identity_reply(message)
    if identity:
        return identity
    if explanation := clarification_reply(message, prior_prompt):
        return explanation
    if plain(message) in {"hola vi un trabajo", "ola vi un trabajo", "vi un trabajo", "hola vi un aviso", "vi un aviso"}:
        return "¡Hola! ¿Qué trabajo viste?"
    # A reply about where someone is from is not a declaration of work coverage.
    # Preserve the distinction even when a greeting precedes the place.
    origin_question = re.search(r"\bde donde (?:es(?: usted)?|eres|son|viene[n]?)\b", plain(prior_prompt))
    origin_reply = re.fullmatch(r"(?:(?:hola|ola|buenas) )?(?:soy |somos )?de (.+)", plain(message))
    if origin_question and origin_reply and find_communes(origin_reply[1]):
        if not facts.get("specialty") and not facts.get("trades"):
            return "Perfecto, gracias. ¿Qué tipo de trabajos realizan?" if (facts.get("workers") or 0) > 1 else "Perfecto, gracias. ¿Qué tipo de trabajo realizas?"
        pending = pending_professional_questions(facts)
        question = next(iter(pending.values()), None)
        return "Perfecto, gracias. " + (question or "Podemos seguir coordinando por aquí.")
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
    question = next(iter(pending_professional_questions(facts).values()), None)
    intent = facts.get("interest_type", "unknown")
    if not question and (intent in {"service_offer", "employment", "both"}
          and (facts.get("specialty") or facts.get("trades"))
          and facts.get("work_area") and facts.get("availability") not in {None, "", "Sin disponibilidad"}
          and not any(facts.get(k) for k in ("contact_available", "contact_declined", "contact_offered"))
          and "contact_phone" not in intake_question_fields(prior_prompt)
          and "contact_email" not in intake_question_fields(prior_prompt)):
        return "Para coordinar, ¿me dejas tu celular? Si prefieres, seguimos por aquí."
    if not question:
        return "Podemos seguir por aquí si tienes dudas sobre el trabajo."
    if plain(question) in plain(prior_prompt):
        if facts.get("turn_changed"):
            return "Podemos seguir por aquí si quieres agregar algo."
        return "Está bien. Podemos seguir con esto cuando tengas el dato o conversar sobre otra duda."
    if question == GALILEA_QUESTION:
        return question
    return (_friendly_ack(message, facts, question, prior_prompt) + " " + question).strip()[:540]


def model_intake_candidate(message: str, facts: dict, prior: str, fallback: str | None) -> bool:
    """Ordinary conversation can be decided by the model, not a fixed interview."""
    if (fallback == GALILEA_QUESTION or not message or private_data(message) or identity_reply(message)
            or is_pure_greeting(message)
            or plain(message) in {"gracias", "muchas gracias", "vale gracias"}):
        return False
    return analyze(message).intent not in {"human", "restricted", "publish"}


def semantic_reasoning_needed(message: str, prior: str, facts: dict) -> bool:
    """Reason more deeply only for ambiguous professional decisions or complex turns."""
    value = plain(message)
    if not value:
        return False
    if re.search(r"\b(?:pero|aunque|depende|en realidad|me equivoque|quise decir|a veces|no siempre)\b", value):
        return True
    if is_intake_prompt(prior) and ((not facts.get("turn_changed") and analyze(message).intent == "unknown") or
            any(status == "ambiguo" for status in (facts.get("field_states") or {}).values())):
        return True
    if needs_deeper_response(message) and len(value.split()) >= 10:
        return True
    return bool(prior and not facts.get("turn_changed") and re.search(r"\b(?:no cacho|no entiendo|ya te dije|no era eso|como te dije)\b", value))


def conversation_fields(facts: dict) -> dict:
    """Independent availability of each professional field, without a preferred order."""
    return {
        "display_name": facts.get("display_name") not in UNKNOWN_NAMES or facts.get("name_opt_out"),
        "specialty": bool(facts.get("specialty") or facts.get("trades")),
        "interest_type": facts.get("interest_type") in {"employment", "service_offer", "both"},
        "entity_type": facts.get("entity_type") not in {None, "", "unknown"},
        "team_available": facts.get("team_available") is not None,
        "workers": (facts.get("workers") is not None
                    or bool((facts.get("declared_context") or {}).get("crew_size"))),
        "has_employees": facts.get("has_employees") is not None,
        "employee_count": facts.get("employee_count") is not None,
        "experience": bool(facts.get("experience")),
        "worked_at_galilea": "worked_at_galilea" in facts.get("declared_context", {}),
        "work_communes": bool(facts.get("work_area") or facts.get("work_communes")),
        "availability": bool(facts.get("availability")),
        "contact_phone": any(facts.get(k) for k in ("contact_available", "contact_declined", "contact_offered")),
        "contact_email": any(facts.get(k) for k in ("contact_available", "contact_declined", "contact_offered")),
    }


def contact_ready(facts: dict) -> bool:
    known = conversation_fields(facts)
    return bool(known["specialty"] and known["interest_type"] and known["work_communes"]
                and known["availability"] and facts.get("availability") != "Sin disponibilidad"
                and not known["contact_phone"])


def conversation_context(facts: dict) -> str:
    labels = {"worked_at_galilea": "worked_at_galilea (si trabajó antes en Galilea)",
              "additional_services": "additional_services (otros trabajos que ofrece)"}
    pending = [labels.get(key, key) for key in pending_professional_questions(facts)]
    if contact_ready(facts):
        pending.append("contact_phone o contact_email (opcional, solo uno)")
    return ("Datos profesionales pendientes aplicables (sin orden obligatorio, pregunta solo lo útil): "
            + (", ".join(pending) or "ninguno")
            + ". Distingue lo desconocido de lo rechazado y no confundas equipo con empleados."
            + " Responde primero la consulta actual; elige el siguiente paso según el objetivo y el historial."
            + " Si la ficha sigue incompleta, retoma un dato útil cuando corresponda.")


def acceptable_intake_draft(draft: str, facts: dict, expected_question: str = "",
                            *, message: str = "") -> bool:
    """Validate independent constraints, not agreement with a scripted next question."""
    value = plain(draft)
    if not draft or private_data(draft) or any(p in value for p in (
        "me queda clara la cantidad", "tengo anotada tu experiencia", "ya se en que comuna",
        "escribe paso", "quedo anotado", "puedes escribir con confianza"
    )):
        return False
    known = conversation_fields(facts)
    asked = intake_question_fields(draft)
    if any(known.get(field) or facts.get("field_states", {}).get(field) == "rechazado_por_usuario"
           for field in asked):
        return False
    scoped_questions = asked & {"worked_at_galilea", "additional_services"}
    if scoped_questions and not scoped_questions.issubset(pending_professional_questions(facts)):
        return False
    contact_fields = asked & {"contact_phone", "contact_email"}
    if contact_fields:
        if not contact_ready(facts) or len(contact_fields) != 1 or not any(
            phrase in value for phrase in ("si prefieres", "si quieres", "si te acomoda", "opcional", "si te parece")
        ):
            return False
    # A short clarification plus a useful follow-up is fine, but do not interrogate.
    if draft.count("?") > 2 or (draft.count("?") > 1 and len(asked) > 1):
        return False
    # A question about a publication or a genuine clarification is allowed.
    # Do not force a professional field when the person has another concern.
    if "?" in draft:
        # Only explicit field questions or useful clarification, not a generic loop.
        return bool(asked or not any(p in value for p in ("me cuentas mas", "cuentame mas", "que mas")))
    # Do not accept a bare acknowledgement or premature closure of an active intake.
    if value in {"ok", "bien", "perfecto", "gracias", "entendido", "listo", "de acuerdo"}:
        return False
    if expected_question and intake_question_fields(expected_question) and not needs_deeper_response(message) and "?" not in message:
        return False
    return True


def needs_deeper_response(message: str) -> bool:
    """Prefer the configured AI for real questions; keep one-word replies local.

    Avoid wasting tokens or passing short yes/no or numbered choices to a model.
    This is about answer quality, never an artificial waiting timer.
    """
    if private_data(message):
        return False
    if asks_about_application(message) or worksite_details_question(message):
        return True
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
    if any(phrase in text for phrase in short_questions):
        return True
    if len(text.split()) >= 15 and ("?" in message or "¿" in message):
        return True
    questions = ("como puedo", "que necesito", "me explicas", "como funciona",
                 "tengo dudas", "que pasa si", "quiero saber", "me puedes contar",
                 "hay alguna obra", "que obras", "que papeles", "que documentos",
                 "puedo postular", "como postulo", "necesito orientacion")
    return any(q in text for q in questions) or (
        ("?" in message or "¿" in message) and bool(text))


def small_talk_reply(message: str, prior_prompt: str = "") -> str | None:
    """Respuestas locales inmediatas: no requieren modelo ni consentimiento de IA."""
    if answer := identity_reply(message):
        return answer
    norm = plain(message)
    if norm in {"como estas", "hola como estas", "ola como estas", "como estai",
                "que tal", "hola que tal", "todo bien", "como va"}:
        return "¡Bien, gracias por preguntar! Cuéntame, ¿en qué te puedo ayudar?"
    if norm in {"gracias", "muchas gracias", "vale gracias", "te pasaste"}:
        return "¡De nada! Aquí estamos para ayudarte."
    if is_pure_greeting(message):
        if plain(prior_prompt).startswith(("hola", "buenas", "buenos dias", "que tal")):
            return "Te leo. ¿En qué te puedo ayudar?"
        return "¡Hola! Cuéntame, ¿en qué te puedo ayudar?"
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
        "Soy Galancito, el asistente de IA de GALANT. ",
        "Hola, te habla Galancito de GALANT. ",
        "Hola, soy Galancito de GALANT. ",
        "Soy Galancito. ",
    ):
        if clean.casefold().startswith(beginning.casefold()):
            clean = clean[len(beginning):].strip()
            break
    # Un proveedor podría ignorar la instrucción y presentarse como bot.
    clean = re.sub(r"^(?:¡?hola[,!.]?\s+)?(?:soy|te habla|te saluda)\s+"
                   r"(?:Galancito(?:,?\s*(?:(?:el|un)\s+)?(?:asistente virtual|asistente de IA|de GALANT|de Red de Obras)"
                   r"(?:\s+de\s+(?:GALANT|Red de Obras))?)?|(?:el\s+|un\s+)?asistente virtual)"
                   r"(?: de (?:GALANT|Red de Obras))?[.!]?\s*", "", clean, flags=re.I)
    return clean[:550]
