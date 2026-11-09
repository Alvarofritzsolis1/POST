"""GALANT JAVIERA v16.6 - separate documentary workflow.

Only reads operational companies and workers. All writes stay in
javiera_local_* tables; a documentary person never joins the active workforce.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .javiera_api import audit, by_org, pdf_for, template_data
from .javiera_layout_api import latest_layout, make_pdf
from .javiera_logic import DOCUMENTS, DOCUMENT_BY_CODE, eligibility, normalize_cargo, render_tokens
from .javiera_matrices import latest_approved_matrix
from .javiera_models import JavieraMatrix, JavieraTemplate
from .javiera_v166_models import (
    JavieraLocalCompany, JavieraLocalPerson, JavieraLocalDossier,
    JavieraLocalIssue, JavieraLocalBatch,
)
from .models import User, utcnow
from .ops_models import Contractor, ContractorWorksite, Worker, WorkerAssignment, Worksite
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v166", tags=["Javiera documentaria v16.6"])
EVENT = {
    "labor_contract": "ingreso", "transfer_addendum": "traslado",
    "sworn_declaration": "declaracion", "extension_addendum": "prorroga",
    "internal_rules_receipt": "reglamento", "ppe_delivery": "entrega_epp",
    "irl": "ingreso", "pts": "ingreso", "pts_receipt": "recepcion_pts",
    "induction": "induccion",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyInput(Strict):
    site_id: str
    origin: str = Field(pattern="^(new|operational|documentary)$")
    source_id: str | None = None
    name: str = Field(default="", max_length=240)
    rut: str = Field(default="", max_length=30)
    details: dict = Field(default_factory=dict)


class PersonInput(Strict):
    company_id: str
    origin: str = Field(pattern="^(new|operational|documentary)$")
    source_id: str | None = None
    name: str = Field(default="", max_length=240)
    rut: str = Field(default="", max_length=30)
    details: dict = Field(default_factory=dict)


class DossierInput(Strict):
    site_id: str
    company_id: str
    person_id: str | None = None
    relationship: str = Field(pattern="^(contractor|subcontractor)$")
    parent_name: str | None = Field(default=None, max_length=240)
    selected_codes: list[str] = Field(default_factory=list, max_length=10)
    shared: dict = Field(default_factory=dict)
    document_data: dict = Field(default_factory=dict)
    dossier_id: str | None = None
    expected_revision: int | None = None


class BatchInput(Strict):
    dossier_id: str
    codes: list[str] = Field(min_length=1, max_length=10)
    reissue_reasons: dict[str, str] = Field(default_factory=dict)


class PreviewInput(Strict):
    dossier_id: str
    code: str


def _dossier(db, user, ident):
    return by_org(db, JavieraLocalDossier, ident, user.org_id)


def _safe_data(value: dict, limit: int = 30000):
    if len(json.dumps(value, ensure_ascii=False)) > limit:
        raise HTTPException(413, "Datos documentales demasiado extensos")


def _only_codes(codes):
    if len(codes) != len(set(codes)) or any(code not in DOCUMENT_BY_CODE for code in codes):
        raise HTTPException(422, "Selección documental duplicada o desconocida")


def _company(db, user, company_id):
    return by_org(db, JavieraLocalCompany, company_id, user.org_id)


def _person(db, user, person_id):
    return by_org(db, JavieraLocalPerson, person_id, user.org_id)


def _document(record, code, db, user):
    """Build one document's values without overwriting a different document's event."""
    company = _company(db, user, record.company_id)
    person = _person(db, user, record.person_id) if record.person_id else None
    site = by_org(db, Worksite, record.site_id, user.org_id)
    data = json.loads(json.dumps(record.shared))
    specific = record.document_data.get(code) or {}
    for key, value in specific.items():
        if key in {"extra", "contract", "event"} and isinstance(value, dict):
            data[key] = {**(data.get(key) if isinstance(data.get(key), dict) else {}), **value}
        elif key not in {"employer", "worker", "site", "event_type"}:
            data[key] = value
    data["employer"] = {"name": company.name, "rut": company.rut or ""}
    data["worker"] = {"name": person.name, "rut": person.rut or ""} if person else {"name": "", "rut": ""}
    data["site"] = {"name": site.name}
    data["event_type"] = EVENT[code]
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    data["extra"] = {**(company.details or {}), **(person.details if person else {}), **extra}
    if record.parent_name:
        data["extra"]["principal_company"] = record.parent_name
    return data


def _status(db, user, record, code):
    templates = template_data(db, user.org_id)
    role = normalize_cargo((record.shared or {}).get("role"))
    matrices = db.execute(select(JavieraMatrix.kind, JavieraMatrix.cargo).where(
        JavieraMatrix.org_id == user.org_id,
        JavieraMatrix.status == "approved")).all()
    approved = {kind + ":" + normalize_cargo(cargo) for kind, cargo in matrices}
    data = _document(record, code, db, user)
    item = next(s for s in eligibility(data, templates, approved) if s["code"] == code)
    if code == "sworn_declaration":
        if record.person_id:
            item.update(status="NO_APLICA", applicability="no_aplica",
                        reason="La declaración corresponde a la empresa, no a una persona.",
                        can_issue=False, can_preview=False)
        elif not (record.document_data.get(code) or {}).get("verified_no_workers"):
            item.update(status="POR_DETERMINAR",
                        reason="Confirmar y documentar la ausencia de trabajadores en el período.",
                        can_issue=False, can_preview=False)
    if code == "sworn_declaration":
        company = _company(db, user, record.company_id)
        if company.source_contractor_id:
            active = db.scalar(select(WorkerAssignment.id).where(
                WorkerAssignment.org_id == user.org_id,
                WorkerAssignment.worksite_id == record.site_id,
                WorkerAssignment.contractor_id == company.source_contractor_id,
                WorkerAssignment.active.is_(True)).limit(1))
            if active:
                item.update(status="NO_APLICA", applicability="no_aplica",
                            reason="La empresa tiene personas activas registradas en esta obra.",
                            can_issue=False, can_preview=False)
    previous = db.scalars(select(JavieraLocalIssue).where(
        JavieraLocalIssue.org_id == user.org_id,
        JavieraLocalIssue.dossier_id == record.id,
        JavieraLocalIssue.code == code).order_by(JavieraLocalIssue.issued_at.desc()).limit(1)).first()
    if previous:
        item["has_history"] = True
    item["code"] = code
    return item, data, previous


def _company_dict(row):
    return {"id": row.id, "site_id": row.site_id, "name": row.name,
            "rut": row.rut or "", "source_contractor_id": row.source_contractor_id,
            "details": row.details, "origin": "documentary"}


def _person_dict(row):
    return {"id": row.id, "company_id": row.company_id, "name": row.name,
            "rut": row.rut or "", "source_worker_id": row.source_worker_id,
            "details": row.details, "origin": "documentary"}


@router.get("/sources")
def sources(site_id: str = "", company_id: str = "",
            user: User = Depends(administrator), db: Session = Depends(get_db)):
    if site_id:
        by_org(db, Worksite, site_id, user.org_id)
    sites = db.scalars(select(Worksite).where(Worksite.org_id == user.org_id).order_by(Worksite.name)).all()
    local_q = select(JavieraLocalCompany).where(JavieraLocalCompany.org_id == user.org_id)
    if site_id:
        local_q = local_q.where(JavieraLocalCompany.site_id == site_id)
    local = db.scalars(local_q.order_by(JavieraLocalCompany.name).limit(500)).all()
    operational_q = select(ContractorWorksite, Contractor).join(
        Contractor, ContractorWorksite.contractor_id == Contractor.id).where(
        ContractorWorksite.org_id == user.org_id)
    if site_id:
        operational_q = operational_q.where(ContractorWorksite.worksite_id == site_id)
    operational = db.execute(operational_q.limit(500)).all()
    people, op_people = [], []
    if company_id:
        company = _company(db, user, company_id)
        people = db.scalars(select(JavieraLocalPerson).where(
            JavieraLocalPerson.org_id == user.org_id,
            JavieraLocalPerson.company_id == company.id).order_by(JavieraLocalPerson.name).limit(500)).all()
        if company.source_contractor_id:
            assignments = db.execute(select(WorkerAssignment, Worker).join(
                Worker, WorkerAssignment.worker_id == Worker.id).where(
                WorkerAssignment.org_id == user.org_id,
                WorkerAssignment.worksite_id == company.site_id,
                WorkerAssignment.contractor_id == company.source_contractor_id).limit(500)).all()
            op_people = [{"id": w.id, "name": w.name, "rut": w.rut or "",
                          "origin": "operational"} for a, w in assignments]
    return {"sites": [{"id": s.id, "name": s.name} for s in sites],
            "companies": [_company_dict(c) for c in local],
            "operational_companies": [{"id": c.id, "name": c.name, "rut": c.rut or "",
                                       "site_id": a.worksite_id, "origin": "operational"}
                                      for a, c in operational],
            "people": [_person_dict(p) for p in people], "operational_people": op_people}


@router.post("/companies")
def save_company(payload: CompanyInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    site = by_org(db, Worksite, payload.site_id, user.org_id)
    _safe_data(payload.details, 9000)
    if payload.origin == "documentary":
        company = _company(db, user, payload.source_id)
        if company.site_id != site.id:
            raise HTTPException(422, "Empresa documental de otra obra")
        return _company_dict(company)
    linked_id = None
    name, rut = payload.name.strip(), payload.rut.strip()
    if payload.origin == "operational":
        origin = by_org(db, Contractor, payload.source_id, user.org_id)
        exists = db.scalar(select(ContractorWorksite.id).where(
            ContractorWorksite.org_id == user.org_id,
            ContractorWorksite.worksite_id == site.id,
            ContractorWorksite.contractor_id == origin.id))
        if not exists:
            raise HTTPException(422, "Empresa no vinculada a la obra")
        linked_id, name, rut = origin.id, origin.name, origin.rut or ""
        previous = db.scalar(select(JavieraLocalCompany).where(
            JavieraLocalCompany.org_id == user.org_id,
            JavieraLocalCompany.site_id == site.id,
            JavieraLocalCompany.source_contractor_id == linked_id))
        if previous:
            return _company_dict(previous)
    if not name or len(name) < 2:
        raise HTTPException(422, "Escribe la razón social de la empresa")
    if payload.origin == "new":
        previous = db.scalar(select(JavieraLocalCompany).where(
            JavieraLocalCompany.org_id == user.org_id,
            JavieraLocalCompany.site_id == site.id,
            JavieraLocalCompany.name == name))
        if previous:
            if rut and previous.rut and rut != previous.rut:
                raise HTTPException(409, "Ya hay una empresa documental con ese nombre y diferente RUT")
            return _company_dict(previous)
    company = JavieraLocalCompany(org_id=user.org_id, site_id=site.id,
        source_contractor_id=linked_id, name=name, rut=rut or None,
        details=payload.details if payload.origin == "new" else {},
        created_by=user.id)
    db.add(company)
    db.flush()
    audit(db, user, "javiera.local_company_created", company.id)
    db.commit()
    return _company_dict(company)


@router.post("/people")
def save_person(payload: PersonInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    company = _company(db, user, payload.company_id)
    _safe_data(payload.details, 9000)
    if payload.origin == "documentary":
        person = _person(db, user, payload.source_id)
        if person.company_id != company.id:
            raise HTTPException(422, "Persona documental de otra empresa")
        return _person_dict(person)
    name, rut = payload.name.strip(), payload.rut.strip()
    source_id = None
    if payload.origin == "operational":
        worker = by_org(db, Worker, payload.source_id, user.org_id)
        if not company.source_contractor_id:
            raise HTTPException(422, "La empresa documental no tiene un vínculo operativo")
        assigned = db.scalar(select(WorkerAssignment.id).where(
            WorkerAssignment.org_id == user.org_id,
            WorkerAssignment.worksite_id == company.site_id,
            WorkerAssignment.contractor_id == company.source_contractor_id,
            WorkerAssignment.worker_id == worker.id))
        if not assigned:
            raise HTTPException(422, "Trabajador fuera de esta empresa y obra")
        source_id, name, rut = worker.id, worker.name, worker.rut or ""
        previous = db.scalar(select(JavieraLocalPerson).where(
            JavieraLocalPerson.org_id == user.org_id,
            JavieraLocalPerson.company_id == company.id,
            JavieraLocalPerson.source_worker_id == source_id))
        if previous:
            return _person_dict(previous)
    if len(name) < 2:
        raise HTTPException(422, "Escribe el nombre de la persona")
    if payload.origin == "new":
        previous = db.scalar(select(JavieraLocalPerson).where(
            JavieraLocalPerson.org_id == user.org_id,
            JavieraLocalPerson.company_id == company.id,
            JavieraLocalPerson.name == name))
        if previous:
            if rut and previous.rut and rut != previous.rut:
                raise HTTPException(409, "Existe una persona documental con este nombre y otro RUT")
            return _person_dict(previous)
    person = JavieraLocalPerson(org_id=user.org_id, company_id=company.id,
        source_worker_id=source_id, name=name, rut=rut or None,
        details=payload.details if payload.origin == "new" else {})
    db.add(person)
    db.flush()
    audit(db, user, "javiera.local_person_created", person.id)
    db.commit()
    return _person_dict(person)


def _dossier_dict(row, db, user):
    company = _company(db, user, row.company_id)
    person = _person(db, user, row.person_id) if row.person_id else None
    site = by_org(db, Worksite, row.site_id, user.org_id)
    return {"id": row.id, "revision": row.revision, "site_id": row.site_id,
            "site_name": site.name, "company_id": row.company_id, "company_name": company.name,
            "person_id": row.person_id, "person_name": person.name if person else None,
            "relationship": row.relationship, "parent_name": row.parent_name,
            "shared": row.shared, "document_data": row.document_data,
            "selected_codes": row.selected_codes, "updated_at": row.updated_at.isoformat()}



class LocalIdentityCorrection(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=240)
    rut: str | None = Field(default=None, max_length=30)


@router.patch("/companies/{ident}")
def correct_company(ident: str, payload: LocalIdentityCorrection,
                    user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Only changes the private documentary copy, never the operational Contractor."""
    company = _company(db, user, ident)
    if payload.name is not None:
        company.name = payload.name.strip()
    if payload.rut is not None:
        company.rut = payload.rut.strip() or None
    company.updated_at = utcnow()
    audit(db, user, "javiera.local_company_corrected", company.id)
    db.commit()
    return _company_dict(company)


@router.patch("/people/{ident}")
def correct_person(ident: str, payload: LocalIdentityCorrection,
                   user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Only changes the private documentary copy, never an operational Worker."""
    person = _person(db, user, ident)
    if payload.name is not None:
        person.name = payload.name.strip()
    if payload.rut is not None:
        person.rut = payload.rut.strip() or None
    person.updated_at = utcnow()
    audit(db, user, "javiera.local_person_corrected", person.id)
    db.commit()
    return _person_dict(person)


@router.post("/dossiers")
def save_dossier(payload: DossierInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    _only_codes(payload.selected_codes)
    _safe_data({"shared": payload.shared, "document_data": payload.document_data})
    site = by_org(db, Worksite, payload.site_id, user.org_id)
    company = _company(db, user, payload.company_id)
    if company.site_id != site.id:
        raise HTTPException(422, "Empresa de otra obra")
    if payload.person_id and _person(db, user, payload.person_id).company_id != company.id:
        raise HTTPException(422, "Persona de otra empresa")
    if payload.relationship == "subcontractor" and not (payload.parent_name or "").strip():
        raise HTTPException(422, "Indica el contratista principal")
    if "sworn_declaration" in payload.selected_codes and (
        payload.person_id or len(payload.selected_codes) > 1):
        raise HTTPException(422, "La declaración de ausencia de trabajadores exige un expediente de empresa separado")
    if not isinstance(payload.document_data, dict) or any(
        code not in DOCUMENT_BY_CODE or not isinstance(v, dict)
        for code, v in payload.document_data.items()):
        raise HTTPException(422, "Datos específicos inválidos")
    if payload.dossier_id:
        record = _dossier(db, user, payload.dossier_id)
        if record.revision != payload.expected_revision:
            raise HTTPException(409, "La ficha fue modificada. Recarga antes de guardar")
        if (record.site_id, record.company_id, record.person_id, record.relationship) != (
            payload.site_id, payload.company_id, payload.person_id, payload.relationship):
            raise HTTPException(409, "No se permite reasignar un expediente a otra identidad")
        if (record.parent_name or "", record.shared, record.document_data, record.selected_codes) == (
            payload.parent_name or "", payload.shared, payload.document_data, payload.selected_codes):
            return _dossier_dict(record, db, user)
        record.revision += 1
    else:
        record = JavieraLocalDossier(org_id=user.org_id, site_id=site.id,
            company_id=company.id, person_id=payload.person_id,
            relationship=payload.relationship, updated_by=user.id)
        db.add(record)
    record.parent_name = (payload.parent_name or "").strip() or None
    record.shared = payload.shared
    record.document_data = payload.document_data
    record.selected_codes = payload.selected_codes
    record.updated_by = user.id
    record.updated_at = utcnow()
    db.flush()
    audit(db, user, "javiera.local_dossier_saved", record.id)
    db.commit()
    return _dossier_dict(record, db, user)


@router.get("/dossiers")
def dossiers(site_id: str = "", user: User = Depends(administrator), db: Session = Depends(get_db)):
    q = select(JavieraLocalDossier).where(JavieraLocalDossier.org_id == user.org_id)
    if site_id:
        by_org(db, Worksite, site_id, user.org_id)
        q = q.where(JavieraLocalDossier.site_id == site_id)
    records = db.scalars(q.order_by(JavieraLocalDossier.updated_at.desc()).limit(100)).all()
    return [_dossier_dict(r, db, user) for r in records]


@router.get("/dossiers/{ident}")
def get_dossier(ident: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    return _dossier_dict(_dossier(db, user, ident), db, user)


@router.get("/dossiers/{ident}/eligibility")
def evaluate(ident: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    record = _dossier(db, user, ident)
    docs = []
    for code in record.selected_codes:
        item, data, previous = _status(db, user, record, code)
        result = {**item, "requires_reissue_reason": bool(previous and item["can_issue"]),
                  "last_issue_id": previous.id if previous else None}
        docs.append(result)
    return {"documents": docs, "revision": record.revision}


def _build_pdf(db, user, record, code, data, preview=False):
    layout = latest_layout(db, user.org_id, code)
    if layout:
        return make_pdf(db, user, layout, data, preview=preview), layout.revision, "excel"
    template = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    if not template or template.published_version <= 0 or not template.body:
        raise HTTPException(409, "Plantilla no aprobada")
    output = render_tokens(template.body, data)
    if code in {"pts", "irl", "pts_receipt"}:
        kind = "IRL" if code == "irl" else "PTS"
        cargo = normalize_cargo(data.get("role"))
        matrix = latest_approved_matrix(db, user.org_id, kind, cargo)
        if not matrix:
            raise HTTPException(409, "Matriz preventiva no aprobada")
        if code != "pts_receipt":
            output += "\n\n" + kind + " · " + matrix.cargo + " · Revisión " + str(matrix.revision)
            for index, section in enumerate(matrix.sections, 1):
                output += "\n\n" + str(index) + ". " + str(section)
    return pdf_for(template.title, output, preview, template.layout), template.published_version, "structured"


@router.post("/preview")
def preview(payload: PreviewInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    record = _dossier(db, user, payload.dossier_id)
    if payload.code not in record.selected_codes:
        raise HTTPException(422, "Selecciona el documento primero")
    item, data, _ = _status(db, user, record, payload.code)
    if not item["can_issue"]:
        raise HTTPException(409, {"reason": item["reason"], "missing_fields": item["missing_fields"],
                                  "errors": item["blocking_errors"], "status": item["status"]})
    raw, _, _ = _build_pdf(db, user, record, payload.code, data, preview=True)
    return Response(content=raw, media_type="application/pdf",
                    headers={"Cache-Control": "no-store"})


def _store(db, user, record, code, reason=""):
    item, data, previous = _status(db, user, record, code)
    if not item["can_issue"]:
        return {"code": code, "ok": False, "reason": item["reason"] or item["status"],
                "missing_fields": item["missing_fields"], "errors": item["blocking_errors"]}
    # Lock the documentary dossier while deciding reuse or reissue.
    db.scalar(select(JavieraLocalDossier.id).where(
        JavieraLocalDossier.org_id == user.org_id,
        JavieraLocalDossier.id == record.id).with_for_update())
    layout = latest_layout(db, user.org_id, code)
    template = template_data(db, user.org_id).get(code) or {}
    revision = layout.revision if layout else template.get("published_version", 0)
    source = "excel" if layout else "structured"
    signature = hashlib.sha256(json.dumps(
        {"data": data, "template": revision, "source": source},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    all_issued = db.scalars(select(JavieraLocalIssue).where(
        JavieraLocalIssue.org_id == user.org_id,
        JavieraLocalIssue.dossier_id == record.id,
        JavieraLocalIssue.code == code).order_by(JavieraLocalIssue.issued_at.desc())).all()
    for old in all_issued:
        if old.snapshot.get("signature") == signature:
            return {"code": code, "ok": True, "id": old.id, "reused": True}
    if all_issued and len(reason.strip()) < 20:
        return {"code": code, "ok": False,
                "reason": "Documento anterior: indica motivo de reemisión (mínimo 20 caracteres)"}
    raw, revision, source = _build_pdf(db, user, record, code, data, preview=False)
    folder = settings().document_dir / user.org_id / "javiera-v166" / record.id
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    ident = str(uuid4())
    path = folder / (ident + ".pdf")
    try:
        with path.open("xb") as writer:
            writer.write(raw)
        path.chmod(0o600)
        row = JavieraLocalIssue(id=ident, org_id=user.org_id,
            dossier_id=record.id, code=code, dossier_revision=record.revision,
            template_revision=revision,
            snapshot={"data": data, "signature": signature, "source": source},
            sha256=hashlib.sha256(raw).hexdigest(), storage_path=str(path),
            issued_by=user.id, reissue_reason=reason.strip() or None)
        db.add(row)
        audit(db, user, "javiera.local_pdf_issued", ident)
        db.commit()
        return {"code": code, "ok": True, "id": ident, "reused": False}
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise


def _file(db, user, ident):
    row = by_org(db, JavieraLocalIssue, ident, user.org_id)
    safe = (settings().document_dir / user.org_id / "javiera-v166").resolve()
    path = Path(row.storage_path).resolve()
    if not path.is_relative_to(safe) or not path.is_file():
        raise HTTPException(404, "PDF privado no disponible")
    return row, path


@router.post("/issue/batch")
def issue_batch(payload: BatchInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    record = _dossier(db, user, payload.dossier_id)
    _only_codes(payload.codes)
    if any(c not in record.selected_codes for c in payload.codes):
        raise HTTPException(422, "Los documentos deben estar seleccionados en el expediente")
    results = []
    for code in payload.codes:
        try:
            results.append(_store(db, user, record, code, payload.reissue_reasons.get(code, "")))
        except HTTPException as exc:
            db.rollback()
            result = exc.detail if isinstance(exc.detail, str) else exc.detail.get("reason", "Documento bloqueado")
            results.append({"code": code, "ok": False, "reason": result})
        except Exception:
            db.rollback()
            results.append({"code": code, "ok": False, "reason": "Error técnico de emisión. Revisar logs del servidor."})
    batch = JavieraLocalBatch(org_id=user.org_id, dossier_id=record.id,
        codes=payload.codes, results=results, created_by=user.id)
    db.add(batch)
    db.flush()
    success = [r["id"] for r in results if r["ok"]]
    if success:
        output = fitz.open()
        for ident in success:
            _, path = _file(db, user, ident)
            with fitz.open(str(path)) as original:
                output.insert_pdf(original)
        folder = settings().document_dir / user.org_id / "javiera-v166" / record.id
        filename = folder / ("paquete-" + batch.id + ".pdf")
        with filename.open("xb") as writer:
            writer.write(output.tobytes(garbage=4, deflate=True))
        filename.chmod(0o600)
        output.close()
        batch.storage_path = str(filename)
    audit(db, user, "javiera.local_batch_created", batch.id)
    db.commit()
    return {"id": batch.id, "results": results, "total": len(results),
            "issued": len(success), "failed": len(results) - len(success),
            "pdf_url": ("/api/v1/javiera/v166/batches/" + batch.id + "/pdf") if success else None}


@router.get("/batches/{ident}/pdf")
def batch_pdf(ident: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = by_org(db, JavieraLocalBatch, ident, user.org_id)
    safe = (settings().document_dir / user.org_id / "javiera-v166").resolve()
    path = Path(row.storage_path).resolve() if row.storage_path else None
    if not path or not path.is_relative_to(safe) or not path.is_file():
        raise HTTPException(404, "Paquete PDF no disponible")
    return FileResponse(path, media_type="application/pdf", filename="JAVIERA-paquete.pdf",
                        content_disposition_type="inline", headers={"Cache-Control": "no-store"})


@router.get("/issues/{ident}/pdf")
def issued_pdf(ident: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    row, path = _file(db, user, ident)
    return FileResponse(path, media_type="application/pdf",
                        filename="JAVIERA-" + row.code + ".pdf",
                        content_disposition_type="inline", headers={"Cache-Control": "no-store"})


@router.get("/history")
def history(dossier_id: str = "", user: User = Depends(administrator), db: Session = Depends(get_db)):
    query = select(JavieraLocalIssue).where(JavieraLocalIssue.org_id == user.org_id)
    batches = select(JavieraLocalBatch).where(JavieraLocalBatch.org_id == user.org_id)
    if dossier_id:
        _dossier(db, user, dossier_id)
        query = query.where(JavieraLocalIssue.dossier_id == dossier_id)
        batches = batches.where(JavieraLocalBatch.dossier_id == dossier_id)
    issues = db.scalars(query.order_by(JavieraLocalIssue.issued_at.desc()).limit(300)).all()
    groups = db.scalars(batches.order_by(JavieraLocalBatch.created_at.desc()).limit(120)).all()
    return {"issues": [{"id": r.id, "dossier_id": r.dossier_id, "code": r.code,
                         "issued_at": r.issued_at.isoformat(), "sha256": r.sha256,
                         "template_revision": r.template_revision, "issued_by": r.issued_by,
                         "reissue_reason": r.reissue_reason} for r in issues],
            "batches": [{"id": b.id, "dossier_id": b.dossier_id,
                         "codes": b.codes, "results": b.results,
                         "created_at": b.created_at.isoformat(),
                         "has_pdf": bool(b.storage_path)} for b in groups]}
