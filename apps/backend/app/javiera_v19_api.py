"""Piloto documental GALANT 19: vistas previas nativas HTML/CSS -> PDF.

Solo permite leer expedientes locales del usuario administrador y matrices
preventivas aprobadas de su organización. No publica, no emite actas ni
altera registros operativos. El generador Excel v18 sigue disponible.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .db import get_db
from .javiera_layout_api import matrix_sections
from .javiera_native import DOCUMENT_TITLES, NativeDocumentError, render_native_pdf
from .javiera_v166_api import _document, _dossier
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v19", tags=["Javiera 19 · Plantillas nativas"])


class NativePreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dossier_id: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=50)


@router.get("/formats")
def native_formats(user: User = Depends(administrator)):
    """Solo un piloto de tres documentos: la emisión actual continúa en v16/18."""
    return {
        "mode": "preview_only",
        "source": "html_css",
        "uses_excel_for_printing": False,
        "requires_physical_signature": True,
        "formats": [{"code": code, "title": title, "status": "pilot"}
                    for code, title in DOCUMENT_TITLES.items()],
        "message": "Los formatos nativos son vistas previas; no sustituyen todavía la emisión actual.",
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
    if payload.code == "irl":
        matrix = matrix_sections(db, user, "IRL", data.get("role", ""))
        if not matrix:
            raise HTTPException(
                409, "Falta matriz IRL aprobada para este cargo. No se inventarán riesgos."
            )
    try:
        pdf = render_native_pdf(payload.code, data, matrix=matrix)
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
