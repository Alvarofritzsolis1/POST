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
    DOC_SHEETS, PROTECTED_DOCUMENT_CELLS, LayoutError, MAX_FILE, cell_text, layout_summary,
    pdf_from_workbook, shared_strings, sheet_files, validate_xlsx,
    Q,
)
from .javiera_models import JavieraDossier, JavieraExcelLayout
from .javiera_matrices import latest_approved_matrix
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


class PilotPrintEnable(Strict):
    confirmed_preview: bool = False


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
    row = latest_approved_matrix(db, user.org_id, kind, cargo)
    return row.sections if row else None


def source_leaks(raw: bytes, pdf: bytes, data: dict) -> list[str]:
    """Detecta restos de la ficha de ejemplo en el PDF final de otra persona.

    Revisa todos los campos variables del origen; compara texto normalizado,
    RUT y teléfono normalizados y fechas imprimibles. Falla cerrado: si una
    cadena inequívoca de otro trabajador/empleador persiste, no se emite.
    """
    import io
    import unicodedata
    from datetime import date, timedelta
    from .javiera_excel import SOURCE_FIELDS, cell_text, shared_strings, sheet_files, spanish_amount, Q

    def normalized(value: str) -> str:
        raw = unicodedata.normalize("NFKD", str(value).casefold())
        without_marks = "".join(ch for ch in raw if not unicodedata.combining(ch))
        return " ".join(without_marks.split())

    def digits(value: str) -> str:
        return "".join(ch for ch in str(value) if ch.isdigit())

    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z)
        original = ET.fromstring(z.read(files["Datos Contrato"]))
        strings = shared_strings(z)
        sample_cells = {c.get("r"): cell_text(c, strings).strip()
                        for c in original.iter(Q("c"))}
    with fitz.open(stream=pdf, filetype="pdf") as output:
        full_text = normalized(" ".join(page.get_text() for page in output))
    full_digits = digits(full_text)
    issues = []
    skip_generic = {"CHILENA", "CHILENO", "CASADO", "SOLTERO", "SOLTERA"}
    date_coordinates = {"C20", "C36", "C37", "C40"}
    numeric_coordinates = {"C9", "C26", "C31", "C32"}
    for coord, field_key in SOURCE_FIELDS.items():
        original_value = sample_cells.get(coord, "")
        if not original_value:
            continue
        new_value = data
        for section in field_key.split("."):
            new_value = new_value.get(section) if isinstance(new_value, dict) else None
        if field_key == "extra.salary_words" and not new_value:
            new_value = spanish_amount((data.get("contract") or {}).get("salary", ""))
        new_value = "" if new_value is None else str(new_value).strip()
        if normalized(original_value) == normalized(new_value):
            continue
        if coord in date_coordinates:
            try:
                old_date = date(1899, 12, 30) + timedelta(days=int(float(original_value)))
                new_date = date.fromisoformat(new_value[:10])
            except (TypeError, ValueError, OverflowError):
                continue
            if old_date != new_date and (
                old_date.strftime("%d/%m/%Y") in full_text or
                str(old_date.day) + "/" + str(old_date.month) + "/" + str(old_date.year) in full_text
            ):
                issues.append(coord)
            continue
        if normalized(original_value).upper() in skip_generic:
            continue
        if coord in numeric_coordinates or field_key.endswith(".rut"):
            old_digits = digits(original_value)
            new_digits = digits(new_value)
            if len(old_digits) >= 7 and old_digits != new_digits and old_digits in full_digits:
                issues.append(coord)
            continue
        old_norm = normalized(original_value)
        if len(old_norm) >= 6 and old_norm in full_text:
            issues.append(coord)
    return sorted(set(issues))



def make_pdf(db: Session, user: User, item: JavieraExcelLayout,
             data: dict, preview: bool) -> bytes:
    raw = private_workbook_path(user, item.workbook_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != item.workbook_sha256:
        raise HTTPException(409, "El Excel privado cambió; revisión y restauración obligatorias")
    matrix = None
    extra = {}
    if item.code in {"pts", "irl"}:
        matrix = matrix_sections(db, user, "PTS" if item.code == "pts" else "IRL",
                                 data.get("role", ""))
        if item.code == "irl":
            extra = {kind:matrix_sections(db,user,kind,data.get("role","")) or []
                     for kind in ("PERFILES","PUESTOS","SUSTANCIAS")}
        if preview and matrix is None:
            matrix = (["PENDIENTE DE REVISIÓN DE PREVENCIÓN"] * 17 if item.code == "pts"
                      else ["Tarea: PENDIENTE DE MATRIZ\nPeligro: PENDIENTE\nRiesgo: PENDIENTE\nMedidas: PENDIENTE"])
    try:
        output = pdf_from_workbook(raw, item.code, data,
                                   changes=item.overrides, matrix=matrix,
                                   extra_matrices=extra, preview=preview)
    except LayoutError as exc:
        raise HTTPException(409, str(exc)) from None
    if not preview:
        leaks = source_leaks(raw, output, data)
        if leaks:
            raise HTTPException(409, "El PDF conserva datos del ejemplo de origen en celdas " +
                                ", ".join(leaks) + "; corrige la plantilla y aprueba otra revisión")
        with fitz.open(stream=output, filetype="pdf") as document:
            printed = "\n".join(page.get_text() for page in document).upper()
        unsafe = (
            "NO EMITIR", "PENDIENTE DE REVISIÓN", "PENDIENTE DE MATRIZ",
            "REVISAR CARGO EN MATRIZ", "CARGO SIN PTS", "PLANTILLA INCOMPLETA",
            "{{", "}}",
        )
        active = [token for token in unsafe if token in printed]
        if active:
            raise HTTPException(409, "El documento contiene marcadores sin resolver: " +
                                ", ".join(active) + ". Corrige la plantilla o matriz antes de emitir")
    return output


@router.get("/status")
def status(user: User = Depends(administrator)):
    return {"engine": "LibreOffice Calc", "available": bool(shutil.which("libreoffice") or shutil.which("soffice")),
            "private_storage": True, "document_types": len(DOC_SHEETS),
             "solo_pilot": settings().javiera_solo_pilot}


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
    digest = hashlib.sha256(raw).hexdigest()
    # No duplicar una fuente que ya fue importada alguna vez, incluso si
    # posteriormente se editaron sus diseños o se importó otra versión.
    previous = db.scalars(select(JavieraExcelLayout).where(
        JavieraExcelLayout.org_id == user.org_id,
        JavieraExcelLayout.workbook_sha256 == digest)).all()
    by_code = {item.code: item for item in previous}
    if found and all(entry["code"] in by_code for entry in found):
        # Nunca silenciar archivos faltantes: es un problema de almacenamiento,
        # no una razón para crear duplicados y perder trazabilidad.
        for entry in found:
            private_workbook_path(user, by_code[entry["code"]].workbook_path)
        return {"templates": found, "missing": [x["code"] for x in items if not x["found"]],
                "status": "already_imported", "sha256": digest,
                "message": "Este Excel ya existe en el historial. No se crearon versiones repetidas."}
    root = settings().document_dir / user.org_id / "javiera" / "layout-sources"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    ident = str(uuid4())
    path = root / (ident + ".xlsx")
    path.write_bytes(raw)
    path.chmod(0o600)
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
                "protected_cells": sorted(PROTECTED_DOCUMENT_CELLS.get(item.code, set())),
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
    forbidden = PROTECTED_DOCUMENT_CELLS.get(obj.code, set())
    if any(edit.coordinate in forbidden for edit in payload.edits):
        raise HTTPException(422, "No puedes modificar cantidades EPP, fechas de prórroga, declaración jurada ni matrices preventivas desde la plantilla. Utiliza los formularios o matrices especializados")
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


@router.post("/layouts/{layout_id}/enable-print")
def enable_print_for_pilot(layout_id: str, payload: PilotPrintEnable,
                           user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Habilitación administrativa del FORMATO para imprimir y firmar en papel.

    No registra firma, recepción, cumplimiento legal ni una revisión independiente.
    La vía de doble revisión existente permanece disponible fuera del piloto.
    """
    if not settings().javiera_solo_pilot:
        raise HTTPException(403, "La habilitación directa está desactivada fuera del piloto")
    if not payload.confirmed_preview:
        raise HTTPException(422, "Abre primero la vista previa y confirma su revisión visual")
    obj = layout_for(db, user, layout_id)
    newest = latest_layout(db, user.org_id, obj.code, approved=False)
    if not newest or newest.id != obj.id:
        raise HTTPException(409, "Esta es una versión antigua; selecciona el diseño vigente")
    if obj.state == "approved":
        return {"id": obj.id, "code": obj.code, "status": obj.state,
                "revision": obj.revision, "pilot_print_only": True}
    if obj.state != "draft":
        raise HTTPException(409, "La plantilla no puede habilitarse para impresión")
    # Fallar de forma segura si falta el Excel original o el motor de PDF.
    layout_preview(layout_id=layout_id, dossier_id="", user=user, db=db)
    obj.state, obj.reviewer_id, obj.reviewed_at = "approved", user.id, utcnow()
    db.flush()
    audit(db, user, "javiera.pilot_format_enabled_for_print", obj.id)
    db.commit()
    return {"id": obj.id, "code": obj.code, "status": obj.state,
            "revision": obj.revision, "pilot_print_only": True,
            "message": "Formato habilitado para imprimir y obtener firmas en papel; no acredita entrega ni firma."}


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
                        "new_end":"2027-01-31",
                        "declaration_reason":"La empresa confirma esta declaración respecto de su dotación",
                        "salary":"600000","hours":"42"},
            "event":{"date":"2026-11-06","epp_items":"Casco de Seguridad; Lentes de Seguridad",
                     "pts_version":"1"},
            "extra":{"representative_name":"REPRESENTANTE SINTETICO",
                "representative_rut":"11.111.111-1",
                "representative_nationality":"CHILENA",
                "employer_city":"CONCEPCION","employer_address":"DIRECCION DE PRUEBA",
                "site_address":"UBICACION DE PRUEBA","specialty":"CARPINTERIA",
                "principal_company":"MANDANTE SINTETICA DE PRUEBA",
                "declaration_period":"2026-10","worker_nationality":"CHILENA",
                "salary_words":"Seiscientos mil pesos"}
        }
        if obj.code == "sworn_declaration":
            data["worker"] = {"name":"", "rut":""}
    output = make_pdf(db, user, obj, data, preview=True)
    return Response(content=output, media_type="application/pdf",
        headers={"Cache-Control":"no-store", "Content-Disposition":"inline; filename=JAVIERA_PREVIEW.pdf"})
