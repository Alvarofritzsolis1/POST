"""Resident-friendly, evidence-aware contact summary shared across GALANT.

This is an on-read presentation model, not hallucinated AI narration.
Only explicitly declared professional facts are used. Unknown dates and
missing contact channels remain visible instead of implying completeness.
"""
from __future__ import annotations

from datetime import date


def _value(lead, key: str) -> str:
    return str(getattr(lead, key, "") or "").strip()


def _known_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def contact_profile(lead) -> dict:
    team = getattr(lead, "team_available", None)
    workers = getattr(lead, "workers", None)
    contact_phone = _value(lead, "contact_phone")
    contact_email = _value(lead, "contact_email")
    choice = getattr(lead, "interest_type", "unknown")
    fields = [
        ("interest_type", "Tipo de interés"),
        ("specialty", "Trabajo u oficio"),
        ("team_available", "Trabaja solo o con equipo"),
        *([("workers", "Personas que pueden acudir")] if team is True else []),
        ("experience", "Experiencia"),
        ("work_area", "Comunas donde puede trabajar"),
        ("availability", "Disponibilidad"),
        ("contact", "Teléfono o correo para coordinar"),
    ]
    counts = {
        "interest_type": choice in {"service_offer", "employment", "both"},
        "specialty": bool(_value(lead, "specialty")),
        "team_available": team is not None,
        "workers": workers is not None,
        "experience": bool(_value(lead, "experience")),
        "work_area": bool(_value(lead, "work_area")),
        # A relative answer such as 'mañana' is known as a declaration,
        # but it cannot confirm a calendar date for a specific worksite.
        "availability": bool(_value(lead, "availability")),
        "contact": bool(contact_phone or contact_email),
    }
    missing = [label for key, label in fields if not counts[key]]
    name = _value(lead, "display_name")
    known_name = bool(name and name not in {"Interesado de Facebook", "Contacto sin nombre"})
    if not known_name and not getattr(lead, "name_opt_out", False):
        missing.append("Nombre de la persona (opcional)")

    subject = name[:75] if known_name else "Este contacto"
    trade = _value(lead, "specialty")
    intro = {
        "employment": "busca empleo",
        "service_offer": "ofrece servicios",
        "both": "busca empleo y también ofrece servicios",
    }.get(choice, "aún no ha definido si busca empleo u ofrece servicios")
    first = subject + " " + intro
    if trade:
        first += (" de " if choice != "employment" else " en ") + trade[:90]
    first += "."
    chunks = [first]

    if team is False:
        chunks.append("Indicó que trabaja por su cuenta.")
    elif team is True and workers is not None:
        chunks.append(f"Señaló que puede acudir con {workers} {'persona' if workers == 1 else 'personas'} en total.")
    elif team is True:
        chunks.append("Puede trabajar con un equipo, pero falta confirmar cuántas personas.")

    experience = _value(lead, "experience")
    if experience:
        chunks.append("Experiencia declarada: " + experience[:150].rstrip(".") + ".")
    area = _value(lead, "work_area")
    if area:
        chunks.append("Zona de trabajo: " + area[:100].rstrip(".") + ".")
    availability = _value(lead, "availability")
    if availability:
        if _known_date(availability):
            chunks.append("Indicó disponibilidad desde el " + availability + ".")
        else:
            chunks.append("Disponibilidad declarada: «" + availability[:85] +
                          "». Falta confirmar una fecha exacta.")
    company = _value(lead, "company")
    if company and company.casefold() != name.casefold():
        chunks.append("Empresa o nombre comercial declarado: " + company[:100].rstrip(".") + ".")

    if not contact_phone and not contact_email:
        chunks.append("Aún no ha compartido teléfono ni correo; por ahora el contacto puede continuar por Messenger.")
    else:
        channels = ("teléfono y correo" if contact_phone and contact_email
                    else "teléfono" if contact_phone else "correo")
        chunks.append("Datos de contacto disponibles: " + channels + ".")
    answered = sum(bool(counts[key]) for key, _ in fields)
    return {
        "summary": " ".join(chunks),
        "completed": answered, "total": len(fields),
        "percent": round(answered * 100 / len(fields)),
        "missing": missing,
        "next_field": missing[0] if missing else None,
        "evidence": "Datos declarados en Messenger o registrados por un operador; no acreditan experiencia ni cumplimiento documental.",
        "sources": getattr(lead, "profile_sources", None) or {},
        "specialty_origin": (
            "Registrado por administración" if getattr(lead, "specialty_source", "") == "manual"
            else "Interpretado del mensaje; requiere confirmación"
        ),
    }
