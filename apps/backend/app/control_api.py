"""Operative monthly matrix and human review without requiring a PDF."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .control_models import (ContributionControl, MonthlyActivity, ProcessCalendar,
                             RequirementApplicability, WorkTask)
from .db import get_db
from .models import User, utcnow
from .monthly_api import valid_period
from .ops_api import association_for, audit_change, site_for, contractor_classification
from .ops_models import (Contractor, ContractorWorksite, MonthlyDocument,
                         Worker, WorkerAssignment)
from .platform_models import DocumentReview
from .security import authorized_user, editor, document_reviewer

router = APIRouter(prefix="/api/v1/control", tags=["GALANT control operativo"])
REQUIREMENTS = ("cotizaciones", "f30_1", "liquidaciones", "asistencia",
                "porteria", "declaracion_jurada", "anticipos")
STATUS = ("pending", "approved", "observed", "rejected", "not_applicable")
CL_TZ = ZoneInfo("America/Santiago")


def today():
    return datetime.now(CL_TZ).date()


def is_independent(company: Contractor, association: ContractorWorksite) -> bool:
    return company.nature == "independent"


def nature_defaults(company: Contractor, association: ContractorWorksite) -> dict[str, bool | None]:
    # Los independientes nunca tienen requisito de anticipos, aunque su
    # frecuencia administrativa esté marcada como esporádica.
    if is_independent(company, association):
        # Anticipos nunca se piden a un independiente.
        return dict.fromkeys(REQUIREMENTS) | {
            "cotizaciones": True, "declaracion_jurada": True, "anticipos": False,
        }
    if association.frequency == "sporadic":
        # Otros esporádicos requieren exigibilidad explícita por mes.
        return dict.fromkeys(REQUIREMENTS)
    if company.nature == "with_workers":
        return dict.fromkeys(REQUIREMENTS) | {
            "cotizaciones": True, "f30_1": True, "liquidaciones": True,
            "asistencia": True, "declaracion_jurada": False,
        }
    # Un contratista no clasificado NO debe convertirse en un incumplimiento ficticio.
    return dict.fromkeys(REQUIREMENTS)


def validated_period(value: str) -> str:
    try:
        return valid_period(value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


class PeriodInput(BaseModel):
    period: str
    @field_validator("period")
    @classmethod
    def verify_period(cls, value: str) -> str:
        return validated_period(value)


class ManualReviewInput(PeriodInput):
    association_id: str
    kind: Literal["cotizaciones", "f30_1", "liquidaciones", "asistencia",
                  "porteria", "declaracion_jurada", "anticipos"]
    status: Literal["pending", "approved", "observed", "rejected", "not_applicable"]
    notes: str = Field(default="", max_length=2000)


class BulkReviewInput(BaseModel):
    reviews: list[ManualReviewInput] = Field(min_length=1, max_length=100)


class ApplicabilityInput(PeriodInput):
    association_id: str
    kind: Literal["cotizaciones", "f30_1", "liquidaciones", "asistencia",
                  "porteria", "declaracion_jurada", "anticipos"]
    applicable: bool
    justification: str = Field(min_length=3, max_length=2000)


class ContributionInput(PeriodInput):
    association_id: str
    worker_assignment_id: str | None = None
    attendance_days: int | None = Field(default=None, ge=0, le=31)
    required_days: int | None = Field(default=None, ge=0, le=31)
    paid_days: int | None = Field(default=None, ge=0, le=31)
    payment_confirmed: bool = False
    daily_rate: Decimal = Field(default=Decimal("4950"), ge=0, le=1000000, decimal_places=2)
    justification: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=2000)
    review_status: Literal["pending", "approved", "observed"] = "pending"
    retention_status: Literal["none", "proposed", "justified", "confirmed", "resolved"] = "none"

    @model_validator(mode="after")
    def check_days(self):
        if (self.required_days is not None and self.attendance_days is not None
                and self.required_days != self.attendance_days and not self.justification.strip()):
            raise ValueError("Justifica por qué los días exigibles difieren de la asistencia")
        return self


class ActivityInput(PeriodInput):
    association_id: str
    status: Literal["with_movements", "no_movements", "unconfirmed"]
    reason: str = Field(default="", max_length=2000)


def validate_worker(db: Session, user: User, association: ContractorWorksite, worker_id: str):
    assignment = db.scalar(select(WorkerAssignment).where(
        WorkerAssignment.id == worker_id,
        WorkerAssignment.org_id == user.org_id,
        WorkerAssignment.contractor_id == association.contractor_id,
        WorkerAssignment.worksite_id == association.worksite_id,
    ))
    if not assignment:
        raise HTTPException(404, "Trabajador no asignado a este contratista y obra")
    return assignment


def change_review(db: Session, user: User, payload: ManualReviewInput) -> MonthlyDocument:
    association, company = association_for(db, user.org_id, payload.association_id)
    defaults = nature_defaults(company, association)
    default_applicability = defaults.get(payload.kind)
    override = db.scalar(select(RequirementApplicability).where(
        RequirementApplicability.org_id == user.org_id,
        RequirementApplicability.association_id == association.id,
        RequirementApplicability.period == payload.period,
        RequirementApplicability.kind == payload.kind,
    ))
    if payload.kind == "anticipos" and is_independent(company, association) and payload.status != "not_applicable":
        raise HTTPException(422, "Un independiente no puede requerir listado de anticipos")
    applicable = override.applicable if override is not None else default_applicability
    if applicable is False and payload.status != "not_applicable":
        raise HTTPException(422, "Este requisito no aplica al contratista; configura su exigibilidad si corresponde")
    if applicable is None and payload.status != "not_applicable":
        raise HTTPException(422, "Primero configura si el requisito es exigible; no se puede aprobar sin clasificar")
    if payload.status in ("observed", "rejected", "not_applicable") and not payload.notes.strip():
        raise HTTPException(422, "Indica un motivo verificable para este estado")
    db.execute(select(ContractorWorksite).where(ContractorWorksite.id == association.id, ContractorWorksite.org_id == user.org_id).with_for_update()).scalar_one()
    row = db.scalar(select(MonthlyDocument).where(
        MonthlyDocument.org_id == user.org_id,
        MonthlyDocument.association_id == association.id,
        MonthlyDocument.period == payload.period,
        MonthlyDocument.kind == payload.kind,
        MonthlyDocument.document_id.is_(None),
    ).order_by(MonthlyDocument.updated_at.desc()).limit(1))
    if row is None:
        row = MonthlyDocument(
            org_id=user.org_id, association_id=association.id, contractor_id=company.id,
            period=payload.period, kind=payload.kind, created_by=user.id,
            document_id=None, review_status="pending", notes="",
        )
        db.add(row)
        db.flush()
    before = {"status": row.review_status, "notes": row.notes}
    row.review_status = payload.status
    row.notes = payload.notes.strip()
    row.reviewed_by = user.id
    row.reviewed_at = utcnow()
    row.updated_at = utcnow()
    audit_change(db, user, "monthly_document", row.id, {
        "manual_review": {"from": before,
                          "to": {"status": row.review_status, "notes": row.notes},
                          "source": "manual_without_pdf" if row.document_id is None else "document"},
    })
    return row


@router.post("/reviews")
def save_review(payload: ManualReviewInput, user: User = Depends(document_reviewer), db: Session = Depends(get_db)):
    row = change_review(db, user, payload)
    db.commit()
    return {"id": row.id, "status": row.review_status, "source": "manual_without_pdf",
            "reviewed_by": row.reviewed_by, "reviewed_at": row.reviewed_at}


@router.post("/reviews/bulk")
def save_bulk(payload: BulkReviewInput, user: User = Depends(document_reviewer), db: Session = Depends(get_db)):
    keys = [(r.association_id, r.period, r.kind) for r in payload.reviews]
    if len(keys) != len(set(keys)):
        raise HTTPException(422, "La operación masiva contiene requisitos repetidos")
    results = [change_review(db, user, item) for item in payload.reviews]
    db.commit()
    return {"updated": len(results), "ids": [row.id for row in results]}


@router.put("/applicability")
def set_applicability(payload: ApplicabilityInput, user: User = Depends(editor), db: Session = Depends(get_db)):
    association, company = association_for(db, user.org_id, payload.association_id)
    if is_independent(company, association) and payload.kind == "anticipos" and payload.applicable:
        raise HTTPException(422, "Los independientes no pueden tener listado de anticipos exigible")
    if company.nature == "with_workers" and payload.kind == "declaracion_jurada" and payload.applicable:
        raise HTTPException(422, "La declaración exclusiva de independientes no aplica")
    row = db.scalar(select(RequirementApplicability).where(
        RequirementApplicability.org_id == user.org_id,
        RequirementApplicability.association_id == association.id,
        RequirementApplicability.period == payload.period,
        RequirementApplicability.kind == payload.kind))
    previous = None if row is None else {"applicable": row.applicable, "justification": row.justification}
    if row is None:
        row = RequirementApplicability(org_id=user.org_id, association_id=association.id,
            period=payload.period, kind=payload.kind, applicable=payload.applicable,
            justification=payload.justification.strip(), updated_by=user.id)
        db.add(row)
        db.flush()
    else:
        row.applicable = payload.applicable
        row.justification = payload.justification.strip()
        row.updated_by = user.id
        row.updated_at = utcnow()
    audit_change(db, user, "requirement_applicability", row.id, {
        "from": previous, "to": {"applicable": row.applicable, "justification": row.justification}})
    db.commit()
    return {"id": row.id, "applicable": row.applicable, "justification": row.justification}


@router.get("/matrix")
def monthly_matrix(site_id: str, period: str, user: User = Depends(authorized_user),
                   db: Session = Depends(get_db)):
    validated_period(period)
    site_for(db, user.org_id, site_id)
    contractor_rows = db.execute(select(ContractorWorksite, Contractor).join(
        Contractor, Contractor.id == ContractorWorksite.contractor_id,
    ).where(ContractorWorksite.org_id == user.org_id,
            Contractor.org_id == user.org_id,
            ContractorWorksite.worksite_id == site_id).order_by(Contractor.name)).all()
    ids = [link.id for link, _ in contractor_rows]
    if not ids:
        return {"period": period, "site_id": site_id, "contractors": [],
                "summary": {"applicable": 0, "approved": 0, "reviewed": 0, "compliance": None, "progress": None}}
    docs = db.scalars(select(MonthlyDocument).where(
        MonthlyDocument.org_id == user.org_id,
        MonthlyDocument.association_id.in_(ids),
        MonthlyDocument.period == period,
    ).order_by(MonthlyDocument.updated_at.desc(), MonthlyDocument.created_at.desc())).all()
    overrides = db.scalars(select(RequirementApplicability).where(
        RequirementApplicability.org_id == user.org_id,
        RequirementApplicability.association_id.in_(ids),
        RequirementApplicability.period == period)).all()
    calendar = {r.kind: r for r in db.scalars(select(ProcessCalendar).where(
        ProcessCalendar.org_id == user.org_id, ProcessCalendar.worksite_id == site_id,
        ProcessCalendar.period == period)).all()}
    by_doc = {}
    for row in docs:
        by_doc.setdefault((row.association_id, row.kind), row)
    by_override = {(row.association_id, row.kind): row for row in overrides}
    count_total = count_approved = count_reviewed = 0
    contractors = []
    now = today()
    for link, company in contractor_rows:
        defaults = nature_defaults(company, link)
        requirements = []
        for kind in REQUIREMENTS:
            override = by_override.get((link.id, kind))
            applicable = override.applicable if override is not None else defaults[kind]
            row = by_doc.get((link.id, kind))
            if row is not None and row.review_status == "not_applicable":
                applicable = False
            schedule = calendar.get(kind)
            if applicable is False:
                state = "not_applicable"
            elif applicable is None:
                state = "needs_classification"
            elif (row and row.review_status == "pending" and row.document_id is None
                  and schedule is not None and now > schedule.due_date):
                state = "overdue"
            elif row and row.review_status in STATUS:
                state = row.review_status
            elif schedule is not None and now < schedule.request_date:
                state = "not_yet_required"
            elif schedule is not None and now > schedule.due_date:
                state = "overdue"
            elif schedule is not None:
                state = "pending"
            else:
                state = "schedule_not_configured"
            if applicable is True and (row is not None or
                 (schedule is not None and now >= schedule.request_date)):
                count_total += 1
                if state == "approved":
                    count_approved += 1
                if state in ("approved", "observed", "rejected", "not_applicable"):
                    count_reviewed += 1
            requirements.append({
                "kind": kind, "applicable": applicable, "state": state,
                "source": "manual_without_pdf" if row and row.document_id is None else
                          "document" if row else None,
                "document_id": row.document_id if row else None,
                "reviewed_by": row.reviewed_by if row else None,
                "reviewed_at": row.reviewed_at if row else None,
                "notes": row.notes if row else "",
                "request_date": schedule.request_date if schedule else None,
                "due_date": schedule.due_date if schedule else None,
            })
        contractors.append({
            "association_id": link.id, "contractor_id": company.id,
            "name": company.name, "rut": company.rut,
            "code": contractor_classification(link, company), "historical_code": link.historical_code, "nature": company.nature,
            "frequency": link.frequency, "status": link.contract_status,
            "requirements": requirements,
        })
    return {"period": period, "site_id": site_id, "contractors": contractors,
        "summary": {"applicable": count_total, "approved": count_approved,
                    "reviewed": count_reviewed,
                    "compliance": round(100 * count_approved / count_total, 1) if count_total else None,
                    "progress": round(100 * count_reviewed / count_total, 1) if count_total else None}}


def contribution_view(row: ContributionControl, association: ContractorWorksite,
                      company: Contractor, worker_name: str | None,
                      auto_attendance: int | None = None,
                      calendar_available: bool = False) -> dict:
    independent = row.subject_key == "independent"
    # Canonical weekly evidence is authoritative only when the new calendar has
    # been initialized. A missing week is unknown, NEVER zero attendance.
    attendance = auto_attendance if calendar_available and not independent else row.attendance_days
    required = (row.required_days if row.required_days is not None else attendance)
    if calendar_available and attendance is None and not independent:
        required = None
    missing = (max(0, required - row.paid_days)
               if required is not None and row.paid_days is not None else None)
    proposal = (Decimal(missing) * row.daily_rate if missing is not None else None)
    compliance = ("conforme" if independent and row.payment_confirmed else
                  "no_entregado" if row.paid_days is None else
                  "pendiente" if not row.payment_confirmed else
                  "observado" if missing and row.justification.strip() else
                  "incomplete" if missing else "conforme")
    return {
        "id": row.id, "association_id": association.id, "site_id": association.worksite_id,
        "contractor": company.name, "contractor_rut": company.rut, "code": contractor_classification(association, company), "historical_code": association.historical_code,
        "period": row.period, "subject_key": row.subject_key,
        "worker_assignment_id": row.worker_assignment_id,
        "worker": worker_name, "attendance_days": attendance,
        "required_days": row.required_days, "paid_days": row.paid_days,
        "payment_confirmed": row.payment_confirmed,
        "daily_rate": str(row.daily_rate), "missing_days": missing,
        "retention_suggested": str(proposal) if proposal is not None else None,
        "retention_status": row.retention_status, "review_status": row.review_status,
        "compliance_status": compliance,
        "justification": row.justification, "notes": row.notes,
        "reviewer_id": row.reviewer_id, "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


@router.put("/contributions")
def save_contributions(payload: ContributionInput, user: User = Depends(editor),
                       db: Session = Depends(get_db)):
    link, company = association_for(db, user.org_id, payload.association_id)
    independent = is_independent(company, link)
    if independent and payload.worker_assignment_id:
        raise HTTPException(422, "Los independientes se revisan por su propio RUT, sin trabajador ficticio")
    if not independent and not payload.worker_assignment_id:
        raise HTTPException(422, "Selecciona un trabajador asignado al contratista")
    if independent and payload.retention_status in ("proposed", "confirmed"):
        raise HTTPException(422, "No calcular retención por días automáticamente a independientes")
    if payload.retention_status == "confirmed" and user.role != "admin":
        raise HTTPException(403, "Solo un administrador puede confirmar una retención propuesta")
    if payload.retention_status in ("proposed", "confirmed") and (
        payload.required_days is None or payload.paid_days is None
        or payload.required_days <= payload.paid_days
    ):
        raise HTTPException(422, "La retención propuesta requiere días faltantes comprobables")
    if payload.retention_status == "confirmed" and not payload.notes.strip():
        raise HTTPException(422, "La confirmación administrativa requiere observaciones de respaldo")
    if payload.retention_status == "justified" and not payload.justification.strip():
        raise HTTPException(422, "Indica la justificación para la diferencia")
    worker = None
    if payload.worker_assignment_id:
        worker = validate_worker(db, user, link, payload.worker_assignment_id)
    subject_key = "independent" if independent else worker.id
    row = db.scalar(select(ContributionControl).where(
        ContributionControl.org_id == user.org_id,
        ContributionControl.association_id == link.id,
        ContributionControl.period == payload.period,
        ContributionControl.subject_key == subject_key))
    old = None
    if row is None:
        row = ContributionControl(
            org_id=user.org_id, association_id=link.id,
            period=payload.period, subject_key=subject_key,
            worker_assignment_id=worker.id if worker else None,
            created_by=user.id, updated_by=user.id,
        )
        db.add(row)
        db.flush()
    else:
        old = {
            "attendance_days": row.attendance_days, "required_days": row.required_days,
            "paid_days": row.paid_days, "payment_confirmed": row.payment_confirmed,
            "daily_rate": str(row.daily_rate), "review_status": row.review_status,
            "retention_status": row.retention_status,
            "justification": row.justification, "notes": row.notes,
        }
    for field in (
        "attendance_days", "required_days", "paid_days", "payment_confirmed",
        "daily_rate", "justification", "notes", "review_status", "retention_status",
    ):
        setattr(row, field, getattr(payload, field))
    row.updated_by = user.id
    row.updated_at = utcnow()
    evidence_changed = bool(old and (
        any(old[field] != getattr(row, field) for field in (
            "attendance_days", "required_days", "paid_days", "payment_confirmed",
        )) or Decimal(old["daily_rate"]) != row.daily_rate
    ))
    if evidence_changed:
        from .platform_models import PaymentFinding
        finding = db.scalar(select(PaymentFinding).where(
            PaymentFinding.org_id == user.org_id,
            PaymentFinding.control_id == row.id).with_for_update())
        if finding and finding.state != "unverified":
            previous_state = finding.state
            finding.state, finding.reviewed_by, finding.reviewed_at = "unverified", user.id, utcnow()
            audit_change(db, user, "payment_finding", finding.id, {
                "invalidated_by_contribution_change": {"from": previous_state, "to": "unverified"}})
        # Una aprobación previa y cualquier retención confirmada deben
        # reexaminarse cuando cambian los días, el pago o la tarifa.
        if old["review_status"] == "approved":
            row.review_status = "pending"
        if old["retention_status"] == "confirmed":
            row.retention_status = "proposed" if (
                not independent and row.required_days is not None
                and row.paid_days is not None
                and row.required_days > row.paid_days
            ) else "none"
        for doc in db.scalars(select(MonthlyDocument).where(
            MonthlyDocument.org_id == user.org_id,
            MonthlyDocument.association_id == link.id,
            MonthlyDocument.period == payload.period,
            MonthlyDocument.kind == "cotizaciones",
            MonthlyDocument.review_status == "approved",
        )).all():
            doc.review_status = "pending"
            doc.updated_at = utcnow()
            audit_change(db, user, "monthly_document", doc.id,
                         {"review_invalidated": "Datos de cotizaciones modificados"})
        if worker:
            for review in db.scalars(select(DocumentReview).where(
                DocumentReview.org_id == user.org_id,
                DocumentReview.association_id == link.id,
                DocumentReview.period == payload.period,
                DocumentReview.subject == worker.id,
                DocumentReview.requirement == "Cotizaciones",
                DocumentReview.state == "approved",
            )).all():
                review.state = "pending"
                review.observation = "Revisar nuevamente: cambiaron los días o el pago de cotizaciones"
                review.reviewed_by = user.id
                review.reviewed_at = utcnow()
                audit_change(db, user, "document_review", review.id,
                             {"review_invalidated": "Datos de cotizaciones modificados"})
    if (not independent and row.retention_status == "none"
            and row.required_days is not None and row.paid_days is not None
            and row.required_days > row.paid_days):
        row.retention_status = "proposed"  # sugerencia, no descuento.
    row.reviewer_id = user.id if row.review_status != "pending" else None
    audit_change(db, user, "contribution_control", row.id, {
        "before": old,
        "after": {
            "attendance_days": row.attendance_days,
            "required_days": row.required_days, "paid_days": row.paid_days,
            "payment_confirmed": row.payment_confirmed,
            "daily_rate": str(row.daily_rate), "review_status": row.review_status,
            "retention_status": row.retention_status,
            "justification": row.justification, "notes": row.notes,
        },
        "evidence_changed": evidence_changed,
    })
    db.commit()
    name = None
    if worker:
        name = db.scalar(select(Worker.name).where(
            Worker.id == worker.worker_id, Worker.org_id == user.org_id))
    return contribution_view(row, link, company, name)


@router.get("/contributions")
def list_contributions(period: str, site_id: str | None = None,
                       user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    validated_period(period)
    if site_id:
        site_for(db, user.org_id, site_id)
    query = select(ContributionControl, ContractorWorksite, Contractor).join(
        ContractorWorksite, ContractorWorksite.id == ContributionControl.association_id,
    ).join(Contractor, Contractor.id == ContractorWorksite.contractor_id).where(
        ContributionControl.org_id == user.org_id,
        ContractorWorksite.org_id == user.org_id,
        Contractor.org_id == user.org_id,
        ContributionControl.period == period,
    )
    if site_id:
        query = query.where(ContractorWorksite.worksite_id == site_id)
    from .v81_service import site_calendar_totals
    per_site = {}
    result = []
    for record, association, company in db.execute(query).all():
        name = None
        if record.worker_assignment_id:
            name = db.scalar(select(Worker.name).join(
                WorkerAssignment, WorkerAssignment.worker_id == Worker.id
            ).where(WorkerAssignment.id == record.worker_assignment_id,
                    WorkerAssignment.org_id == user.org_id,
                    Worker.org_id == user.org_id))
        if association.worksite_id not in per_site:
            per_site[association.worksite_id] = site_calendar_totals(
                db, user.org_id, association.worksite_id, period)
        calendar_available, totals = per_site[association.worksite_id]
        result.append(contribution_view(record, association, company, name,
            auto_attendance=totals.get(record.worker_assignment_id),
            calendar_available=calendar_available and bool(record.worker_assignment_id)))
    return result


@router.put("/activity")
def set_activity(payload: ActivityInput, user: User = Depends(editor),
                 db: Session = Depends(get_db)):
    association, _ = association_for(db, user.org_id, payload.association_id)
    if payload.status == "no_movements" and not payload.reason.strip():
        raise HTTPException(422, "Indica el motivo de no registrar movimientos")
    record = db.scalar(select(MonthlyActivity).where(
        MonthlyActivity.org_id == user.org_id,
        MonthlyActivity.association_id == association.id,
        MonthlyActivity.period == payload.period))
    if not record:
        record = MonthlyActivity(org_id=user.org_id, association_id=association.id,
                                 period=payload.period, changed_by=user.id)
        db.add(record)
        db.flush()
    before = record.status
    record.status = payload.status
    record.reason = payload.reason.strip()
    record.changed_by = user.id
    record.updated_at = utcnow()
    if payload.status == "no_movements":
        found = db.scalar(select(WorkTask).where(
            WorkTask.org_id == user.org_id, WorkTask.association_id == association.id,
            WorkTask.period == payload.period,
            WorkTask.kind == "review_continuity", WorkTask.status == "open"))
        if not found:
            db.add(WorkTask(org_id=user.org_id, worksite_id=association.worksite_id,
                association_id=association.id, period=payload.period, kind="review_continuity",
                title="Revisar continuidad contractual y determinar si corresponde carta de término",
                created_by=user.id, updated_by=user.id, priority="high"))
    audit_change(db, user, "monthly_activity", record.id,
                 {"from": before, "to": record.status, "reason": record.reason})
    db.commit()
    return {"id": record.id, "association_id": association.id,
            "period": record.period, "status": record.status, "reason": record.reason}


@router.get("/activity")
def list_activity(site_id: str, period: str, user: User = Depends(authorized_user),
                  db: Session = Depends(get_db)):
    site_for(db, user.org_id, site_id)
    validated_period(period)
    return [{"id": r.id, "association_id": r.association_id, "period": r.period,
             "status": r.status, "reason": r.reason, "changed_by": r.changed_by}
            for r in db.scalars(select(MonthlyActivity).join(
                ContractorWorksite, ContractorWorksite.id == MonthlyActivity.association_id).where(
                MonthlyActivity.org_id == user.org_id,
                MonthlyActivity.period == period,
                ContractorWorksite.org_id == user.org_id,
                ContractorWorksite.worksite_id == site_id)).all()]
