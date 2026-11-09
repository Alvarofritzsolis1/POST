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

from .config import settings
from .db import get_db
from .javiera_layout_api import matrix_sections
from .javiera_logic import render_tokens, check_template_fields, rut_valid
from .javiera_models import JavieraRevision, JavieraTemplate
from .models import AuditEvent, utcnow
from .javiera_native import DOCUMENT_TITLES, NativeDocumentError, render_native_pdf
from .javiera_v166_api import _document, _dossier
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v19", tags=["Javiera 19 · Plantillas nativas"])


class NativePreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dossier_id: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=50)


class EnablePilotText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    confirmed_content: bool = False


def _text_source(db: Session, user: User, code: str):
    """Preview-only authoring; pilot does NOT publish a professional signoff."""
    template = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    if template is None:
        return None, None, "missing"
    latest = db.scalar(select(JavieraRevision).where(
        JavieraRevision.org_id == user.org_id,
        JavieraRevision.template_id == template.id
    ).order_by(JavieraRevision.revision.desc()))
    if latest and latest.revision > template.published_version:
        if latest.state == "pilot_print" and latest.contents.get("body"):
            return latest.contents["body"], latest.revision, "pilot_print"
        return None, None, "requires_review"
    if template.published_version > 0 and template.body:
        return template.body, template.published_version, "published"
    return None, None, "missing"


@router.post("/templates/{code}/enable-preview")
def enable_text_preview(code: str, payload: EnablePilotText,
                        user: User = Depends(administrator),
                        db: Session = Depends(get_db)):
    """Enable *preview only* with one admin, without falsely publishing approval."""
    if code not in ORIGINAL_TEXT_CODES:
        raise HTTPException(422, "La habilitación de texto solo corresponde a formatos migrados.")
    if not settings().javiera_solo_pilot:
        raise HTTPException(403, "La habilitación administrativa requiere modo piloto.")
    if not payload.confirmed_content:
        raise HTTPException(422, "Confirma que revisaste el contenido original.")
    template = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    if template is None:
        raise HTTPException(404, "Plantilla documental no encontrada.")
    latest = db.scalar(select(JavieraRevision).where(
        JavieraRevision.org_id == user.org_id,
        JavieraRevision.template_id == template.id
    ).order_by(JavieraRevision.revision.desc()))
    if latest is None or latest.revision != payload.revision:
        raise HTTPException(409, "Existe una versión diferente; revisa el último borrador.")
    if latest.state == "pilot_print":
        return {"code": code, "revision": latest.revision,
                "status": "pilot_print", "preview_only": True}
    if latest.state != "draft":
        raise HTTPException(409, "El formato no tiene un borrador pendiente.")
    content = latest.contents or {}
    try:
        check_template_fields(content.get("fields", []), content.get("body", ""))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if len(content.get("body", "").strip()) < 20:
        raise HTTPException(422, "El texto original debe estar completo.")
    latest.state = "pilot_print"
    # No se modifica published_version, no se crean firmas ni aprobaciones profesionales.
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="javiera.native_text_preview_enabled", resource_id=latest.id))
    db.commit()
    return {"code": code, "revision": latest.revision,
            "status": "pilot_print", "preview_only": True}


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
    sources = {code: _text_source(db, user, code)
               for code in ORIGINAL_TEXT_CODES}
    return {
        "mode": "preview_only",
        "source": "html_css",
        "uses_excel_for_printing": False,
        "requires_physical_signature": True,
        "formats": [
            {"code": code, "title": title,
             "status": ("ready" if code not in ORIGINAL_TEXT_CODES or
                        sources[code][0] else "requires_published_text"),
             "source_kind": sources[code][2] if code in ORIGINAL_TEXT_CODES else "native",
             "editable_in": "Configuración de plantillas documentales",
             "source_revision": sources[code][1]
                 if code in ORIGINAL_TEXT_CODES else None}
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
    # La vista previa A4 no debe eludir la validación de identidad documental.
    identities = [
        ("empresa", (data.get("employer") or {}).get("rut")),
        ("persona", (data.get("worker") or {}).get("rut")),
    ]
    if payload.code == "sworn_declaration":
        identities = [identities[0],
                      ("representante", (data.get("extra") or {}).get("representative_rut"))]
    for label, rut in identities:
        if not rut_valid(rut):
            raise HTTPException(422, "RUT inválido de " + label + "; corrígelo en la ficha.")
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
        body, _, _ = _text_source(db, user, payload.code)
        if not body:
            raise HTTPException(
                409, "Falta revisar y habilitar el texto original para vista previa. "
                     "Abre Configuración → Plantillas y cláusulas."
            )
        try:
            approved_text = render_tokens(body, data)
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
