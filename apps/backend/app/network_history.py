"""Presentación segura de la auditoría de Red de Obras para usuarios operativos.

Los registros OpsChange se conservan íntegros. Este adaptador devuelve solamente
campos permitidos y nombres comprensibles; no expone el JSON de auditoría.
"""

from datetime import date

from sqlalchemy import select

from .ops_models import Contractor, Worksite

TITLES = {
    "network_requirement": ("Requerimiento creado", "Requerimiento actualizado"),
    "network_capacity": ("Disponibilidad publicada", "Disponibilidad actualizada"),
    "network_capacity_renewal": ("Disponibilidad renovada", "Disponibilidad renovada"),
    "network_award": ("Partida adjudicada", "Adjudicación actualizada"),
    "network_award_revision": ("Adjudicación reprogramada", "Adjudicación reprogramada"),
    "network_item_amendment": ("Partida ampliada", "Partida ampliada"),
    "network_coordination": ("Coordinación iniciada", "Coordinación actualizada"),
    "network_participant": ("Coordinador incorporado", "Coordinación actualizada"),
}
FIELDS = {
    "site_id": "Obra",
    "title": "Título",
    "specialty": "Especialidad",
    "start_date": "Fecha de inicio",
    "end_date": "Fecha de término",
    "deadline": "Fecha límite",
    "priority": "Prioridad",
    "workers": "Trabajadores solicitados",
    "state": "Estado",
    "availability": "Disponibilidad",
    "available_date": "Disponible desde",
    "expires_on": "Vigencia hasta",
    "quantity": "Cantidad",
    "unit": "Unidad",
    "executed": "Cantidad ejecutada",
    "contractor_id": "Contratista",
    "items": "Partidas",
}
STATES = {
    "published": "Publicado", "draft": "Borrador", "cancelled": "Cancelado",
    "low": "Baja", "normal": "Normal", "high": "Alta", "urgent": "Urgente",
    "assigned": "Adjudicado", "ready": "Habilitado", "in_progress": "En ejecución",
    "completed": "Finalizado", "revoked": "Revocado",
    "estimated": "Estimada", "confirmed": "Confirmada", "discarded": "Descartada",
    "committed": "Comprometida", "pending": "Pendiente",
}


def _public_value(db, org_id, field, value):
    if value is None or value == "":
        return "Sin definir"
    if field == "items":
        return str(len(value)) + " partidas" if isinstance(value, list) else None
    if isinstance(value, (dict, list)):
        return None
    if field == "site_id":
        name = db.scalar(
            select(Worksite.name).where(Worksite.id == value, Worksite.org_id == org_id)
        )
        return name or "Obra no disponible"
    if field == "contractor_id":
        name = db.scalar(
            select(Contractor.name).where(
                Contractor.id == value, Contractor.org_id == org_id
            )
        )
        return name or "Contratista no disponible"
    if field in {"start_date", "end_date", "deadline", "available_date", "expires_on"}:
        try:
            return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
        except ValueError:
            return "Fecha no disponible"
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return STATES.get(str(value), str(value)[:180])


def history_view(db, user, row):
    change = row.changes if isinstance(row.changes, dict) else {}
    before = change.get("from") if isinstance(change.get("from"), dict) else {}
    after = change.get("to") if isinstance(change.get("to"), dict) else {}
    created = change.get("from") is None
    pair = TITLES.get(row.entity_type, ("Actividad registrada", "Actividad actualizada"))
    title = pair[0] if created else pair[1]
    details = []
    for field, label in FIELDS.items():
        if field not in after:
            continue
        old = _public_value(db, user.org_id, field, before.get(field))
        new = _public_value(db, user.org_id, field, after[field])
        if new is None or (not created and old == new):
            continue
        details.append({
            "label": label,
            "before": None if created or field not in before else old,
            "after": new,
        })
    reason = change.get("reason")
    return {
        "id": row.id,
        "title": title,
        "actor": row.user_id,
        "at": row.created_at,
        "details": details[:12],
        "reason": reason[:500] if isinstance(reason, str) else "",
    }
