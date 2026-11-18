"""Small deterministic Spanish intake. Never interprets text as permission/action.

Only explicit facts are extracted; unknown individuals are not made companies.
Curated spelling aliases apply to trades, never to consent or authorization.
"""
from collections import Counter
from datetime import date, datetime, timezone
from dataclasses import dataclass
import re
import unicodedata

from .galancito_flow import wants_human
from .network_service import key


def plain(text: str) -> str:
    value = "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                    if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


TRADES = {
    "Gasfitería": ("gasfite", "gasfiter", "gasfiteria", "gasfitero", "gasfitero", "gafiter", "maestro sanitario"),
    "Carpintería": ("carpintero", "carpinteros", "carpinteria", "carpinter", "carpintreo", "carpinterio", "mueblista", "mueblero"),
    "Pintura": ("pintor", "pintores", "pintura", "pinturas", "pinturero", "pintur"),
    "Albañilería": ("albanil", "albaniles", "albanileria", "albanir", "pandereta"),
    "Electricidad": ("electrico", "electricista", "electricidad", "electricito", "eletricista", "electrisista"),
    "Aseo": ("aseo", "limpieza"),
    "Soldadura": ("soldador", "soldadura", "soldadoro", "sodador"),
    "Cerámica": ("ceramista", "ceramica", "ceramico", "seramista"),
    "Tabiquería": ("tabique", "tabiques", "tabiquero", "tabiqueria", "volcanita"),
    "Impermeabilización": ("impermeabilizacion", "impermeabilizar", "impermiabilizacion"),
    "Enfierradura": ("enfierrador", "enfierradura", "enfierador", "fierrero"),
    "Hormigonado": ("hormigon", "hormigonado", "hormigonero"),
    "Techumbres": ("techumbre", "techumbres", "techero", "cubiertas", "cubierta"),
    "Ventanas": ("ventanero", "ventanas", "aluminio", "vidrios", "ventaneria"),
    "Pavimentación": ("pavimentos", "pavimentacion", "pavimentador"),
    "Jardinería": ("jardinero", "jardineria", "paisajismo"),
}


def contains(text: str, phrase: str) -> bool:
    return f" {plain(phrase)} " in f" {text} "


def private_data(text: str) -> bool:
    return bool(re.search(
        r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[0-9kK]\b|"
        r"(?i:clave\s*[úu]nica|contrase[ñn]a|password|token|api[_ ]?key)\s*[:=]|"
        r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|" 
        r"(?<!\d)(?:\+?56[\s.-]?)?9[\s.-]?\d{4}[\s.-]?\d{4}(?!\d)|"
        r"(?i:(?:nvapi-|gsk_|sk-|AIza)[a-z0-9_\-]{8,})", text))


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


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", key(text or "")).strip()


def _has_phrase(text: str, phrase: str) -> bool:
    needle = _norm(phrase)
    return bool(needle and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", _norm(text)))


def _category(lead, guides, requirements, messages):
    if lead.specialty.strip() and getattr(lead, "specialty_source", "manual") != "message":
        return lead.specialty.strip()[:100], "declarada", "Registrada por administración"
    # Do not use private conversation history without AI consent. Guiding a
    # human is possible without classifying a person's literacy or knowledge.
    if not lead.ai_consent:
        return "Por confirmar", "sin_datos", "Preguntar oficio al interesado"
    if lead.specialty.strip():
        return lead.specialty.strip()[:100], "sugerida", "Oficio declarado en un mensaje; pendiente de confirmación administrativa"
    recent = " ".join(msg.body[:400] for msg in messages
                      if msg.direction == "inbound")[-1200:]
    approved = {}
    for guide in guides:
        for alias in [guide.trade, *(guide.aliases or [])]:
            if _has_phrase(recent, alias):
                approved[key(guide.trade)] = guide.trade
    if len(approved) == 1:
        return next(iter(approved.values()))[:100], "sugerida", "Coincidencia textual con una guía aprobada"
    if len(approved) > 1:
        return "Por confirmar", "ambigua", "Mencionó más de un oficio; confirmar con el interesado"
    published = {key(r.specialty):r.specialty for r in requirements}
    found = {k:v for k,v in published.items() if _has_phrase(recent,v)}
    if len(found) == 1:
        return next(iter(found.values()))[:100], "sugerida", "Coincidencia textual con una necesidad publicada"
    return "Por confirmar", "sin_datos", "Preguntar oficio al interesado"


def classify_lead(lead, guides, requirements, messages=(), *, today: date | None = None):
    """Categorize the work queue, not the person's suitability or education."""
    today = today or datetime.now(timezone.utc).date()
    category, source, evidence = _category(lead, guides, requirements, messages)
    linked = next((r for r in requirements if r.id == lead.requirement_id), None)
    due = lead.follow_up_on
    overdue = bool(due and due <= today and lead.status != "archived")
    if lead.status == "archived":
        stage, urgency, action = "Cerrado", "none", "Sin seguimiento activo"
    elif lead.needs_support:
        stage, urgency, action = "Apoyo humano", "high", "Llamar o orientar personalmente, un paso a la vez"
    elif overdue:
        stage, urgency, action = "Seguimiento vencido", "high", "Revisar compromiso de seguimiento"
    elif lead.unread:
        stage, urgency, action = "Responder", "high", "Leer mensaje y responder dentro de la ventana permitida"
    elif source in {"ambigua", "sin_datos"}:
        stage, urgency, action = "Por clasificar", "normal", "Confirmar qué oficio realiza"
    elif not linked:
        stage, urgency, action = "Por vincular", "normal", "Buscar necesidad compatible y verificar con administración"
    elif lead.status in {"pending_review", "shortlisted"}:
        stage, urgency, action = "Revisión", "normal", "Contrastar datos con residente antes de decidir"
    elif lead.workers is None:
        stage, urgency, action = "Datos pendientes", "normal", "Preguntar si trabaja solo o con ayudantes"
    elif not lead.availability:
        stage, urgency, action = "Datos pendientes", "normal", "Preguntar disponibilidad por comuna y fecha"
    else:
        stage, urgency, action = "En seguimiento", "normal", "Confirmar interés y próximos pasos con el residente"
    if lead.last_inbound_at and not lead.ai_paused:
        last = lead.last_inbound_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last).total_seconds() > 24*3600:
            action += ". No enviar mensajes fuera de la ventana de Meta"
    return {
        "id": lead.id, "name": lead.display_name, "company": lead.company,
        "category": category, "category_source": source, "category_evidence": evidence,
        "status": lead.status, "stage": stage, "urgency": urgency,
        "next_action": action[:260], "requirement_id": lead.requirement_id,
        "requirement_title": linked.title if linked else None,
        "follow_up_on": due.isoformat() if due else None,
        "follow_up_note": (lead.follow_up_note or "")[:240],
        "needs_support": bool(lead.needs_support),
        "unread": bool(lead.unread), "human_review_required": True,
        "suggestion_only": True,
    }


def dashboard(rows):
    categorized = Counter(item["category"] for item in rows)
    stages = Counter(item["stage"] for item in rows)
    needs = Counter(item["requirement_title"] or "Sin necesidad asignada" for item in rows)
    return {
        "total": len(rows),
        "urgent": sum(row["urgency"] == "high" for row in rows),
        "needs_human": sum(row["needs_support"] for row in rows),
        "unlinked": sum(not row["requirement_id"] for row in rows),
        "overdue": sum(row["stage"] == "Seguimiento vencido" for row in rows),
        "by_category": dict(categorized.most_common(26)),
        "by_stage": dict(stages.most_common()),
        "by_requirement": dict(needs.most_common(50)),
        "rows": sorted(rows, key=lambda r: (
            {"high": 0, "normal": 1, "none": 2}.get(r["urgency"], 3),
            r["follow_up_on"] or "9999-12-31", r["name"].lower())),
        "disclaimer": "Prioridad de trabajo, no calificación del candidato; siempre requiere revisión humana.",
    }
