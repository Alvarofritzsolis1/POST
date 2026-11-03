"""Contract and administrative workflows independent of uploaded files."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .control_api import REQUIREMENTS, nature_defaults, today, validate_worker, validated_period
from .control_models import (ContractRegister, ContributionControl, MonthlyActivity,
                             OffboardingCase, ProcessCalendar, RequirementApplicability, WorkTask)
from .db import get_db
from .models import User, utcnow
from .ops_api import association_for, audit_change, site_for
from .ops_models import Contractor, ContractorWorksite, MonthlyDocument
from .security import authorized_user, editor

router = APIRouter(prefix="/api/v1/control/admin", tags=["Gestión administrativa"])


class CalendarInput(BaseModel):
    worksite_id: str
    period: str
    kind: Literal["cotizaciones", "f30_1", "liquidaciones", "asistencia",
                  "porteria", "declaracion_jurada", "anticipos"]
    request_date: date
    due_date: date
    alert_date: date | None = None

    @model_validator(mode="after")
    def validate(self):
        validated_period(self.period)
        if self.due_date < self.request_date:
            raise ValueError("El vencimiento no puede anteceder la fecha de solicitud")
        if self.alert_date and self.alert_date > self.due_date:
            raise ValueError("La alerta no puede ser posterior al vencimiento")
        return self


class ContractInput(BaseModel):
    association_id: str
    worker_assignment_id: str | None = None
    contract_type: Literal["fixed_term", "indefinite", "project", "services"]
    start_date: date
    end_date: date | None = None
    status: Literal["active", "ended", "suspended"] = "active"
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("Fecha de término anterior al inicio")
        if self.contract_type == "indefinite" and self.end_date is not None:
            raise ValueError("No indicar término para contrato indefinido; registra su baja expresamente")
        if self.contract_type == "fixed_term" and self.end_date is None:
            raise ValueError("El contrato a plazo fijo debe indicar su fecha de término")
        return self


class TaskInput(BaseModel):
    worksite_id: str
    association_id: str | None = None
    period: str | None = None
    title: str = Field(min_length=3, max_length=240)
    kind: Literal["review_continuity", "verify_payment", "review_document",
                  "contract_expiry", "letter_review", "manual", "monthly_request"] = "manual"
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    due_date: date | None = None
    assigned_to: str | None = None
    notes: str = Field(default="", max_length=2000)


class TaskPatch(BaseModel):
    status: Literal["open", "in_progress", "resolved", "cancelled"]
    notes: str = Field(default="", max_length=2000)
    assigned_to: str | None = None


class OffboardingInput(BaseModel):
    association_id: str
    stage: Literal["requested", "background_review", "contract_review",
                   "letter_decision", "preparation", "sent", "closed"]
    letter_decision: Literal["pending", "required", "not_required"] = "pending"
    letter_reason: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=2000)
    @model_validator(mode="after")
    def validate(self):
        if self.letter_decision == "not_required" and not self.letter_reason.strip():
            raise ValueError("Justificar por qué no corresponde carta")
        if self.stage in {"preparation", "sent", "closed"} and self.letter_decision == "pending":
            raise ValueError("Revisa antes si corresponde una carta de término")
        return self


def task_view(row: WorkTask):
    return {"id": row.id, "worksite_id": row.worksite_id,
            "association_id": row.association_id, "period": row.period,
            "title": row.title, "kind": row.kind,
            "priority": row.priority, "status": row.status,
            "due_date": row.due_date, "assigned_to": row.assigned_to,
            "notes": row.notes, "updated_at": row.updated_at}


def contract_view(row: ContractRegister):
    return {"id": row.id, "association_id": row.association_id,
            "worker_assignment_id": row.worker_assignment_id,
            "contract_type": row.contract_type, "start_date": row.start_date,
            "end_date": row.end_date, "status": row.status, "notes": row.notes,
            "created_by": row.created_by, "updated_at": row.updated_at}


@router.put("/calendar")
def upsert_calendar(payload: CalendarInput, user: User = Depends(editor),
                    db: Session = Depends(get_db)):
    site_for(db, user.org_id, payload.worksite_id)
    row = db.scalar(select(ProcessCalendar).where(
        ProcessCalendar.org_id == user.org_id,
        ProcessCalendar.worksite_id == payload.worksite_id,
        ProcessCalendar.period == payload.period,
        ProcessCalendar.kind == payload.kind))
    before = None if row is None else {
        "request_date": str(row.request_date), "due_date": str(row.due_date),
        "alert_date": str(row.alert_date) if row.alert_date else None}
    if row is None:
        row = ProcessCalendar(org_id=user.org_id, worksite_id=payload.worksite_id,
            period=payload.period, kind=payload.kind, request_date=payload.request_date,
            due_date=payload.due_date, alert_date=payload.alert_date, updated_by=user.id)
        db.add(row)
        db.flush()
    else:
        row.request_date = payload.request_date
        row.due_date = payload.due_date
        row.alert_date = payload.alert_date
        row.updated_by = user.id
        row.updated_at = utcnow()
    audit_change(db, user, "process_calendar", row.id, {
        "from": before,
        "to": {"request_date": str(row.request_date), "due_date": str(row.due_date)}})
    db.commit()
    return {"id": row.id, "worksite_id": row.worksite_id,
            "period": row.period, "kind": row.kind,
            "request_date": row.request_date, "due_date": row.due_date,
            "alert_date": row.alert_date}


@router.get("/calendar")
def list_calendar(period: str, site_id: str | None = None, user: User = Depends(authorized_user),
                  db: Session = Depends(get_db)):
    validated_period(period)
    query = select(ProcessCalendar).where(ProcessCalendar.org_id == user.org_id,
                                         ProcessCalendar.period == period)
    if site_id:
        site_for(db, user.org_id, site_id)
        query = query.where(ProcessCalendar.worksite_id == site_id)
    return [{"id": row.id, "worksite_id": row.worksite_id, "period": row.period,
             "kind": row.kind, "request_date": row.request_date, "due_date": row.due_date,
             "alert_date": row.alert_date} for row in db.scalars(query).all()]


@router.post("/contracts")
def create_contract(payload: ContractInput, user: User = Depends(editor),
                    db: Session = Depends(get_db)):
    link, _ = association_for(db, user.org_id, payload.association_id)
    if payload.worker_assignment_id:
        validate_worker(db, user, link, payload.worker_assignment_id)
    row = ContractRegister(org_id=user.org_id, association_id=link.id,
        worker_assignment_id=payload.worker_assignment_id,
        contract_type=payload.contract_type, start_date=payload.start_date,
        end_date=payload.end_date, status=payload.status, notes=payload.notes,
        created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    audit_change(db, user, "contract", row.id, {"created": contract_view(row)})
    db.commit()
    return contract_view(row)


@router.put("/contracts/{contract_id}")
def update_contract(contract_id: str, payload: ContractInput,
                    user: User = Depends(editor), db: Session = Depends(get_db)):
    row = db.scalar(select(ContractRegister).where(
        ContractRegister.id == contract_id, ContractRegister.org_id == user.org_id))
    if not row:
        raise HTTPException(404, "Contrato no encontrado")
    if row.association_id != payload.association_id:
        raise HTTPException(422, "No se puede trasladar el contrato a otra obra o empresa")
    link, _ = association_for(db, user.org_id, payload.association_id)
    if payload.worker_assignment_id:
        validate_worker(db, user, link, payload.worker_assignment_id)
    before = contract_view(row)
    for field in ("worker_assignment_id", "contract_type", "start_date",
                  "end_date", "status", "notes"):
        setattr(row, field, getattr(payload, field))
    row.updated_by = user.id
    row.updated_at = utcnow()
    audit_change(db, user, "contract", row.id,
                 {"from": before, "to": contract_view(row)})
    db.commit()
    return contract_view(row)


@router.get("/contracts")
def list_contracts(site_id: str | None = None, user: User = Depends(authorized_user),
                   db: Session = Depends(get_db)):
    query = select(ContractRegister).join(
        ContractorWorksite, ContractorWorksite.id == ContractRegister.association_id,
    ).where(ContractRegister.org_id == user.org_id,
            ContractorWorksite.org_id == user.org_id)
    if site_id:
        site_for(db, user.org_id, site_id)
        query = query.where(ContractorWorksite.worksite_id == site_id)
    now = today()
    result = []
    for row in db.scalars(query).all():
        data = contract_view(row)
        days = (row.end_date - now).days if row.end_date and row.status == "active" else None
        data["days_until_expiry"] = days
        data["expiry_alert"] = ("expired" if days is not None and days < 0 else
                                "7_days" if days is not None and days <= 7 else
                                "15_days" if days is not None and days <= 15 else
                                "30_days" if days is not None and days <= 30 else None)
        result.append(data)
    return result


@router.post("/tasks", status_code=201)
def create_task(payload: TaskInput, user: User = Depends(editor),
                db: Session = Depends(get_db)):
    site_for(db, user.org_id, payload.worksite_id)
    if payload.association_id:
        link, _ = association_for(db, user.org_id, payload.association_id)
        if link.worksite_id != payload.worksite_id:
            raise HTTPException(422, "La tarea no corresponde a esta obra")
    if payload.period:
        validated_period(payload.period)
    if payload.assigned_to and not db.scalar(select(User.id).where(
        User.id == payload.assigned_to, User.org_id == user.org_id, User.enabled.is_(True))):
        raise HTTPException(422, "Responsable no pertenece a la organización")
    row = WorkTask(org_id=user.org_id, worksite_id=payload.worksite_id,
        association_id=payload.association_id, period=payload.period,
        kind=payload.kind, title=payload.title, priority=payload.priority,
        due_date=payload.due_date, assigned_to=payload.assigned_to,
        notes=payload.notes, created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    audit_change(db, user, "work_task", row.id, {"created": payload.title})
    db.commit()
    return task_view(row)


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: TaskPatch, user: User = Depends(editor),
                db: Session = Depends(get_db)):
    row = db.scalar(select(WorkTask).where(
        WorkTask.id == task_id, WorkTask.org_id == user.org_id))
    if not row:
        raise HTTPException(404, "Tarea no encontrada")
    if payload.assigned_to and not db.scalar(select(User.id).where(
        User.id == payload.assigned_to, User.org_id == user.org_id, User.enabled.is_(True))):
        raise HTTPException(422, "Responsable no pertenece a la organización")
    previous = {"status": row.status, "notes": row.notes}
    row.status, row.notes, row.assigned_to = (
        payload.status, payload.notes, payload.assigned_to)
    row.updated_at, row.updated_by = utcnow(), user.id
    audit_change(db, user, "work_task", row.id, {
        "from": previous, "to": {"status": row.status, "notes": row.notes}})
    db.commit()
    return task_view(row)


@router.get("/tasks")
def list_tasks(site_id: str | None = None, period: str | None = None,
               status: str | None = None, user: User = Depends(authorized_user),
               db: Session = Depends(get_db)):
    query = select(WorkTask).where(WorkTask.org_id == user.org_id)
    if site_id:
        site_for(db, user.org_id, site_id)
        query = query.where(WorkTask.worksite_id == site_id)
    if period:
        validated_period(period)
        query = query.where((WorkTask.period == period) | WorkTask.period.is_(None))
    if status:
        if status not in ("open", "in_progress", "resolved", "cancelled"):
            raise HTTPException(422, "Estado de tarea inválido")
        query = query.where(WorkTask.status == status)
    return [task_view(r) for r in db.scalars(query.order_by(WorkTask.created_at.desc()).limit(500)).all()]


@router.put("/offboarding")
def upsert_offboarding(payload: OffboardingInput, user: User = Depends(editor),
                       db: Session = Depends(get_db)):
    association, _ = association_for(db, user.org_id, payload.association_id)
    row = db.scalar(select(OffboardingCase).where(
        OffboardingCase.org_id == user.org_id,
        OffboardingCase.association_id == association.id,
        OffboardingCase.status == "open"))
    if row is None:
        row = OffboardingCase(org_id=user.org_id, association_id=association.id,
                              changed_by=user.id)
        db.add(row)
        db.flush()
    previous = {"stage": row.stage, "letter_decision": row.letter_decision}
    row.stage = payload.stage
    row.status = "closed" if payload.stage == "closed" else "open"
    row.letter_decision, row.letter_reason = payload.letter_decision, payload.letter_reason.strip()
    row.notes, row.changed_by, row.updated_at = payload.notes.strip(), user.id, utcnow()
    audit_change(db, user, "offboarding", row.id,
        {"from": previous, "to": {"stage": row.stage, "letter_decision": row.letter_decision}})
    db.commit()
    return {"id": row.id, "association_id": row.association_id,
            "stage": row.stage, "status": row.status,
            "letter_decision": row.letter_decision,
            "letter_reason": row.letter_reason, "notes": row.notes}


@router.get("/offboarding")
def list_offboarding(site_id: str | None = None, user: User = Depends(authorized_user),
                     db: Session = Depends(get_db)):
    query = select(OffboardingCase).join(
        ContractorWorksite, ContractorWorksite.id == OffboardingCase.association_id
    ).where(OffboardingCase.org_id == user.org_id, ContractorWorksite.org_id == user.org_id)
    if site_id:
        site_for(db, user.org_id, site_id)
        query = query.where(ContractorWorksite.worksite_id == site_id)
    return [{"id": row.id, "association_id": row.association_id,
             "stage": row.stage, "status": row.status,
             "letter_decision": row.letter_decision, "letter_reason": row.letter_reason,
             "notes": row.notes} for row in db.scalars(query).all()]


@router.get("/alerts")
def list_alerts(site_id: str | None = None, user: User = Depends(authorized_user),
                db: Session = Depends(get_db)):
    # Queries are always scoped to the authenticated organization and optionally one worksite.
    contracts = list_contracts(site_id=site_id, user=user, db=db)
    tasks = list_tasks(site_id=site_id, status="open", user=user, db=db)
    today_date = today()
    alerts = []
    for contract in contracts:
        if contract["expiry_alert"]:
            alerts.append({"kind": "contract_expiry", "priority": "high",
                "association_id": contract["association_id"], "date": contract["end_date"],
                "message": "Contrato próximo a vencer o vencido", "reference_id": contract["id"]})
    for task in tasks:
        alerts.append({"kind": task["kind"], "priority": task["priority"],
            "association_id": task["association_id"], "date": task["due_date"],
            "message": task["title"], "reference_id": task["id"]})
    query = select(ContributionControl, ContractorWorksite).join(
        ContractorWorksite, ContractorWorksite.id == ContributionControl.association_id
    ).where(ContributionControl.org_id == user.org_id,
            ContractorWorksite.org_id == user.org_id)
    if site_id:
        query = query.where(ContractorWorksite.worksite_id == site_id)
    for row, link in db.execute(query).all():
        if not row.payment_confirmed:
            alerts.append({"kind": "unconfirmed_payment", "priority": "high",
                "association_id": link.id, "date": None,
                "message": "Pago de cotizaciones pendiente de confirmar", "reference_id": row.id})
        if (row.subject_key != "independent" and row.required_days is not None
                and row.paid_days is not None and row.paid_days < row.required_days):
            alerts.append({"kind": "contribution_difference", "priority": "critical",
                "association_id": link.id, "date": None,
                "message": "Diferencia de días cotizados", "reference_id": row.id})
    # Documentos exigibles solo desde el inicio de solicitud configurado.
    schedules = select(ProcessCalendar).where(
        ProcessCalendar.org_id == user.org_id,
        ProcessCalendar.request_date <= today_date)
    if site_id:
        schedules = schedules.where(ProcessCalendar.worksite_id == site_id)
    for scheduled in db.scalars(schedules).all():
        contractors = db.execute(select(ContractorWorksite, Contractor).join(
            Contractor, Contractor.id == ContractorWorksite.contractor_id).where(
            ContractorWorksite.org_id == user.org_id,
            Contractor.org_id == user.org_id,
            ContractorWorksite.worksite_id == scheduled.worksite_id)).all()
        for link, company in contractors:
            applicability = db.scalar(select(RequirementApplicability).where(
                RequirementApplicability.org_id == user.org_id,
                RequirementApplicability.association_id == link.id,
                RequirementApplicability.period == scheduled.period,
                RequirementApplicability.kind == scheduled.kind))
            required = (applicability.applicable if applicability is not None else
                        nature_defaults(company, link).get(scheduled.kind))
            if required is not True:
                continue
            entries = db.scalars(select(MonthlyDocument).where(
                MonthlyDocument.org_id == user.org_id,
                MonthlyDocument.association_id == link.id,
                MonthlyDocument.period == scheduled.period,
                MonthlyDocument.kind == scheduled.kind)).all()
            if any(x.review_status in ("approved", "not_applicable") for x in entries):
                continue
            if not entries or any(x.review_status in ("observed", "rejected", "pending") for x in entries):
                alerts.append({"kind": "document_pending", "priority": "high" if today_date>scheduled.due_date else "normal",
                    "association_id": link.id, "date": scheduled.due_date,
                    "message": f"{company.name}: documento {scheduled.kind} pendiente ({scheduled.period})",
                    "reference_id": scheduled.id})
    # No movimientos + evidencia de asistencia o portería: alerta, nunca baja automática.
    inactivity = select(MonthlyActivity).where(
        MonthlyActivity.org_id == user.org_id, MonthlyActivity.status == "no_movements")
    for item in db.scalars(inactivity).all():
        link = db.scalar(select(ContractorWorksite).where(
            ContractorWorksite.id == item.association_id,
            ContractorWorksite.org_id == user.org_id))
        if not link or (site_id and link.worksite_id != site_id):
            continue
        has_attendance = db.scalar(select(ContributionControl.id).where(
            ContributionControl.org_id == user.org_id,
            ContributionControl.association_id == link.id,
            ContributionControl.period == item.period,
            ContributionControl.attendance_days > 0).limit(1)) is not None
        has_gate_report = db.scalar(select(MonthlyDocument.id).where(
            MonthlyDocument.org_id == user.org_id,
            MonthlyDocument.association_id == link.id,
            MonthlyDocument.period == item.period,
            MonthlyDocument.kind == "porteria",
            MonthlyDocument.review_status == "approved").limit(1)) is not None
        if has_attendance or has_gate_report:
            alerts.append({"kind": "movement_conflict", "priority": "critical",
                "association_id": link.id, "date": None,
                "message": f"Sin movimientos incompatible con asistencia/portería en {item.period}",
                "reference_id": item.id})
    return {"date": today_date, "total": len(alerts),
            "alerts": sorted(alerts, key=lambda a: (
                {"critical": 0, "high": 1, "normal": 2, "low": 3}.get(a["priority"], 4),
                str(a["date"] or "9999-12-31")))}
