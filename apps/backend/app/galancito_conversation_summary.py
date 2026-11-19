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
            and not private_data(m.body)]
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
    main = [_value(lead, key) for key in
            ("interest_type", "specialty", "team_available", "experience",
             "work_area", "availability")]
    parts = []
    if main[0]:
        parts.append(main[0] + (" en " + main[1] if main[1] else ""))
    elif main[1]:
        parts.append("Oficio registrado: " + main[1])
    if main[2]:
        parts.append(main[2])
    if main[3]:
        parts.append("Experiencia: " + main[3])
    if main[4]:
        parts.append("Zona: " + main[4])
    if main[5]:
        parts.append("Disponibilidad: " + main[5])
    if parts:
        overview = ". ".join(parts).rstrip(".") + "."
    elif meaningful:
        overview = ("Hay mensajes del contacto, pero todavía no hay suficientes "
                    "datos profesionales registrados para resumir su perfil.")
    elif inbound:
        overview = ("La conversación contiene principalmente saludos o respuestas "
                    "breves; aún faltan datos para un resumen profesional.")
    else:
        overview = "Este contacto todavía no tiene mensajes recibidos para analizar."
    profile = contact_profile(lead)
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
