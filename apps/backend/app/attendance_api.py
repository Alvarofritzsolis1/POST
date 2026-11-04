"""Five weekly attendance windows, signed-day transcription and monthly balance."""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from openpyxl import Workbook
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .admin_api import catalogs_for
from .bulk_import import safe_cell, workbook_response
from .control_api import CL_TZ, today
from .control_models import ContractRegister, ContributionControl
from .db import get_db
from .models import Document, User, utcnow
from .monthly_api import valid_period
from .ops_api import association_for, audit_change, site_for
from .ops_models import Contractor, ContractorWorksite, Worker, WorkerAssignment
from .platform_models import (AttendanceRoster, AttendanceWeek, AttendanceWorkerWeek,
                              WorkerTermination)
from .security import authorized_user, attendance_editor, attendance_reviewer

router = APIRouter(prefix="/api/v1/attendance", tags=["Asistencia semanal"])


def period_value(value: str) -> str:
    try:
        return valid_period(value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def week_dates(period: str, number: int) -> list[date]:
    year, month = map(int, period_value(period).split("-"))
    if number not in range(1, 6):
        raise HTTPException(422, "Semana debe estar entre 1 y 5")
    first = 1 + (number - 1) * 7
    last = min(first + 6, calendar.monthrange(year, month)[1])
    return [date(year, month, day) for day in range(first, last + 1)]


def completed_on_time(completed_at, due_date: date) -> bool | None:
    if completed_at is None:
        return None
    timestamp = completed_at if completed_at.tzinfo else completed_at.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(CL_TZ).date() <= due_date


class RosterInput(BaseModel):
    association_id: str
    period: str
    status: Literal["included", "excluded"]
    reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid(self):
        period_value(self.period)
        if self.status == "excluded" and not self.reason.strip():
            raise ValueError("Indica por qué no se considera este contratista")
        return self


class SignatureInput(BaseModel):
    worker_assignment_id: str
    signed_dates: list[date] = Field(default_factory=list, max_length=31)
    excluded: bool = False
    reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def valid(self):
        if len(set(self.signed_dates)) != len(self.signed_dates):
            raise ValueError("Una firma diaria aparece dos veces")
        if self.excluded and (self.signed_dates or not self.reason.strip()):
            raise ValueError("Trabajador excluido requiere motivo y no puede tener firmas")
        return self


class WeekInput(BaseModel):
    association_id: str
    period: str
    week_number: int = Field(ge=1, le=5)
    entries: list[SignatureInput] = Field(default_factory=list, max_length=5000)
    complete: bool = False
    source_document_id: str | None = None
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid(self):
        days = set(week_dates(self.period, self.week_number))
        if not days:
            raise ValueError("La quinta semana no existe en este mes")
        ids = [r.worker_assignment_id for r in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Trabajador repetido en la semana")
        if any(day not in days for row in self.entries for day in row.signed_dates):
            raise ValueError("Firma fuera de los días de esta semana")
        if any(day > today() for row in self.entries for day in row.signed_dates):
            raise ValueError("No se pueden registrar firmas futuras")
        if self.complete and max(days) > today():
            raise ValueError("Solo puedes completar una semana cuando haya finalizado")
        return self


class WeekReview(BaseModel):
    state: Literal["approved", "observed"]
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid(self):
        if self.state == "observed" and not self.note.strip():
            raise ValueError("Explica la observación")
        return self


def _worker_eligible(assignment, contracts, terminations, days):
    if not days:
        return False
    history = contracts.get(assignment.id, [])
    if not history:
        return assignment.active
    return any(c.start_date <= days[-1]
               and (terminations.get(c.id) is None or terminations[c.id].effective_date >= days[0])
               and (c.status != "ended" or terminations.get(c.id) is not None)
               for c in history)


def _context(db, org_id, site_id, period):
    links = db.execute(select(ContractorWorksite, Contractor).join(
        Contractor, and_(Contractor.id == ContractorWorksite.contractor_id,
                         Contractor.org_id == org_id)).where(
        ContractorWorksite.org_id == org_id,
        ContractorWorksite.worksite_id == site_id)).all()
    workers = db.execute(select(WorkerAssignment, Worker).join(
        Worker, and_(Worker.id == WorkerAssignment.worker_id, Worker.org_id == org_id)).where(
        WorkerAssignment.org_id == org_id,
        WorkerAssignment.worksite_id == site_id)).all()
    assignments = defaultdict(list)
    for assignment, worker in workers:
        assignments[assignment.contractor_id].append((assignment, worker))
    contracts = defaultdict(list)
    for c in db.scalars(select(ContractRegister).where(
            ContractRegister.org_id == org_id,
            ContractRegister.worker_assignment_id.in_([a.id for a, _ in workers]))):
        contracts[c.worker_assignment_id].append(c)
    terms = {t.contract_id: t for t in db.scalars(select(WorkerTermination).where(
        WorkerTermination.org_id == org_id,
        WorkerTermination.contract_id.in_([c.id for rows in contracts.values() for c in rows])))}
    rosters = {r.association_id: r for r in db.scalars(select(AttendanceRoster).where(
        AttendanceRoster.org_id == org_id,
        AttendanceRoster.period == period,
        AttendanceRoster.association_id.in_([link.id for link, _ in links])))}
    weeks = {(w.association_id, w.week_number): w for w in db.scalars(select(AttendanceWeek).where(
        AttendanceWeek.org_id == org_id,
        AttendanceWeek.period == period,
        AttendanceWeek.association_id.in_([link.id for link, _ in links])))}
    entries = defaultdict(dict)
    for row in db.scalars(select(AttendanceWorkerWeek).where(
        AttendanceWorkerWeek.org_id == org_id,
        AttendanceWorkerWeek.week_id.in_([w.id for w in weeks.values()]))):
        entries[row.week_id][row.worker_assignment_id] = row
    controls = {(c.association_id, c.subject_key): c for c in db.scalars(
        select(ContributionControl).where(
            ContributionControl.org_id == org_id,
            ContributionControl.period == period,
            ContributionControl.association_id.in_([link.id for link, _ in links])))}
    from .network_service import actor_name
    users = {}
    for u in db.scalars(select(User).where(User.org_id == org_id)):
        name = actor_name(db, u.id)
        users[u.id] = "Usuario sin nombre registrado" if "@" in name else name
    return links, assignments, contracts, terms, rosters, weeks, entries, controls, users


@router.get("/roster")
def roster(site_id: str, period: str, user: User = Depends(authorized_user),
           db: Session = Depends(get_db)):
    site_for(db, user.org_id, site_id)
    if user.role == "administrative":
        from .network_service import assigned_sites
        if site_id not in assigned_sites(db, user):
            raise HTTPException(403, "No tienes permiso para consultar asistencia de esta obra")
    period_value(period)
    links, assignments, contracts, terms, rosters, weeks, entries, controls, users = _context(
        db, user.org_id, site_id, period)
    due_days = catalogs_for(db, user.org_id)["attendance_due_days"]
    result, overdue_count, completed_count = [], 0, 0
    for link, company in sorted(links, key=lambda pair: pair[1].name.casefold()):
        saved_roster = rosters.get(link.id)
        status = saved_roster.status if saved_roster else (
            "included" if link.contract_status == "active" and company.nature == "with_workers"
            else "excluded")
        people = assignments[company.id]
        signed_by_worker = defaultdict(set)
        week_rows = []
        for number in range(1, 6):
            days = week_dates(period, number)
            if not days:
                week_rows.append({"week_number": number, "dates": [], "state": "not_applicable",
                                  "severity": "gray", "entries": [], "missing_workers": 0})
                continue
            week = weeks.get((link.id, number))
            week_entries = entries.get(week.id, {}) if week else {}
            expected = [(a, w) for a, w in people if _worker_eligible(a, contracts, terms, days)]
            missing_workers = sum(a.id not in week_entries for a, _ in expected)
            if status == "excluded":
                state, severity = "excluded", "gray"
            elif week and week.state == "completed" and missing_workers == 0:
                completed_count += 1
                state = week.review_state if week.review_state != "pending" else "completed"
                severity = "green" if state == "approved" else "orange"
            elif today() > days[-1] + timedelta(days=due_days):
                overdue_count += 1
                state, severity = "overdue", "red"
            elif week:
                state, severity = "draft", "orange"
            else:
                state, severity = "pending", "orange" if today() >= days[0] else "gray"
            if week and week.state == "completed" and status == "included":
                for assignment_id, entry in week_entries.items():
                    if not entry.excluded:
                        signed_by_worker[assignment_id].update(entry.signed_dates or [])
            week_rows.append({
                "id": week.id if week else None, "week_number": number,
                "dates": [str(d) for d in days], "due_date": str(days[-1] + timedelta(days=due_days)),
                "state": state, "severity": severity,
                "saved_state": week.state if week else "missing",
                "source_document_id": week.source_document_id if week else None,
                "notes": week.notes if week else "",
                "entered_by": users.get(week.entered_by) if week else None,
                "entered_at": week.entered_at if week else None,
                "updated_by": users.get(week.updated_by) if week else None,
                "updated_at": week.updated_at if week else None,
                "completed_by": users.get(week.completed_by) if week else None,
                "completed_at": week.completed_at if week else None,
                "completed_on_time": completed_on_time(
                    week.completed_at if week and week.state == "completed" else None,
                    days[-1] + timedelta(days=due_days)),
                "review_state": week.review_state if week else None,
                "reviewed_by": users.get(week.reviewed_by) if week else None,
                "reviewed_at": week.reviewed_at if week else None,
                "review_note": week.review_note if week else "",
                "missing_workers": missing_workers,
                "entries": [{"worker_assignment_id": a.id, "worker": w.name,
                             "rut": w.rut, "signed_dates": (week_entries[a.id].signed_dates or []) if a.id in week_entries else [],
                             "excluded": week_entries[a.id].excluded if a.id in week_entries else False,
                             "reason": week_entries[a.id].reason if a.id in week_entries else "",
                             "recorded": a.id in week_entries}
                            for a, w in expected],
            })
        worker_rows = []
        for assignment, worker in people:
            control = controls.get((link.id, assignment.id))
            days_signed = len(signed_by_worker[assignment.id])
            paid = control.paid_days if control else None
            worker_rows.append({"assignment_id": assignment.id, "name": worker.name,
                                "rut": worker.rut, "signed_days": days_signed,
                                "paid_days": paid,
                                "difference": days_signed - paid if paid is not None else None})
        result.append({"association_id": link.id, "contractor_id": company.id,
                       "contractor": company.name, "rut": company.rut,
                       "site_id": link.worksite_id, "nature": company.nature,
                       "administrative_status": link.contract_status,
                       "roster_status": status,
                       "roster_reason": saved_roster.reason if saved_roster else (
                           "Sin inclusión automática: revisar naturaleza y actividad del contratista"
                           if status == "excluded" else ""),
                       "roster_updated_by": users.get(saved_roster.updated_by) if saved_roster else None,
                       "roster_updated_at": saved_roster.updated_at if saved_roster else None,
                       "weeks": week_rows, "workers": worker_rows,
                       "signed_days": sum(row["signed_days"] for row in worker_rows),
                       "paid_days": sum(row["paid_days"] or 0 for row in worker_rows if row["paid_days"] is not None),
                       "missing_payment_days": sum(max(0, row["difference"] or 0) for row in worker_rows)})
    if user.role == "administrative":
        # El registro de asistencia no incluye los días pagados ni el balance financiero.
        for company in result:
            company["paid_days"] = None
            company["missing_payment_days"] = None
            for worker in company["workers"]:
                worker["paid_days"] = None
                worker["difference"] = None
    return {"site_id": site_id, "period": period, "contractors": result,
            "summary": {"contractors": sum(c["roster_status"] == "included" for c in result), "overdue_weeks": overdue_count,
                        "completed_weeks": completed_count,
                        "signed_days": sum(c["signed_days"] for c in result if c["roster_status"] == "included"),
                        "missing_payment_days": sum(c["missing_payment_days"] for c in result if c["roster_status"] == "included")}}


@router.put("/roster")
def update_roster(body: RosterInput, user: User = Depends(attendance_editor),
                  db: Session = Depends(get_db)):
    association, _ = association_for(db, user.org_id, body.association_id)
    if user.role == "administrative":
        from .network_service import assigned_sites
        if association.worksite_id not in assigned_sites(db, user):
            raise HTTPException(403, "No tienes permiso para modificar esta obra")
    if body.status == "included" and association.contract_status != "active":
        raise HTTPException(422, "Solo se puede incluir un contratista administrativamente activo")
    db.scalar(select(ContractorWorksite).where(ContractorWorksite.id == association.id).with_for_update())
    row = db.scalar(select(AttendanceRoster).where(
        AttendanceRoster.org_id == user.org_id, AttendanceRoster.association_id == association.id,
        AttendanceRoster.period == body.period))
    before = {"status": row.status, "reason": row.reason} if row else None
    if row is None:
        row = AttendanceRoster(org_id=user.org_id, association_id=association.id,
                               period=body.period, updated_by=user.id)
        db.add(row)
    row.status, row.reason = body.status, body.reason.strip()
    row.updated_by, row.updated_at = user.id, utcnow()
    db.flush()
    audit_change(db, user, "attendance_roster", row.id,
                 {"from": before, "to": {"status": row.status, "reason": row.reason},
                  "association_id": association.id, "period": row.period})
    db.commit()
    return {"id": row.id, "status": row.status, "updated_at": row.updated_at}


@router.put("/weeks")
def save_week(body: WeekInput, user: User = Depends(attendance_editor),
              db: Session = Depends(get_db)):
    association, company = association_for(db, user.org_id, body.association_id)
    if user.role == "administrative":
        from .network_service import assigned_sites
        if association.worksite_id not in assigned_sites(db, user):
            raise HTTPException(403, "No tienes permiso para modificar esta obra")
    days = week_dates(body.period, body.week_number)
    db.scalar(select(ContractorWorksite).where(ContractorWorksite.id == association.id).with_for_update())
    roster_row = db.scalar(select(AttendanceRoster).where(
        AttendanceRoster.org_id == user.org_id, AttendanceRoster.association_id == association.id,
        AttendanceRoster.period == body.period))
    if (roster_row and roster_row.status == "excluded") or association.contract_status != "active" or (
            roster_row is None and company.nature != "with_workers"):
        raise HTTPException(422, "Incluye un contratista activo antes de registrar asistencia")
    if user.role == "administrative" and body.source_document_id:
        raise HTTPException(422, "En Control de Asistencia no se adjuntan documentos")
    if body.complete and today() > days[-1] + timedelta(days=catalogs_for(db, user.org_id)["attendance_due_days"]):
        if len(body.notes.strip()) < 10:
            raise HTTPException(422, "Explica brevemente el motivo del registro fuera de plazo")
    if body.source_document_id and not db.scalar(select(Document.id).where(
            Document.id == body.source_document_id, Document.org_id == user.org_id)):
        raise HTTPException(404, "Documento de asistencia no encontrado")
    _, assignments, contracts, terms, _, _, _, _, _ = _context(
        db, user.org_id, association.worksite_id, body.period)
    expected = {a.id for a, _ in assignments[association.contractor_id]
                if _worker_eligible(a, contracts, terms, days)}
    supplied = {entry.worker_assignment_id for entry in body.entries}
    if not supplied <= expected:
        raise HTTPException(422, "La planilla contiene trabajadores ajenos o fuera de esta semana")
    if body.complete and supplied != expected:
        raise HTTPException(422, "Faltan trabajadores: registra sus firmas, cero firmas o una exclusión motivada")
    week = db.scalar(select(AttendanceWeek).where(
        AttendanceWeek.org_id == user.org_id, AttendanceWeek.association_id == association.id,
        AttendanceWeek.period == body.period,
        AttendanceWeek.week_number == body.week_number).with_for_update())
    old = {"state": week.state, "review_state": week.review_state,
           "source_document_id": week.source_document_id, "notes": week.notes} if week else None
    if week is None:
        week = AttendanceWeek(org_id=user.org_id, association_id=association.id,
                              period=body.period, week_number=body.week_number,
                              entered_by=user.id, updated_by=user.id)
        db.add(week)
        db.flush()
    previous = {entry.worker_assignment_id: entry for entry in db.scalars(select(AttendanceWorkerWeek).where(
        AttendanceWorkerWeek.org_id == user.org_id, AttendanceWorkerWeek.week_id == week.id)).all()}
    changes = []
    for item in body.entries:
        row = previous.get(item.worker_assignment_id)
        before = {"signed_dates": row.signed_dates, "excluded": row.excluded, "reason": row.reason} if row else None
        if row is None:
            row = AttendanceWorkerWeek(org_id=user.org_id, week_id=week.id,
                                       worker_assignment_id=item.worker_assignment_id,
                                       updated_by=user.id)
            db.add(row)
        row.signed_dates = sorted(str(day) for day in item.signed_dates)
        row.excluded, row.reason = item.excluded, item.reason.strip()
        row.updated_by, row.updated_at = user.id, utcnow()
        after = {"signed_dates": row.signed_dates, "excluded": row.excluded, "reason": row.reason}
        if before != after:
            changes.append({"worker_assignment_id": item.worker_assignment_id,
                            "from": before, "to": after})
    week.state = "completed" if body.complete else "draft"
    week.source_document_id = body.source_document_id or week.source_document_id
    week.notes, week.updated_by, week.updated_at = body.notes.strip(), user.id, utcnow()
    if body.complete and week.completed_at is None:
        # La primera entrega permanece registrada; una corrección no borra el atraso histórico.
        week.completed_by, week.completed_at = user.id, utcnow()
    if changes or old != {"state": week.state, "review_state": week.review_state,
                          "source_document_id": week.source_document_id, "notes": week.notes}:
        week.review_state, week.review_note, week.reviewed_by, week.reviewed_at = "pending", "", None, None
    audit_change(db, user, "attendance_week", week.id, {
        "association_id": association.id, "period": body.period, "week_number": body.week_number,
        "from": old, "to": {"state": week.state, "source_document_id": week.source_document_id,
                              "notes": week.notes}, "entries": changes})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "La semana fue creada por otro usuario; vuelve a cargarla") from None
    return {"id": week.id, "state": week.state, "review_state": week.review_state,
            "entered_at": week.entered_at, "completed_at": week.completed_at}


@router.put("/weeks/{week_id}/review")
def review_week(week_id: str, body: WeekReview,
                user: User = Depends(attendance_reviewer), db: Session = Depends(get_db)):
    week = db.scalar(select(AttendanceWeek).where(
        AttendanceWeek.id == week_id, AttendanceWeek.org_id == user.org_id).with_for_update())
    if not week:
        raise HTTPException(404, "Semana no encontrada")
    if week.state != "completed":
        raise HTTPException(422, "Completa la semana antes de revisarla")
    old = {"state": week.review_state, "note": week.review_note}
    week.review_state, week.review_note = body.state, body.note.strip()
    week.reviewed_by, week.reviewed_at = user.id, utcnow()
    audit_change(db, user, "attendance_week", week.id,
                 {"review": {"from": old, "to": {"state": week.review_state,
                                                   "note": week.review_note},
                             "reviewed_by": user.id, "reviewed_at": str(week.reviewed_at)}})
    db.commit()
    return {"id": week.id, "review_state": week.review_state, "reviewed_at": week.reviewed_at}


@router.get("/export")
def export_attendance(site_id: str, period: str,
                      user: User = Depends(attendance_reviewer), db: Session = Depends(get_db)):
    data = roster(site_id, period, user, db)
    workbook = Workbook()
    workbook.remove(workbook.active)
    for number in range(1, 6):
        sheet = workbook.create_sheet(f"Semana {number}")
        sheet.append(["CONTRATISTA", "RUT EMPRESA", "ESTADO BASE", "TRABAJADOR",
                      "RUT TRABAJADOR", "DIAS FIRMADOS", "DIAS PAGADOS MES",
                      "BALANCE MENSUAL", "FECHAS FIRMADAS", "ESTADO SEMANA", "INGRESADO POR",
                      "INGRESADO EL", "CUMPLIO PLAZO", "REVISADO POR", "REVISADO EL", "RESPALDO ID"])
        for contractor in data["contractors"]:
            week = contractor["weeks"][number - 1]
            for entry in week.get("entries", []) or [{"worker": "Sin trabajadores",
                                                       "rut": "", "signed_dates": []}]:
                worker = next((w for w in contractor["workers"]
                               if w["assignment_id"] == entry.get("worker_assignment_id")), None)
                sheet.append([safe_cell(contractor["contractor"]), safe_cell(contractor["rut"]),
                              contractor["roster_status"], safe_cell(entry["worker"]),
                              safe_cell(entry["rut"]), len(entry["signed_dates"]),
                              worker["paid_days"] if worker else None,
                              worker["difference"] if worker else None,
                              ", ".join(entry["signed_dates"]), week["state"],
                              week.get("entered_by"), str(week.get("entered_at") or ""),
                              ("Sí" if week.get("completed_on_time") else "No")
                              if week.get("completed_on_time") is not None else "Pendiente",
                              week.get("reviewed_by"), str(week.get("reviewed_at") or ""),
                              week.get("source_document_id")])
    return workbook_response(workbook, f"asistencia-{period}.xlsx")
