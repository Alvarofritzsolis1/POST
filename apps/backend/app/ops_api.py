"""Manual operational register for sites, contractors and workers."""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db
from .models import User, utcnow
from .ops_models import (
    AuditPeriod, Contractor, ContractorWorksite, OpsChange, Worker,
    WorkerAssignment, Worksite,
)
from .rules import valid_rut
from .platform_models import ContractorDetails
from .security import authorized_user, editor

router = APIRouter(prefix="/api/v1/ops", tags=["Operación manual"])
INITIAL_PERIOD = "2026-09"
DEFAULT_SITES = ("Lomas Verdes", "Brisas de Junquillar", "Concepción")
Nature = Literal["independent", "with_workers", "unclassified"]
Frequency = Literal["fixed", "sporadic", "unclassified"]
ContractStatus = Literal["active", "suspended", "offboarding", "inactive"]


def normalize_rut(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    if not re.fullmatch(r"[0-9.kK\-\s]+", raw):
        raise ValueError("RUT inválido")
    compact = re.sub(r"[^0-9kK]", "", raw).upper()
    if not valid_rut(compact):
        raise ValueError("RUT inválido")
    return str(int(compact[:-1])) + "-" + compact[-1]


def clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > 180:
        raise ValueError("El nombre debe tener entre 1 y 180 caracteres")
    return cleaned


def clean_code(value: str | None) -> str:
    cleaned = (value or "").strip().upper()
    if len(cleaned) > 20:
        raise ValueError("El código histórico supera 20 caracteres")
    return cleaned


class ContractorCreate(BaseModel):
    site_id: str
    name: str = Field(min_length=1, max_length=180)
    rut: str | None = None
    historical_code: str | None = ""
    nature: Nature = "unclassified"
    frequency: Frequency = "unclassified"
    contract_status: ContractStatus = "active"

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return clean_name(value)

    @field_validator("rut")
    @classmethod
    def rut_valid(cls, value: str | None) -> str | None:
        return normalize_rut(value)

    @field_validator("historical_code")
    @classmethod
    def code_valid(cls, value: str | None) -> str:
        return clean_code(value)


class ContractorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    rut: str | None = None
    historical_code: str | None = None
    nature: Nature | None = None
    frequency: Frequency | None = None
    contract_status: ContractStatus | None = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str | None) -> str | None:
        return clean_name(value) if value is not None else None

    @field_validator("rut")
    @classmethod
    def rut_valid(cls, value: str | None) -> str | None:
        return normalize_rut(value)

    @field_validator("historical_code")
    @classmethod
    def code_valid(cls, value: str | None) -> str:
        return clean_code(value)


class WorkerCreate(BaseModel):
    site_id: str
    contractor_id: str
    name: str = Field(min_length=1, max_length=180)
    rut: str | None = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return clean_name(value)

    @field_validator("rut")
    @classmethod
    def rut_valid(cls, value: str | None) -> str | None:
        return normalize_rut(value)


class WorkerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    rut: str | None = None
    active: bool | None = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str | None) -> str | None:
        return clean_name(value) if value is not None else None

    @field_validator("rut")
    @classmethod
    def rut_valid(cls, value: str | None) -> str | None:
        return normalize_rut(value)


def ensure_sites(db: Session, org_id: str) -> list[Worksite]:
    """Create only missing defaults; safe for older databases after `init-db`."""
    for attempt in range(2):
        try:
            existing = db.scalars(select(Worksite).where(Worksite.org_id == org_id)).all()
            by_name = {site.name: site for site in existing}
            for name in DEFAULT_SITES:
                if name not in by_name:
                    site = Worksite(org_id=org_id, name=name)
                    db.add(site)
                    db.flush()
                    by_name[name] = site
            for site in by_name.values():
                if db.scalar(select(AuditPeriod.id).where(
                    AuditPeriod.org_id == org_id, AuditPeriod.worksite_id == site.id,
                    AuditPeriod.period == INITIAL_PERIOD,
                )) is None:
                    db.add(AuditPeriod(org_id=org_id, worksite_id=site.id, period=INITIAL_PERIOD))
            db.commit()
            return db.scalars(select(Worksite).where(Worksite.org_id == org_id).order_by(Worksite.name)).all()
        except IntegrityError:
            db.rollback()
            if attempt:
                raise
    return []


def site_for(db: Session, org_id: str, site_id: str) -> Worksite:
    site = db.scalar(select(Worksite).where(Worksite.id == site_id, Worksite.org_id == org_id))
    if site is None:
        raise HTTPException(404, "Obra no encontrada")
    return site


def association_for(db: Session, org_id: str, association_id: str) -> tuple[ContractorWorksite, Contractor]:
    record = db.execute(select(ContractorWorksite, Contractor).join(
        Contractor, Contractor.id == ContractorWorksite.contractor_id,
    ).where(ContractorWorksite.id == association_id,
            ContractorWorksite.org_id == org_id,
            Contractor.org_id == org_id)).first()
    if record is None:
        raise HTTPException(404, "Contratista no encontrado en la obra")
    return record[0], record[1]


def assignment_for(db: Session, org_id: str, assignment_id: str) -> tuple[WorkerAssignment, Worker]:
    record = db.execute(select(WorkerAssignment, Worker).join(
        Worker, Worker.id == WorkerAssignment.worker_id,
    ).where(WorkerAssignment.id == assignment_id,
            WorkerAssignment.org_id == org_id,
            Worker.org_id == org_id)).first()
    if record is None:
        raise HTTPException(404, "Trabajador no encontrado en la obra")
    return record[0], record[1]


def audit_change(db: Session, user: User, kind: str, entity_id: str, changes: dict) -> None:
    db.add(OpsChange(org_id=user.org_id, user_id=user.id,
                     entity_type=kind, entity_id=entity_id, changes=changes))


def has_active_workers(db: Session, org_id: str, contractor_id: str) -> bool:
    return db.scalar(select(WorkerAssignment.id).where(
        WorkerAssignment.org_id == org_id,
        WorkerAssignment.contractor_id == contractor_id,
        WorkerAssignment.active.is_(True),
    ).limit(1)) is not None


def contractor_classification(link: ContractorWorksite, contractor: Contractor) -> str:
    """Labor nature only; frequency and historical COD remain independent fields."""
    return {"with_workers": "CT", "independent": "CI"}.get(contractor.nature, "SIN CLASIFICAR")


def contractor_view(link: ContractorWorksite, contractor: Contractor, worker_count: int = 0) -> dict:
    return {
        "id": link.id, "site_id": link.worksite_id,
        "contractor_id": contractor.id, "name": contractor.name, "rut": contractor.rut,
        "historical_code": link.historical_code, "nature": contractor.nature,
        "frequency": link.frequency, "contract_status": link.contract_status,
        "classification": contractor_classification(link, contractor),
        "worker_count": worker_count,
    }


def worker_view(link: WorkerAssignment, worker: Worker) -> dict:
    return {
        "id": link.id, "site_id": link.worksite_id,
        "contractor_id": link.contractor_id, "worker_id": worker.id,
        "name": worker.name, "rut": worker.rut, "active": link.active,
    }


@router.get("/sites")
def sites(user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    rows = ensure_sites(db, user.org_id)
    return [{"id": row.id, "name": row.name, "initial_period": INITIAL_PERIOD} for row in rows]


@router.get("/contractors")
def contractors(site_id: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    site_for(db, user.org_id, site_id)
    rows = db.execute(select(ContractorWorksite, Contractor).join(
        Contractor, Contractor.id == ContractorWorksite.contractor_id,
    ).where(ContractorWorksite.org_id == user.org_id,
            ContractorWorksite.worksite_id == site_id,
            Contractor.org_id == user.org_id).order_by(Contractor.name)).all()
    counts = dict(db.execute(select(WorkerAssignment.contractor_id, func.count(WorkerAssignment.id)).where(
        WorkerAssignment.org_id == user.org_id,
        WorkerAssignment.worksite_id == site_id,
        WorkerAssignment.active.is_(True),
    ).group_by(WorkerAssignment.contractor_id)).all())
    extras = {r.contractor_id: r.values for r in db.scalars(select(ContractorDetails).where(ContractorDetails.contractor_id.in_([c.id for _, c in rows])))}
    return [{**contractor_view(link, contractor, counts.get(contractor.id, 0)), "details": extras.get(contractor.id, {})} for link, contractor in rows]


@router.post("/contractors", status_code=201)
def create_contractor(payload: ContractorCreate,
                      user: User = Depends(editor), db: Session = Depends(get_db)):
    site_for(db, user.org_id, payload.site_id)
    contractor = None
    if payload.rut:
        contractor = db.scalar(select(Contractor).where(
            Contractor.org_id == user.org_id, Contractor.rut == payload.rut))
    if contractor is None:
        name_match = db.scalar(select(Contractor).where(
            Contractor.org_id == user.org_id,
            func.lower(Contractor.name) == payload.name.lower()))
        if name_match:
            if payload.rut and name_match.rut != payload.rut:
                raise HTTPException(409, "Ya existe una empresa con ese nombre y otro RUT")
            if not payload.rut and name_match.rut:
                raise HTTPException(409, "Ya existe una empresa con ese nombre; indica su RUT")
            contractor = name_match
    elif contractor.name.casefold() != payload.name.casefold():
        raise HTTPException(409, "El RUT ya pertenece a otra empresa")
    if contractor and contractor.nature not in {payload.nature, "unclassified"} and payload.nature != "unclassified":
        raise HTTPException(409, "La naturaleza de la empresa difiere de la ficha existente")
    if contractor and db.scalar(select(ContractorWorksite.id).where(
        ContractorWorksite.org_id == user.org_id,
        ContractorWorksite.worksite_id == payload.site_id,
        ContractorWorksite.contractor_id == contractor.id,
    )):
        raise HTTPException(409, "El contratista ya está asociado a esta obra")
    try:
        if contractor is None:
            contractor = Contractor(org_id=user.org_id, name=payload.name,
                                    rut=payload.rut, nature=payload.nature)
            db.add(contractor)
            db.flush()
            audit_change(db, user, "contractor", contractor.id,
                         {"created": {"name": contractor.name, "rut": contractor.rut,
                                      "nature": contractor.nature}})
        elif contractor.nature == "unclassified" and payload.nature != "unclassified":
            if payload.nature == "independent" and has_active_workers(db, user.org_id, contractor.id):
                raise HTTPException(409, "No se puede clasificar como independiente con trabajadores activos")
            contractor.nature = payload.nature
            contractor.updated_at = utcnow()
            audit_change(db, user, "contractor", contractor.id,
                         {"nature": {"from": "unclassified", "to": payload.nature}})
        link = ContractorWorksite(org_id=user.org_id, worksite_id=payload.site_id,
                                  contractor_id=contractor.id,
                                  historical_code=payload.historical_code,
                                  frequency=payload.frequency,
                                  contract_status=payload.contract_status)
        db.add(link)
        db.flush()
        audit_change(db, user, "contractor_worksite", link.id,
                     {"created": {"worksite_id": link.worksite_id,
                                  "contractor_id": contractor.id,
                                  "historical_code": link.historical_code,
                                  "frequency": link.frequency,
                                  "contract_status": link.contract_status}})
        db.commit()
        return contractor_view(link, contractor)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe un contratista con ese RUT o en esa obra") from None


@router.patch("/contractors/{association_id}")
def update_contractor(association_id: str, payload: ContractorPatch,
                      user: User = Depends(editor), db: Session = Depends(get_db)):
    link, contractor = association_for(db, user.org_id, association_id)
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "No se enviaron cambios")
    changes: dict[str, dict] = {}
    link_changes: dict[str, dict] = {}
    for field in ("name", "rut", "nature"):
        if field in fields:
            value = fields[field]
            if value is None and field != "rut":
                raise HTTPException(422, f"{field} no puede estar vacío")
            previous = getattr(contractor, field)
            if previous != value:
                if field == "nature" and value == "independent" and has_active_workers(db, user.org_id, contractor.id):
                    raise HTTPException(409, "No se puede clasificar como independiente con trabajadores activos")
                setattr(contractor, field, value)
                changes[field] = {"from": previous, "to": value}
    for field in ("historical_code", "frequency", "contract_status"):
        if field in fields:
            value = fields[field]
            if value is None:
                raise HTTPException(422, f"{field} no puede estar vacío")
            previous = getattr(link, field)
            if previous != value:
                setattr(link, field, value)
                link_changes[field] = {"from": previous, "to": value}
    if changes:
        contractor.updated_at = utcnow()
        audit_change(db, user, "contractor", contractor.id, changes)
    if link_changes:
        link.updated_at = utcnow()
        audit_change(db, user, "contractor_worksite", link.id, link_changes)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "El RUT ya está registrado para otra empresa") from None
    return contractor_view(link, contractor, db.scalar(select(func.count(WorkerAssignment.id)).where(
        WorkerAssignment.org_id == user.org_id,
        WorkerAssignment.worksite_id == link.worksite_id,
        WorkerAssignment.contractor_id == contractor.id,
        WorkerAssignment.active.is_(True))) or 0)


@router.get("/workers")
def workers(site_id: str, contractor_id: str | None = None,
            user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    site_for(db, user.org_id, site_id)
    query = select(WorkerAssignment, Worker).join(
        Worker, Worker.id == WorkerAssignment.worker_id,
    ).where(WorkerAssignment.org_id == user.org_id,
            WorkerAssignment.worksite_id == site_id,
            Worker.org_id == user.org_id)
    if contractor_id:
        query = query.where(WorkerAssignment.contractor_id == contractor_id)
    rows = db.execute(query.order_by(Worker.name)).all()
    return [worker_view(link, worker) for link, worker in rows]


@router.post("/workers", status_code=201)
def create_worker(payload: WorkerCreate,
                  user: User = Depends(editor), db: Session = Depends(get_db)):
    site_for(db, user.org_id, payload.site_id)
    association = db.scalar(select(ContractorWorksite).where(
        ContractorWorksite.org_id == user.org_id,
        ContractorWorksite.worksite_id == payload.site_id,
        ContractorWorksite.contractor_id == payload.contractor_id))
    if association is None:
        raise HTTPException(404, "Contratista no asociado a la obra")
    contractor = db.scalar(select(Contractor).where(
        Contractor.id == payload.contractor_id, Contractor.org_id == user.org_id))
    if contractor is None:
        raise HTTPException(404, "Contratista no encontrado")
    if contractor.nature == "independent":
        raise HTTPException(409, "Un independiente no puede tener trabajadores dependientes")
    worker = db.scalar(select(Worker).where(
        Worker.org_id == user.org_id, Worker.rut == payload.rut)) if payload.rut else None
    if worker and worker.name.casefold() != payload.name.casefold():
        raise HTTPException(409, "El RUT ya pertenece a otro trabajador")
    if worker and db.scalar(select(WorkerAssignment.id).where(
        WorkerAssignment.org_id == user.org_id,
        WorkerAssignment.worksite_id == payload.site_id,
        WorkerAssignment.contractor_id == payload.contractor_id,
        WorkerAssignment.worker_id == worker.id)):
        raise HTTPException(409, "El trabajador ya está asignado a este contratista y obra")
    try:
        if worker is None:
            worker = Worker(org_id=user.org_id, name=payload.name, rut=payload.rut)
            db.add(worker)
            db.flush()
            audit_change(db, user, "worker", worker.id,
                         {"created": {"name": worker.name, "rut": worker.rut}})
        link = WorkerAssignment(org_id=user.org_id, worksite_id=payload.site_id,
                                contractor_id=payload.contractor_id, worker_id=worker.id,
                                active=True)
        db.add(link)
        db.flush()
        audit_change(db, user, "worker_assignment", link.id,
                     {"created": {"worksite_id": link.worksite_id,
                                  "contractor_id": link.contractor_id, "worker_id": worker.id}})
        db.commit()
        return worker_view(link, worker)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "El RUT o la asignación ya existen") from None


@router.patch("/workers/{assignment_id}")
def update_worker(assignment_id: str, payload: WorkerPatch,
                  user: User = Depends(editor), db: Session = Depends(get_db)):
    link, worker = assignment_for(db, user.org_id, assignment_id)
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "No se enviaron cambios")
    worker_changes: dict[str, dict] = {}
    link_changes: dict[str, dict] = {}
    for field in ("name", "rut"):
        if field in fields:
            value = fields[field]
            if value is None and field != "rut":
                raise HTTPException(422, "El nombre no puede estar vacío")
            previous = getattr(worker, field)
            if previous != value:
                setattr(worker, field, value)
                worker_changes[field] = {"from": previous, "to": value}
    if "active" in fields:
        if fields["active"] is None:
            raise HTTPException(422, "El estado activo no puede estar vacío")
        if link.active != fields["active"]:
            if fields["active"]:
                contractor = db.scalar(select(Contractor).where(
                    Contractor.id == link.contractor_id, Contractor.org_id == user.org_id))
                if contractor is None or contractor.nature == "independent":
                    raise HTTPException(409, "Un independiente no puede tener trabajadores dependientes")
            link_changes["active"] = {"from": link.active, "to": fields["active"]}
            link.active = fields["active"]
    if worker_changes:
        worker.updated_at = utcnow()
        audit_change(db, user, "worker", worker.id, worker_changes)
    if link_changes:
        link.updated_at = utcnow()
        audit_change(db, user, "worker_assignment", link.id, link_changes)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "El RUT ya está registrado para otro trabajador") from None
    return worker_view(link, worker)


@router.get("/history")
def history(entity_type: str | None = None, entity_id: str | None = None,
            limit: int = Query(default=100, ge=1, le=500),
            user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    query = select(OpsChange).where(OpsChange.org_id == user.org_id)
    if entity_type:
        query = query.where(OpsChange.entity_type == entity_type)
    if entity_id:
        query = query.where(OpsChange.entity_id == entity_id)
    rows = db.scalars(query.order_by(OpsChange.created_at.desc()).limit(limit)).all()
    return [{"id": row.id, "entity_type": row.entity_type,
             "entity_id": row.entity_id, "user_id": row.user_id,
             "changes": row.changes, "created_at": row.created_at} for row in rows]
