"""Preview, correction and atomic import of operational spreadsheet records."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .config import settings
from .db import get_db
from .models import AuditEvent, User
from .ops_import import (HISTORICAL_MARKS, MAPPED_STATES, MAX_IMPORT_BYTES,
                         _key, parse_import, validate_rows)
from .ops_models import (Contractor, ContractorWorksite, OpsChange, Worker,
                         WorkerAssignment, Worksite)
from .security import authorized_user, editor

router = APIRouter(prefix="/api/v1/ops/imports", tags=["operational-imports"])


class CommitImport(BaseModel):
    site_id: str
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=10000)
    historical_status_mapping: dict[str, str] = Field(default_factory=dict)
    source_format: Literal["excel", "csv"]
    preview_token: str


def _row_digest(rows: list[dict[str, Any]]) -> str:
    row_ids = [str(row.get("row_id", "")) for row in rows]
    if not all(row_ids) or len(row_ids) != len(set(row_ids)):
        raise HTTPException(422, "Las filas deben conservar identificadores únicos de la vista previa")
    return hashlib.sha256("\n".join(sorted(row_ids)).encode()).hexdigest()


def _site(db: Session, user: User, site_id: str) -> Worksite:
    site = db.scalar(select(Worksite).where(Worksite.id == site_id, Worksite.org_id == user.org_id))
    if not site:
        raise HTTPException(404, "Obra no encontrada")
    return site


@router.post("/preview")
async def preview_import(file: UploadFile = File(...), site_id: str = Form(...),
                         column_map: str | None = Form(None),
                         user: User = Depends(editor), db: Session = Depends(get_db)):
    _site(db, user, site_id)
    try:
        data = await file.read(MAX_IMPORT_BYTES + 1)
        if len(data) > MAX_IMPORT_BYTES:
            raise HTTPException(413, "La planilla supera 8 MB")
        try:
            mapping = json.loads(column_map) if column_map else None
        except json.JSONDecodeError:
            raise HTTPException(422, "Mapeo de columnas inválido") from None
        if mapping is not None and not isinstance(mapping, dict):
            raise HTTPException(422, "Mapeo de columnas inválido")
        result = parse_import(data, file.filename or "", mapping)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        await file.close()
    result["source_format"] = "csv" if (file.filename or "").lower().endswith(".csv") else "excel"
    result["site_id"] = site_id
    now = datetime.now(timezone.utc)
    result["preview_token"] = jwt.encode({
        "purpose": "ops-import-preview", "org": user.org_id, "user": user.id,
        "site": site_id, "format": result["source_format"],
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "row_digest": _row_digest(result["rows"]), "row_count": len(result["rows"]),
        "iat": now, "exp": now + timedelta(minutes=30),
    }, settings().app_secret, algorithm="HS256")
    # Existing RUTs are visible during preview, without changing the database.
    existing_companies = set(db.scalars(select(Contractor.rut).where(Contractor.org_id == user.org_id)).all())
    existing_workers = set(db.scalars(select(Worker.rut).where(Worker.org_id == user.org_id)).all())
    for row in result["rows"]:
        if row["rut"] in (existing_companies if row["kind"] == "contractor" else existing_workers):
            row["warnings"].append("RUT ya registrado; se vinculará a la obra si corresponde")
    result["summary"]["warnings"] = sum(bool(row["warnings"]) for row in result["rows"])
    return result


def _status_payload(raw_values: dict[str, str], metadata: dict[str, dict[str, str | None]],
                    mapping: dict[str, str], source: str,
                    source_hash: str) -> dict[str, dict[str, str | None]]:
    return {column: {"raw": raw, "mapped": mapping.get(raw), "origin": source,
                     "source_file_sha256": source_hash, "validation": "pending",
                     "source_header": metadata[column]["source_header"],
                     "period": metadata[column]["period"],
                     "requirement": metadata[column]["requirement"]}
            for column, raw in raw_values.items()}


def _merge_statuses(record: ContractorWorksite | WorkerAssignment, incoming: dict[str, dict],
                    db: Session, user: User) -> int:
    previous = dict(record.imported_statuses or {})
    changes = {}
    for column, status in incoming.items():
        if column not in previous:
            previous[column] = status
            changes[column] = status
        elif {key: value for key, value in previous[column].items() if key != "history"} != status:
            # Never replace an earlier historic mark without preserving it.
            old = previous[column]
            history = list(old.get("history", [])) if isinstance(old, dict) else []
            history.append({key: value for key, value in old.items() if key != "history"})
            previous[column] = {**status, "history": history}
            changes[column] = previous[column]
    if not changes:
        return 0
    record.imported_statuses = previous
    db.add(OpsChange(org_id=user.org_id, user_id=user.id, entity_type=record.__tablename__,
                     entity_id=record.id, changes={"imported_statuses": changes}))
    return len(changes)


def _require_same_name(existing: Contractor | Worker, incoming: dict[str, Any]):
    if _key(existing.name) != _key(incoming["name"]):
        raise HTTPException(409, {"row_id": incoming.get("row_id"),
                                  "error": f"RUT {incoming['rut']} ya pertenece a {existing.name}; corrige la fila"})


@router.post("/commit")
def commit_import(body: CommitImport, user: User = Depends(editor), db: Session = Depends(get_db)):
    _site(db, user, body.site_id)
    try:
        attestation = jwt.decode(body.preview_token, settings().app_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(422, "La vista previa venció o no es válida; vuelve a cargar el archivo") from None
    if (attestation.get("purpose") != "ops-import-preview" or
            attestation.get("org") != user.org_id or attestation.get("user") != user.id or
            attestation.get("site") != body.site_id or attestation.get("format") != body.source_format or
            attestation.get("row_count") != len(body.rows) or
            attestation.get("row_digest") != _row_digest(body.rows)):
        raise HTTPException(422, "Las filas no corresponden a la vista previa; vuelve a cargar el archivo")
    try:
        rows = validate_rows(body.rows)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    invalid = [{"row_id": row.get("row_id"), "errors": row["errors"]} for row in rows if row["errors"]]
    if invalid:
        raise HTTPException(422, {"rows": invalid})
    raw_marks = {mark for row in rows for mark in row["historical_statuses"].values() if mark in HISTORICAL_MARKS}
    missing = raw_marks - {key.strip().upper() for key in body.historical_status_mapping}
    if missing:
        raise HTTPException(422, f"Confirma el significado histórico de: {', '.join(sorted(missing))}")
    mapping = {key.strip().upper(): value for key, value in body.historical_status_mapping.items()}
    if any(value not in MAPPED_STATES for value in mapping.values()):
        raise HTTPException(422, "Mapeo histórico no admitido")
    counters: Counter[str] = Counter()
    imported_rows = []
    try:
        contractors = {record.rut: record for record in db.scalars(
            select(Contractor).where(Contractor.org_id == user.org_id)).all() if record.rut}
        associations = {record.contractor_id: record for record in db.scalars(
            select(ContractorWorksite).where(ContractorWorksite.org_id == user.org_id,
                                             ContractorWorksite.worksite_id == body.site_id)).all()}
        workers = {record.rut: record for record in db.scalars(
            select(Worker).where(Worker.org_id == user.org_id)).all() if record.rut}
        assignments = {(record.contractor_id, record.worker_id): record for record in db.scalars(
            select(WorkerAssignment).where(WorkerAssignment.org_id == user.org_id,
                                           WorkerAssignment.worksite_id == body.site_id)).all()}
        # Contractors first, so a flat spreadsheet can list workers before the
        # company row without making the import order significant.
        for row in (item for item in rows if item["kind"] == "contractor"):
            rut = row["rut"]
            contractor = contractors.get(rut)
            created = False
            if contractor:
                _require_same_name(contractor, row)
                updated = False
                if row.get("nature") and contractor.nature not in {"unclassified", row["nature"]}:
                    raise HTTPException(409, {"row_id": row.get("row_id"), "error": "Naturaleza incompatible con empresa existente"})
                if row.get("nature") and row["nature"] != "unclassified" and contractor.nature == "unclassified":
                    if row["nature"] == "independent" and db.scalar(select(WorkerAssignment.id).where(
                            WorkerAssignment.org_id == user.org_id,
                            WorkerAssignment.contractor_id == contractor.id,
                            WorkerAssignment.active.is_(True)).limit(1)):
                        raise HTTPException(409, {"row_id": row.get("row_id"),
                                                  "error": "La empresa tiene trabajadores activos en otra obra"})
                    contractor.nature = row["nature"]
                    updated = True
                    db.add(OpsChange(org_id=user.org_id, user_id=user.id, entity_type="contractor",
                                     entity_id=contractor.id, changes={"nature": row["nature"]}))
            else:
                updated = False
                contractor = Contractor(org_id=user.org_id, name=row["name"], rut=rut,
                                        nature=row.get("nature") or "unclassified")
                db.add(contractor)
                db.flush()
                contractors[rut] = contractor
                created = True
                counters["created_contractors"] += 1
                db.add(OpsChange(org_id=user.org_id, user_id=user.id, entity_type="contractor",
                                 entity_id=contractor.id, changes={"imported": True, "source": body.source_format}))
            association = associations.get(contractor.id)
            linked = association is None
            if linked:
                association = ContractorWorksite(org_id=user.org_id, worksite_id=body.site_id,
                                                 contractor_id=contractor.id,
                                                 historical_code=row.get("historical_code") or "",
                                                 frequency=row.get("frequency") or "unclassified",
                                                 contract_status=row.get("contract_status") or "active")
                db.add(association)
                db.flush()
                associations[contractor.id] = association
                counters["linked_contractors"] += 1
                db.add(OpsChange(org_id=user.org_id, user_id=user.id, entity_type="contractor_worksite",
                                 entity_id=association.id, changes={"imported": True, "source": body.source_format}))
            else:
                for field, default in (("historical_code", ""), ("frequency", "unclassified"),
                                       ("contract_status", "active")):
                    value = row.get(field)
                    current = getattr(association, field)
                    if value and current not in {default, value}:
                        raise HTTPException(409, {"row_id": row.get("row_id"), "error": f"{field} incompatible con relación existente"})
                    if value and current == default and current != value:
                        setattr(association, field, value)
                        updated = True
                        db.add(OpsChange(org_id=user.org_id, user_id=user.id,
                                         entity_type="contractor_worksite", entity_id=association.id,
                                         changes={field: value}))
            changed = _merge_statuses(association, _status_payload(row["historical_statuses"],
                                                                 row["historical_statuses_meta"], mapping,
                                                                 body.source_format, attestation["file_sha256"]), db, user)
            counters["historical_statuses_count"] += changed
            result = "created" if created else "linked" if linked else "updated" if updated or changed else "existing"
            if result == "existing":
                counters["skipped"] += 1
            imported_rows.append({"row_id": row.get("row_id"), "result": result, "entity_id": contractor.id})
        for row in (item for item in rows if item["kind"] == "worker"):
            contractor = contractors.get(row["contractor_rut"])
            if not contractor or contractor.id not in associations:
                raise HTTPException(422, {"row_id": row.get("row_id"),
                                          "error": "Contratista no registrado en esta obra"})
            if contractor.nature == "independent":
                raise HTTPException(422, {"row_id": row.get("row_id"),
                                          "error": "Un independiente no puede tener trabajadores dependientes; corrige su naturaleza"})
            worker = workers.get(row["rut"])
            created = False
            if worker:
                _require_same_name(worker, row)
            else:
                worker = Worker(org_id=user.org_id, name=row["name"], rut=row["rut"])
                db.add(worker)
                db.flush()
                workers[worker.rut] = worker
                created = True
                counters["created_workers"] += 1
                db.add(OpsChange(org_id=user.org_id, user_id=user.id, entity_type="worker",
                                 entity_id=worker.id, changes={"imported": True, "source": body.source_format}))
            key = (contractor.id, worker.id)
            assignment = assignments.get(key)
            linked = assignment is None
            if linked:
                assignment = WorkerAssignment(org_id=user.org_id, worksite_id=body.site_id,
                                              contractor_id=contractor.id, worker_id=worker.id)
                db.add(assignment)
                db.flush()
                assignments[key] = assignment
                counters["assigned_workers"] += 1
                db.add(OpsChange(org_id=user.org_id, user_id=user.id, entity_type="worker_assignment",
                                 entity_id=assignment.id, changes={"imported": True, "source": body.source_format}))
            changed = _merge_statuses(assignment, _status_payload(row["historical_statuses"],
                                                                row["historical_statuses_meta"], mapping,
                                                                body.source_format, attestation["file_sha256"]), db, user)
            counters["historical_statuses_count"] += changed
            result = "created" if created else "assigned" if linked else "updated" if changed else "existing"
            if result == "existing":
                counters["skipped"] += 1
            imported_rows.append({"row_id": row.get("row_id"), "result": result, "entity_id": worker.id})
        db.add(AuditEvent(org_id=user.org_id, user_id=user.id, action="ops.import.committed",
                          resource_id=body.site_id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Otra importación modificó estos RUT; vuelve a previsualizar") from None
    except Exception:
        db.rollback()
        raise
    return {
        "created_contractors": counters["created_contractors"],
        "linked_contractors": counters["linked_contractors"],
        "created_workers": counters["created_workers"],
        "assigned_workers": counters["assigned_workers"],
        "skipped": counters["skipped"],
        "historical_statuses_count": counters["historical_statuses_count"],
        "imported_rows": imported_rows,
    }


TEMPLATE_HEADERS = {
    "contractors": ["tipo", "nombre", "rut", "codigo_historico", "naturaleza", "frecuencia", "estado_contractual"],
    "workers": ["tipo", "nombre", "rut", "rut_contratista"],
    "monthly": ["tipo", "nombre", "rut", "codigo_historico", "rut_contratista",
                "2026-09 Cotizaciones", "2026-09 F30-1", "2026-09 Liquidación firmada",
                "2026-09 Libro de asistencia", "2026-09 Informe de portería",
                "2026-09 Declaración jurada", "2026-09 Listado de anticipos"],
}


@router.get("/templates/{kind}")
def download_template(kind: str, format: Literal["xlsx", "csv"] = "xlsx",
                      user: User = Depends(authorized_user)):
    if kind not in TEMPLATE_HEADERS:
        raise HTTPException(404, "Plantilla no encontrada")
    headers = TEMPLATE_HEADERS[kind]
    if format == "csv":
        output = io.StringIO()
        csv.writer(output, delimiter=";").writerow(headers)
        content = ("\ufeff" + output.getvalue()).encode("utf-8")
        mime = "text/csv; charset=utf-8"
    else:
        workbook = Workbook()
        workbook.active.title = "Importación"
        workbook.active.append(headers)
        stream = io.BytesIO()
        workbook.save(stream)
        content = stream.getvalue()
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content=content, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="galant-{kind}.{format}"',
                             "Cache-Control": "no-store"})
