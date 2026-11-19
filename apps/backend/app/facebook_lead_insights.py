"""Sugerencias operativas locales para conversaciones de Red de Obras.

No se adjudica, no se aprueba documentación y no se guardan datos sugeridos
sin confirmación humana. No se envían conversaciones a proveedores externos.
"""
import re
from datetime import date
from sqlalchemy import select

from .network_service import key, today as local_today
from .galancito_triage import TRADES
from .galancito_links import audit_event, canonical_trade, trade_terms
from .facebook_crm_models import FacebookLeadTrade, FacebookNeedAssociation
from .network_models import NetworkRequirement

# La extracción de nombres es conservadora: solo frases de presentación explícita.
_NAME = re.compile(
    r"(?i)(?:\bme\s+llamo\b|\bmi\s+nombre\s+es\b|\bsoy\b|\bhabla\b)"
    r"\s+([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+"
    r"(?:\s+[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+){0,3})\b"
)
_EXCLUDED = {
    "maestro", "gasfiter", "electricista", "carpintero", "trabajador",
    "independiente", "contratista", "persona", "empresa", "albañil",
    "constructor", "interesado", "nuevo", "hola", "galancito",
    "de", "una", "un", "yo",
}


def name_from_conversation(messages) -> dict | None:
    """Nombre expresamente declarado; nunca adivinar por oficio o PSID."""
    for message in messages:
        if message.direction != "inbound":
            continue
        body = message.body[:350]
        result = _NAME.search(body)
        if result:
            words = result.group(1).split()
            if any(key(word) in _EXCLUDED for word in words):
                continue
            name = " ".join(words)[:95]
            return {"field": "name", "value": name,
                    "source": "mensaje_explicito", "evidence": "Presentación del contacto",
                    "confirmed": False}
    return None


def suggestions_for_lead(lead, messages) -> list[dict]:
    """Proponer únicamente campos desconocidos, nunca sobrescribir campos humanos."""
    result = []
    if not lead.display_name or lead.display_name == "Interesado de Facebook":
        name = name_from_conversation(messages)
        if name:
            result.append(name)
    # El oficio y la dotación pueden haber sido extraídos por reglas del webhook.
    if lead.specialty and lead.specialty_source == "message":
        result.append({"field": "specialty", "value": lead.specialty,
                       "source": "mensaje", "evidence": "Oficio mencionado en conversación",
                       "confirmed": False})
    if lead.workers is not None:
        result.append({"field": "workers", "value": lead.workers,
                       "source": "declaracion", "evidence": "Cantidad declarada, no verificada",
                       "confirmed": False})
    return result


def _trade_group(value: str) -> str:
    normalized = key(value)
    for canonical, aliases in TRADES.items():
        if normalized in {key(canonical), *(key(alias) for alias in aliases)}:
            return key(canonical)
    return normalized


def active_trades(db, lead) -> list[str]:
    rows = db.scalars(select(FacebookLeadTrade.trade).where(
        FacebookLeadTrade.org_id == lead.org_id, FacebookLeadTrade.lead_id == lead.id,
        FacebookLeadTrade.active.is_(True),
    ).order_by(FacebookLeadTrade.first_seen_at, FacebookLeadTrade.id)).all()
    return list(dict.fromkeys([*rows, *([lead.specialty] if lead.specialty else [])]))


def ranked_needs(lead, requirements, site_names: dict, limit: int = 3, *,
                 trades=None) -> list[dict]:
    """Compare every registered specialty to the active needs."""
    specialties = trades if trades is not None else ([lead.specialty] if lead.specialty else [])
    groups = {_trade_group(specialty) for specialty in specialties}
    tokens = {token for specialty in specialties for token in key(specialty).split() if len(token) >= 5}
    if not groups:
        return []
    recommendations = []
    for req in requirements:
        if req.org_id != lead.org_id or req.state != "published" or req.deadline < local_today():
            continue
        wanted = key(req.specialty)
        if not wanted:
            continue
        exact = any(_trade_group(trade) in groups for trade in (trade_terms(req.specialty) or [req.specialty]))
        # Coincidencias parciales tienen que compartir una palabra informativa.
        related = bool(tokens.intersection(x for x in wanted.split() if len(x) >= 5))
        if not exact and not related:
            continue
        score = 60 if exact else 35
        reasons = ["Mismo oficio registrado" if exact else "Oficio relacionado: confirmar especialidad"]
        checks = 1
        if lead.workers is not None:
            checks += 1
            if lead.workers >= req.workers:
                score += 20
                reasons.append("Dotación declarada suficiente")
            else:
                reasons.append("Faltan personas para la dotación solicitada")
        try:
            available = date.fromisoformat(lead.availability)
        except (ValueError, TypeError):
            available = None
        if available:
            checks += 1
            if available <= req.start_date:
                score += 20
                reasons.append("Fecha declarada compatible")
            else:
                reasons.append("La fecha de inicio requiere coordinación")
        if checks < 3:
            reasons.append("Confirmar dotación y fecha antes de derivar")
        recommendations.append({
            "id": req.id, "title": req.title, "site": site_names.get(req.site_id, "Obra"),
            "specialty": req.specialty, "workers": req.workers,
            "start_date": req.start_date.isoformat(),
            "score": score, "reasons": reasons[:4],
            "review_required": True,
        })
    return sorted(recommendations, key=lambda item: (-item["score"], item["start_date"], item["id"]))[:limit]


def link_unique_requirement(db, lead, *, today: date) -> bool:
    """Associate one exact active need only after enough professional facts.

    Linking is for follow-up, never an approval, hiring decision or award.
    Ambiguous or incomplete profiles remain unlinked for human review.
    """
    if (lead.requirement_id or lead.interest_type not in {"service_offer", "both"} or
            not lead.specialty or lead.workers is None or not lead.availability):
        return False
    try:
        available = date.fromisoformat(lead.availability)
    except (TypeError, ValueError):
        return False
    trades = {key(canonical_trade(trade)) for trade in active_trades(db, lead)}
    needs = db.scalars(select(NetworkRequirement).where(
        NetworkRequirement.org_id == lead.org_id,
        NetworkRequirement.state == "published",
        NetworkRequirement.deadline >= today,
    ).limit(201)).all()
    if len(needs) > 200:
        return False
    matches = [
        req for req in needs if lead.workers >= req.workers and available <= req.start_date
        and any(key(canonical_trade(trade)) in trades
                for trade in (trade_terms(req.specialty) or [req.specialty]))
    ]
    if len(matches) != 1:
        return False
    lead.requirement_id = matches[0].id
    return True



def trace_unique_requirement(db, lead, *, today: date, remote_id=None) -> None:
    if not link_unique_requirement(db, lead, today=today):
        return
    existing = db.scalar(select(FacebookNeedAssociation).where(
        FacebookNeedAssociation.lead_id == lead.id,
        FacebookNeedAssociation.requirement_id == lead.requirement_id,
    ))
    if existing:
        if existing.state == "unlinked":
            lead.requirement_id = None
        return
    db.add(FacebookNeedAssociation(
        org_id=lead.org_id, lead_id=lead.id, requirement_id=lead.requirement_id,
        state="linked", reviewed_by=None,
    ))
    audit_event(db, lead, "need_auto_linked", source="rule",
                requirement_id=lead.requirement_id, remote_id=remote_id)
