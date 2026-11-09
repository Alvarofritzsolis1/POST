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
from .javiera_models import JavieraExcelLayout, JavieraSignoff, JavieraReviewerAuthorization
from .javiera_review import CHECKLISTS, BASIS, specialty_for_code, valid_reviewer, audit as review_audit
from .javiera_v166_api import documentary_template_status
from .models import User
from .security import administrator, document_reviewer

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


# Reviewer portal: separated from operational and administrative permissions.
# A human reviewer with an active specialty authorization may review and
# publish *someone else's* documented draft. No self-approval or bulk bypass.
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .javiera_layout_api import latest_layout, layout_preview
from .models import utcnow


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    verdict: Literal["approved", "rejected"]
    checklist: dict[str, bool]
    comments: str = Field(min_length=40, max_length=4000)


def _review_scopes(db: Session, user: User):
    if user.role == "admin":
        grants = db.scalars(select(JavieraReviewerAuthorization).where(
            JavieraReviewerAuthorization.org_id == user.org_id,
            JavieraReviewerAuthorization.user_id == user.id,
            JavieraReviewerAuthorization.active.is_(True))).all()
    else:
        grants = db.scalars(select(JavieraReviewerAuthorization).where(
            JavieraReviewerAuthorization.org_id == user.org_id,
            JavieraReviewerAuthorization.user_id == user.id,
            JavieraReviewerAuthorization.active.is_(True))).all()
    return {entry.specialty for entry in grants}


def _review_layout(db: Session, user: User, ident: str):
    obj = db.get(JavieraExcelLayout, ident)
    if not obj or obj.org_id != user.org_id:
        raise HTTPException(404, "Plantilla no encontrada en tu organización")
    scope = specialty_for_code(obj.code)
    valid_reviewer(db, user, scope)
    if obj.author_id == user.id:
        raise HTTPException(403, "La persona que importa o modifica la plantilla no puede aprobarla")
    if obj.state != "draft":
        raise HTTPException(409, "Esta versión no está pendiente de revisión")
    latest = latest_layout(db, user.org_id, obj.code, approved=False)
    if not latest or latest.id != obj.id:
        raise HTTPException(409, "Existe una versión más reciente; revisa el último borrador")
    return obj, scope


@router.get("/review/queue")
def review_queue(user: User = Depends(document_reviewer), db: Session = Depends(get_db)):
    scopes = _review_scopes(db, user)
    if not scopes:
        return {"authorized": False, "documents": [],
                "message": "Un administrador debe designarte revisor laboral o preventivo."}
    drafts = db.scalars(select(JavieraExcelLayout).where(
        JavieraExcelLayout.org_id == user.org_id,
        JavieraExcelLayout.state == "draft").order_by(
        JavieraExcelLayout.code, JavieraExcelLayout.revision.desc())).all()
    seen, items = set(), []
    for row in drafts:
        if row.code in seen:
            continue
        seen.add(row.code)
        scope = specialty_for_code(row.code)
        if scope not in scopes or row.author_id == user.id:
            continue
        items.append({
            "id": row.id, "code": row.code, "sheet": row.source_sheet,
            "revision": row.revision, "specialty": scope,
            "source_sha256": row.workbook_sha256,
            "checks": list(CHECKLISTS[scope]),
            "regulatory_basis": BASIS[scope],
        })
    return {"authorized": True, "scopes": sorted(scopes), "documents": items,
            "message": "Revisa el PDF de muestra y registra evidencia antes de autorizar."}


@router.get("/review/layouts/{layout_id}/preview")
def review_preview(layout_id: str, user: User = Depends(document_reviewer),
                   db: Session = Depends(get_db)):
    _review_layout(db, user, layout_id)
    return layout_preview(layout_id=layout_id, dossier_id="", user=user, db=db)


@router.post("/review/layouts/{layout_id}/decision")
def review_decision(layout_id: str, payload: ReviewDecision,
                    user: User = Depends(document_reviewer),
                    db: Session = Depends(get_db)):
    obj, scope = _review_layout(db, user, layout_id)
    if obj.revision != payload.expected_revision:
        raise HTTPException(409, "La revisión cambió. Recarga la plantilla.")
    expected = set(CHECKLISTS[scope])
    if set(payload.checklist) != expected or (
        payload.verdict == "approved" and not all(payload.checklist.values())
    ):
        raise HTTPException(422, "Comprueba cada criterio antes de aprobar")
    previous = db.scalar(select(JavieraSignoff).where(
        JavieraSignoff.org_id == user.org_id,
        JavieraSignoff.resource_kind == "excel_layout",
        JavieraSignoff.resource_id == obj.id,
        JavieraSignoff.specialty == scope))
    if previous:
        raise HTTPException(409, "Este borrador ya tiene un acta registrada")
    row = JavieraSignoff(org_id=user.org_id, resource_kind="excel_layout",
        resource_id=obj.id, specialty=scope, verdict=payload.verdict,
        reviewer_id=user.id, checklist=payload.checklist,
        comments=payload.comments, regulatory_basis=BASIS[scope])
    db.add(row)
    db.flush()
    if payload.verdict == "approved":
        obj.state, obj.reviewer_id, obj.reviewed_at = "approved", user.id, utcnow()
    review_audit(db, user, "javiera.review_v17_" + payload.verdict, row.id)
    db.commit()
    return {"id": row.id, "layout_id": obj.id, "verdict": payload.verdict,
            "published": obj.state == "approved", "revision": obj.revision,
            "message": "Aprobación profesional registrada y versión publicada." if
                       obj.state == "approved" else "Observaciones registradas. El autor debe crear una nueva revisión."}
