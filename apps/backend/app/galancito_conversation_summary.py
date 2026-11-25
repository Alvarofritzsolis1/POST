"""Grounded summary of a Messenger conversation for administrative review.

Stored professional fields plus actual inbound message excerpts are authoritative.
An optional AI narrative may be displayed alongside this evidence, never instead.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence

from .galancito_contact_profile import contact_profile
from .galancito_contact_email import EMAIL
from .galancito_triage import private_data

_IGNORABLE = re.compile(
    r"(?i)^\s*(?:hola|hoal|holaa+|buenas|buenos dias|buenas tardes|"
    r"ok|oka|okey|gracias|muchas gracias|saludos|si|sí|no|dale|ya|"
    r"buen dia|buen día|hello|hey)[\s!¡.,?¿]*$"
)
_UNWARRANTED = re.compile(
    r"(?i)\b(?:contratad[oa]s?|aprobaci[oó]n garantizada|"
    r"aprobado para trabajar|verificad[oa]s?|se le asign[oó]|se contrat[oó]|"
    r"documentaci[oó]n al d[ií]a|empleo asegurado|acuerdo firmado)\b"
)
_SPACES = re.compile(r"\s+")
FIELDS = (
    ("interest_type", "Interés"),
    ("specialty", "Oficio principal"),
    ("team_available", "Modalidad de trabajo"),
    ("workers", "Personas disponibles"),
    ("experience", "Experiencia declarada"),
    ("work_area", "Zona de trabajo"),
    ("availability", "Disponibilidad"),
    ("company", "Empresa o nombre comercial"),
)


def _clean(value: str, limit: int = 210) -> str:
    return _SPACES.sub(" ", (value or "").strip())[:limit]


def _value(lead, key: str) -> str:
    val = getattr(lead, key, None)
    if key == "interest_type":
        return {"employment": "Busca empleo", "service_offer": "Ofrece servicios",
                "both": "Busca empleo y ofrece servicios"}.get(val, "")
    if key == "team_available":
        return "Trabaja con equipo" if val is True else "Trabaja solo/a" if val is False else ""
    if key == "workers":
        return f"{val} persona(s)" if val is not None else ""
    return _clean(str(val)) if val not in (None, "", "unknown", []) else ""


def summarize_conversation(lead, messages: Sequence) -> dict:
    """Real inbound evidence and recorded facts; no made-up customer statements."""
    inbound = [m for m in messages if getattr(m, "direction", "") == "inbound"]
    sources = getattr(lead, "profile_sources", None) or {}
    safe = [m for m in inbound if (getattr(m, "body", "") or "").strip()
            and not private_data(m.body) and not EMAIL.search(m.body)]
    meaningful = [m for m in safe if not _IGNORABLE.fullmatch(_clean(m.body, 250))]
    evidence = [{
        "id": str(m.id),
        "text": _clean(m.body, 180),
        "at": m.created_at.isoformat() if getattr(m, "created_at", None) else None,
        "source_message_id": getattr(m, "remote_id", None),
    } for m in meaningful[-8:]]
    fields = []
    for key, label in FIELDS:
        value = _value(lead, key)
        if not value:
            continue
        origin = sources.get(key, {})
        source = (origin.get("source", "") if isinstance(origin, dict) else "")
        fields.append({
            "key": key, "label": label, "value": value,
            "source": "manual" if source == "manual" else
                      "chat" if source in {"message", "messenger"} else "registrado",
            "at": origin.get("at") if isinstance(origin, dict) else None,
            "source_message_id": origin.get("message_id") if isinstance(origin, dict) else None,
        })
    context = sources.get("_declared_context") or {}
    for key, label in (("crew_expandable", "Posibilidad de ampliar cuadrilla"),
                       ("declared_origin", "Procedencia declarada"),
                       ("crew_size", "Tamaño de cuadrilla declarado"),
                       ("preferred_contact", "Canal de contacto preferido")):
        origin = context.get(key) or {}
        val = origin.get("value")
        if val is None:
            continue
        value = ("Sí; cantidad adicional no confirmada" if val else "No") if key == "crew_expandable" else _clean(str(val), 60)
        if value and not private_data(value):
            fields.append({"key": key, "label": label, "value": value, "source": "chat",
                           "at": origin.get("at"), "source_message_id": origin.get("message_id")})
    # A unified narrative for residents and Facebook admins. Avoid the
    # unnatural 'field: value. field: value' fallback.
    profile = contact_profile(lead)
    if not fields and meaningful:
        overview = ("Hay mensajes del contacto, pero todavía faltan datos "
                    "profesionales para preparar una presentación confiable.")
    elif not fields and inbound:
        overview = ("Solo se registran saludos breves. Todavía no existen "
                    "datos profesionales para preparar una ficha confiable.")
    elif not fields:
        overview = "Este contacto todavía no tiene mensajes recibidos para resumir."
    else:
        overview = profile["summary"]
    last_inbound = inbound[-1].created_at.isoformat() if inbound and inbound[-1].created_at else None
    fingerprint = hashlib.sha256(json.dumps({
        "messages": [(str(m.id), getattr(m, "body", "")[:700],
                      str(getattr(m, "updated_at", ""))) for m in inbound[-35:]],
        "fields": [(f["key"], f["value"], f["source"]) for f in fields],
        "missing": profile["missing"],
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {
        "summary": overview[:800],
        "facts": fields,
        "missing": profile["missing"],
        "evidence": evidence,
        "message_count": len(inbound),
        "review_required": True,
        "source": "datos_y_conversacion",
        "fingerprint": fingerprint,
        "last_inbound_at": last_inbound,
        "ai": None,
    }


def brief_contains_private_data(brief: dict) -> bool:
    """Review text sent to AI, not opaque database message IDs.

    A generated message UUID can accidentally resemble a RUT or telephone;
    scanning serialized JSON falsely rejects otherwise safe, consented briefs.
    """
    return any(private_data(value) for value in (
        [str(f.get("value", "")) for f in brief["facts"] if f["key"] != "company"]
        + [str(e.get("text", "")) for e in brief["evidence"]]
        + [str(value) for value in brief["missing"][:8]]
    ))


def safe_model_input(brief: dict) -> str:
    """Only non-sensitive professional facts and real selected messages go to AI."""
    return json.dumps({
        "facts": [{"label": f["label"], "value": f["value"]}
                  for f in brief["facts"] if f["key"] != "company"],
        "messages": [{"id": e["id"], "text": e["text"]} for e in brief["evidence"]],
        "missing": brief["missing"][:8],
    }, ensure_ascii=False)[:4000]


def validate_ai_brief(raw: str, brief: dict) -> dict | None:
    """Reject ungrounded references, numbers, sensitive data and hiring claims."""
    try:
        parsed = json.loads((raw or "").strip())
    except (TypeError, ValueError, AttributeError):
        return None
    if not isinstance(parsed, dict):
        return None
    summary = _clean(parsed.get("summary", ""), 500) if isinstance(parsed.get("summary"), str) else ""
    refs = parsed.get("evidence_ids")
    allowed = {m["id"] for m in brief["evidence"]}
    if not (25 <= len(summary) <= 500 and isinstance(refs, list)
            and 1 <= len(refs) <= 4 and all(isinstance(i, str) and i in allowed for i in refs)):
        return None
    if private_data(summary) or _UNWARRANTED.search(summary):
        return None
    facts = " ".join(f["value"] for f in brief["facts"])
    excerpts = " ".join(e["text"] for e in brief["evidence"] if e["id"] in refs)
    available_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", facts + " " + excerpts))
    model_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", summary))
    if not model_numbers.issubset(available_numbers):
        return None
    return {
        "summary": summary,
        "evidence_ids": list(dict.fromkeys(refs)),
        "review_required": True,
        "source": "ia_con_evidencia",
    }
