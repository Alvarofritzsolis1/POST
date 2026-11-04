"""v8.1 operational weekly attendance and objectively frozen monthly assessments.

Separate tables preserve v8 legacy evidence without destructive calendar rewrites.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .admin_api import catalogs_for
from .attendance_api import _context, _worker_eligible
from .calendar_v81 import calendar_weeks, dates_of_week, deadline_utc, grade, CL_TZ
from .control_api import today
from .control_models import ContributionControl
from .platform_models import PaymentFinding
from .db import get_db
from .models import AuditEvent, Organization, User, utcnow
from .platform_models import OrganizationSettings
from .network_models import NetworkMembership
from .network_service import actor_name, assigned_sites
from .ops_api import association_for, audit_change, site_for
from .ops_models import Contractor, ContractorWorksite, WorkerAssignment
from .security import authorized_user, attendance_editor, administrator
from .v81_models import CalendarWeek, CalendarEntry, CalendarDuty, MonthlyAssessment

router = APIRouter(prefix="/api/v1/attendance-v81", tags=["Asistencia calendario y evaluación v8.1"])


def _scope(db, user, site_id):
    site_for(db, user.org_id, site_id)
    if user.role == "administrative" and site_id not in assigned_sites(db, user):
        raise HTTPException(403, "No tienes autorización en esta obra")


def _name(db, user_id):
    name = actor_name(db, user_id) if user_id else ""
    return name if name and "@" not in name else "Nombre pendiente de registro"


def _settings(db, org_id):
    row = db.get(OrganizationSettings, org_id)
    return dict(row.values or {}) if row else {}


def _deadline(db, org_id, last, site_id):
    values = _settings(db, org_id)
    policy = (values.get("attendance_policies") or {}).get(site_id, {})
    grace = policy.get("grace_days", catalogs_for(db, org_id)["attendance_due_days"])
    return deadline_utc(last, grace, policy.get("cutoff", "23:59"))


def _instant(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _role(db, user, target_id):
    target = db.scalar(select(User).where(
        User.id == target_id, User.org_id == user.org_id, User.enabled.is_(True)))
    if not target or target.role != "administrative":
        raise HTTPException(422, "Selecciona un usuario con perfil Administrativo")
    return target


def _eligible(db, user, association, period, number):
    dates = dates_of_week(period, number)
    _, assignments, contracts, terminations, _, _, _, _, _ = _context(
        db, user.org_id, association.worksite_id, period)
    return [(a, w) for a, w in assignments[association.contractor_id]
            if _worker_eligible(a, contracts, terminations, dates)]


class PolicyInput(BaseModel):
    site_id: str
    grace_days: int = Field(ge=0, le=31)
    cutoff: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    completion_weight: Decimal = Field(ge=0, le=1)


@router.get("/settings")
def settings(site_id: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    _scope(db, user, site_id)
    values = _settings(db, user.org_id)
    policy = (values.get("attendance_policies") or {}).get(site_id, {})
    return {"site_id": site_id,
            "grace_days": policy.get("grace_days", catalogs_for(db, user.org_id)["attendance_due_days"]),
            "cutoff": policy.get("cutoff", "23:59"),
            "completion_weight": float(Decimal(str(values.get("attendance_grade_completion_weight", "0.70"))))}


@router.put("/settings")
def save_settings(body: PolicyInput, user: User = Depends(administrator),
                  db: Session = Depends(get_db)):
    _scope(db, user, body.site_id)
    db.scalar(select(Organization).where(Organization.id == user.org_id).with_for_update())
    current = db.get(OrganizationSettings, user.org_id)
    if current is None:
        current = OrganizationSettings(org_id=user.org_id, values={})
        db.add(current)
    values = dict(current.values or {})
    policies = dict(values.get("attendance_policies") or {})
    old = {"site": policies.get(body.site_id),
           "completion_weight": values.get("attendance_grade_completion_weight")}
    policies[body.site_id] = {"grace_days": body.grace_days, "cutoff": body.cutoff}
    values["attendance_policies"] = policies
    values["attendance_grade_completion_weight"] = str(body.completion_weight)
    current.values = values
    audit_change(db, user, "attendance_policy", body.site_id, {"from": old,
        "to": {"site": policies[body.site_id],
               "completion_weight": str(body.completion_weight)}})
    db.commit()
    return {"ok": True, "site_id": body.site_id}


@router.get("/contractors")
def search_contractors(site_id: str, q: str = "", limit: int = 30,
                       user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    _scope(db, user, site_id)
    if not 1 <= limit <= 50:
        raise HTTPException(422, "Límite de resultados no válido")
    text = q.strip()
    if not text:
        return {"items": [], "has_more": False}
    search = "%" + text.replace("%", "\\%").replace("_", "\\_") + "%"
    query = (select(ContractorWorksite, Contractor)
        .join(Contractor, Contractor.id == ContractorWorksite.contractor_id)
        .where(ContractorWorksite.org_id == user.org_id,
               Contractor.org_id == user.org_id,
               ContractorWorksite.worksite_id == site_id,
               (Contractor.name.ilike(search, escape="\\") |
                Contractor.rut.ilike(search, escape="\\")))
        .order_by(Contractor.name).limit(limit + 1))
    found = db.execute(query).all()
    matches = found[:limit]
    company_ids = [company.id for _, company in matches]
    counts = dict(db.execute(select(
        WorkerAssignment.contractor_id, func.count(WorkerAssignment.id))
        .where(WorkerAssignment.org_id == user.org_id,
               WorkerAssignment.worksite_id == site_id,
               WorkerAssignment.contractor_id.in_(company_ids),
               WorkerAssignment.active.is_(True))
        .group_by(WorkerAssignment.contractor_id)).all()) if company_ids else {}
    return {"items": [{
        "association_id": association.id, "contractor_id": company.id, "contractor": company.name, "rut": company.rut,
        "workers": counts.get(company.id, 0), "active": association.contract_status == "active",
    } for association, company in matches], "has_more": len(found) > limit}


@router.get("/roster")
def roster(site_id: str, period: str, association_id: str | None = None,
           user: User = Depends(authorized_user),
           db: Session = Depends(get_db)):
    _scope(db, user, site_id)
    try:
        ranges = calendar_weeks(period)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if association_id:
        association, _ = association_for(db, user.org_id, association_id)
        if association.worksite_id != site_id:
            raise HTTPException(404, "Contratista no encontrado en esta obra")
    links, assignments, contracts, terms, rosters, _, _, controls, _ = _context(
        db, user.org_id, site_id, period, association_id=association_id)
    ids = [a.id for a, _ in links]
    weeks = db.scalars(select(CalendarWeek).where(
        CalendarWeek.org_id == user.org_id, CalendarWeek.period == period,
        CalendarWeek.association_id.in_(ids))).all() if ids else []
    week_map = {(w.association_id, w.week_number): w for w in weeks}
    all_entries = db.scalars(select(CalendarEntry).where(
        CalendarEntry.org_id == user.org_id,
        CalendarEntry.week_id.in_([w.id for w in weeks]))).all() if weeks else []
    entry_map = {(e.week_id, e.worker_assignment_id): e for e in all_entries}
    all_duties = db.scalars(select(CalendarDuty).where(
        CalendarDuty.org_id == user.org_id, CalendarDuty.period == period,
        CalendarDuty.association_id.in_(ids))).all() if ids else []
    duty_map = {(d.association_id, d.week_number): d for d in all_duties}
    current = utcnow()
    result = []
    for link, company in sorted(links, key=lambda item: item[1].name.casefold()):
        roster_row = rosters.get(link.id)
        included = (roster_row.status == "included" if roster_row
                    else link.contract_status == "active" and company.nature == "with_workers")
        people = assignments[company.id]
        spans = []
        signed = defaultdict(set)
        for number, (first, last) in enumerate(ranges, 1):
            days = dates_of_week(period, number)
            if not days:
                # Calendar slot contains only Saturday/Sunday: no weekly duty.
                continue
            expected = [(a, w) for a, w in people if _worker_eligible(
                a, contracts, terms, days)]
            week = week_map.get((link.id, number))
            duty = duty_map.get((link.id, number))
            deadline = _instant(duty.deadline_at) if duty else _deadline(db, user.org_id, last, site_id)
            week_entries = []
            for assignment, worker in expected:
                entry = entry_map.get((week.id, assignment.id)) if week else None
                if entry and week.state == "completed" and not entry.excluded:
                    signed[assignment.id].update(day for day in (entry.signed_dates or [])
                                                 if day in {d.isoformat() for d in days})
                week_entries.append({
                    "worker_assignment_id": assignment.id, "worker": worker.name,
                    "rut": worker.rut, "signed_dates": [day for day in (entry.signed_dates or [])
                        if day in {d.isoformat() for d in days}] if entry else [],
                    "excluded": entry.excluded if entry else False,
                    "reason": entry.reason if entry else "",
                    "recorded": entry is not None,
                })
            missing = sum(not e["recorded"] for e in week_entries)
            complete = bool(week and week.state == "completed" and missing == 0)
            if not included:
                status = "excluded"
            elif not expected:
                status = "not_required"
            elif duty and duty.exempt:
                status = "not_required"
            elif complete:
                status = "completed_on_time" if week.completed_on_time else "completed_late"
            elif week and week.migrated:
                status = "needs_legacy_review"
            elif current > deadline:
                status = "overdue"
            elif week:
                status = "draft"
            else:
                status = "pending"
            spans.append({
                "id": week.id if week else None, "week_number": number,
                "start_date": first.isoformat(), "end_date": last.isoformat(),
                "dates": [day.isoformat() for day in days], "state": status,
                "saved_state": week.state if week else "missing",
                "due_at": deadline.isoformat(),
                "completed_at": week.completed_at if week else None,
                "completed_on_time": week.completed_on_time if week else None,
                "entered_by": _name(db, week.entered_by) if week else None,
                "updated_by": _name(db, week.updated_by) if week else None,
                "completed_by": _name(db, week.completed_by) if week and week.completed_by else None,
                "notes": week.notes if week else "",
                "revision": week.revision if week else 0,
                "migrated": week.migrated if week else False,
                "missing_workers": missing,
                "assigned_to": duty.assigned_to if duty else None,
                "entries": week_entries,
            })
        people_rows = []
        for assignment, worker in people:
            payment = controls.get((link.id, assignment.id))
            attendance = len(signed[assignment.id])
            row = {"assignment_id": assignment.id, "name": worker.name,
                   "rut": worker.rut, "signed_days": attendance}
            if user.role == "admin":
                row["paid_days"] = payment.paid_days if payment else None
                row["difference"] = (attendance - payment.paid_days
                                     if payment and payment.paid_days is not None
                                     and all(w["state"] in {"completed_on_time", "completed_late", "excluded", "not_required"} for w in spans)
                                     else None)
            people_rows.append(row)
        result.append({
            "association_id": link.id, "contractor": company.name,
            "rut": company.rut, "included": included,
            "workers": people_rows, "weeks": spans,
        })
    return {"site_id": site_id, "period": period, "contractors": result,
            "week_count": sum(bool(dates_of_week(period, i))
                               for i in range(1, len(ranges) + 1))}


class EntryInput(BaseModel):
    worker_assignment_id: str
    signed_dates: list[date] = Field(default_factory=list)
    excluded: bool = False
    reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def check(self):
        if len(set(self.signed_dates)) != len(self.signed_dates):
            raise ValueError("Fecha de asistencia duplicada")
        if self.excluded and (self.signed_dates or not self.reason.strip()):
            raise ValueError("La exclusión requiere motivo y ningún día firmado")
        return self


class SaveWeek(BaseModel):
    association_id: str
    period: str
    week_number: int = Field(ge=1, le=6)
    entries: list[EntryInput] = Field(default_factory=list, max_length=5000)
    complete: bool = False
    notes: str = Field(default="", max_length=2000)
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def valid(self):
        days = set(dates_of_week(self.period, self.week_number))
        if not days:
            raise ValueError("Semana sin días laborales: sábados y domingos no generan asistencia")
        if len({r.worker_assignment_id for r in self.entries}) != len(self.entries):
            raise ValueError("Trabajador repetido")
        if any(day not in days for row in self.entries for day in row.signed_dates):
            raise ValueError("Fecha fuera de la semana")
        if any(day > today() for row in self.entries for day in row.signed_dates):
            raise ValueError("No puedes ingresar asistencia futura")
        if self.complete and max(days) > today():
            raise ValueError("La semana todavía no ha terminado")
        return self


@router.put("/weeks")
def save_week(body: SaveWeek, user: User = Depends(attendance_editor), db: Session = Depends(get_db)):
    association, company = association_for(db, user.org_id, body.association_id)
    _scope(db, user, association.worksite_id)
    if association.contract_status != "active" or company.nature != "with_workers":
        raise HTTPException(422, "Contratista no habilitado para asistencia dependiente")
    db.scalar(select(ContractorWorksite).where(
        ContractorWorksite.id == association.id).with_for_update())
    duty = db.scalar(select(CalendarDuty).where(
        CalendarDuty.org_id == user.org_id, CalendarDuty.association_id == association.id,
        CalendarDuty.period == body.period, CalendarDuty.week_number == body.week_number))
    if duty and duty.exempt:
        raise HTTPException(409, "La semana está justificada como no exigible")
    if user.role == "administrative" and duty and duty.assigned_to != user.id:
        raise HTTPException(403, "El registro semanal fue asignado a otro administrativo")
    expected = {a.id for a, _ in _eligible(db, user, association, body.period, body.week_number)}
    supplied = {e.worker_assignment_id for e in body.entries}
    if not supplied <= expected or body.complete and supplied != expected:
        raise HTTPException(422, "Faltan trabajadores exigibles o hay asignaciones ajenas")
    first, last = calendar_weeks(body.period)[body.week_number - 1]
    now = utcnow()
    deadline = _instant(duty.deadline_at) if duty else _deadline(db, user.org_id, last, association.worksite_id)
    week = db.scalar(select(CalendarWeek).where(
        CalendarWeek.org_id == user.org_id, CalendarWeek.association_id == association.id,
        CalendarWeek.period == body.period, CalendarWeek.week_number == body.week_number
    ).with_for_update())
    if (week.revision if week else 0) != body.revision:
        raise HTTPException(409, "El registro fue modificado por otra persona. Actualiza antes de guardar")
    first_completion = not week or week.completed_at is None
    if body.complete and first_completion and now > deadline and len(body.notes.strip()) < 10:
        raise HTTPException(422, "Registro fuera de plazo: explica el motivo (mínimo 10 caracteres)")
    if week is None:
        week = CalendarWeek(org_id=user.org_id, association_id=association.id,
            period=body.period, week_number=body.week_number, start_date=first, end_date=last,
            entered_by=user.id, updated_by=user.id, deadline_at=deadline)
        db.add(week)
        db.flush()
    before = {"state": week.state, "revision": week.revision}
    old_entries = {e.worker_assignment_id: e for e in db.scalars(select(CalendarEntry).where(
        CalendarEntry.org_id == user.org_id, CalendarEntry.week_id == week.id))}
    changes = []
    for item in body.entries:
        row = old_entries.get(item.worker_assignment_id)
        snapshot = {"dates": list(row.signed_dates), "excluded": row.excluded, "reason": row.reason} if row else None
        if row is None:
            row = CalendarEntry(org_id=user.org_id, week_id=week.id,
                worker_assignment_id=item.worker_assignment_id, updated_by=user.id)
            db.add(row)
        # Historical weekend signatures remain available as evidence, even when
        # the new Monday-Friday editor cannot display or edit those dates.
        # This preserves original data; compliance totals use weekdays only.
        historical_nonworkdays = [
            stored for stored in (row.signed_dates or [])
            if date.fromisoformat(stored).weekday() >= 5
            and first <= date.fromisoformat(stored) <= last
        ]
        row.signed_dates = sorted(set(
            [day.isoformat() for day in item.signed_dates] + historical_nonworkdays
        ))
        row.excluded, row.reason = item.excluded, item.reason.strip()
        row.updated_at, row.updated_by = now, user.id
        after = {"dates": row.signed_dates, "excluded": row.excluded, "reason": row.reason}
        if snapshot != after:
            changes.append({"worker_assignment_id": item.worker_assignment_id,
                            "from": snapshot, "to": after})
    week.state = "completed" if body.complete else "draft"
    week.notes, week.updated_by, week.updated_at = body.notes.strip(), user.id, now
    week.deadline_at = deadline
    if body.complete and first_completion:
        week.completed_by, week.completed_at = user.id, now
        week.completed_on_time = now <= deadline
    week.revision += 1
    if changes or before["state"] != week.state:
        # A newly completed/corrected attendance week can change the legal
        # payment comparison. Preserve paid days, but require admin re-review.
        controls = db.scalars(select(ContributionControl).where(
            ContributionControl.org_id == user.org_id,
            ContributionControl.association_id == association.id,
            ContributionControl.period == body.period,
            ContributionControl.worker_assignment_id.in_(expected)
        ).with_for_update()).all() if expected else []
        for control in controls:
            prior = {"review": control.review_status,
                     "retention": control.retention_status}
            control.review_status = "pending"
            control.retention_status = "none"
            control.reviewer_id = None
            control.updated_at = now
            for finding in db.scalars(select(PaymentFinding).where(
                PaymentFinding.org_id == user.org_id,
                PaymentFinding.control_id == control.id)).all():
                finding.state = "unverified"
                finding.reviewed_at = now
                finding.reviewed_by = user.id
            audit_change(db, user, "contribution_control", control.id, {
                "invalidated_by_attendance_week": week.id, "from": prior,
                "to": {"review": "pending", "retention": "none"},
            })
    audit_change(db, user, "attendance_calendar_week", week.id,
        {"from": before, "to": {"state": week.state, "revision": week.revision},
         "changes": changes, "late": bool(body.complete and not week.completed_on_time),
         "reason": week.notes, "due_at": deadline.isoformat()})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe otro registro de esta semana. Actualiza los datos") from None
    return {"id": week.id, "state": week.state, "revision": week.revision,
            "completed_at": week.completed_at, "completed_on_time": week.completed_on_time}


class DutyGeneration(BaseModel):
    site_id: str
    period: str
    user_id: str


@router.post("/duties/generate")
def generate_duties(body: DutyGeneration, user: User = Depends(administrator),
                    db: Session = Depends(get_db)):
    _scope(db, user, body.site_id)
    _role(db, user, body.user_id)
    if body.site_id not in assigned_sites(db, db.get(User, body.user_id)):
        raise HTTPException(422, "El administrativo no está asignado a esa obra")
    ranges = calendar_weeks(body.period)
    db.scalar(select(ContractorWorksite).where(
        ContractorWorksite.org_id == user.org_id,
        ContractorWorksite.worksite_id == body.site_id).order_by(ContractorWorksite.id).limit(1).with_for_update())
    links, assignments, contracts, terms, rosters, _, _, _, _ = _context(
        db, user.org_id, body.site_id, body.period)
    created = 0
    for association, company in links:
        if association.contract_status != "active" or company.nature != "with_workers":
            continue
        current_roster = rosters.get(association.id)
        if current_roster and current_roster.status == "excluded":
            continue
        for number, (_, last) in enumerate(ranges, 1):
            days = dates_of_week(body.period, number)
            if not days:
                continue
            expected_ids = [a.id for a, _ in assignments[company.id]
                            if _worker_eligible(a, contracts, terms, days)]
            if not expected_ids:
                continue
            existing = db.scalar(select(CalendarDuty.id).where(
                CalendarDuty.org_id == user.org_id, CalendarDuty.association_id == association.id,
                CalendarDuty.period == body.period, CalendarDuty.week_number == number))
            if existing:
                continue
            db.add(CalendarDuty(org_id=user.org_id, association_id=association.id,
                worksite_id=body.site_id, period=body.period, week_number=number,
                assigned_to=body.user_id, created_by=user.id, expected_workers=expected_ids,
                deadline_at=_deadline(db, user.org_id, last, body.site_id)))
            created += 1
    audit_change(db, user, "attendance_duties", body.site_id,
                 {"period": body.period, "assigned_to": body.user_id, "created": created})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Las obligaciones fueron asignadas simultáneamente; vuelve a consultar") from None
    return {"created": created, "period": body.period, "site_id": body.site_id}


class DutyEdit(BaseModel):
    assigned_to: str | None = None
    exempt: bool = False
    exemption_reason: str = Field(default="", max_length=1000)


@router.patch("/duties/{duty_id}")
def edit_duty(duty_id: str, body: DutyEdit,
              user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = db.scalar(select(CalendarDuty).where(
        CalendarDuty.id == duty_id, CalendarDuty.org_id == user.org_id).with_for_update())
    if not row:
        raise HTTPException(404, "Obligación no encontrada")
    if body.exempt and not body.exemption_reason.strip():
        raise HTTPException(422, "Explica la exención")
    target = body.assigned_to or row.assigned_to
    _role(db, user, target)
    if row.worksite_id not in assigned_sites(db, db.get(User, target)):
        raise HTTPException(422, "Administrativo sin autorización en la obra")
    old = {"assigned_to": row.assigned_to, "exempt": row.exempt,
           "reason": row.exemption_reason}
    row.assigned_to, row.exempt = target, body.exempt
    row.exemption_reason = body.exemption_reason.strip()
    audit_change(db, user, "attendance_duty", row.id, {"from": old,
        "to": {"assigned_to": target, "exempt": row.exempt, "reason": row.exemption_reason}})
    db.commit()
    return {"id": row.id, "assigned_to": target, "exempt": row.exempt}


def _assessment(db, org_id, period, person_id):
    duties = [d for d in db.scalars(select(CalendarDuty).where(
        CalendarDuty.org_id == org_id, CalendarDuty.period == period,
        CalendarDuty.assigned_to == person_id).order_by(CalendarDuty.id)).all()
        if dates_of_week(period, d.week_number)]
    keys = {(row.association_id, row.week_number) for row in duties}
    weeks = db.scalars(select(CalendarWeek).where(
        CalendarWeek.org_id == org_id, CalendarWeek.period == period,
        CalendarWeek.association_id.in_([k[0] for k in keys]))).all() if keys else []
    indexed = {(w.association_id, w.week_number): w for w in weeks}
    collected = db.scalars(select(CalendarEntry).where(
        CalendarEntry.org_id == org_id,
        CalendarEntry.week_id.in_([w.id for w in weeks]))).all() if weeks else []
    present = defaultdict(set)
    for record in collected:
        present[record.week_id].add(record.worker_assignment_id)
    required = [d for d in duties if not d.exempt]
    def done(duty):
        week = indexed.get((duty.association_id, duty.week_number))
        return bool(week and week.state == "completed" and week.completed_at is not None
                    and set(duty.expected_workers or []).issubset(present[week.id]))
    completed = [d for d in required if done(d)]
    punctual = [d for d in completed if _instant(
        indexed[(d.association_id, d.week_number)].completed_at) <= _instant(d.deadline_at)]
    weight = Decimal(str(_settings(db, org_id).get("attendance_grade_completion_weight", "0.70")))
    values = grade(len(completed), len(punctual), len(required), completion_weight=weight)
    values["completion_weight"] = float(weight)
    # Access is visible to the admin but never contributes to the grade.
    month_start = calendar_weeks(period)[0][0]
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    first_utc = datetime.combine(month_start, datetime.min.time(), CL_TZ).astimezone(timezone.utc)
    last_utc = datetime.combine(next_month, datetime.min.time(), CL_TZ).astimezone(timezone.utc)
    login_count, last_login = db.execute(select(
        func.count(AuditEvent.id), func.max(AuditEvent.created_at)).where(
        AuditEvent.org_id == org_id, AuditEvent.user_id == person_id,
        AuditEvent.action == "login", AuditEvent.created_at >= first_utc,
        AuditEvent.created_at < last_utc)).one()
    values["login_count"] = int(login_count)
    values["last_login_at"] = last_login.isoformat() if last_login else None
    values["overdue"] = sum(
        d not in completed and utcnow() > _instant(d.deadline_at) for d in required)
    values["delivered_late"] = len(completed) - len(punctual)
    values["exempt"] = len(duties) - len(required)
    companies = dict(db.execute(
        select(ContractorWorksite.id, Contractor.name)
        .join(Contractor, Contractor.id == ContractorWorksite.contractor_id)
        .where(ContractorWorksite.org_id == org_id,
               Contractor.org_id == org_id,
               ContractorWorksite.id.in_([d.association_id for d in duties]))
    ).all()) if duties else {}
    values["duties"] = [{
        "id": d.id, "association_id": d.association_id,
        "contractor": companies.get(d.association_id, "Contratista sin nombre"),
        "week_number": d.week_number,
        "deadline_at": d.deadline_at.isoformat(), "exempt": d.exempt,
        "completed_at": indexed[(d.association_id, d.week_number)].completed_at.isoformat()
                        if d in completed else None
    } for d in duties]
    return values


@router.get("/evaluations")
def evaluations(period: str, user_id: str | None = None,
                user: User = Depends(administrator), db: Session = Depends(get_db)):
    calendar_weeks(period)
    users = [db.get(User, user_id)] if user_id else db.scalars(select(User).where(
        User.org_id == user.org_id, User.role == "administrative")).all()
    result = []
    for target in users:
        if target is None or target.org_id != user.org_id:
            raise HTTPException(404, "Usuario no encontrado")
        values = _assessment(db, user.org_id, period, target.id)
        last = db.scalar(select(MonthlyAssessment).where(
            MonthlyAssessment.org_id == user.org_id, MonthlyAssessment.period == period,
            MonthlyAssessment.user_id == target.id).order_by(
            MonthlyAssessment.revision.desc()).limit(1))
        result.append({"user_id": target.id, "name": _name(db, target.id), **values,
            "approved": ({"revision": last.revision, "grade": float(last.grade_value)
                          if last.grade_value is not None else None,
                          "approved_at": last.approved_at, "observations": last.observations}
                         if last else None)})
    return {"period": period, "rows": result}


class FinalizeInput(BaseModel):
    period: str
    user_id: str
    observations: str = Field(default="", max_length=2000)


@router.post("/evaluations/finalize")
def finalize(body: FinalizeInput, user: User = Depends(administrator),
             db: Session = Depends(get_db)):
    calendar_weeks(body.period)
    target = db.scalar(select(User).where(
        User.id == body.user_id, User.org_id == user.org_id))
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    values = _assessment(db, user.org_id, body.period, body.user_id)
    if values["required"] == 0:
        raise HTTPException(422, "No hay obligaciones exigibles: sin evaluación")
    if any(utcnow() <= datetime.fromisoformat(d["deadline_at"]) and not d["exempt"]
           for d in values["duties"]):
        raise HTTPException(409, "Debes esperar al vencimiento del último plazo semanal")
    latest = db.scalar(select(func.max(MonthlyAssessment.revision)).where(
        MonthlyAssessment.org_id == user.org_id, MonthlyAssessment.period == body.period,
        MonthlyAssessment.user_id == body.user_id)) or 0
    assessment = MonthlyAssessment(org_id=user.org_id, period=body.period,
        user_id=body.user_id, revision=latest + 1,
        metrics=values, grade_value=Decimal(str(values["grade"])),
        observations=body.observations.strip(), approved_by=user.id)
    db.add(assessment)
    db.flush()
    audit_change(db, user, "attendance_assessment", assessment.id,
        {"period": body.period, "name": _name(db, body.user_id),
         "revision": assessment.revision, "grade": values["grade"]})
    db.commit()
    return {"id": assessment.id, "revision": assessment.revision, "grade": values["grade"]}


# V9.2: Vista administrativa unificada, de solo lectura, sin tablas paralelas.
# Conserva la lógica semanal v8.1/v9.1 y su evidencia histórica.
@router.get("/overview")
def operational_overview(site_id: str, period: str, as_of: date | None = None,
                         user: User = Depends(authorized_user),
                         db: Session = Depends(get_db)):
    """Contratistas, cumplimiento semanal y estado contractual/finiquitos por obra.

    'as_of' permite consultar la vigencia documental a una fecha histórica. Un
    contrato vencido no equivale a término: requiere confirmación humana.
    """
    from .control_models import ContractRegister
    from .ops_models import Worker
    from .platform_models import WorkerTermination

    _scope(db, user, site_id)
    # El roster valida el período y calcula plazos/obligaciones sin reescribir firmas.
    attendance = roster(site_id=site_id, period=period, association_id=None,
                        user=user, db=db)
    snapshot = as_of or today()
    links = {row.contractor_id: row for row in db.scalars(
        select(ContractorWorksite).where(
            ContractorWorksite.org_id == user.org_id,
            ContractorWorksite.worksite_id == site_id)).all()}
    assignments = db.execute(select(WorkerAssignment, Worker).join(
        Worker, Worker.id == WorkerAssignment.worker_id).where(
            WorkerAssignment.org_id == user.org_id,
            Worker.org_id == user.org_id,
            WorkerAssignment.worksite_id == site_id)).all()
    assignment_ids = [a.id for a, _ in assignments]
    histories = defaultdict(list)
    if assignment_ids:
        for contract in db.scalars(select(ContractRegister).where(
                ContractRegister.org_id == user.org_id,
                ContractRegister.worker_assignment_id.in_(assignment_ids))).all():
            histories[contract.worker_assignment_id].append(contract)
    contract_ids = [c.id for rows in histories.values() for c in rows]
    terms = {}
    if contract_ids:
        terms = {t.contract_id: t for t in db.scalars(
            select(WorkerTermination).where(
                WorkerTermination.org_id == user.org_id,
                WorkerTermination.contract_id.in_(contract_ids))).all()}
    options = catalogs_for(db, user.org_id)
    alert_days = options.get("expiry_alert_days") or [30]
    notice_days = max(int(value) for value in alert_days)
    termination_days = options.get("termination_due_days")
    people_by_contractor = defaultdict(list)
    for assignment, worker in assignments:
        available = [c for c in histories[assignment.id] if c.start_date <= snapshot]
        contract = max(available, key=lambda c: (c.start_date, c.created_at, c.id)) if available else None
        term = terms.get(contract.id) if contract else None
        ended = bool(term and term.effective_date <= snapshot)
        if not contract:
            labor_state = "por_verificar"
        elif ended:
            labor_state = "terminado"
        elif (contract.status not in ("active", "ended")
              or (contract.status == "ended" and not (term and snapshot < term.effective_date))
              or (snapshot >= today() and not assignment.active)):
            labor_state = "por_verificar"
        elif contract.end_date and contract.end_date < snapshot:
            labor_state = "vencido"
        elif contract.end_date and contract.end_date <= snapshot + timedelta(days=notice_days):
            labor_state = "por_vencer"
        else:
            labor_state = "vigente"
        finiquito_state = (term.review_state or "missing") if ended else "not_applicable"
        finiquito_overdue = bool(
            ended and finiquito_state == "missing"
            and termination_days is not None
            and snapshot > term.effective_date + timedelta(days=int(termination_days))
        )
        people_by_contractor[assignment.contractor_id].append({
            "assignment_id": assignment.id,
            "name": worker.name, "rut": worker.rut,
            "contract_id": contract.id if contract else None,
            "contract_type": contract.contract_type if contract else None,
            "start_date": contract.start_date.isoformat() if contract else None,
            "end_date": contract.end_date.isoformat() if contract and contract.end_date else None,
            "labor_state": labor_state,
            "termination_date": term.effective_date.isoformat() if ended else None,
            "finiquito_state": finiquito_state,
            "finiquito_overdue": finiquito_overdue,
        })
    rows = []
    for item in attendance["contractors"]:
        association = next(
            (a for a in links.values() if a.id == item["association_id"]), None)
        # El contratista puede estar activo aun sin trabajadores vigentes.
        if association is None:
            continue
        current_people = sorted(people_by_contractor[association.contractor_id],
                                key=lambda worker: worker["name"].casefold())
        status_counts = {key: sum(p["labor_state"] == key for p in current_people)
                         for key in ("vigente", "por_vencer", "vencido",
                                     "terminado", "por_verificar")}
        pending_finiquitos = sum(
            p["labor_state"] == "terminado"
            and p["finiquito_state"] != "approved" for p in current_people)
        rows.append({
            "association_id": association.id,
            "contractor": item["contractor"], "rut": item["rut"],
            "contractor_active": association.contract_status == "active",
            "contractor_status": association.contract_status,
            "attendance_applicable": item["included"],
            "weeks": [{key: value for key, value in w.items()
                       if key not in {"entries"}}
                      for w in item["weeks"]],
            "staff": current_people,
            "staff_counts": status_counts,
            "pending_finiquitos": pending_finiquitos,
            "overdue_finiquitos": sum(p["finiquito_overdue"] for p in current_people),
        })
    rows.sort(key=lambda item: item["contractor"].casefold())
    active = [r for r in rows if r["contractor_active"]]
    applicable_weeks = [w for r in active if r["attendance_applicable"]
                        for w in r["weeks"] if w["state"] not in ("excluded", "not_required")]
    return {
        "site_id": site_id, "period": period, "as_of": snapshot.isoformat(),
        "week_count": attendance["week_count"], "contractors": rows,
        "summary": {
            "active_contractors": len(active),
            "workers_vigente": sum(r["staff_counts"]["vigente"] +
                                   r["staff_counts"]["por_vencer"] for r in active),
            "workers_por_verificar": sum(r["staff_counts"]["por_verificar"] for r in active),
            "contracts_ending": sum(r["staff_counts"]["por_vencer"] for r in active),
            "contracts_expired": sum(r["staff_counts"]["vencido"] for r in active),
            "pending_finiquitos": sum(r["pending_finiquitos"] for r in active),
            "overdue_finiquitos": sum(r["overdue_finiquitos"] for r in active),
            "attendance_done": sum(w["state"] in ("completed_on_time", "completed_late")
                                    for w in applicable_weeks),
            "attendance_late": sum(w["state"] == "completed_late" for w in applicable_weeks),
            "attendance_overdue": sum(w["state"] == "overdue" for w in applicable_weeks),
            "attendance_pending": sum(w["state"] in ("pending", "draft", "needs_legacy_review")
                                       for w in applicable_weeks),
        },
    }


@router.get("/my-evaluation")
def my_monthly_evaluation(period: str, user: User = Depends(authorized_user),
                          db: Session = Depends(get_db)):
    """La administrativa ve solo su evaluación; aprobación/cierre sigue siendo de admin."""
    try:
        calendar_weeks(period)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if user.role != "administrative":
        raise HTTPException(403, "La evaluación personal es exclusiva del perfil Administrativo")
    values = _assessment(db, user.org_id, period, user.id)
    # Solo obligaciones propias; el detalle de acceso no forma parte de la nota.
    return {key: values[key] for key in (
        "required", "completed", "punctual", "overdue",
        "delivered_late", "exempt", "grade", "duties"
    )}
