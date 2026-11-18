"""Sugerencias operativas locales para conversaciones de Red de Obras.

No se adjudica, no se aprueba documentación y no se guardan datos sugeridos
sin confirmación humana. No se envían conversaciones a proveedores externos.
"""
import re
from datetime import date

from .network_service import key
from .galancito_triage import TRADES

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


def ranked_needs(lead, requirements, site_names: dict, limit: int = 3) -> list[dict]:
    """Clasificación orientativa basada en HECHOS, no probabilidad de contratación."""
    specialty = key(lead.specialty or "")
    specialty_group = _trade_group(lead.specialty or "")
    if not specialty:
        return []
    recommendations = []
    for req in requirements:
        if req.org_id != lead.org_id or req.state != "published":
            continue
        wanted = key(req.specialty)
        if not wanted:
            continue
        exact = wanted == specialty or _trade_group(req.specialty) == specialty_group
        # Coincidencias parciales tienen que compartir una palabra informativa.
        tokens = {x for x in specialty.split() if len(x) >= 5}
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
