"""Importación histórica de contratos/anexos: preview firmado y commit atómico."""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .contract_import import canonical, parse_contracts
from .control_models import ContractAmendment, ContractRegister
from .db import get_db
from .models import User, utcnow
from .ops_api import audit_change, site_for
from .ops_import import MAX_IMPORT_BYTES
from .ops_import_api import _row_digest
from .ops_models import Contractor, ContractorWorksite, Worker, WorkerAssignment
from .security import authorized_user, editor

router = APIRouter(prefix="/api/v1/control/import/contracts", tags=["Importación contratos"])


class ContractCommit(BaseModel):
    site_id: str
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=10000)
    preview_token: str


def resolve_links(db: Session, user: User, site_id: str, row: dict) -> tuple[ContractorWorksite, WorkerAssignment | None]:
    contractor = db.scalar(select(Contractor).where(
        Contractor.org_id == user.org_id, Contractor.rut == row["contractor_rut"]))
    if contractor is None:
        raise HTTPException(422, f"Fila {row['row_id']}: RUT de contratista no registrado. Importa primero empresas.")
    association = db.scalar(select(ContractorWorksite).where(
        ContractorWorksite.org_id == user.org_id,
        ContractorWorksite.contractor_id == contractor.id,
        ContractorWorksite.worksite_id == site_id))
    if association is None:
        raise HTTPException(422, f"Fila {row['row_id']}: empresa no asociada a esta obra.")
    assignment = None
    if row["worker_rut"]:
        worker = db.scalar(select(Worker).where(
            Worker.org_id == user.org_id, Worker.rut == row["worker_rut"]))
        if worker is None:
            raise HTTPException(422, f"Fila {row['row_id']}: trabajador no registrado. Importa primero trabajadores.")
        assignment = db.scalar(select(WorkerAssignment).where(
            WorkerAssignment.org_id == user.org_id,
            WorkerAssignment.worksite_id == site_id,
            WorkerAssignment.contractor_id == contractor.id,
            WorkerAssignment.worker_id == worker.id))
        if assignment is None:
            raise HTTPException(422, f"Fila {row['row_id']}: trabajador no asignado a esta empresa y obra.")
    return association, assignment


@router.post("/preview")
async def preview_contracts(
    file: UploadFile = File(...), site_id: str = Form(...),
    user: User = Depends(editor), db: Session = Depends(get_db)
):
    site_for(db, user.org_id, site_id)
    try:
        data = await file.read(MAX_IMPORT_BYTES + 1)
        if len(data) > MAX_IMPORT_BYTES:
            raise HTTPException(413, "El archivo supera 8 MB")
        try:
            result = parse_contracts(data, file.filename or "")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    finally:
        await file.close()
    for item in result["rows"]:
        if not item["errors"]:
            try:
                resolve_links(db, user, site_id, item)
            except HTTPException as exc:
                item["errors"].append(str(exc.detail))
    result["summary"]["errors"] = sum(bool(x["errors"]) for x in result["rows"])
    now = datetime.now(timezone.utc)
    result["preview_token"] = jwt.encode({
        "purpose": "contract-import-preview",
        "org": user.org_id, "user": user.id, "site": site_id,
        "row_count": len(result["rows"]), "row_digest": _row_digest(result["rows"]),
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "iat": now, "exp": now + timedelta(minutes=30),
    }, settings().app_secret, algorithm="HS256")
    result["site_id"] = site_id
    return result


@router.post("/commit")
def commit_contracts(
    payload: ContractCommit, user: User = Depends(editor), db: Session = Depends(get_db)
):
    site_for(db, user.org_id, payload.site_id)
    try:
        signed = jwt.decode(payload.preview_token, settings().app_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(422, "Vista previa expirada o firma inválida; vuelve a cargar el Excel") from None
    if (signed.get("purpose") != "contract-import-preview" or
        signed.get("org") != user.org_id or signed.get("user") != user.id or
        signed.get("site") != payload.site_id or
        signed.get("row_count") != len(payload.rows) or
        signed.get("row_digest") != _row_digest(payload.rows)):
        raise HTTPException(403, "Vista previa no corresponde a esta organización, usuario u obra")
    normalized = [canonical(row) for row in payload.rows]
    invalid = [{"row_id": r.get("row_id"), "errors": r["errors"]} for r in normalized if r["errors"]]
    if invalid:
        raise HTTPException(422, {"rows": invalid})
    ids = [r.get("row_id") for r in normalized]
    if any(not str(x or "").strip() for x in ids) or len(ids) != len(set(ids)):
        raise HTTPException(422, "Las filas requieren identificadores únicos de origen")
    # A contract must be available before importing any associated annex.
    normalized.sort(key=lambda r: (r["kind"] == "amendment", r["start_date"], r["amendment_date"] or ""))
    counters = {"created": 0, "amendments": 0, "unchanged": 0}
    imported_rows = []
    for row in normalized:
        association, assignment = resolve_links(db, user, payload.site_id, row)
        query = select(ContractRegister).where(
            ContractRegister.org_id == user.org_id,
            ContractRegister.association_id == association.id,
            ContractRegister.start_date == date.fromisoformat(row["start_date"]),
            ContractRegister.contract_type == row["contract_type"])
        query = query.where(
            ContractRegister.worker_assignment_id == assignment.id if assignment
            else ContractRegister.worker_assignment_id.is_(None))
        contracts = db.scalars(query).all()
        if len(contracts) > 1:
            raise HTTPException(409, f"Fila {row['row_id']}: contratos duplicados; requiere revisión")
        contract = contracts[0] if contracts else None
        if row["kind"] == "contract":
            if contract:
                original_end = row["end_date"]
                if ((contract.end_date.isoformat() if contract.end_date else None) != original_end
                    or contract.status != row["status"]):
                    raise HTTPException(409, f"Fila {row['row_id']}: contrato existente con datos diferentes. Revisa antes de sobrescribir")
                counters["unchanged"] += 1
                imported_rows.append({"row_id": row["row_id"], "result": "unchanged"})
                continue
            contract = ContractRegister(
                org_id=user.org_id, association_id=association.id,
                worker_assignment_id=assignment.id if assignment else None,
                contract_type=row["contract_type"],
                start_date=date.fromisoformat(row["start_date"]),
                end_date=date.fromisoformat(row["end_date"]) if row["end_date"] else None,
                status=row["status"], notes=row["notes"],
                created_by=user.id, updated_by=user.id)
            db.add(contract)
            db.flush()
            audit_change(db, user, "contract", contract.id, {
                "import": {"file_sha256": signed["file_sha256"], "row_id": row["row_id"],
                           "source_sheet": row.get("source_sheet"), "source_row": row.get("source_row")}})
            counters["created"] += 1
            imported_rows.append({"row_id": row["row_id"], "result": "created"})
            continue
        if contract is None:
            raise HTTPException(422, f"Fila {row['row_id']}: anexo sin contrato original; importa el contrato primero")
        reference = row["reference"]
        existing = db.scalar(select(ContractAmendment).where(
            ContractAmendment.org_id == user.org_id,
            ContractAmendment.contract_id == contract.id,
            ContractAmendment.reference == reference))
        new_end = date.fromisoformat(row["end_date"])
        if existing:
            if existing.new_end_date != new_end or existing.amendment_date != date.fromisoformat(row["amendment_date"]):
                raise HTTPException(409, f"Fila {row['row_id']}: referencia de anexo repetida con datos diferentes")
            counters["unchanged"] += 1
            imported_rows.append({"row_id": row["row_id"], "result": "unchanged"})
            continue
        previous_end = contract.end_date
        # No rewriting indefinite contracts or shortening their end date silently.
        if contract.contract_type == "indefinite" or (previous_end and new_end < previous_end):
            raise HTTPException(422, f"Fila {row['row_id']}: anexo requiere revisión individual")
        amendment = ContractAmendment(
            org_id=user.org_id, contract_id=contract.id,
            amendment_date=date.fromisoformat(row["amendment_date"]),
            previous_end_date=previous_end, new_end_date=new_end, reference=reference,
            notes=row["notes"], created_by=user.id)
        db.add(amendment)
        contract.end_date = new_end
        contract.updated_by = user.id
        contract.updated_at = utcnow()
        db.flush()
        audit_change(db, user, "contract_amendment", amendment.id,
            {"contract_id": contract.id, "old_end": str(previous_end), "new_end": str(new_end),
             "file_sha256": signed["file_sha256"], "row_id": row["row_id"]})
        counters["amendments"] += 1
        imported_rows.append({"row_id": row["row_id"], "result": "amendment"})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "La importación presenta registros duplicados o concurrencia; revisar") from None
    return {**counters, "rows": imported_rows}


@router.get("/template")
def template_contracts(format: str = "xlsx", user: User = Depends(authorized_user)):
    columns = [
        "RUT contratista", "RUT trabajador", "Tipo contrato", "Fecha inicio",
        "Fecha término", "Tipo registro", "Fecha anexo", "Referencia",
        "Estado contrato", "Observaciones",
    ]
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(columns)
        return Response(content=("\ufeff" + buffer.getvalue()).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="GALANT_plantilla_contratos.csv"',
                     "Cache-Control": "no-store"})
    if format != "xlsx":
        raise HTTPException(422, "Formato debe ser csv o xlsx")
    book = Workbook()
    sh = book.active
    sh.title = "Contratos y anexos"
    sh.append(columns)
    sh.append(["", "", "Plazo fijo", "01/09/2026", "30/09/2026",
               "Contrato", "", "CONTRATO-001", "Activo", "Ejemplo; completar RUT antes de importar"])
    sh.append(["", "", "Plazo fijo", "01/09/2026", "31/10/2026",
               "Anexo", "25/09/2026", "ANEXO-001", "Activo", "Ejemplo de prórroga"])
    stream = io.BytesIO()
    book.save(stream)
    return Response(content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="GALANT_plantilla_contratos.xlsx"',
                 "Cache-Control": "no-store"})
