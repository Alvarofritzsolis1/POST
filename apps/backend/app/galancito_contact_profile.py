"""Concise, evidence-aware read model for each Messenger conversation.

Derived from persisted, voluntarily supplied professional facts on each API read.
Never store a model-written free-text summary or infer contractor compliance.
"""
def contact_profile(lead) -> dict:
    fields = [
        ("interest_type", "Tipo de interés"),
        ("specialty", "Trabajo u oficio"),
        ("team_available", "Trabaja solo o con equipo"),
        ("experience", "Experiencia"),
        ("work_area", "Comuna donde trabaja"),
        ("availability", "Disponibilidad"),
    ]
    counts = {
        "interest_type": getattr(lead, "interest_type", "unknown") in {"service_offer", "employment"},
        "specialty": bool(lead.specialty and lead.specialty.strip()),
        "team_available": getattr(lead, "team_available", None) is not None,
        "experience": bool(lead.experience and lead.experience.strip()),
        "work_area": bool(getattr(lead, "work_area", "").strip()),
        "availability": bool(lead.availability and lead.availability.strip()),
    }
    missing = [label for key, label in fields if not counts[key]]
    answered = sum(counts.values())
    choice = getattr(lead, "interest_type", "unknown")
    if choice == "service_offer":
        intro = "Ofrece servicios por su cuenta"
    elif choice == "employment":
        intro = "Busca empleo como trabajador"
    else:
        intro = "Tipo de interés por aclarar"
    narrative = [intro]
    if lead.specialty:
        narrative.append("oficio: " + lead.specialty.strip()[:100])
    team = getattr(lead, "team_available", None)
    if team is False:
        narrative.append("trabaja solo/a")
    elif team is True:
        if lead.workers is not None:
            narrative.append("puede acudir con " + str(lead.workers) + " persona(s) en total")
        else:
            narrative.append("puede acudir con otras personas; cantidad pendiente")
    if lead.experience:
        narrative.append("experiencia declarada: " + lead.experience.strip()[:120])
    if getattr(lead, "work_area", ""):
        narrative.append("comuna: " + lead.work_area.strip()[:80])
    if lead.availability:
        narrative.append("disponibilidad declarada: " + lead.availability.strip()[:100])
    if lead.company:
        narrative.append("nombre comercial registrado: " + lead.company.strip()[:100])
    if lead.requirement_id:
        narrative.append("tiene una necesidad vinculada por administración")
    return {
        "summary": ". ".join(narrative) + ". Pendiente de validación por administración.",
        "completed": answered, "total": len(fields),
        "percent": round(answered * 100 / len(fields)),
        "missing": missing,
        "next_field": missing[0] if missing else None,
        "evidence": "Datos declarados en la conversación o registrados manualmente; no acreditan documentos ni contratación.",
        "specialty_origin": ("Registrado por administración" if lead.specialty_source == "manual"
                             else "Interpretado del mensaje; requiere confirmación"),
    }
