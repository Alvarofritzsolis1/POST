"""API de maquetaciones XLSX originales, impresión y revisión en JAVIERA."""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import fitz
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .javiera_excel import (
    DOC_SHEETS, LayoutError, MAX_FILE, cell_text, layout_summary,
    pdf_from_workbook, shared_strings, sheet_files, validate_xlsx,
    Q,
)
from .javiera_models import JavieraDossier, JavieraExcelLayout, JavieraMatrix
from .javiera_review import require_signoff, specialty_for_code
from .models import AuditEvent, User, utcnow
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/admin/excel", tags=["JAVIERA · Impresión Excel"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CellEdit(Strict):
    coordinate: str = Field(pattern=r"^[A-Z]{1,3}[1-9]\d{0,5}$")
    text: str | None = Field(default=None, max_length=15000)
    style_from: str | None = Field(default=None, pattern=r"^[A-Z]{1,3}[1-9]\d{0,5}$")
    row_height: float | None = Field(default=None, ge=10, le=120)


class LayoutChange(Strict):
    expected_revision: int = Field(ge=1)
    edits: list[CellEdit] = Field(min_length=1, max_length=250)
    reason: str = Field(min_length=10, max_length=800)


def audit(db: Session, user: User, action: str, ident: str):
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id, action=action, resource_id=ident))


def layout_for(db: Session, user: User, ident: str) -> JavieraExcelLayout:
    obj = db.get(JavieraExcelLayout, ident)
    if not obj or obj.org_id != user.org_id:
        raise HTTPException(404, "Plantilla Excel no encontrada")
    return obj


def private_workbook_path(user: User, path: str) -> Path:
    root = (settings().document_dir / user.org_id / "javiera" / "layout-sources").resolve()
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise HTTPException(404, "Plantilla privada no disponible")
    return resolved


def latest_layout(db: Session, org_id: str, code: str, approved: bool = True):
    query = select(JavieraExcelLayout).where(
        JavieraExcelLayout.org_id == org_id, JavieraExcelLayout.code == code)
    if approved:
        query = query.where(JavieraExcelLayout.state == "approved")
    return db.scalar(query.order_by(JavieraExcelLayout.revision.desc()))


def matrix_sections(db: Session, user: User, kind: str, cargo: str) -> list[str] | None:
    from .javiera_logic import normalize_cargo
    row = db.scalar(select(JavieraMatrix).where(
        JavieraMatrix.org_id == user.org_id,
        JavieraMatrix.kind == kind,
        JavieraMatrix.cargo == normalize_cargo(cargo),
        JavieraMatrix.status == "approved"
    ).order_by(JavieraMatrix.revision.desc()))
    return row.sections if row else None


def source_leaks(raw: bytes, pdf: bytes, data: dict) -> list[str]:
    """Impide emitir ejemplos identificatorios de la planilla como datos del trabajador real."""
    from .javiera_excel import SOURCE_FIELDS, cell_text, shared_strings, sheet_files, Q
    with ZipFile(__import__("io").BytesIO(raw)) as z:
        files = sheet_files(z)
        original = ET.fromstring(z.read(files["Datos Contrato"]))
        strings = shared_strings(z)
        candidates = []
        for coord in ("C5", "C6", "C7", "C8", "C10", "C13", "C17", "C18", "C22", "C25"):
            row = original.find(".//" + Q("c") + "[@r='" + coord + "']")
            if row is None:
                continue
            value = cell_text(row, strings).strip()
            if len(value) < 6:
                continue
            node = data
            for part in SOURCE_FIELDS[coord].split("."):
                node = node.get(part) if isinstance(node, dict) else None
            actual = str(node or "").strip()
            if actual.casefold() != value.casefold():
                candidates.append((coord, value))
    with fitz.open(stream=pdf, filetype="pdf") as output:
        full_text = " ".join(page.get_text() for page in output).casefold()
    return [coord for coord, value in candidates if value.casefold() in full_text]


def make_pdf(db: Session, user: User, item: JavieraExcelLayout,
             data: dict, preview: bool) -> bytes:
    raw = private_workbook_path(user, item.workbook_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != item.workbook_sha256:
        raise HTTPException(409, "El Excel privado cambió; revisión y restauración obligatorias")
    matrix = matrix_sections(db, user, "PTS", data.get("role", "")) if item.code == "pts" else None
    if preview and item.code == "pts" and matrix is None:
        matrix = ["PENDIENTE DE REVISIÓN DE PREVENCIÓN"] * 17
    try:
        output = pdf_from_workbook(raw, item.code, data,
                                   changes=item.overrides, matrix=matrix, preview=preview)
    except LayoutError as exc:
        raise HTTPException(409, str(exc)) from None
    if not preview:
        leaks = source_leaks(raw, output, data)
        if leaks:
            raise HTTPException(409, "El PDF conserva datos del ejemplo de origen en celdas " +
                                ", ".join(leaks) + "; corrige la plantilla y aprueba otra revisión")
    return output


@router.get("/status")
def status(user: User = Depends(administrator)):
    return {"engine": "LibreOffice Calc", "available": bool(shutil.which("libreoffice") or shutil.which("soffice")),
            "private_storage": True, "document_types": len(DOC_SHEETS)}


@router.post("/import")
async def import_excel(file: UploadFile = File(...),
                       user: User = Depends(administrator),
                       db: Session = Depends(get_db)):
    raw = await file.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise HTTPException(413, "Plantilla Excel supera 12 MB")
    try:
        items = layout_summary(raw)
    except LayoutError as exc:
        raise HTTPException(422, str(exc)) from None
    found = [x for x in items if x["found"]]
    if len(found) < 8:
        raise HTTPException(422, "Se requiere la plantilla original con al menos 8 hojas documentales")
    root = settings().document_dir / user.org_id / "javiera" / "layout-sources"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    ident = str(uuid4())
    path = root / (ident + ".xlsx")
    path.write_bytes(raw)
    path.chmod(0o600)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        for entry in found:
            code = entry["code"]
            old = db.scalar(select(func.max(JavieraExcelLayout.revision)).where(
                JavieraExcelLayout.org_id == user.org_id,
                JavieraExcelLayout.code == code)) or 0
            row = JavieraExcelLayout(org_id=user.org_id, code=code, revision=old + 1,
                source_sheet=entry["sheet"], workbook_path=str(path), workbook_sha256=digest,
                inventory=entry, overrides={}, author_id=user.id)
            db.add(row)
        db.flush()
        audit(db, user, "javiera.excel_layout_import", ident)
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return {"templates": found, "missing": [x["code"] for x in items if not x["found"]],
        "status": "draft", "sha256": digest, "message": "Diseños importados en privado; requieren revisión especializada"}


@router.get("/layouts")
def layouts(user: User = Depends(administrator), db: Session = Depends(get_db)):
    rows = db.scalars(select(JavieraExcelLayout).where(
        JavieraExcelLayout.org_id == user.org_id).order_by(
        JavieraExcelLayout.code, JavieraExcelLayout.revision.desc()).limit(140)).all()
    return [{"id": r.id, "code": r.code, "sheet": r.source_sheet,
             "revision": r.revision, "status": r.state, "inventory": r.inventory,
             "cells_modified": len(r.overrides), "author_id": r.author_id,
             "reviewer_id": r.reviewer_id, "created_at": r.created_at.isoformat()}
            for r in rows]


@router.get("/layouts/{layout_id}/cells")
def cells(layout_id: str, start_row: int = 1, max_rows: int = 40,
          user: User = Depends(administrator), db: Session = Depends(get_db)):
    item = layout_for(db, user, layout_id)
    if start_row < 1 or max_rows < 1 or max_rows > 75:
        raise HTTPException(422, "Solicita entre 1 y 75 filas")
    raw = private_workbook_path(user, item.workbook_path).read_bytes()
    with ZipFile(__import__("io").BytesIO(raw)) as z:
        files = sheet_files(z)
        root = ET.fromstring(z.read(files[item.source_sheet]))
        strings = shared_strings(z)
        result = []
        for row in root.findall(".//" + Q("sheetData") + "/" + Q("row")):
            number = int(row.get("r", 0))
            if not start_row <= number < start_row + max_rows:
                continue
            for cell in row.findall(Q("c")):
                coord = cell.get("r")
                formula = cell.find(Q("f"))
                override = item.overrides.get(coord, {})
                text = cell_text(cell, strings)
                if text or formula is not None or override:
                    result.append({"cell": coord, "row": number,
                                   "value": override.get("text", text),
                                   "formula": formula.text if formula is not None else None,
                                   "style": cell.get("s"),
                                   "modified": bool(override)})
        merges = [el.get("ref") for el in root.findall(".//" + Q("mergeCell"))]
        return {"id":item.id, "sheet":item.source_sheet, "revision":item.revision,
                "status":item.state, "start_row":start_row, "max_rows":max_rows,
                "cells":result[:1600], "merged":merges[:160],
                "has_more":any(int(row.get("r",0)) >= start_row+max_rows
                               for row in root.findall(".//" + Q("sheetData") + "/" + Q("row")))}


@router.post("/layouts/{layout_id}/revise")
def revise_layout(layout_id: str, payload: LayoutChange,
                  user: User = Depends(administrator), db: Session = Depends(get_db)):
    obj = layout_for(db, user, layout_id)
    if obj.revision != payload.expected_revision:
        raise HTTPException(409, "La plantilla fue modificada; recarga para evitar sobrescribir otra versión")
    current = latest_layout(db, user.org_id, obj.code, approved=False)
    if current.id != obj.id:
        raise HTTPException(409, "Debes editar la revisión más reciente")
    changes = {**obj.overrides}
    for edit in payload.edits:
        data = edit.model_dump(exclude_none=True, exclude={"coordinate"})
        changes[edit.coordinate] = {**changes.get(edit.coordinate, {}), **data}
    if len(changes) > 1500:
        raise HTTPException(413, "Demasiadas modificaciones a la plantilla")
    fresh = JavieraExcelLayout(org_id=user.org_id, code=obj.code,
        revision=obj.revision + 1, source_sheet=obj.source_sheet,
        workbook_path=obj.workbook_path, workbook_sha256=obj.workbook_sha256,
        overrides=changes, inventory=obj.inventory, author_id=user.id)
    db.add(fresh)
    db.flush()
    audit(db, user, "javiera.excel_layout_revision", fresh.id)
    db.commit()
    return {"id":fresh.id, "revision":fresh.revision, "status":"draft",
            "reason":payload.reason, "changes":len(changes)}


@router.post("/layouts/{layout_id}/approve")
def approve_layout(layout_id: str, user: User = Depends(administrator),
                   db: Session = Depends(get_db)):
    obj = layout_for(db, user, layout_id)
    if obj.state != "draft":
        raise HTTPException(409, "La plantilla no está pendiente de aprobación")
    if obj.author_id == user.id:
        raise HTTPException(403, "El autor no puede publicar su propia maquetación")
    require_signoff(db, user, "excel_layout", obj.id, specialty_for_code(obj.code))
    obj.state, obj.reviewer_id, obj.reviewed_at = "approved", user.id, utcnow()
    db.flush()
    audit(db, user, "javiera.excel_layout_approved", obj.id)
    db.commit()
    return {"id":obj.id, "code":obj.code, "status":obj.state, "revision":obj.revision}


@router.get("/layouts/{layout_id}/preview")
def layout_preview(layout_id: str, dossier_id: str = "",
                   user: User = Depends(administrator), db: Session = Depends(get_db)):
    obj = layout_for(db, user, layout_id)
    if dossier_id:
        data_obj = db.get(JavieraDossier, dossier_id)
        if not data_obj or data_obj.org_id != user.org_id:
            raise HTTPException(404, "Expediente fuera de tu organización")
        data = data_obj.data
    else:
        data = {
            "employer":{"name":"EMPRESA SINTETICA DE PRUEBA","rut":"11.111.111-1"},
            "worker":{"name":"TRABAJADOR SINTETICO","rut":"11.111.111-1"},
            "site":{"name":"OBRA DE PRUEBA"}, "role":"CARPINTERO",
            "contract":{"start":"2026-11-01","end":"2026-12-01",
                        "salary":"600000","hours":"42"},
            "event":{"date":"2026-11-06"},
            "extra":{"representative_name":"REPRESENTANTE SINTETICO",
                "representative_rut":"11.111.111-1","employer_city":"CONCEPCION",
                "worker_nationality":"CHILENA","salary_words":"Seiscientos mil pesos"}
        }
    output = make_pdf(db, user, obj, data, preview=True)
    return Response(content=output, media_type="application/pdf",
        headers={"Cache-Control":"no-store", "Content-Disposition":"inline; filename=JAVIERA_PREVIEW.pdf"})
