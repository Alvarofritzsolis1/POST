"""Small deterministic Spanish intake. Never interprets text as permission/action.

Only explicit facts are extracted; unknown individuals are not made companies.
Curated spelling aliases apply to trades, never to consent or authorization.
"""
from dataclasses import dataclass
import re
import unicodedata

from .galancito_flow import wants_human


def plain(text: str) -> str:
    value = "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                    if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


TRADES = {
    "Gasfitería": ("gasfite", "gasfiter", "gasfiteria", "gasfitero", "maestro sanitario"),
    "Carpintería": ("carpintero", "carpinteros", "carpinteria", "carpinter", "mueblista"),
    "Pintura": ("pintor", "pintores", "pintura", "pinturas"),
    "Albañilería": ("albanil", "albaniles", "albanileria"),
    "Electricidad": ("electrico", "electricista", "electricidad"),
    "Aseo": ("aseo", "limpieza"),
    "Soldadura": ("soldador", "soldadura"),
    "Cerámica": ("ceramista", "ceramica", "ceramico"),
}


def contains(text: str, phrase: str) -> bool:
    return f" {plain(phrase)} " in f" {text} "


def private_data(text: str) -> bool:
    return bool(re.search(
        r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[0-9kK]\b|"
        r"(?i:clave\s*[úu]nica|contrase[ñn]a|password|token|api[_ ]?key)\s*[:=]|"
        r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", text))


@dataclass(frozen=True)
class Intake:
    intent: str = "unknown"
    specialty: str = ""
    entity_type: str = "unknown"
    workers: int | None = None
    availability: str = ""


def analyze(message: str, trades: dict | None = None) -> Intake:
    text = plain(message)
    intent = "unknown"
    specialty = next((name for name, aliases in {**TRADES, **(trades or {})}.items()
                      if any(contains(text, a) and not contains(text, "no soy " + a)
                             for a in aliases)), "")
    workers_match = re.search(r"\b(?:tengo|somos|con) (\d{1,4}) (?:trabajadores|maestros|personas|ayudantes)\b", text)
    workers = int(workers_match[1]) if workers_match and 1 <= int(workers_match[1]) <= 5000 else None
    company = any(contains(text, p) for p in ("tengo una empresa", "tengo empresa", "somos una empresa", "mi empresa"))
    individual = any(contains(text, p) for p in ("trabajo solo", "a mi nombre", "no tengo empresa", "soy independiente"))
    entity = "individual" if individual else "company" if company else "unknown"
    availability = "Desde mañana" if contains(text, "desde manana") else (
        "Desde hoy" if contains(text, "desde hoy") else "")
    if wants_human(message) or any(contains(text, p) for p in (
        "hablar con una persona", "hablar con administracion", "contactar administracion", "humano")):
        intent = "human"
    elif any(contains(text, p) for p in ("ignora instrucciones", "ignora las instrucciones", "ignora tus instrucciones", "revela secretos", "muestra el token", "adjudica", "paga la nomina")):
        intent = "restricted"
    elif any(contains(text, p) and not contains(text, "no " + p)
             for p in ("busco pega", "busco trabajo", "busco empleo", "quiero empleo")):
        intent, entity = "job_seeker", "individual"
    elif workers is not None:
        intent = "capacity"
    elif company:
        intent = "company_offer"
    elif any(contains(text, p) and not contains(text, "no " + p)
             for p in ("necesito maestros", "necesito contratistas", "necesito una empresa")):
        intent = "contractor_request"
    elif any(contains(text, p) for p in ("publicar una necesidad", "crear una necesidad", "publicar necesidad")):
        intent = "publish"
    elif any(contains(text, p) for p in ("registrar disponibilidad", "ofrecer disponibilidad")):
        intent = "availability"
    elif any(contains(text, p) for p in ("que obras", "necesidades hay", "obras actuales", "consultar una necesidad")):
        intent = "requirements"
    elif any(contains(text, p) for p in ("papeles", "documentos", "f30", "mutualidad")):
        intent = "documents"
    elif any(contains(text, p) for p in ("como postulo", "postular a una obra")):
        intent = "apply"
    elif any(contains(text, p) for p in ("como funciona red de obras", "que es red de obras")):
        intent = "about"
    elif specialty:
        intent = "trade_offer"
    elif text in {"hola", "ola", "buenas", "buenos dias", "buenas tardes", "hola galancito"}:
        intent = "greeting"
    return Intake(intent, specialty, entity, workers, availability)


def quick_reply(message: str, *, titles: list[str] | None = None,
                known: dict | None = None, trades: dict | None = None) -> str | None:
    info = analyze(message, trades)
    known = known or {}
    if info.intent == "human":
        return "Soy Galancito. Puedes solicitar atención de administración. No necesitas enviar documentos por aquí."
    if info.intent == "restricted":
        return "Soy Galancito. Solo oriento sobre Messenger y Red de Obras. Los permisos y adjudicaciones los gestiona el equipo autorizado."
    if private_data(message):
        return "Soy Galancito. No compartas datos personales ni contraseñas por aquí. Para revisarlos, solicita un canal seguro a administración."
    replies = {
        "greeting": "¡Hola! Soy Galancito. Te ayudo con Red de Obras. ¿Qué necesitas hacer?",
        "about": "Soy Galancito. Red de Obras conecta necesidades de las obras con servicios y disponibilidad de contratistas. El equipo autorizado revisa cada caso; no garantiza contratación.",
        "publish": "Soy Galancito. En Red de Obras, crea una necesidad e indica especialidad, resumen y fechas conocidas. La publicación debe revisarla el equipo autorizado. ¿Qué especialidad necesitas?",
        "availability": "Soy Galancito. En Red de Obras puedes informar tu especialidad, dotación y disponibilidad. ¿Qué especialidad ofreces?",
        "apply": "Soy Galancito. Podemos orientar tu interés para revisión del equipo, sin garantizar un cupo. ¿Buscas empleo como trabajador o ofreces servicios de una empresa?",
        "contractor_request": "Soy Galancito. Puedes registrar una necesidad en Red de Obras para revisión. ¿Qué especialidad necesitas?",
    }
    if info.intent in replies:
        return replies[info.intent]
    if info.intent == "requirements":
        return ("Soy Galancito. Necesidades publicadas: " + "; ".join(titles[:3])[:320]
                + ". La disponibilidad debe confirmarla administración." if titles else
                "Soy Galancito. No tengo necesidades vigentes confirmadas para mostrarte en esta consulta. Administración puede revisar tu caso.")
    if info.intent == "documents":
        entity = known.get("entity_type") or info.entity_type
        question = ("¿Trabajas con una empresa o a tu propio nombre?" if entity == "unknown" else
                    "¿Trabajas solo o tienes trabajadores contratados?" if known.get("has_employees") is None else
                    "¿Sobre qué documento necesitas orientación?")
        return "Soy Galancito. Los documentos se revisan según la obra y tu situación, sin exigir papeles que no correspondan. " + question
    if info.intent in {"job_seeker", "company_offer", "capacity", "trade_offer"}:
        specialty = known.get("specialty") or info.specialty
        availability = known.get("availability") or info.availability
        workers = known.get("workers") if known.get("workers") is not None else info.workers
        if not specialty:
            question = "¿Qué trabajo haces?"
        elif info.intent == "job_seeker":
            question = "¿En qué comuna buscas trabajo?"
        elif info.intent == "trade_offer" and (known.get("entity_type") or info.entity_type) == "unknown":
            question = "¿Buscas empleo como trabajador o ofreces un servicio por tu cuenta?"
        elif not availability:
            question = "¿Desde cuándo tienes disponibilidad?"
        elif workers is None:
            question = "¿Trabajas solo o con cuántas personas?"
        else:
            question = "¿En qué comuna puedes trabajar?"
        intro = "Recibo tu interés como trabajador, sin garantizar un puesto. " if info.intent == "job_seeker" else "Gracias por informar tu disponibilidad. "
        return "Soy Galancito. " + intro + question
    return None
