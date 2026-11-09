"""Piloto documental GALANT 19: vistas previas nativas HTML/CSS -> PDF.

Solo permite leer expedientes locales del usuario administrador y matrices
preventivas aprobadas de su organización. No publica, no emite actas ni
altera registros operativos. El generador Excel v18 sigue disponible.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .javiera_layout_api import matrix_sections
from .javiera_logic import render_tokens
from .javiera_models import JavieraTemplate
from .javiera_native import DOCUMENT_TITLES, NativeDocumentError, render_native_pdf
from .javiera_v166_api import _document, _dossier
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v19", tags=["Javiera 19 · Plantillas nativas"])


class NativePreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dossier_id: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=50)


ORIGINAL_TEXT_CODES = frozenset({
    "labor_contract", "transfer_addendum", "extension_addendum",
    "sworn_declaration", "ppe_delivery", "pts", "pts_receipt",
})


@router.get("/formats")
def native_formats(user: User = Depends(administrator),
                   db: Session = Depends(get_db)):
    """All ten A4 layouts available; seven require approved source texts."""
    rows = db.scalars(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id,
        JavieraTemplate.code.in_(ORIGINAL_TEXT_CODES),
    )).all()
    published = {row.code: row for row in rows
                 if row.published_version > 0 and row.body and row.body.strip()}
    return {
        "mode": "preview_only",
        "source": "html_css",
        "uses_excel_for_printing": False,
        "requires_physical_signature": True,
        "formats": [
            {"code": code, "title": title,
             "status": ("ready" if code not in ORIGINAL_TEXT_CODES or code in published
                        else "requires_published_text"),
             "editable_in": "Configuración de plantillas documentales",
             "source_revision": published[code].published_version
                 if code in published else None}
            for code, title in DOCUMENT_TITLES.items()
        ],
        "message": ("Diez diseños nativos. Los siete documentos laborales y de entrega "
                    "solo se generan tras publicar y verificar su texto original. "
                    "La emisión definitiva permanece en Excel."),
    }


@router.post("/preview")
def preview_native(payload: NativePreviewInput,
                   user: User = Depends(administrator),
                   db: Session = Depends(get_db)):
    if payload.code not in DOCUMENT_TITLES:
        raise HTTPException(422, "Este documento aún no está migrado al motor nativo.")
    record = _dossier(db, user, payload.dossier_id)
    if payload.code not in record.selected_codes:
        raise HTTPException(422, "Selecciona el documento dentro del expediente.")
    data = _document(record, payload.code, db, user)
    matrix = None
    if payload.code in {"irl", "pts"}:
        kind = payload.code.upper()
        matrix = matrix_sections(db, user, kind, data.get("role", ""))
        if not matrix:
            raise HTTPException(
                409, f"Falta matriz {kind} aprobada para este cargo. No se inventará contenido."
            )
    approved_text = None
    if payload.code in ORIGINAL_TEXT_CODES:
        template = db.scalar(select(JavieraTemplate).where(
            JavieraTemplate.org_id == user.org_id,
            JavieraTemplate.code == payload.code,
            JavieraTemplate.published_version > 0,
        ))
        if template is None or not template.body or not template.body.strip():
            raise HTTPException(
                409, "El formato nativo está diseñado, pero falta publicar "
                     "el texto original y sus cláusulas. Abre el editor documental."
            )
        try:
            approved_text = render_tokens(template.body, data)
        except ValueError as exc:
            raise HTTPException(
                422, "Falta completar un campo requerido por el texto aprobado: " + str(exc)
            ) from None
        if "{{" in approved_text or "}}" in approved_text:
            raise HTTPException(422, "El texto contiene variables sin resolver.")
    try:
        pdf = render_native_pdf(payload.code, data, matrix=matrix,
                                approved_text=approved_text)
    except NativeDocumentError as exc:
        raise HTTPException(422, str(exc)) from None
    return Response(
        content=pdf, media_type="application/pdf",
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": 'inline; filename="proyecto-javiera-vista-previa.pdf"',
            "X-Content-Type-Options": "nosniff",
        },
    )
