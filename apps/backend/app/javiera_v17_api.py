"""GALANT 17: one-import, ten-document onboarding for the original XLSX layouts.

The workbook always stays in private organization storage. No personal data
or workbook contents are copied to GitHub, logs, or operational worker tables.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .javiera_excel import DOC_SHEETS, MAX_FILE, LayoutError, layout_summary
from .javiera_layout_api import import_excel
from .javiera_models import JavieraExcelLayout
from .javiera_review import specialty_for_code
from .javiera_v166_api import documentary_template_status
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v17", tags=["Javiera · Biblioteca guiada 17"])


@router.get("/library")
def library(user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Non-sensitive, per-organization status of the ten source worksheets."""
    report = documentary_template_status(user=user, db=db)
    latest = db.scalars(select(JavieraExcelLayout).where(
        JavieraExcelLayout.org_id == user.org_id
    ).order_by(JavieraExcelLayout.revision.desc()).limit(300)).all()
    rows = {}
    for layout in latest:
        rows.setdefault(layout.code, layout)
    docs = [{
        **item,
        "title": {
            "labor_contract": "Contrato de trabajo",
            "transfer_addendum": "Anexo de traslado",
            "extension_addendum": "Anexo de prórroga",
            "sworn_declaration": "Declaración jurada",
            "internal_rules_receipt": "Recepción de Reglamento Interno",
            "ppe_delivery": "Entrega de EPP",
            "irl": "Información de Riesgos Laborales",
            "pts": "Procedimiento de Trabajo Seguro",
            "pts_receipt": "Recepción de PTS",
            "induction": "Inducción preventiva",
        }[item["code"]],
        "specialty": specialty_for_code(item["code"]),
        "layout_id": rows[item["code"]].id if item["code"] in rows else None,
        "author_id": rows[item["code"]].author_id if item["code"] in rows else None,
        "can_preview": bool(item["imported"] and report["engine_available"]),
    } for item in report["documents"]]
    return {"documents": docs, "total": len(DOC_SHEETS),
            "imported": sum(bool(d["imported"]) for d in docs),
            "published": sum(bool(d["ready"]) for d in docs),
            "awaiting_review": sum(d["state"] == "draft" for d in docs),
            "engine_available": report["engine_available"],
            "requires_human_approval": True,
            "source": "Excel original privado, sin alta operativa"}


@router.post("/library/import")
async def import_ten_templates(file: UploadFile = File(...),
                               user: User = Depends(administrator),
                               db: Session = Depends(get_db)):
    """One upload prepares *all ten* editable drafts, or reuses same private version."""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(422, "Selecciona el archivo Excel .xlsx de Proyecto Javiera")
    raw = await file.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise HTTPException(413, "El Excel supera el límite de 12 MB")
    try:
        items = layout_summary(raw)
    except LayoutError as exc:
        raise HTTPException(422, str(exc)) from None
    missing = [x["sheet"] for x in items if not x["found"]]
    if missing:
        raise HTTPException(422, {"message": "El asistente requiere las diez hojas originales.",
                                  "missing_sheets": missing})
    digest = hashlib.sha256(raw).hexdigest()
    previous = db.scalars(select(JavieraExcelLayout).where(
        JavieraExcelLayout.org_id == user.org_id,
        JavieraExcelLayout.workbook_sha256 == digest)).all()
    by_code = {x.code: x for x in previous}
    private_root = (settings().document_dir / user.org_id /
                    "javiera" / "layout-sources").resolve()
    if len(by_code) == len(DOC_SHEETS) and all(
        x.code in by_code and
        Path(by_code[x.code].workbook_path).resolve().is_relative_to(private_root) and
        Path(by_code[x.code].workbook_path).is_file()
        for x in previous
    ):
        return {"status": "already_imported", "created": 0,
                "matched": len(DOC_SHEETS),
                "message": "Este Excel ya está importado. Conservamos sus revisiones.",
                "library": library(user=user, db=db)}
    await file.seek(0)
    outcome = await import_excel(file=file, user=user, db=db)
    return {"status": "imported_as_draft", "created": len(outcome["templates"]),
            "matched": len(DOC_SHEETS),
            "message": "Diez plantillas preparadas para revisar. Ninguna se ha aprobado automáticamente.",
            "library": library(user=user, db=db)}
