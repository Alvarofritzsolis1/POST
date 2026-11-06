"""Proyecto JAVIERA v16 — APIs privadas para expedientes, editor y PDF.

No existe publicación automática de cláusulas, matrices, acuses o firmas.
Toda salida definitiva requiere plantilla y matriz aprobadas por otro admin.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import fitz
from openpyxl import load_workbook
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .javiera_logic import (DOCUMENTS, DOCUMENT_BY_CODE, check_template_fields,
                            eligibility, normalize_cargo, render_tokens)
from .javiera_models import (JavieraDossier, JavieraHistory, JavieraIssue,
                             JavieraMatrix, JavieraRevision, JavieraTemplate)
from .models import AuditEvent, User, utcnow
from .ops_models import Contractor, ContractorWorksite, Worker, WorkerAssignment, Worksite
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera", tags=["Proyecto JAVIERA"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DossierInput(Strict):
    site_id: str
    employer_id: str
    worker_id: str | None = None
    parent_id: str | None = None
    relationship: str = Field(pattern="^(contractor|subcontractor)$")
    data: dict = Field(default_factory=dict)
    expected_revision: int | None = None


class Evaluation(Strict):
    data: dict = Field(default_factory=dict)
    dossier_id: str | None = None
    data_revision: int = 0


class Action(Strict):
    dossier_id: str
    code: str


class TemplateChange(Strict):
    title: str = Field(min_length=3, max_length=180)
    area: str = Field(min_length=3, max_length=65)
    body: str = Field(min_length=20, max_length=35000)
    fields: list[str] = Field(min_length=1, max_length=70)
    rule: dict = Field(default_factory=dict)
    layout: dict = Field(default_factory=dict)
    reason: str = Field(min_length=6, max_length=500)


class MatrixChange(Strict):
    kind: str = Field(pattern="^(PTS|IRL)$")
    cargo: str = Field(min_length=2, max_length=160)
    sections: list[str] = Field(min_length=1, max_length=35)
    source: str = Field(default="", max_length=180)


class HistoryReview(Strict):
    verified: bool
    reason: str = Field(min_length=6, max_length=300)


def audit(db: Session, user: User, action: str, resource: str):
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action=action, resource_id=resource))


def by_org(db: Session, cls, ident: str, org: str):
    result = db.get(cls, ident)
    if result is None or result.org_id != org:
        raise HTTPException(404, "Registro no encontrado")
    return result


def dossier(db, user, ident):
    return by_org(db, JavieraDossier, ident, user.org_id)


def template_data(db, org):
    rows = db.scalars(select(JavieraTemplate).where(JavieraTemplate.org_id == org)).all()
    result = {}
    for row in rows:
        draft = db.scalar(select(JavieraRevision).where(
            JavieraRevision.org_id == org, JavieraRevision.template_id == row.id,
            JavieraRevision.state == "draft").order_by(JavieraRevision.revision.desc()))
        result[row.code] = {"area": row.area, "title": row.title, "fields": row.fields,
            "rule": row.rule, "published_version": row.published_version,
            "has_body": bool(row.body or (draft and draft.contents.get("body")))}
    return result


def resolve_data(db: Session, user: User, record: DossierInput) -> dict:
    if len(json.dumps(record.data, ensure_ascii=False)) > 24000:
        raise HTTPException(413, "Ficha demasiado extensa")
    site = by_org(db, Worksite, record.site_id, user.org_id)
    employer = by_org(db, Contractor, record.employer_id, user.org_id)
    if not db.scalar(select(ContractorWorksite.id).where(
        ContractorWorksite.org_id == user.org_id,
        ContractorWorksite.worksite_id == site.id,
        ContractorWorksite.contractor_id == employer.id)):
        raise HTTPException(422, "El empleador no está vinculado con la obra")
    if record.parent_id:
        parent = by_org(db, Contractor, record.parent_id, user.org_id)
        if parent.id == employer.id:
            raise HTTPException(422, "El contratista principal debe ser diferente")
        if record.relationship != "subcontractor":
            raise HTTPException(422, "Indica el tipo Subcontratos")
    elif record.relationship == "subcontractor":
        raise HTTPException(422, "Indica el contratista principal")
    worker = None
    if record.worker_id:
        worker = by_org(db, Worker, record.worker_id, user.org_id)
        assigned = db.scalar(select(WorkerAssignment.id).where(
            WorkerAssignment.org_id == user.org_id,
            WorkerAssignment.worker_id == worker.id,
            WorkerAssignment.contractor_id == employer.id,
            WorkerAssignment.worksite_id == site.id))
        if not assigned:
            raise HTTPException(422, "Trabajador sin vínculo con el empleador en esta obra")
    data = json.loads(json.dumps(record.data, ensure_ascii=False))
    data["employer"] = {"name": employer.name, "rut": employer.rut or ""}
    data["site"] = {"name": site.name}
    data["worker"] = {"name": worker.name, "rut": worker.rut or ""} if worker else {"name": "", "rut": ""}
    return data


def evaluated(db: Session, user: User, data: dict, dossier_id: str | None):
    templates = template_data(db, user.org_id)
    cargo = normalize_cargo(data.get("role"))
    matrix_rows = db.execute(select(JavieraMatrix.kind, JavieraMatrix.cargo).where(
        JavieraMatrix.org_id == user.org_id, JavieraMatrix.status == "approved")).all()
    approved = {kind + ":" + matrix_cargo for kind, matrix_cargo in matrix_rows}
    existing, history = set(), set()
    if dossier_id:
        record = dossier(db, user, dossier_id)
        existing = set(db.scalars(select(JavieraIssue.code).where(
            JavieraIssue.org_id == user.org_id, JavieraIssue.dossier_id == dossier_id,
            JavieraIssue.dossier_revision == record.revision)).all())
        history = set(db.scalars(select(JavieraIssue.code).where(
            JavieraIssue.org_id == user.org_id, JavieraIssue.dossier_id == dossier_id,
            JavieraIssue.dossier_revision != record.revision)).all())
        history.update(db.scalars(select(JavieraHistory.code).where(
            JavieraHistory.org_id == user.org_id, JavieraHistory.dossier_id == dossier_id)).all())
    return eligibility(data, templates, approved, existing, history)


def pdf_for(title: str, body: str, draft: bool) -> bytes:
    """Generación A4 sin ejecución HTML/JS ni escritura de campos por el cliente."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 50
    page.insert_text((45, y), "GALANT · PROYECTO JAVIERA", fontsize=10, fontname="helv")
    y += 34
    if draft:
        page.insert_text((45, y), "VISTA PREVIA · NO VÁLIDO PARA FIRMA NI ENTREGA",
                         fontsize=10, color=(0.75, 0.2, 0.2))
        y += 35
    for chunk in [title, "", *body.splitlines()]:
        lines = []
        # Fit in A4 with explicit word wrapping, avoiding text clipping.
        for paragraph in (chunk or " ").split("\n"):
            words = paragraph.split()
            line = ""
            for word in words:
                candidate = (line + " " + word).strip()
                if fitz.get_text_length(candidate, fontname="helv", fontsize=10) > 495 and line:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line or " ")
        for line in lines:
            if y > 775:
                page = doc.new_page(width=595, height=842)
                y = 55
            page.insert_text((48, y), line[:350], fontsize=10, fontname="helv")
            y += 16
    out = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return out


@router.get("/catalog")
def catalog(user: User = Depends(administrator), db: Session = Depends(get_db)):
    configured = template_data(db, user.org_id)
    return [{"code": code, "area": configured.get(code, {}).get("area", area),
             "title": configured.get(code, {}).get("title", title),
             "required_fields": configured.get(code, {}).get("fields", fields),
             "published_version": configured.get(code, {}).get("published_version", 0)}
            for code, area, title, _, fields in DOCUMENTS]


@router.get("/sources")
def sources(site_id: str = "", contractor_id: str = "",
            user: User = Depends(administrator), db: Session = Depends(get_db)):
    sites = db.scalars(select(Worksite).where(Worksite.org_id == user.org_id)
                       .order_by(Worksite.name).limit(100)).all()
    company_query = select(ContractorWorksite, Contractor).join(
        Contractor, ContractorWorksite.contractor_id == Contractor.id).where(
        ContractorWorksite.org_id == user.org_id)
    if site_id:
        by_org(db, Worksite, site_id, user.org_id)
        company_query = company_query.where(ContractorWorksite.worksite_id == site_id)
    companies = db.execute(company_query.limit(500)).all()
    workers = []
    if site_id and contractor_id:
        by_org(db, Contractor, contractor_id, user.org_id)
        assignments = db.execute(select(WorkerAssignment, Worker).join(
            Worker, WorkerAssignment.worker_id == Worker.id).where(
            WorkerAssignment.org_id == user.org_id, WorkerAssignment.worksite_id == site_id,
            WorkerAssignment.contractor_id == contractor_id).limit(500)).all()
        workers = [{"id": w.id, "name": w.name, "rut": w.rut,
                    "active": a.active} for a, w in assignments]
    return {"sites": [{"id": s.id, "name": s.name} for s in sites],
            "contractors": [{"id": c.id, "site_id": a.worksite_id,
                             "name": c.name, "rut": c.rut, "nature": c.nature}
                            for a, c in companies],
            "workers": workers}


@router.post("/dossiers")
def save_dossier(payload: DossierInput,
                 user: User = Depends(administrator), db: Session = Depends(get_db)):
    data = resolve_data(db, user, payload)
    record = None
    dossier_id = payload.data.get("_dossier_id")
    if dossier_id:
        record = dossier(db, user, dossier_id)
        if payload.expected_revision != record.revision:
            raise HTTPException(409, "Otro usuario modificó la ficha. Recarga antes de guardar")
    if record is None:
        record = JavieraDossier(org_id=user.org_id, updated_by=user.id)
        db.add(record)
    record.site_id = payload.site_id
    record.employer_id = payload.employer_id
    record.worker_id = payload.worker_id
    record.parent_id = payload.parent_id
    record.relationship = payload.relationship
    data.pop("_dossier_id", None)
    record.data = data
    record.revision = (record.revision + 1) if dossier_id else 1
    record.updated_at = utcnow()
    record.updated_by = user.id
    db.flush()
    audit(db, user, "javiera.dossier_saved", record.id)
    db.commit()
    return {"id": record.id, "revision": record.revision, "data": data}


@router.get("/dossiers")
def list_dossiers(site_id: str = "", employer_id: str = "", user: User = Depends(administrator),
                  db: Session = Depends(get_db)):
    query = select(JavieraDossier).where(JavieraDossier.org_id == user.org_id)
    if site_id:
        by_org(db, Worksite, site_id, user.org_id)
        query = query.where(JavieraDossier.site_id == site_id)
    if employer_id:
        by_org(db, Contractor, employer_id, user.org_id)
        query = query.where(JavieraDossier.employer_id == employer_id)
    rows = db.scalars(query.order_by(JavieraDossier.updated_at.desc()).limit(120)).all()
    return [{"id": r.id, "site_id": r.site_id, "employer_id": r.employer_id,
             "worker_id": r.worker_id, "relationship": r.relationship,
             "revision": r.revision, "updated_at": r.updated_at.isoformat()} for r in rows]


@router.get("/dossiers/{dossier_id}")
def get_dossier(dossier_id: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = dossier(db, user, dossier_id)
    issues = db.scalars(select(JavieraIssue).where(
        JavieraIssue.org_id == user.org_id, JavieraIssue.dossier_id == row.id).order_by(
        JavieraIssue.issued_at.desc()).limit(100)).all()
    historical = db.scalars(select(JavieraHistory).where(
        JavieraHistory.org_id == user.org_id, JavieraHistory.dossier_id == row.id).limit(100)).all()
    return {"id": row.id, "revision": row.revision, "data": row.data,
            "site_id": row.site_id, "employer_id": row.employer_id,
            "parent_id": row.parent_id, "worker_id": row.worker_id,
            "relationship": row.relationship,
            "issues": [{"id": d.id, "code": d.code, "at": d.issued_at.isoformat(),
                        "sha256": d.sha256, "version": d.template_revision,
                        "evidence": "no_presentada"} for d in issues],
            "historical": [{"id": h.id, "code": h.code, "state": h.evidence_state,
                            "comment": h.comment} for h in historical]}


@router.post("/eligibility/evaluate")
def evaluate(payload: Evaluation, user: User = Depends(administrator), db: Session = Depends(get_db)):
    if len(json.dumps(payload.data, ensure_ascii=False)) > 24000:
        raise HTTPException(413, "Ficha demasiado extensa")
    if payload.dossier_id:
        dossier(db, user, payload.dossier_id)
    data = payload.data
    return {"data_revision": payload.data_revision,
            "documents": evaluated(db, user, data, payload.dossier_id)}


def prepared(db, user, ident: str, code: str, preview: bool):
    if code not in DOCUMENT_BY_CODE:
        raise HTTPException(404, "Documento desconocido")
    record = dossier(db, user, ident)
    result = next(d for d in evaluated(db, user, record.data, ident) if d["code"] == code)
    if (preview and not result["can_preview"]) or (not preview and not result["can_issue"]):
        raise HTTPException(409, {"error": "Documento bloqueado", "status": result["status"],
                                  "missing_fields": result["missing_fields"],
                                  "errors": result["blocking_errors"], "reason": result["reason"]})
    template = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    if not template:
        raise HTTPException(409, "Plantilla pendiente de configuración")
    if not preview and template.published_version == 0:
        raise HTTPException(409, "Plantilla no aprobada")
    body = template.body
    title = template.title
    if preview and not body:
        draft = db.scalar(select(JavieraRevision).where(
            JavieraRevision.org_id == user.org_id, JavieraRevision.template_id == template.id,
            JavieraRevision.state == "draft").order_by(JavieraRevision.revision.desc()))
        if draft:
            body = draft.contents.get("body", "")
            title = draft.contents.get("title", title)
    if not body:
        raise HTTPException(409, "Plantilla sin contenido previsualizable")
    output = render_tokens(body, record.data)
    if code in {"pts", "irl", "pts_receipt"}:
        kind = "IRL" if code == "irl" else "PTS"
        cargo = normalize_cargo(record.data.get("role"))
        matrix = db.scalar(select(JavieraMatrix).where(
            JavieraMatrix.org_id == user.org_id,
            JavieraMatrix.kind == kind, JavieraMatrix.cargo == cargo,
            JavieraMatrix.status == "approved").order_by(JavieraMatrix.revision.desc()))
        if not matrix:
            raise HTTPException(409, "Matriz preventiva pendiente de aprobación")
        if code != "pts_receipt":
            output += "\n\n" + kind + " · " + matrix.cargo + " · Revisión " + str(matrix.revision)
            for number, section in enumerate(matrix.sections, 1):
                output += "\n\n" + str(number) + ". " + str(section)
    return record, template, title, output


@router.post("/preview")
def preview(data: Action, user: User = Depends(administrator), db: Session = Depends(get_db)):
    record, template, title, text = prepared(db, user, data.dossier_id, data.code, True)
    return Response(content=pdf_for(title, text, True),
                    media_type="application/pdf", headers={"Cache-Control": "no-store"})


@router.post("/issue")
def issue(data: Action, user: User = Depends(administrator), db: Session = Depends(get_db)):
    record, template, title, text = prepared(db, user, data.dossier_id, data.code, False)
    existing = db.scalar(select(JavieraIssue).where(
        JavieraIssue.org_id == user.org_id, JavieraIssue.dossier_id == record.id,
        JavieraIssue.code == data.code, JavieraIssue.template_revision == template.published_version,
        JavieraIssue.dossier_revision == record.revision))
    if existing:
        return {"id": existing.id, "sha256": existing.sha256, "reused": True}
    raw = pdf_for(title, text, False)
    digest = hashlib.sha256(raw).hexdigest()
    ident = str(uuid4())
    directory = settings().document_dir / user.org_id / "javiera" / record.id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    location = directory / (ident + ".pdf")
    try:
        with location.open("xb") as handle:
            handle.write(raw)
        location.chmod(0o600)
        obj = JavieraIssue(id=ident, org_id=user.org_id, dossier_id=record.id,
            code=data.code, template_revision=template.published_version,
            dossier_revision=record.revision, snapshot={"data": record.data,
                "title": template.title, "body": template.body, "fields": template.fields,
                "layout": template.layout, "rendered": text},
            sha256=digest, storage_path=str(location), issued_by=user.id)
        db.add(obj)
        audit(db, user, "javiera.pdf_issued", obj.id)
        db.commit()
    except Exception:
        db.rollback()
        location.unlink(missing_ok=True)
        raise
    return {"id": ident, "sha256": digest, "reused": False}


@router.get("/issued/{issue_id}/pdf")
def issued_pdf(issue_id: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    item = by_org(db, JavieraIssue, issue_id, user.org_id)
    path = Path(item.storage_path)
    allowed = (settings().document_dir / user.org_id / "javiera").resolve()
    if not path.resolve().is_relative_to(allowed) or not path.is_file():
        raise HTTPException(404, "PDF no disponible")
    return FileResponse(path, media_type="application/pdf",
                        filename="GALANT-JAVIERA-" + item.code + ".pdf")


@router.get("/admin/templates")
def admin_templates(user: User = Depends(administrator), db: Session = Depends(get_db)):
    rows = {r.code: r for r in db.scalars(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id)).all()}
    result = []
    for code, area, title, _, required in DOCUMENTS:
        row = rows.get(code)
        revisions = db.scalars(select(JavieraRevision).where(
            JavieraRevision.org_id == user.org_id, JavieraRevision.template_id == row.id
        ).order_by(JavieraRevision.revision.desc()).limit(5)).all() if row else []
        result.append({"code": code, "title": row.title if row else title,
            "area": row.area if row else area, "body": row.body if row else "",
            "fields": row.fields if row else required,
            "rule": row.rule if row else {}, "layout": row.layout if row else {},
            "published_version": row.published_version if row else 0,
            "revisions": [{"revision": v.revision, "state": v.state,
                           "author_id": v.author_id, "reason": v.reason,
                           "contents": v.contents} for v in revisions]})
    return result


@router.put("/admin/templates/{code}")
def change_template(code: str, change: TemplateChange, user: User = Depends(administrator),
                    db: Session = Depends(get_db)):
    if code not in DOCUMENT_BY_CODE:
        raise HTTPException(404, "Tipo documental desconocido")
    try:
        check_template_fields(change.fields, change.body)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    row = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    if not row:
        row = JavieraTemplate(org_id=user.org_id, code=code,
            title=DOCUMENT_BY_CODE[code][2], area=DOCUMENT_BY_CODE[code][1],
            fields=DOCUMENT_BY_CODE[code][4])
        db.add(row)
        db.flush()
    last = db.scalar(select(func.max(JavieraRevision.revision)).where(
        JavieraRevision.template_id == row.id)) or 0
    revision = JavieraRevision(org_id=user.org_id, template_id=row.id, revision=last + 1,
        contents={"title": change.title, "area": change.area, "body": change.body,
                  "fields": change.fields, "rule": change.rule, "layout": change.layout},
        author_id=user.id, reason=change.reason)
    db.add(revision)
    db.flush()
    audit(db, user, "javiera.template_draft", revision.id)
    db.commit()
    return {"revision": revision.revision, "state": revision.state,
            "message": "Borrador guardado; requiere revisión por otro administrador"}


@router.post("/admin/templates/{code}/approve/{revision}")
def approve_template(code: str, revision: int,
                     user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    if not row:
        raise HTTPException(404, "Plantilla no encontrada")
    item = db.scalar(select(JavieraRevision).where(
        JavieraRevision.org_id == user.org_id,
        JavieraRevision.template_id == row.id, JavieraRevision.revision == revision))
    if not item or item.state != "draft":
        raise HTTPException(409, "Versión no disponible para aprobación")
    if item.author_id == user.id:
        raise HTTPException(403, "La aprobación requiere un segundo administrador")
    if revision <= row.published_version:
        raise HTTPException(409, "No se puede reemplazar con una revisión anterior")
    obj = item.contents
    row.title, row.area, row.body = obj["title"], obj["area"], obj["body"]
    row.fields, row.rule, row.layout = obj["fields"], obj["rule"], obj["layout"]
    row.published_version, row.updated_at = revision, utcnow()
    item.state, item.reviewer_id, item.reviewed_at = "published", user.id, utcnow()
    audit(db, user, "javiera.template_published", item.id)
    db.commit()
    return {"code": code, "published_version": revision}


@router.get("/admin/matrices")
def matrices(kind: str = "", user: User = Depends(administrator), db: Session = Depends(get_db)):
    query = select(JavieraMatrix).where(JavieraMatrix.org_id == user.org_id)
    if kind:
        if kind not in {"PTS", "IRL"}:
            raise HTTPException(422, "Matriz inválida")
        query = query.where(JavieraMatrix.kind == kind)
    rows = db.scalars(query.order_by(JavieraMatrix.cargo, JavieraMatrix.revision.desc()).limit(800)).all()
    return [{"id": r.id, "kind": r.kind, "cargo": r.cargo, "revision": r.revision,
             "sections": r.sections, "status": r.status, "source": r.source,
             "author_id": r.author_id} for r in rows]


@router.post("/admin/matrices")
def change_matrix(item: MatrixChange, user: User = Depends(administrator),
                  db: Session = Depends(get_db)):
    cargo = normalize_cargo(item.cargo)
    if item.kind == "PTS" and (len(item.sections) != 17 or any(not str(s).strip() for s in item.sections)):
        raise HTTPException(422, "PTS requiere 17 secciones con contenido")
    if len(json.dumps(item.sections, ensure_ascii=False)) > 50000:
        raise HTTPException(413, "Matriz excesivamente grande")
    version = db.scalar(select(func.max(JavieraMatrix.revision)).where(
        JavieraMatrix.org_id == user.org_id, JavieraMatrix.kind == item.kind,
        JavieraMatrix.cargo == cargo)) or 0
    row = JavieraMatrix(org_id=user.org_id, kind=item.kind, cargo=cargo,
        revision=version + 1, sections=item.sections, source=item.source,
        author_id=user.id)
    db.add(row)
    db.flush()
    audit(db, user, "javiera.matrix_draft", row.id)
    db.commit()
    return {"id": row.id, "revision": row.revision, "status": row.status}


@router.post("/admin/matrices/{matrix_id}/approve")
def approve_matrix(matrix_id: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = by_org(db, JavieraMatrix, matrix_id, user.org_id)
    if row.status != "draft":
        raise HTTPException(409, "Matriz no está en borrador")
    if row.author_id == user.id:
        raise HTTPException(403, "Requiere validación independiente de prevención")
    row.status, row.reviewer_id = "approved", user.id
    audit(db, user, "javiera.matrix_approved", row.id)
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/dossiers/{dossier_id}/history/{code}")
async def upload_historical(dossier_id: str, code: str, file: UploadFile = File(...),
                            user: User = Depends(administrator), db: Session = Depends(get_db)):
    record = dossier(db, user, dossier_id)
    if code not in DOCUMENT_BY_CODE:
        raise HTTPException(404, "Documento no identificado")
    raw = await file.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "Máximo 10 MB")
    if not raw.startswith(b"%PDF-"):
        raise HTTPException(415, "Se requiere PDF válido")
    try:
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            if pdf.is_encrypted or pdf.page_count < 1 or pdf.page_count > 200:
                raise HTTPException(422, "PDF no admitido")
    except fitz.FileDataError:
        raise HTTPException(422, "PDF dañado") from None
    ident = str(uuid4())
    root = settings().document_dir / user.org_id / "javiera" / record.id
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / (ident + "-historico.pdf")
    with path.open("xb") as output:
        output.write(raw)
    path.chmod(0o600)
    row = JavieraHistory(id=ident, org_id=user.org_id, dossier_id=record.id,
        code=code, sha256=hashlib.sha256(raw).hexdigest(), storage_path=str(path),
        evidence_state="pending", uploaded_by=user.id)
    db.add(row)
    audit(db, user, "javiera.history_uploaded", row.id)
    db.commit()
    return {"id": ident, "status": "pending", "message": "Requiere verificación independiente"}


@router.post("/admin/history/{history_id}/verify")
def verify_history(history_id: str, data: HistoryReview,
                   user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = by_org(db, JavieraHistory, history_id, user.org_id)
    if row.uploaded_by == user.id:
        raise HTTPException(403, "No puedes verificar tu propia carga")
    if row.evidence_state != "pending":
        raise HTTPException(409, "Documento ya revisado")
    row.evidence_state = "verified" if data.verified else "rejected"
    row.verified_by, row.comment = user.id, data.reason
    audit(db, user, "javiera.history_verified", row.id)
    db.commit()
    return {"id": row.id, "state": row.evidence_state}
