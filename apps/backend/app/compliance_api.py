"""Monthly manual controls. OCR evidence never automatically confirms payment."""
import calendar
import re
from collections import defaultdict
from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from openpyxl import Workbook
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import get_db
from .models import Document, User, utcnow
from .ops_api import association_for, assignment_for, audit_change, site_for
from .ops_models import Contractor, ContractorWorksite, Worker, WorkerAssignment, Worksite
from .platform_models import Contribution, DocumentReview, Employment, RetentionRate
from .security import authorized_user, editor
from .bulk_import import safe_cell, workbook_response

router = APIRouter(prefix="/api/v1/ops", tags=["Cumplimiento y cotizaciones"])
Period = str


def period_dates(period):
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", period):
        raise HTTPException(422, "Período inválido; utiliza AAAA-MM")
    year, month = map(int, period.split("-"))
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def classification(link, contractor):
    if link.frequency == "sporadic":
        return "ESP"
    return {"with_workers": "CT", "independent": "CI"}.get(contractor.nature, "SIN CLASIFICAR")


def rate_for(db, org_id, period):
    start, _ = period_dates(period)
    row = db.scalar(select(RetentionRate).where(RetentionRate.org_id == org_id, RetentionRate.effective_from <= start).order_by(RetentionRate.effective_from.desc()).limit(1))
    return row.daily_clp if row else 4950


class ContributionInput(BaseModel):
    association_id: str
    subject: str
    period: str
    required_days: int | None = Field(default=None, ge=0, le=31)
    paid_days: int | None = Field(default=None, ge=0, le=31)
    attendance_days: int | None = Field(default=None, ge=0, le=31)
    confirmed: bool = False
    justification: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_period(self):
        _, end = period_dates(self.period)
        for field in ("required_days", "attendance_days"):
            value = getattr(self, field)
            if value is not None and value > end.day:
                raise ValueError("Días superiores al período; justificar y corregir")
        if self.confirmed and self.paid_days is None:
            raise ValueError("Confirmar un pago requiere días pagados registrados")
        return self


@router.put("/contributions")
def save_contribution(body: ContributionInput, user: User = Depends(editor), db: Session = Depends(get_db)):
    link, company = association_for(db, user.org_id, body.association_id)
    if body.subject == "independent":
        if company.nature != "independent":
            raise HTTPException(422, "El control individual CI requiere contratista independiente")
    else:
        assignment, worker = assignment_for(db, user.org_id, body.subject)
        if assignment.worksite_id != link.worksite_id or assignment.contractor_id != company.id:
            raise HTTPException(422, "Trabajador no asociado a este contratista y obra")
    row = db.scalar(select(Contribution).where(Contribution.org_id == user.org_id, Contribution.worksite_id == link.worksite_id, Contribution.contractor_id == company.id, Contribution.subject == body.subject, Contribution.period == body.period).with_for_update())
    if row is None:
        row = Contribution(org_id=user.org_id, worksite_id=link.worksite_id, contractor_id=company.id, subject=body.subject, period=body.period)
        db.add(row)
    old = {k: getattr(row, k) for k in ("required_days", "paid_days", "attendance_days", "confirmed", "justification")}
    for key, value in body.model_dump(exclude={"association_id", "subject", "period"}).items():
        setattr(row, key, value)
    row.reviewed_by, row.reviewed_at = user.id, utcnow()
    try:
        db.flush()
        audit_change(db, user, "contribution", row.id, {"from": old, "to": body.model_dump()})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Otro usuario creó el control; recarga antes de guardar") from None
    return {"id": row.id}


def contribution_rows(db, user, period, site_id=None, contractor_id=None, include_sporadic=False):
    first, last = period_dates(period)
    if site_id:
        site_for(db, user.org_id, site_id)
    query = select(ContractorWorksite, Contractor, Worksite).join(Contractor, Contractor.id == ContractorWorksite.contractor_id).join(Worksite, Worksite.id == ContractorWorksite.worksite_id).where(ContractorWorksite.org_id == user.org_id, Contractor.org_id == user.org_id, Worksite.org_id == user.org_id)
    if site_id:
        query = query.where(Worksite.id == site_id)
    if contractor_id:
        query = query.where(Contractor.id == contractor_id)
    associations = db.execute(query.order_by(Worksite.name, Contractor.name)).all()
    assignment_rows = db.execute(select(WorkerAssignment, Worker).join(Worker, Worker.id == WorkerAssignment.worker_id).where(WorkerAssignment.org_id == user.org_id, Worker.org_id == user.org_id)).all()
    by_company = defaultdict(list)
    for a, w in assignment_rows:
        by_company[(a.worksite_id, a.contractor_id)].append((a, w))
    episodes = defaultdict(list)
    for e in db.scalars(select(Employment).where(Employment.org_id == user.org_id)):
        episodes[e.assignment_id].append(e)
    records = {(c.worksite_id, c.contractor_id, c.subject): c for c in db.scalars(select(Contribution).where(Contribution.org_id == user.org_id, Contribution.period == period))}
    rate = rate_for(db, user.org_id, period)
    rows = []
    for link, company, site in associations:
        kind = classification(link, company)
        if kind not in {"CT", "CI"} and not include_sporadic:
            continue
        subjects = [("independent", company.name, company.rut, None)] if company.nature == "independent" else [(a.id, w.name, w.rut, a) for a, w in by_company[(site.id, company.id)]]
        for subject, name, rut, assignment in subjects:
            record = records.get((site.id, company.id, subject))
            history = episodes.get(subject, [])
            relevant = [e for e in history if e.start_date <= last and (e.end_date is None or e.end_date >= first)]
            if assignment and not record and ((history and not relevant) or (not history and not assignment.active)):
                continue
            suggested = None
            if relevant:
                days = set()
                for e in relevant:
                    days.update(range((max(first, e.start_date)-first).days, (min(last, e.end_date or last)-first).days+1))
                suggested = min(30, len(days))
            required = record.required_days if record else None
            paid = record.paid_days if record else None
            difference = required - paid if required is not None and paid is not None else None
            missing = max(0, difference) if difference is not None else None
            confirmed = bool(record and record.confirmed)
            # Missing data and unconfirmed declarations never become confirmed breaches.
            state = "sin información" if paid is None else "justificado" if record.justification else "pendiente de confirmación" if not confirmed else "con diferencias" if missing else "confirmado"
            rows.append({"association_id": link.id, "site_id": site.id, "site": site.name, "contractor_id": company.id,
                         "contractor": company.name, "contractor_rut": company.rut, "classification": kind,
                         "subject": subject, "worker": name, "worker_rut": rut, "period": period,
                         "required_days": required, "suggested_days": suggested, "paid_days": paid,
                         "attendance_days": record.attendance_days if record else None,
                         "difference": difference, "missing_days": missing, "excess_days": max(0, -difference) if difference is not None else None,
                         "daily_clp": rate, "estimated_retention": missing*rate if missing is not None else None,
                         "confirmed": confirmed, "state": state, "justification": record.justification if record else "",
                         "reviewed_at": record.reviewed_at.isoformat() if record else None,
                         "reviewed_by": record.reviewed_by if record else None})
    return rows


def summarize(rows):
    paid = [r["paid_days"] for r in rows if r["paid_days"] is not None]
    confirmed = [r["paid_days"] for r in rows if r["paid_days"] is not None and r["confirmed"]]
    return {"records": len(rows), "denominator": len(paid), "average_paid_days": sum(paid)/len(paid) if paid else None,
            "confirmed_denominator": len(confirmed), "average_confirmed_days": sum(confirmed)/len(confirmed) if confirmed else None,
            "without_information": len(rows)-len(paid), "coverage": len(paid)/len(rows) if rows else None,
            "with_differences": sum((r["missing_days"] or 0) > 0 for r in rows),
            "pending_confirmation": sum(r["paid_days"] is not None and not r["confirmed"] for r in rows),
            "confirmed": sum(r["confirmed"] for r in rows),
            "missing_days": sum(r["missing_days"] or 0 for r in rows),
            "estimated_retention": sum(r["estimated_retention"] or 0 for r in rows)}


@router.get("/contributions")
def contributions(period: str, site_id: str | None = None, contractor_id: str | None = None, include_sporadic: bool = False, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    rows = contribution_rows(db, user, period, site_id, contractor_id, include_sporadic)
    sites, companies, types = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in rows:
        sites[r["site_id"]].append(r)
        companies[(r["site_id"], r["contractor_id"])].append(r)
        types[r["classification"]].append(r)
    return {"rows": rows, "summary": summarize(rows),
            "by_site": [{"site_id": key, "site": rs[0]["site"], **summarize(rs)} for key, rs in sites.items()],
            "by_contractor": [{"site_id": key[0], "contractor_id": key[1], "contractor": rs[0]["contractor"], **summarize(rs)} for key, rs in companies.items()],
            "by_classification": {key: summarize(rs) for key, rs in types.items()}}


@router.get("/contributions/report")
def contribution_report(period: str, site_id: str | None = None, include_sporadic: bool = False, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    data = contributions(period, site_id, None, include_sporadic, user, db)
    rows = data["rows"]
    wb = Workbook()
    wb.remove(wb.active)
    fields = [("contractor", "Contratista"), ("contractor_rut", "RUT contratista"), ("classification", "Clasificación"), ("site", "Obra"), ("worker", "Trabajador / CI"), ("worker_rut", "RUT trabajador / CI"), ("period", "Mes auditado"), ("required_days", "Días requeridos"), ("paid_days", "Días pagados registrados"), ("difference", "Diferencia"), ("estimated_retention", "Retención estimada CLP"), ("state", "Estado pago"), ("reviewed_at", "Fecha revisión"), ("reviewed_by", "Usuario revisión"), ("attendance_days", "Asistencia"), ("justification", "Justificación")]
    grouped = {"Consolidado": rows}
    for r in rows:
        grouped.setdefault(r["site_id"], []).append(r)
    for i, (key, rs) in enumerate(grouped.items()):
        title = "Consolidado" if key == "Consolidado" else re.sub(r"[\\/*?:\[\]]", "", rs[0]["site"])[:25] + f" {i}"
        sheet = wb.create_sheet(title)
        sheet.append([label for _, label in fields])
        for r in rs:
            sheet.append([safe_cell(r.get(k)) for k, _ in fields])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = 23
    sheet = wb.create_sheet("Promedios y cobertura")
    sheet.append(["Nivel", "Registro", "Promedio días registrados", "Denominador", "Sin información", "Retención estimada CLP"])
    for level, values in [("General", [{"label": period, **data["summary"]}]), ("Obra", data["by_site"]), ("Contratista", data["by_contractor"])]:
        for r in values:
            sheet.append([level, safe_cell(r.get("label") or r.get("site") or r.get("contractor")), r["average_paid_days"], r["denominator"], r["without_information"], r["estimated_retention"]])
    return workbook_response(wb, f"cotizaciones-{period}.xlsx")


REQUIREMENTS = {"CT": ["Cotizaciones", "F30-1", "Liquidaciones", "Libro de asistencia"], "CI": ["Cotizaciones", "Declaración jurada"], "ESP": [], "SIN CLASIFICAR": []}


class ReviewInput(BaseModel):
    association_id: str
    subject: str = "contractor"
    period: str
    requirement: str = Field(min_length=1, max_length=80)
    state: Literal["pending", "approved", "observed", "not_applicable"]
    observation: str = Field(default="", max_length=1000)
    document_id: str | None = None


@router.put("/document-reviews")
def save_review(body: ReviewInput, user: User = Depends(editor), db: Session = Depends(get_db)):
    period_dates(body.period)
    link, company = association_for(db, user.org_id, body.association_id)
    if body.subject != "contractor":
        assignment, _ = assignment_for(db, user.org_id, body.subject)
        if assignment.worksite_id != link.worksite_id or assignment.contractor_id != company.id:
            raise HTTPException(422, "Asignación no corresponde a la obra y contratista")
    if body.requirement not in REQUIREMENTS[classification(link, company)] + ["Listado de anticipos"]:
        raise HTTPException(422, "Requisito no aplicable; revisar clasificación")
    if company.nature == "independent" and body.requirement == "Listado de anticipos":
        raise HTTPException(422, "Anticipos no aplican a CI")
    if body.state in {"observed", "not_applicable"} and not body.observation.strip():
        raise HTTPException(422, "Se requiere una observación o justificación")
    if body.document_id and not db.scalar(select(Document.id).where(Document.id == body.document_id, Document.org_id == user.org_id)):
        raise HTTPException(404, "Documento no encontrado")
    row = db.scalar(select(DocumentReview).where(DocumentReview.org_id == user.org_id, DocumentReview.association_id == link.id, DocumentReview.subject == body.subject, DocumentReview.period == body.period, DocumentReview.requirement == body.requirement).with_for_update())
    old = {"state": row.state, "observation": row.observation, "document_id": row.document_id} if row else None
    if row is None:
        row = DocumentReview(org_id=user.org_id, **body.model_dump())
        db.add(row)
    for key, val in body.model_dump().items():
        setattr(row, key, val)
    row.reviewed_by, row.reviewed_at = user.id, utcnow()
    try:
        db.flush()
        audit_change(db, user, "document_review", row.id, {"from": old, "to": body.model_dump()})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Control creado por otro usuario; recarga") from None
    return {"id": row.id}


@router.get("/document-reviews")
def document_matrix(period: str, site_id: str | None = None, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    period_dates(period)
    if site_id:
        site_for(db, user.org_id, site_id)
    query = select(ContractorWorksite, Contractor).join(Contractor, Contractor.id == ContractorWorksite.contractor_id).where(ContractorWorksite.org_id == user.org_id, Contractor.org_id == user.org_id)
    if site_id:
        query = query.where(ContractorWorksite.worksite_id == site_id)
    controls = {(r.association_id, r.subject, r.requirement): r for r in db.scalars(select(DocumentReview).where(DocumentReview.org_id == user.org_id, DocumentReview.period == period))}
    rows = []
    for link, company in db.execute(query):
        requirements = REQUIREMENTS[classification(link, company)]
        subjects = [("contractor", company.name)]
        for a, w in db.execute(select(WorkerAssignment, Worker).join(Worker, Worker.id == WorkerAssignment.worker_id).where(WorkerAssignment.org_id == user.org_id, WorkerAssignment.worksite_id == link.worksite_id, WorkerAssignment.contractor_id == company.id, WorkerAssignment.active.is_(True))):
            subjects.append((a.id, w.name))
        for subject, name in subjects:
            keys = list(requirements)
            if (link.id, subject, "Listado de anticipos") in controls and company.nature != "independent":
                keys.append("Listado de anticipos")
            for requirement in keys:
                r = controls.get((link.id, subject, requirement))
                rows.append({"association_id": link.id, "site_id": link.worksite_id, "contractor": company.name, "subject": subject, "name": name, "period": period, "requirement": requirement,
                             "state": r.state if r else "pending", "observation": r.observation if r else "", "document_id": r.document_id if r else None,
                             "reviewed_by": r.reviewed_by if r else None, "reviewed_at": r.reviewed_at.isoformat() if r else None})
    return rows


@router.get("/overview")
def overview(period: str, site_id: str | None = None, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    controls = contributions(period, site_id, None, False, user, db)
    matrix = document_matrix(period, site_id, user, db)
    query = select(ContractorWorksite, Contractor).join(Contractor, Contractor.id == ContractorWorksite.contractor_id).where(ContractorWorksite.org_id == user.org_id, Contractor.org_id == user.org_id)
    if site_id:
        query = query.where(ContractorWorksite.worksite_id == site_id)
    links = db.execute(query).all()
    docs = defaultdict(list)
    for row in matrix:
        docs[row["association_id"]].append(row)
    cards = []
    for link, company in links:
        records = docs[link.id]
        applicable = [r for r in records if r["state"] != "not_applicable"]
        state = "con observaciones" if any(r["state"] == "observed" for r in applicable) else "al día" if applicable and all(r["state"] == "approved" for r in applicable) else "pendiente de información"
        cards.append({"association_id": link.id, "contractor": company.name, "classification": classification(link, company), "state": state,
                      "approved": sum(r["state"] == "approved" for r in applicable), "pending": sum(r["state"] == "pending" for r in applicable), "applicable": len(applicable)})
    active_query = select(WorkerAssignment).where(WorkerAssignment.org_id == user.org_id, WorkerAssignment.active.is_(True))
    if site_id:
        active_query = active_query.where(WorkerAssignment.worksite_id == site_id)
    return {"classifications": {kind: sum(c["classification"] == kind for c in cards) for kind in ("CT", "CI", "ESP", "SIN CLASIFICAR")},
            "active_workers": len({r.worker_id for r in db.scalars(active_query)}),
            "up_to_date": sum(c["state"] == "al día" for c in cards), "observed": sum(c["state"] == "con observaciones" for c in cards),
            "pending_documents": sum(c["pending"] for c in cards), "contractors": cards, "contributions": controls["summary"]}
