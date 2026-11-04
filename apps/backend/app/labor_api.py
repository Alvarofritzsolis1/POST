"""Worker-first labor register: contracts, actual terminations and finiquito review."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .admin_api import catalogs_for
from .control_api import monthly_matrix, today
from .control_models import ContractAmendment, ContractRegister, ContributionControl
from .db import get_db
from .models import Document, Organization, User, utcnow
from .ops_api import association_for, assignment_for, audit_change, clean_name, normalize_rut, site_for
from .ops_models import Contractor, ContractorWorksite, OpsChange, Worker, WorkerAssignment, Worksite
from .platform_models import ContractAttachment, PaymentFinding, WorkerTermination
from .security import authorized_user, contract_entry_editor, document_reviewer, editor

router = APIRouter(prefix="/api/v1/labor", tags=["Trabajadores y finiquitos"])


class ContractData(BaseModel):
    contract_type: str = Field(min_length=2, max_length=24)
    start_date: date
    end_date: date | None = None
    status: Literal["active", "suspended"] = "active"
    notes: str = Field(default="", max_length=2000)
    document_id: str | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("Fecha pactada anterior al inicio")
        if self.contract_type == "fixed_term" and self.end_date is None:
            raise ValueError("Plazo fijo requiere fecha de término pactada")
        return self


class WorkerIntake(BaseModel):
    site_id: str
    contractor_id: str
    name: str = Field(min_length=2, max_length=180)
    rut: str
    contract: ContractData

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return clean_name(value)

    @field_validator("rut")
    @classmethod
    def valid_rut(cls, value):
        normalized = normalize_rut(value)
        if not normalized:
            raise ValueError("RUT obligatorio")
        return normalized


class WorkerEdit(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    rut: str | None = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return clean_name(value) if value is not None else value

    @field_validator("rut")
    @classmethod
    def valid_rut(cls, value):
        normalized = normalize_rut(value)
        if not normalized:
            raise ValueError("RUT obligatorio")
        return normalized


class ContractCreate(ContractData):
    assignment_id: str


class ContractEdit(BaseModel):
    contract_type: str | None = Field(default=None, min_length=2, max_length=24)
    end_date: date | None = None
    status: Literal["active", "suspended"] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class AmendmentInput(BaseModel):
    amendment_date: date
    new_end_date: date | None = None
    reference: str = Field(min_length=2, max_length=160)
    notes: str = Field(default="", max_length=2000)
    document_id: str | None = None


class AttachmentInput(BaseModel):
    document_id: str
    kind: Literal["contract", "amendment"] = "contract"


class TerminationInput(BaseModel):
    effective_date: date
    cause: str = Field(min_length=2, max_length=80)
    ratification_mode: Literal["unrecorded", "electronic", "notary", "labor_inspection", "other"] = "unrecorded"
    issued_at: date | None = None
    signed_at: date | None = None
    observation: str = Field(default="", max_length=2000)


class FiniquitoDocument(BaseModel):
    document_id: str
    issued_at: date | None = None
    signed_at: date | None = None
    ratification_mode: Literal["unrecorded", "electronic", "notary", "labor_inspection", "other"] = "unrecorded"


class ReviewFiniquito(BaseModel):
    state: Literal["approved", "observed", "rejected"]
    observation: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def reason(self):
        if self.state != "approved" and not self.observation.strip():
            raise ValueError("Indica el motivo de la observación o rechazo")
        return self


class PaymentFindingInput(BaseModel):
    state: Literal["unverified", "declared_unpaid", "insufficient", "verified"]
    document_id: str | None = None
    documented_amount: int | None = Field(default=None, ge=0)
    expected_amount: int | None = Field(default=None, ge=0)
    observation: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def evidence(self):
        if self.state != "unverified" and (not self.document_id or not self.observation.strip()):
            raise ValueError("Una conclusión de pago requiere documento y motivo de revisión")
        if self.state == "insufficient" and (self.documented_amount is not None and
                self.expected_amount is not None and self.documented_amount >= self.expected_amount):
            raise ValueError("El monto documentado no es inferior al esperado")
        return self


def _contract_type(db, org_id, kind):
    allowed = {"indefinite", "fixed_term", "project", "services"} | set(catalogs_for(db, org_id)["extra_contract_types"])
    if kind not in allowed:
        raise HTTPException(422, "Tipo contractual no configurado")


def _document(db, user, doc_id):
    doc = db.scalar(select(Document).where(Document.id == doc_id, Document.org_id == user.org_id))
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    if not doc.original_name.lower().endswith(".pdf"):
        raise HTTPException(422, "El contrato o finiquito requiere PDF")
    return doc


def _contract(db, user, contract_id, lock=False):
    query = select(ContractRegister).where(ContractRegister.id == contract_id,
                                            ContractRegister.org_id == user.org_id)
    row = db.scalar(query.with_for_update() if lock else query)
    if not row or row.worker_assignment_id is None:
        raise HTTPException(404, "Contrato laboral no encontrado")
    return row


def _create_contract(db, user, assignment, association, payload):
    _contract_type(db, user.org_id, payload.contract_type)
    if payload.document_id:
        _document(db, user, payload.document_id)
    previous = db.scalars(select(ContractRegister).where(
        ContractRegister.org_id == user.org_id,
        ContractRegister.worker_assignment_id == assignment.id,
        ContractRegister.status.in_(("active", "suspended")),
    ).with_for_update()).all()
    if previous:
        raise HTTPException(409, "Existe un contrato vigente; registra su término efectivo antes de iniciar otro")
    row = ContractRegister(org_id=user.org_id, association_id=association.id,
                           worker_assignment_id=assignment.id, contract_type=payload.contract_type,
                           start_date=payload.start_date, end_date=payload.end_date,
                           status=payload.status, notes=payload.notes.strip(),
                           created_by=user.id, updated_by=user.id)
    db.add(row)
    db.flush()
    if payload.document_id:
        db.add(ContractAttachment(org_id=user.org_id, contract_id=row.id,
                                  document_id=payload.document_id, kind="contract", created_by=user.id))
    assignment.active = payload.status == "active"
    audit_change(db, user, "contract", row.id, {"created": {
        "assignment_id": assignment.id, "contract_type": row.contract_type,
        "start_date": str(row.start_date), "end_date": str(row.end_date) if row.end_date else None,
        "status": row.status, "document_id": payload.document_id}})
    return row


def _registry_query(org_id, site_id=None, contractor_id=None, search=None,
                    labor_state=None, contract_type=None, upcoming=False, finiquito_pending=False,
                    max_days=30):
    newest = (select(ContractRegister.id).where(
        ContractRegister.org_id == org_id,
        ContractRegister.worker_assignment_id == WorkerAssignment.id,
    ).order_by(ContractRegister.start_date.desc(), ContractRegister.created_at.desc(),
               ContractRegister.id.desc()).limit(1).correlate(WorkerAssignment).scalar_subquery())
    now = today()
    ended = and_(WorkerTermination.id.is_not(None), WorkerTermination.effective_date <= now)
    state = case(
        (ended, "ended"),
        (ContractRegister.id.is_(None), "observed"),
        (ContractRegister.status == "ended", "observed"),
        (ContractRegister.status == "suspended", "observed"),
        (and_(ContractRegister.end_date.is_not(None), ContractRegister.end_date < now), "expired_needs_review"),
        (and_(ContractRegister.end_date.is_not(None), ContractRegister.end_date <= now + timedelta(days=max_days)), "ending_soon"),
        else_="active",
    ).label("labor_state")
    finiquito = case(
        (ended, func.coalesce(WorkerTermination.review_state, "missing")),
        else_="not_applicable",
    ).label("finiquito_state")
    query = (select(
        WorkerAssignment.id.label("assignment_id"), Worker.id.label("worker_id"),
        Worker.name.label("worker_name"), Worker.rut.label("worker_rut"),
        Contractor.id.label("contractor_id"), Contractor.name.label("contractor_name"),
        Worksite.id.label("site_id"), Worksite.name.label("site_name"),
        ContractRegister.id.label("contract_id"), ContractRegister.contract_type,
        ContractRegister.start_date, ContractRegister.end_date,
        ContractRegister.status.label("contract_status"),
        WorkerTermination.id.label("termination_id"), WorkerTermination.effective_date,
        WorkerTermination.document_id.label("finiquito_document_id"),
        state, finiquito,
    ).select_from(WorkerAssignment)
        .join(Worker, and_(Worker.id == WorkerAssignment.worker_id, Worker.org_id == org_id))
        .join(Contractor, and_(Contractor.id == WorkerAssignment.contractor_id, Contractor.org_id == org_id))
        .join(Worksite, and_(Worksite.id == WorkerAssignment.worksite_id, Worksite.org_id == org_id))
        .outerjoin(ContractRegister, ContractRegister.id == newest)
        .outerjoin(WorkerTermination, and_(WorkerTermination.contract_id == ContractRegister.id,
                                           WorkerTermination.org_id == org_id))
        .where(WorkerAssignment.org_id == org_id))
    if site_id:
        query = query.where(Worksite.id == site_id)
    if contractor_id:
        query = query.where(Contractor.id == contractor_id)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(or_(func.lower(Worker.name).like(term), Worker.rut.like(term)))
    if labor_state:
        query = query.where(state == labor_state)
    if contract_type:
        query = query.where(ContractRegister.contract_type == contract_type)
    if upcoming:
        query = query.where(state == "ending_soon")
    if finiquito_pending:
        query = query.where(ended, WorkerTermination.review_state != "approved")
    return query


def _registry(db, user, site_id=None, contractor_id=None, search=None, labor_state=None,
              contract_type=None, upcoming=False, finiquito_pending=False, page=1, page_size=50):
    if site_id:
        site_for(db, user.org_id, site_id)
    max_days = max(catalogs_for(db, user.org_id)["expiry_alert_days"])
    query = _registry_query(user.org_id, site_id, contractor_id, search, labor_state,
                            contract_type, upcoming, finiquito_pending, max_days)
    derived = query.subquery()
    counts = db.execute(select(
        func.count().label("total"),
        func.sum(case((derived.c.labor_state == "active", 1), else_=0)).label("active"),
        func.sum(case((derived.c.labor_state == "ending_soon", 1), else_=0)).label("ending_soon"),
        func.sum(case((derived.c.labor_state == "expired_needs_review", 1), else_=0)).label("expired"),
        func.sum(case((derived.c.labor_state == "ended", 1), else_=0)).label("ended"),
        func.sum(case((and_(derived.c.labor_state == "ended",
                            derived.c.finiquito_state != "approved"), 1), else_=0)).label("finiquito_pending"),
    ).select_from(derived)).mappings().one()
    rows = db.execute(query.order_by(Worker.name, Worker.rut, WorkerAssignment.id)
                      .limit(page_size).offset((page - 1) * page_size)).mappings().all()
    alert_days = catalogs_for(db, user.org_id)["expiry_alert_days"]
    result = []
    for row in rows:
        data = dict(row)
        if data["labor_state"] == "expired_needs_review":
            data["severity"] = "red"
            data["alert"] = "Contrato vencido sin regularización; confirmar continuidad o término"
        elif data["labor_state"] == "ending_soon":
            days = (data["end_date"] - today()).days
            threshold = min((d for d in alert_days if days <= d), default=max(alert_days))
            data["severity"] = "orange"
            data["alert"] = f"Contrato vence en {days} días (umbral {threshold})"
        elif data["finiquito_state"] in {"missing", "delivered", "observed", "rejected"}:
            due = catalogs_for(db, user.org_id)["termination_due_days"]
            is_overdue = due is not None and data["effective_date"] and today() > data["effective_date"] + timedelta(days=due) and data["finiquito_state"] == "missing"
            data["severity"] = "red" if is_overdue else "orange"
            data["alert"] = "Finiquito pendiente de entrega o revisión"
        elif data["labor_state"] == "active":
            data["severity"], data["alert"] = "green", "Contrato vigente"
        else:
            data["severity"], data["alert"] = "gray", "Registro histórico o sin información suficiente"
        result.append(data)
    return {"rows": result, "page": page, "page_size": page_size,
            "summary": {key: int(value or 0) for key, value in counts.items()}}


@router.get("/workers")
def workers(site_id: str | None = None, contractor_id: str | None = None,
            search: str | None = Query(None, max_length=100),
            labor_state: Literal["active", "ending_soon", "expired_needs_review", "ended", "observed"] | None = None,
            contract_type: str | None = None, upcoming: bool = False,
            finiquito_pending: bool = False, page: int = Query(1, ge=1),
            page_size: int = Query(50, ge=1, le=100),
            user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    return _registry(db, user, site_id, contractor_id, search, labor_state,
                     contract_type, upcoming, finiquito_pending, page, page_size)


@router.get("/contractors")
def contractor_options(site_id: str | None = None, user: User = Depends(authorized_user),
                       db: Session = Depends(get_db)):
    if site_id:
        site_for(db, user.org_id, site_id)
    query = select(ContractorWorksite, Contractor).join(
        Contractor, and_(Contractor.id == ContractorWorksite.contractor_id,
                         Contractor.org_id == user.org_id)).where(
        ContractorWorksite.org_id == user.org_id)
    if site_id:
        query = query.where(ContractorWorksite.worksite_id == site_id)
    return [{"id": link.id, "site_id": link.worksite_id, "contractor_id": company.id,
             "name": company.name, "nature": company.nature}
            for link, company in db.execute(query.order_by(Contractor.name)).all()]


@router.post("/workers", status_code=201)
def create_worker(body: WorkerIntake, user: User = Depends(contract_entry_editor), db: Session = Depends(get_db)):
    if user.role == "administrative":
        from .network_service import assigned_sites
        if body.site_id not in assigned_sites(db, user):
            raise HTTPException(403, "No tienes permiso para registrar trabajadores en esta obra")
        if body.contract.document_id:
            raise HTTPException(422, "El registro de contratos no admite archivos adjuntos")
    association, company = association_for(db, user.org_id, db.scalar(select(ContractorWorksite.id).where(
        ContractorWorksite.org_id == user.org_id,
        ContractorWorksite.contractor_id == body.contractor_id,
        ContractorWorksite.worksite_id == body.site_id,
    )) or "")
    if company.nature == "independent":
        raise HTTPException(422, "Un independiente no admite trabajadores dependientes")
    db.scalar(select(Organization).where(Organization.id == user.org_id).with_for_update())
    worker = db.scalar(select(Worker).where(Worker.org_id == user.org_id, Worker.rut == body.rut))
    if worker and worker.name.casefold() != body.name.casefold():
        raise HTTPException(409, "RUT existente con nombre distinto; revisa identidad")
    if worker is None:
        worker = Worker(org_id=user.org_id, name=body.name, rut=body.rut)
        db.add(worker)
        db.flush()
    assignment = db.scalar(select(WorkerAssignment).where(
        WorkerAssignment.org_id == user.org_id, WorkerAssignment.worker_id == worker.id,
        WorkerAssignment.worksite_id == body.site_id,
        WorkerAssignment.contractor_id == body.contractor_id))
    if assignment:
        raise HTTPException(409, "La persona ya está asignada; registra un nuevo contrato en su ficha")
    assignment = WorkerAssignment(org_id=user.org_id, worker_id=worker.id,
                                  contractor_id=body.contractor_id, worksite_id=body.site_id)
    db.add(assignment)
    db.flush()
    contract = _create_contract(db, user, assignment, association, body.contract)
    audit_change(db, user, "worker", worker.id, {"created": {"assignment_id": assignment.id}})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "RUT o asignación duplicada; recarga los datos") from None
    return {"assignment_id": assignment.id, "worker_id": worker.id, "contract_id": contract.id}


@router.post("/contracts", status_code=201)
def create_contract(body: ContractCreate, user: User = Depends(contract_entry_editor), db: Session = Depends(get_db)):
    assignment, _ = assignment_for(db, user.org_id, body.assignment_id)
    if user.role == "administrative":
        from .network_service import assigned_sites
        if assignment.worksite_id not in assigned_sites(db, user):
            raise HTTPException(403, "No tienes permiso para registrar contratos en esta obra")
        if body.document_id:
            raise HTTPException(422, "El registro de contratos no admite archivos adjuntos")
    association = db.scalar(select(ContractorWorksite).where(
        ContractorWorksite.org_id == user.org_id,
        ContractorWorksite.contractor_id == assignment.contractor_id,
        ContractorWorksite.worksite_id == assignment.worksite_id))
    if not association:
        raise HTTPException(409, "Asignación sin relación con contratista y obra")
    db.scalar(select(Organization).where(Organization.id == user.org_id).with_for_update())
    row = _create_contract(db, user, assignment, association, body)
    db.commit()
    return {"id": row.id, "assignment_id": assignment.id}


@router.patch("/workers/{assignment_id}")
def edit_worker(assignment_id: str, body: WorkerEdit, user: User = Depends(editor),
                db: Session = Depends(get_db)):
    assignment, worker = assignment_for(db, user.org_id, assignment_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Indica al menos un campo para actualizar")
    db.scalar(select(Organization).where(Organization.id == user.org_id).with_for_update())
    if "rut" in changes and changes["rut"] != worker.rut and db.scalar(select(Worker.id).where(
            Worker.org_id == user.org_id, Worker.rut == changes["rut"], Worker.id != worker.id)):
        raise HTTPException(409, "RUT ya pertenece a otra persona; no se fusionan identidades automáticamente")
    before = {key: getattr(worker, key) for key in changes}
    for key, value in changes.items():
        setattr(worker, key, value)
    worker.updated_at = utcnow()
    audit_change(db, user, "worker", worker.id, {"before": before, "after": changes,
                                                  "assignment_id": assignment.id})
    db.commit()
    return {"id": assignment.id, "worker_id": worker.id, "name": worker.name, "rut": worker.rut}


@router.patch("/contracts/{contract_id}")
def edit_contract(contract_id: str, body: ContractEdit, user: User = Depends(editor),
                  db: Session = Depends(get_db)):
    row = _contract(db, user, contract_id, lock=True)
    if row.status == "ended":
        raise HTTPException(409, "Contrato terminado; consulta el historial")
    changes = body.model_dump(exclude_unset=True)
    if "contract_type" in changes:
        _contract_type(db, user.org_id, changes["contract_type"])
    if (changes.get("contract_type", row.contract_type) == "fixed_term"
            and changes.get("end_date", row.end_date) is None):
        raise HTTPException(422, "Plazo fijo requiere fecha pactada")
    if changes.get("end_date", row.end_date) and changes.get("end_date", row.end_date) < row.start_date:
        raise HTTPException(422, "Fecha pactada anterior al ingreso")
    before = {k: str(getattr(row, k)) if isinstance(getattr(row, k), date) else getattr(row, k) for k in changes}
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_at, row.updated_by = utcnow(), user.id
    audit_change(db, user, "contract", row.id, {"before": before, "after": {k: str(v) if isinstance(v, date) else v for k, v in changes.items()}})
    db.commit()
    return {"id": row.id, "status": row.status, "end_date": row.end_date}


@router.post("/contracts/{contract_id}/amendments", status_code=201)
def add_amendment(contract_id: str, body: AmendmentInput, user: User = Depends(editor),
                  db: Session = Depends(get_db)):
    row = _contract(db, user, contract_id, lock=True)
    if row.status == "ended":
        raise HTTPException(409, "No se puede prorrogar un contrato terminado")
    if body.new_end_date and body.new_end_date < row.start_date:
        raise HTTPException(422, "Nueva fecha anterior al ingreso")
    if row.contract_type == "fixed_term" and body.new_end_date is None:
        raise HTTPException(422, "Plazo fijo requiere nueva fecha pactada")
    if body.document_id:
        _document(db, user, body.document_id)
    amendment = ContractAmendment(org_id=user.org_id, contract_id=row.id,
                                  amendment_date=body.amendment_date, previous_end_date=row.end_date,
                                  new_end_date=body.new_end_date, reference=body.reference,
                                  notes=body.notes, created_by=user.id)
    db.add(amendment)
    row.end_date, row.updated_by, row.updated_at = body.new_end_date, user.id, utcnow()
    db.flush()
    if body.document_id:
        db.add(ContractAttachment(org_id=user.org_id, contract_id=row.id,
                                  document_id=body.document_id, kind="amendment", created_by=user.id))
    audit_change(db, user, "contract_amendment", amendment.id, {"contract_id": row.id,
        "previous_end_date": str(amendment.previous_end_date), "new_end_date": str(body.new_end_date),
        "reference": body.reference, "document_id": body.document_id})
    db.commit()
    return {"id": amendment.id, "contract_id": row.id, "end_date": row.end_date}


@router.post("/contracts/{contract_id}/attachments", status_code=201)
def attach_contract(contract_id: str, body: AttachmentInput, user: User = Depends(document_reviewer),
                    db: Session = Depends(get_db)):
    row = _contract(db, user, contract_id)
    _document(db, user, body.document_id)
    found = db.scalar(select(ContractAttachment).where(
        ContractAttachment.org_id == user.org_id, ContractAttachment.contract_id == row.id,
        ContractAttachment.document_id == body.document_id))
    if found:
        return {"id": found.id, "document_id": found.document_id}
    attached = ContractAttachment(org_id=user.org_id, contract_id=row.id,
                                  document_id=body.document_id, kind=body.kind, created_by=user.id)
    db.add(attached)
    db.flush()
    audit_change(db, user, "contract_attachment", attached.id, {"contract_id": row.id,
                                                                   "document_id": body.document_id})
    db.commit()
    return {"id": attached.id, "document_id": attached.document_id}


@router.post("/contracts/{contract_id}/termination", status_code=201)
def terminate(contract_id: str, body: TerminationInput, user: User = Depends(editor),
              db: Session = Depends(get_db)):
    row = _contract(db, user, contract_id, lock=True)
    if row.status == "ended" or db.scalar(select(WorkerTermination.id).where(
            WorkerTermination.contract_id == row.id, WorkerTermination.org_id == user.org_id)):
        raise HTTPException(409, "Este contrato ya tiene término registrado")
    if body.effective_date < row.start_date or body.effective_date > today():
        raise HTTPException(422, "Fecha efectiva fuera del período laboral o futura")
    causes = catalogs_for(db, user.org_id)["termination_causes"]
    if body.cause not in causes:
        raise HTTPException(422, "Causal de término no configurada")
    term = WorkerTermination(org_id=user.org_id, contract_id=row.id,
                             effective_date=body.effective_date, cause=body.cause,
                             ratification_mode=body.ratification_mode,
                             issued_at=body.issued_at, signed_at=body.signed_at,
                             observation=body.observation.strip(), created_by=user.id)
    db.add(term)
    row.status, row.updated_by, row.updated_at = "ended", user.id, utcnow()
    assignment, _ = assignment_for(db, user.org_id, row.worker_assignment_id)
    assignment.active = False
    db.flush()
    audit_change(db, user, "worker_termination", term.id, {"contract_id": row.id,
        "effective_date": str(term.effective_date), "cause": term.cause,
        "ratification_mode": term.ratification_mode, "recorded_at": str(term.recorded_at)})
    db.commit()
    return {"id": term.id, "review_state": term.review_state, "effective_date": term.effective_date}


@router.post("/terminations/{termination_id}/document")
def deliver_finiquito(termination_id: str, body: FiniquitoDocument,
                      user: User = Depends(document_reviewer), db: Session = Depends(get_db)):
    term = db.scalar(select(WorkerTermination).where(WorkerTermination.id == termination_id,
                                                     WorkerTermination.org_id == user.org_id).with_for_update())
    if not term:
        raise HTTPException(404, "Finiquito no encontrado")
    _document(db, user, body.document_id)
    old = {"document_id": term.document_id, "state": term.review_state}
    term.document_id, term.issued_at, term.signed_at = body.document_id, body.issued_at, body.signed_at
    term.ratification_mode = body.ratification_mode
    term.review_state, term.reviewed_by, term.reviewed_at = "delivered", None, None
    term.updated_at = utcnow()
    audit_change(db, user, "worker_termination", term.id,
                 {"document": {"before": old, "after": {"document_id": term.document_id,
                                                           "state": term.review_state}}})
    db.commit()
    return {"id": term.id, "review_state": term.review_state, "document_id": term.document_id}


@router.post("/terminations/{termination_id}/review")
def review_finiquito(termination_id: str, body: ReviewFiniquito,
                     user: User = Depends(document_reviewer), db: Session = Depends(get_db)):
    term = db.scalar(select(WorkerTermination).where(WorkerTermination.id == termination_id,
                                                     WorkerTermination.org_id == user.org_id).with_for_update())
    if not term:
        raise HTTPException(404, "Finiquito no encontrado")
    if not term.document_id:
        raise HTTPException(422, "Carga el documento antes de revisarlo")
    old = {"state": term.review_state, "observation": term.observation}
    term.review_state, term.observation = body.state, body.observation.strip()
    term.reviewed_by, term.reviewed_at, term.updated_at = user.id, utcnow(), utcnow()
    audit_change(db, user, "worker_termination", term.id, {"review": {
        "from": old, "to": {"state": term.review_state, "observation": term.observation},
        "reviewed_by": user.id, "reviewed_at": str(term.reviewed_at)}})
    db.commit()
    return {"id": term.id, "review_state": term.review_state, "reviewed_by": term.reviewed_by}


@router.put("/contributions/{control_id}/finding")
def payment_finding(control_id: str, body: PaymentFindingInput,
                    user: User = Depends(document_reviewer), db: Session = Depends(get_db)):
    control = db.scalar(select(ContributionControl).where(
        ContributionControl.id == control_id, ContributionControl.org_id == user.org_id).with_for_update())
    if not control:
        raise HTTPException(404, "Control de cotizaciones no encontrado")
    if body.state == "declared_unpaid" and control.payment_confirmed:
        raise HTTPException(422, "No se puede declarar falta de pago mientras el control indica pago confirmado")
    if body.state == "verified" and not control.payment_confirmed:
        raise HTTPException(422, "Confirma el pago en el control antes de verificarlo")
    if body.document_id and not db.scalar(select(Document.id).where(
            Document.id == body.document_id, Document.org_id == user.org_id)):
        raise HTTPException(404, "Documento no encontrado")
    if body.state == "insufficient":
        days_short = (control.required_days is not None and control.paid_days is not None
                      and control.required_days > control.paid_days)
        amount_short = (body.expected_amount is not None and body.documented_amount is not None
                        and body.expected_amount > body.documented_amount)
        if not (days_short or amount_short):
            raise HTTPException(422, "No hay diferencia verificable de días o monto")
    row = db.scalar(select(PaymentFinding).where(
        PaymentFinding.control_id == control.id, PaymentFinding.org_id == user.org_id).with_for_update())
    before = None if row is None else {"state": row.state, "document_id": row.document_id,
                                      "documented_amount": str(row.documented_amount),
                                      "expected_amount": str(row.expected_amount)}
    if row is None:
        row = PaymentFinding(org_id=user.org_id, control_id=control.id, reviewed_by=user.id)
        db.add(row)
    row.state, row.document_id = body.state, body.document_id
    row.documented_amount, row.expected_amount = body.documented_amount, body.expected_amount
    row.observation, row.reviewed_by, row.reviewed_at = body.observation.strip(), user.id, utcnow()
    db.flush()
    audit_change(db, user, "payment_finding", row.id,
                 {"from": before, "to": {"state": row.state, "document_id": row.document_id,
                                          "documented_amount": body.documented_amount,
                                          "expected_amount": body.expected_amount,
                                          "observation": row.observation}, "control_id": control.id})
    db.commit()
    return {"id": row.id, "state": row.state, "reviewed_by": row.reviewed_by}


@router.get("/workers/{assignment_id}")
def worker_detail(assignment_id: str, user: User = Depends(authorized_user),
                  db: Session = Depends(get_db)):
    assignment, worker = assignment_for(db, user.org_id, assignment_id)
    association = db.scalar(select(ContractorWorksite).where(
        ContractorWorksite.org_id == user.org_id,
        ContractorWorksite.worksite_id == assignment.worksite_id,
        ContractorWorksite.contractor_id == assignment.contractor_id))
    if not association:
        raise HTTPException(409, "Relación laboral sin empresa y obra")
    company = db.get(Contractor, assignment.contractor_id)
    site = db.get(Worksite, assignment.worksite_id)
    contracts = db.scalars(select(ContractRegister).where(
        ContractRegister.org_id == user.org_id,
        ContractRegister.worker_assignment_id == assignment.id,
    ).order_by(ContractRegister.start_date.desc(), ContractRegister.created_at.desc())).all()
    ids = [c.id for c in contracts]
    terms = {t.contract_id: t for t in db.scalars(select(WorkerTermination).where(
        WorkerTermination.org_id == user.org_id, WorkerTermination.contract_id.in_(ids))).all()} if ids else {}
    amendments = db.scalars(select(ContractAmendment).where(
        ContractAmendment.org_id == user.org_id, ContractAmendment.contract_id.in_(ids))
    ).all() if ids else []
    attachments = db.scalars(select(ContractAttachment).where(
        ContractAttachment.org_id == user.org_id, ContractAttachment.contract_id.in_(ids))
    ).all() if ids else []
    audit_ids = [worker.id, assignment.id, *ids, *[a.id for a in amendments], *[t.id for t in terms.values()]]
    history = db.scalars(select(OpsChange).where(
        OpsChange.org_id == user.org_id, OpsChange.entity_id.in_(audit_ids),
    ).order_by(OpsChange.created_at.desc()).limit(100)).all()
    summary = _registry(db, user, site_id=site.id, contractor_id=company.id,
                        search=worker.rut or worker.name, page_size=100)
    current = next((r for r in summary["rows"] if r["assignment_id"] == assignment_id), None)
    # Fetch just this assignment when it falls after the first registry page.
    if current is None:
        current = db.execute(_registry_query(user.org_id, site_id=site.id).where(
            WorkerAssignment.id == assignment_id)).mappings().first()
        current = dict(current) if current else None
    return {"id": assignment.id, "worker_id": worker.id, "association_id": association.id,
            "name": worker.name,
            "rut": worker.rut, "contractor_id": company.id, "contractor": company.name,
            "site_id": site.id, "site": site.name, "current": current,
            "contracts": [{"id": c.id, "contract_type": c.contract_type,
                           "start_date": c.start_date, "end_date": c.end_date,
                           "status": c.status, "notes": c.notes,
                           "termination": ({"id": terms[c.id].id,
                                            "effective_date": terms[c.id].effective_date,
                                            "recorded_at": terms[c.id].recorded_at,
                                            "cause": terms[c.id].cause,
                                            "ratification_mode": terms[c.id].ratification_mode,
                                            "issued_at": terms[c.id].issued_at,
                                            "signed_at": terms[c.id].signed_at,
                                            "document_id": terms[c.id].document_id,
                                            "review_state": terms[c.id].review_state,
                                            "observation": terms[c.id].observation,
                                            "reviewed_by": terms[c.id].reviewed_by,
                                            "reviewed_at": terms[c.id].reviewed_at} if c.id in terms else None),
                           "amendments": [{"id": a.id, "date": a.amendment_date,
                                           "previous_end_date": a.previous_end_date,
                                           "new_end_date": a.new_end_date,
                                           "reference": a.reference, "notes": a.notes}
                                          for a in amendments if a.contract_id == c.id],
                           "attachments": [{"id": a.id, "document_id": a.document_id,
                                            "kind": a.kind}
                                           for a in attachments if a.contract_id == c.id]}
                          for c in contracts],
            "history": [{"id": h.id, "entity_type": h.entity_type,
                         "changes": h.changes, "created_at": h.created_at,
                         "user_id": h.user_id} for h in history]}


@router.get("/alerts")
def alerts(period: str | None = None, site_id: str | None = None,
           page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200),
           user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    if site_id:
        site_for(db, user.org_id, site_id)
    period = period or today().strftime("%Y-%m")
    from .control_api import validated_period
    validated_period(period)
    config = catalogs_for(db, user.org_id)
    stats = _registry(db, user, site_id=site_id, page_size=1)["summary"]
    worker_query = _registry_query(user.org_id, site_id=site_id,
                                   max_days=max(config["expiry_alert_days"]))
    center = []
    def add(kind, severity, label, site, when, target_id, target_section):
        center.append({"kind": kind, "severity": severity, "label": label,
                       "site": site, "date": when, "target_id": target_id,
                       "target_section": target_section})
    for w in db.execute(worker_query.where(or_(
            ContractRegister.end_date <= today() + timedelta(days=max(config["expiry_alert_days"])),
            WorkerTermination.id.is_not(None),
    ))).mappings():
        if w["labor_state"] == "expired_needs_review":
            add("contract_expired", "red", w["worker_name"], w["site_name"],
                w["end_date"], w["assignment_id"], "workers")
        elif w["labor_state"] == "ending_soon":
            add("contract_ending", "orange", w["worker_name"], w["site_name"],
                w["end_date"], w["assignment_id"], "workers")
        if w["labor_state"] == "ended" and w["finiquito_state"] != "approved":
            due = config["termination_due_days"]
            critical = due is not None and w["finiquito_state"] == "missing" and today() > w["effective_date"] + timedelta(days=due)
            add("finiquito_pending", "red" if critical else "orange", w["worker_name"],
                w["site_name"], w["effective_date"], w["assignment_id"], "workers")
    links = db.execute(select(ContractorWorksite, Contractor, Worksite).join(
        Contractor, and_(Contractor.id == ContractorWorksite.contractor_id,
                         Contractor.org_id == user.org_id)).join(
        Worksite, and_(Worksite.id == ContractorWorksite.worksite_id,
                       Worksite.org_id == user.org_id)).where(
        ContractorWorksite.org_id == user.org_id,
        *((ContractorWorksite.worksite_id == site_id,) if site_id else ()),
    )).all()
    unclassified = set()
    for link, company, site in links:
        if company.nature == "unclassified" or link.frequency == "unclassified":
            unclassified.add(company.id)
            add("classification", "orange", company.name, site.name, None, link.id, "contractors")
    critical_docs = set()
    for site in {site.id: site for _, _, site in links}.values():
        from .attendance_api import roster as attendance_roster
        attendance = attendance_roster(site.id, period, user, db)
        for company in attendance["contractors"]:
            for week in company["weeks"]:
                if week["state"] == "overdue":
                    add("attendance_missing", "red",
                        company["contractor"] + " · asistencia semana " + str(week["week_number"]),
                        site.name, week["due_date"], company["association_id"], "attendance")
        matrix = monthly_matrix(site.id, period, user, db)
        for company in matrix["contractors"]:
            for req in company["requirements"]:
                if req["applicable"] is not True:
                    continue
                if req["state"] == "overdue":
                    critical_docs.add(company["association_id"])
                    add("document_overdue", "red", company["name"] + " · " + req["kind"],
                        site.name, req["due_date"], company["association_id"], "documents")
                elif req["state"] in {"observed", "rejected", "pending"} and req["document_id"]:
                    add("document_review", "orange", company["name"] + " · " + req["kind"],
                        site.name, req["due_date"], company["association_id"], "documents")
    difference_ids = set()
    controls = db.execute(select(ContributionControl, ContractorWorksite, Worksite).join(
        ContractorWorksite, and_(ContractorWorksite.id == ContributionControl.association_id,
                                 ContractorWorksite.org_id == user.org_id)).join(
        Worksite, and_(Worksite.id == ContractorWorksite.worksite_id,
                       Worksite.org_id == user.org_id)).where(
        ContributionControl.org_id == user.org_id, ContributionControl.period == period,
        *((ContractorWorksite.worksite_id == site_id,) if site_id else ()),
    )).all()
    finding_by_control = {f.control_id: f for f in db.scalars(select(PaymentFinding).where(
        PaymentFinding.org_id == user.org_id,
        PaymentFinding.control_id.in_([row.id for row, _, _ in controls]),
    )).all()}
    unpaid_ids = set()
    for row, link, site in controls:
        finding = finding_by_control.get(row.id)
        if finding and finding.state == "declared_unpaid":
            unpaid_ids.add(row.id)
            add("declared_unpaid", "red", "Cotizaciones declaradas sin pago verificado",
                site.name, None, row.id, "contributions")
        elif finding and finding.state == "insufficient":
            difference_ids.add(row.id)
            add("payment_difference", "red", "Pago inferior al requerido, revisión confirmada",
                site.name, None, row.id, "contributions")
        if row.required_days is not None and row.paid_days is not None and row.paid_days < row.required_days:
            difference_ids.add(row.id)
            if not finding or finding.state not in {"insufficient", "declared_unpaid"}:
                severity = "red" if row.payment_confirmed and row.review_status == "approved" else "orange"
                add("payment_difference", severity, "Diferencia de días cotizados",
                    site.name, None, row.id, "contributions")
    center.sort(key=lambda a: (0 if a["severity"] == "red" else 1,
                               a["site"] or "", str(a["date"] or ""), a["label"]))
    return {"period": period, "page": page, "page_size": page_size,
            "total_alerts": len(center), "summary": {
        "critical_contractors": len(critical_docs),
        "workers_expired": stats["expired"], "workers_ending": stats["ending_soon"],
        "finiquito_pending": stats["finiquito_pending"],
        "incomplete_contributions": len(difference_ids),
        "payment_differences": len(difference_ids),
        "declared_unpaid": len(unpaid_ids),
        "unclassified_contractors": len(unclassified),
        "attendance_overdue": sum(a["kind"] == "attendance_missing" for a in center),
    }, "alerts": center[(page - 1) * page_size:page * page_size]}
