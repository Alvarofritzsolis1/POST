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
        *([("entity_type", "Ofrece servicios como independiente o empresa")]
          if choice in {"service_offer", "both"} else []),
        ("team_available", "Trabaja solo o con equipo"),
        *([("workers", "Personas que pueden acudir")] if team is True else []),
        ("experience", "Experiencia"),
        ("work_area", "Comunas donde puede trabajar"),
        ("availability", "Disponibilidad"),
    ]
    context = (getattr(lead, "profile_sources", None) or {}).get("_declared_context") or {}
    galilea = context.get("worked_at_galilea") or {}
    worked_at_galilea = galilea.get("value")
    galilea_label = {True: "Sí, declarado", False: "No, declarado"}.get(worked_at_galilea)
    if galilea.get("state") == "rechazado_por_usuario":
        galilea_label = "Prefirió no responder"
    if choice in {"service_offer", "employment", "both"} and _value(lead, "specialty"):
        fields.append(("worked_at_galilea", "Experiencia previa en Galilea"))
    declared = {field: context[field]["value"] for field in (
        "declared_origin", "crew_size", "preferred_contact") if (context.get(field) or {}).get("value")}
    counts = {
        "interest_type": choice in {"service_offer", "employment", "both"},
        "specialty": bool(_value(lead, "specialty")),
        "entity_type": _value(lead, "entity_type") not in {"", "unknown"},
        "team_available": team is not None,
        "workers": workers is not None or bool(declared.get("crew_size")),
        "experience": bool(_value(lead, "experience")),
        "worked_at_galilea": worked_at_galilea is not None,
        "work_area": bool(_value(lead, "work_area")),
        # A relative answer such as 'mañana' is known as a declaration,
        # but it cannot confirm a calendar date for a specific worksite.
        "availability": bool(_value(lead, "availability")),
    }
    sources = {field: origin for field, origin in (getattr(lead, "profile_sources", None) or {}).items()
               if not field.startswith("_")}
    known = {**counts, "work_communes": counts["work_area"],
             "has_employees": getattr(lead, "has_employees", None) is not None,
             "employee_count": getattr(lead, "employee_count", None) is not None,
             "contact_phone": bool(contact_phone), "contact_email": bool(contact_email)}
    name = _value(lead, "display_name")
    known_name = bool(name and name not in {"Interesado de Facebook", "Contacto sin nombre"})
    known["display_name"] = known_name
    states = {}
    for field, present in known.items():
        recorded = (galilea if field == "worked_at_galilea" else sources.get(field, {})).get("state")
        if recorded and (present or recorded != "confirmado_por_declaracion"):
            states[field] = recorded
        else:
            states[field] = "confirmado_por_declaracion" if present else "pendiente"
    for field, opt_out in (("display_name", "name_opt_out"), ("contact_phone", "phone_opt_out"),
                           ("contact_email", "email_opt_out")):
        if not known[field] and getattr(lead, opt_out, False):
            states[field] = "rechazado_por_usuario"
    if _value(lead, "experience") == "No informado por el interesado":
        states["experience"] = "rechazado_por_usuario"
    missing = [label for key, label in fields if not counts[key] and states[key] != "rechazado_por_usuario"]

    subject = name[:75] if known_name else "Este contacto"
    trade = _value(lead, "specialty")
    notice_trade = (context.get("notice_trade") or {}).get("value")
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
    if notice_trade:
        chunks.append(f"Consultó un aviso de {notice_trade.lower()}.")

    if crew := declared.get("crew_size"):
        chunks.append("Tamaño de cuadrilla declarado: «" + crew[:100] + "».")
    elif team is False:
        chunks.append("Indicó que trabaja por su cuenta.")
    elif team is True and workers is not None:
        chunks.append(f"Señaló que puede acudir con {workers} {'persona' if workers == 1 else 'personas'} en total.")
    elif team is True:
        chunks.append("Puede trabajar con un equipo, pero falta confirmar cuántas personas.")

    flexibility = context.get("crew_expandable", {}).get("value")
    origin = context.get("declared_origin", {}).get("value")
    if flexibility is True:
        chunks.append("Indicó que puede ampliar la cuadrilla; cantidad adicional no confirmada.")
    elif flexibility is False:
        chunks.append("Indicó que no puede sumar más personas.")
    if isinstance(origin, str) and origin:
        chunks.append("Procedencia declarada: " + origin[:60] + ". No equivale a zona de trabajo confirmada.")

    employees = getattr(lead, "employee_count", None)
    if getattr(lead, "has_employees", None) is False:
        chunks.append("Declaró que trabaja sin personal contratado.")
    elif employees == 1:
        chunks.append("Declaró una persona contratada.")
    elif employees is not None:
        chunks.append(f"Declaró {employees} personas contratadas.")
    elif getattr(lead, "has_employees", None):
        chunks.append("Declaró que tiene personal contratado, sin indicar cuántas personas.")

    experience = _value(lead, "experience")
    if experience:
        chunks.append("Experiencia declarada: " + experience[:150].rstrip(".") + ".")
    if worked_at_galilea is True:
        chunks.append("Declaró que trabajó antes en Galilea.")
    elif worked_at_galilea is False:
        chunks.append("Declaró que no ha trabajado antes en Galilea.")
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
    channel = {"whatsapp": "WhatsApp", "messenger": "Messenger", "email": "correo electrónico"}.get(declared.get("preferred_contact"))
    if channel:
        chunks.append("Prefiere conversar por " + channel + ".")
    answered = sum(counts[key] and states[key] != "rechazado_por_usuario" for key, _ in fields)
    applicable = sum(states[key] != "rechazado_por_usuario" for key, _ in fields)
    return {
        "summary": " ".join(chunks),
        "completed": answered, "total": applicable,
        "percent": round(answered * 100 / applicable) if applicable else None,
        "missing": missing,
        "field_states": {**states, **{field: context[field].get("state", "confirmado_por_declaracion")
                                    for field in declared}},
        "contact_state": ("canal_voluntario" if contact_phone or contact_email else "solo_messenger"),
        "next_field": missing[0] if missing else None,
        "evidence": "Datos declarados en Messenger o registrados por un operador; no acreditan experiencia ni cumplimiento documental.",
        "sources": sources,
        "declared_context": context,
        "galilea_experience": galilea_label,
        "notice_trade": notice_trade,
        "specialty_origin": (
            "Registrado por administración" if getattr(lead, "specialty_source", "") == "manual"
            else "Interpretado del mensaje; requiere confirmación"
        ),
    }
