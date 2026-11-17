"""Galancito: transparent rule-based triage, without deciding employment.

This module NEVER edits leads, publishes ads, or sends Messenger messages.
Use only facts known to the organization and approved trade guides. No model
or remote service is needed for the daily follow-up overview.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import re

from .network_service import key


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", key(text or "")).strip()


def _has_phrase(text: str, phrase: str) -> bool:
    needle = _norm(phrase)
    return bool(needle and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", _norm(text)))


def _category(lead, guides, requirements, messages):
    if lead.specialty.strip():
        return lead.specialty.strip()[:100], "declarada", "Registrada por administración"
    # Do not use private conversation history without AI consent. Guiding a
    # human is possible without classifying a person's literacy or knowledge.
    if not lead.ai_consent:
        return "Por confirmar", "sin_datos", "Preguntar oficio al interesado"
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
