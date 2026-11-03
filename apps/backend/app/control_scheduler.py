"""Ejecuta solicitudes por calendario aun cuando ningún navegador está abierto.

Se llama desde el worker y es idempotente. Nunca aplica descuentos,
revoca contratistas ni crea cartas automáticamente.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .control_api import today
from .control_models import ProcessCalendar, WorkTask
from .models import User, utcnow
from .ops_models import OpsChange


def calendar_tick(db: Session, on_date: date | None = None) -> int:
    current = on_date or today()
    due = db.scalars(select(ProcessCalendar).where(
        ProcessCalendar.request_date <= current)).all()
    added = 0
    for entry in due:
        # Evita crear nuevas tareas si la solicitud previa fue cerrada.
        present = db.scalar(select(WorkTask.id).where(
            WorkTask.org_id == entry.org_id,
            WorkTask.worksite_id == entry.worksite_id,
            WorkTask.period == entry.period,
            WorkTask.kind == "monthly_request",
            WorkTask.title == "Solicitar "+entry.kind).limit(1))
        if present:
            continue
        admin_id = db.scalar(select(User.id).where(
            User.org_id == entry.org_id,
            User.role == "admin", User.enabled.is_(True)).limit(1))
        if not admin_id:
            continue
        task = WorkTask(org_id=entry.org_id, worksite_id=entry.worksite_id,
            association_id=None, period=entry.period, kind="monthly_request",
            title="Solicitar "+entry.kind, due_date=entry.due_date,
            priority="high" if current > entry.due_date else "normal",
            created_by=admin_id, updated_by=admin_id)
        db.add(task)
        db.flush()
        db.add(OpsChange(org_id=entry.org_id, user_id=admin_id,
            entity_type="work_task", entity_id=task.id,
            changes={"source": "calendar", "period": entry.period,
                     "kind": entry.kind, "activated_on": str(current)}))
        added += 1
    return added
