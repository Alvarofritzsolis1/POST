"""Piloto documental GALANT 19: vistas previas nativas HTML/CSS -> PDF.

Solo permite leer expedientes locales del usuario administrador y matrices
preventivas aprobadas de su organización. No publica, no emite actas ni
altera registros operativos. El generador Excel v18 sigue disponible.
"""
from __future__ import annotations

import fitz

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .javiera_matrices import latest_approved_matrix
from .javiera_formula_equivalence import pesos_a_letras_excel, INVALID_AMOUNT
from .javiera_logic import DOCUMENT_BY_CODE, render_tokens, check_template_fields, rut_valid
from .javiera_irl import preventive_matrix_blocker
from .javiera_models import JavieraRevision, JavieraTemplate
from .javiera_native_edit import TOKEN, NativeHtmlError, bind_native_html, plain_text_to_html, validate_native_html
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


def _source_from_row(template: JavieraTemplate | None,
                     latest: JavieraRevision | None):
    if template is None:
        return None, None, "missing"
    if latest and latest.revision > template.published_version:
        if latest.state == "pilot_print" and (latest.contents or {}).get("body"):
            return latest.contents["body"], latest.revision, "pilot_print"
        return None, None, "requires_review"
    if template.published_version > 0 and template.body:
        return template.body, template.published_version, "published"
    return None, None, "missing"


def _text_source(db: Session, user: User, code: str):
    """Preview-only authoring; pilot does NOT publish professional signoff."""
    template = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    if template is None:
        return _source_from_row(None, None)
    latest = db.scalar(select(JavieraRevision).where(
        JavieraRevision.org_id == user.org_id,
        JavieraRevision.template_id == template.id
    ).order_by(JavieraRevision.revision.desc()))
    return _source_from_row(template, latest)


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


class NativeHtmlDraft(BaseModel):
    """Solo edición de diseño documental; no altera el texto Excel ni emisiones."""
    model_config = ConfigDict(extra="forbid")
    html: str = Field(min_length=20, max_length=35000)
    reason: str = Field(min_length=6, max_length=500)


def _latest_native_revision(db: Session, row: JavieraTemplate | None):
    if row is None:
        return None
    return db.scalar(select(JavieraRevision).where(
        JavieraRevision.org_id == row.org_id,
        JavieraRevision.template_id == row.id,
    ).order_by(JavieraRevision.revision.desc()))


def _native_source_from_row(row: JavieraTemplate | None,
                            latest: JavieraRevision | None):
    """Devuelve fragmento habilitado, revisión y estado, sin publicar contratos."""
    if row is None:
        return None, None, "missing"
    if latest and latest.revision > row.published_version:
        markup = (latest.contents or {}).get("layout", {}).get("native_html")
        if markup:
            if latest.state == "pilot_print":
                return markup, latest.revision, "pilot_print"
            return None, latest.revision, "requires_review"
        # Un borrador textual sin edición HTML debe seguir usando el flujo textual.
        return None, latest.revision, "missing"
    if row.published_version > 0 and (row.layout or {}).get("native_html"):
        return row.layout["native_html"], row.published_version, "published"
    return None, None, "missing"


@router.get("/editor/{code}")
def native_editor(code: str, user: User = Depends(administrator),
                  db: Session = Depends(get_db)):
    """Texto editable HTML por tipo documental; no expone archivos Excel."""
    if code not in DOCUMENT_TITLES:
        raise HTTPException(404, "Documento no reconocido.")
    row = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    latest = _latest_native_revision(db, row)
    active, revision, state = _native_source_from_row(row, latest)
    newer_layout = (latest.contents or {}).get("layout", {}) if latest else {}
    draft_html = newer_layout.get("native_html") if latest else None
    if draft_html:
        editor_html = draft_html
        status = latest.state
        revision = latest.revision
    elif active:
        editor_html = active
        status = state
    else:
        # Reutilizar cláusulas existentes como texto, sin reescribirlas.
        body = ((latest.contents or {}).get("body") if latest else "") or (
            row.body if row else "")
        editor_html = plain_text_to_html(body) if body else ""
        status = "unconfigured"
    return {
        "code": code, "title": row.title if row else DOCUMENT_TITLES[code],
        "html": editor_html, "revision": revision, "state": status,
        "mode": "supplement" if code in {
            "irl", "induction", "internal_rules_receipt"} else "main_body",
        "preview_only": True,
        "needs_review": status in {"draft", "unconfigured", "requires_review"},
    }


@router.get("/editor/{code}/history")
def native_editor_history(code: str, user: User = Depends(administrator),
                          db: Session = Depends(get_db)):
    """Historial visual de borradores, sin sobrescribir plantillas publicadas."""
    if code not in DOCUMENT_TITLES:
        raise HTTPException(404, "Documento no reconocido.")
    row = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    if row is None:
        return {"code": code, "revisions": []}
    revisions = db.scalars(select(JavieraRevision).where(
        JavieraRevision.org_id == user.org_id,
        JavieraRevision.template_id == row.id,
    ).order_by(JavieraRevision.revision.desc()).limit(50)).all()
    return {
        "code": code,
        "revisions": [{
            "revision": item.revision, "state": item.state,
            "reason": item.reason, "created_at": item.created_at.isoformat(),
            "html": (item.contents or {}).get("layout", {}).get("native_html"),
        } for item in revisions
            if (item.contents or {}).get("layout", {}).get("native_html")],
        "restoration_policy": "copy_as_new_draft",
    }


@router.put("/editor/{code}")
def save_native_html(code: str, payload: NativeHtmlDraft,
                     user: User = Depends(administrator),
                     db: Session = Depends(get_db)):
    """Guardar nuevo diseño sin modificar la plantilla profesional publicada."""
    if code not in DOCUMENT_TITLES:
        raise HTTPException(404, "Documento no reconocido.")
    try:
        cleaned = validate_native_html(payload.html)
    except NativeHtmlError as exc:
        raise HTTPException(422, str(exc)) from None
    row = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    if row is None:
        meta = DOCUMENT_BY_CODE[code]
        row = JavieraTemplate(
            org_id=user.org_id, code=code,
            title=meta[2], area=meta[1],
            fields=list(meta[4]), body="", layout={}, rule={},
        )
        db.add(row)
        db.flush()
    latest = _latest_native_revision(db, row)
    revision_number = (latest.revision + 1) if latest else 1
    # Partir de la última revisión conservando los vínculos/variables, no del Excel.
    snapshot = dict(latest.contents or {}) if latest else {}
    snapshot.setdefault("title", row.title)
    snapshot.setdefault("area", row.area)
    snapshot.setdefault("body", row.body)
    snapshot.setdefault("fields", row.fields)
    snapshot.setdefault("rule", row.rule)
    layout = dict(snapshot.get("layout") or row.layout or {})
    layout["native_html"] = cleaned
    snapshot["layout"] = layout
    draft = JavieraRevision(
        org_id=user.org_id, template_id=row.id,
        revision=revision_number, contents=snapshot,
        reason=payload.reason.strip(), author_id=user.id,
    )
    db.add(draft)
    db.flush()
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="javiera.native_html_draft_saved",
                      resource_id=draft.id))
    db.commit()
    return {"code": code, "revision": revision_number,
            "state": "draft", "message": "Diseño HTML guardado como borrador."}


@router.post("/editor/{code}/enable-preview")
def enable_native_html(code: str, payload: EnablePilotText,
                       user: User = Depends(administrator),
                       db: Session = Depends(get_db)):
    """Habilita SOLO el diseño HTML para vista previa con un único ADMIN."""
    if code not in DOCUMENT_TITLES:
        raise HTTPException(404, "Documento no reconocido.")
    if not settings().javiera_solo_pilot:
        raise HTTPException(403, "Requiere modo piloto de administrador único.")
    if not payload.confirmed_content:
        raise HTTPException(422, "Confirma que revisaste el texto y el diseño.")
    row = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id, JavieraTemplate.code == code))
    latest = _latest_native_revision(db, row)
    if latest is None or latest.revision != payload.revision:
        raise HTTPException(409, "El diseño cambió. Abre la última revisión antes de habilitar.")
    if latest.state == "pilot_print":
        return {"code": code, "revision": latest.revision, "preview_only": True}
    if latest.state != "draft":
        raise HTTPException(409, "La revisión ya no está en borrador.")
    try:
        validate_native_html((latest.contents or {}).get("layout", {}).get("native_html", ""))
    except NativeHtmlError as exc:
        raise HTTPException(422, str(exc)) from None
    latest.state = "pilot_print"
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="javiera.native_html_preview_enabled",
                      resource_id=latest.id))
    db.commit()
    return {"code": code, "revision": latest.revision, "preview_only": True}


# Datos necesarios para PDF HTML, no la lista excesiva de celdas del Excel.
NATIVE_BASE_FIELDS = {
    "labor_contract": ["role", "employment_type", "contract.start",
                       "contract.salary", "contract.hours", "event.date"],
    "transfer_addendum": ["role", "contract.transfer_date", "event.date"],
    "extension_addendum": ["contract.end", "contract.new_end", "event.date"],
    "sworn_declaration": ["extra.representative_name", "extra.representative_rut",
                          "contract.declaration_reason", "event.date"],
    "internal_rules_receipt": ["event.date", "extra.regulation_version"],
    "ppe_delivery": ["role", "event.epp_items", "event.date"],
    "irl": ["role", "event.date"],
    "pts": ["role", "event.date", "extra.representative_name",
            "extra.representative_rut"],
    "pts_receipt": ["role", "event.pts_version", "event.date"],
    "induction": ["role", "event.date", "event.induction_topics"],
}


@router.get("/formats")
def native_formats(user: User = Depends(administrator),
                   db: Session = Depends(get_db)):
    """All ten A4 layouts available; seven require approved source texts."""
    rows = db.scalars(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id,
        JavieraTemplate.code.in_(list(DOCUMENT_TITLES)),
    )).all()
    by_code = {row.code: row for row in rows}
    latest_by_id = {}
    if rows:
        revisions = db.scalars(select(JavieraRevision).where(
            JavieraRevision.org_id == user.org_id,
            JavieraRevision.template_id.in_([row.id for row in rows]),
        ).order_by(JavieraRevision.revision.desc())).all()
        for revision in revisions:
            latest_by_id.setdefault(revision.template_id, revision)
    sources = {
        code: _source_from_row(by_code.get(code),
                               latest_by_id.get(by_code[code].id)
                               if code in by_code else None)
        for code in ORIGINAL_TEXT_CODES
    }
    native_sources = {
        code: _native_source_from_row(
            by_code.get(code),
            latest_by_id.get(by_code[code].id) if code in by_code else None
        ) for code in DOCUMENT_TITLES
    }
    def required_fields(code: str) -> list[str]:
        row = by_code.get(code)
        last = latest_by_id.get(row.id) if row else None
        fragment = native_sources[code][0]
        if not fragment and last:
            fragment = (last.contents or {}).get("layout", {}).get("native_html")
        if not fragment and code in ORIGINAL_TEXT_CODES:
            fragment = (sources[code][0] or
                        (last.contents or {}).get("body", "") if last else
                        sources[code][0] or (row.body if row else ""))
        tokens = TOKEN.findall(fragment or "")
        return list(dict.fromkeys([*NATIVE_BASE_FIELDS[code], *tokens]))

    def status(code: str) -> str:
        native_markup, _, native_state = native_sources[code]
        if native_state == "requires_review":
            return "requires_review"
        if native_markup:
            return "ready"
        if code not in ORIGINAL_TEXT_CODES:
            return "ready"
        return "ready" if sources[code][0] else "requires_published_text"
    return {
        "mode": "preview_only",
        "source": "html_css",
        "uses_excel_for_printing": False,
        "requires_physical_signature": True,
        "formats": [
            {"code": code, "title": title,
             "status": status(code),
             "source_kind": ("html_editable" if native_sources[code][0]
                 else sources[code][2] if code in ORIGINAL_TEXT_CODES
                 else "native_default"),
             "editable_in": "Editor HTML de Proyecto Javiera",
             "required_fields": required_fields(code),
             "source_revision": (
                 native_sources[code][1] or
                 (sources[code][1] if code in ORIGINAL_TEXT_CODES else None)
             )}
            for code, title in DOCUMENT_TITLES.items()
        ],
        "message": ("Diez formatos HTML editables, con vista previa PDF A4. "
                    "Los documentos pendientes exigen revisar su texto antes de imprimir. "
                    "Excel queda disponible solo como referencia histórica."),
    }


class NativeBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dossier_id: str = Field(min_length=1, max_length=100)
    codes: list[str] = Field(min_length=1, max_length=10)


@router.post("/preview/batch")
def preview_native_batch(payload: NativeBatchInput,
                         user: User = Depends(administrator),
                         db: Session = Depends(get_db)):
    """Paquete A4 nativo, sin depender de Excel y sin crear emisiones ficticias."""
    if len(set(payload.codes)) != len(payload.codes):
        raise HTTPException(422, "Selecciona cada documento una sola vez.")
    if any(code not in DOCUMENT_TITLES for code in payload.codes):
        raise HTTPException(422, "Se encontró un documento no reconocido.")
    # Comprueba integridad del expediente, permisos y contenido POR DOCUMENTO.
    _dossier(db, user, payload.dossier_id)
    merged = fitz.open()
    try:
        for code in payload.codes:
            response = preview_native(
                NativePreviewInput(dossier_id=payload.dossier_id, code=code),
                user=user, db=db
            )
            with fitz.open(stream=response.body, filetype="pdf") as part:
                merged.insert_pdf(part)
        if merged.page_count > 80:
            raise HTTPException(422, "El paquete supera 80 páginas A4.")
        output = merged.tobytes(garbage=3, deflate=True)
    finally:
        merged.close()
    return Response(
        content=output, media_type="application/pdf",
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": 'inline; filename="documentos-para-firma-a4.pdf"',
            "X-Content-Type-Options": "nosniff",
        },
    )


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
    if payload.code in {"irl", "pts"}:
        document_fields = record.document_data or {}
        manual = []
        for code, key in (("irl", "irl_manual_labor"), ("pts", "pts_manual_labor")):
            entry = document_fields.get(code) or {}
            text = (entry.get("event") or {}).get(key, "")
            if isinstance(text, str) and text.strip():
                manual.append(text)
        if manual:
            raise HTTPException(
                409, "Hay una labor manual pendiente de incorporar a la matriz preventiva. "
                     "Conserva el borrador y solicita revisión antes de imprimir IRL/PTS."
            )
    # Paridad del campo original 'Datos Contrato' C32 -> 'NUMEROS A LETRAS' S4.
    # Este cálculo se limita al contrato y jamás sustituye fórmulas del Excel.
    if payload.code == "labor_contract":
        contract = data.get("contract")
        if isinstance(contract, dict) and contract.get("salary") not in (None, ""):
            salary_words = pesos_a_letras_excel(contract["salary"])
            if salary_words == INVALID_AMOUNT:
                raise HTTPException(
                    422, "Sueldo base inválido. Ingresa pesos enteros de 0 a 999.999.999."
                )
            data["contract"] = {**contract, "salary_words": salary_words}
            # El editor de plantillas ya emplea {{extra.salary_words}}.
            # Mantener ambos nombres en la ruta documental, sin modificar Excel.
            data["extra"] = {**(data.get("extra") or {}), "salary_words": salary_words}
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
    if payload.code in {"irl", "pts", "pts_receipt"}:
        kind = "IRL" if payload.code == "irl" else "PTS"
        approved = latest_approved_matrix(db, user.org_id, kind, data.get("role", ""))
        matrix = approved.sections if approved else None
        if not matrix:
            raise HTTPException(
                409, f"Falta matriz {kind} aprobada para este cargo. No se inventará contenido."
            )
        issue = preventive_matrix_blocker(kind, matrix)
        if issue:
            raise HTTPException(409, issue)
        # La versión impresa procede siempre de la matriz aprobada, nunca
        # de una casilla editable del expediente o del usuario.
        if kind == "IRL":
            data["extra"] = {**(data.get("extra") or {}),
                             "irl_revision": f"IRL revisión {approved.revision}"}
        else:
            data["event"] = {**(data.get("event") or {}),
                             "pts_version": f"PTS revisión {approved.revision}"}
    row = db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == user.org_id,
        JavieraTemplate.code == payload.code,
    ))
    latest = _latest_native_revision(db, row)
    native_fragment, _, native_state = _native_source_from_row(row, latest)
    if native_state == "requires_review":
        raise HTTPException(
            409, "El HTML tiene cambios sin habilitar. Abre el editor y revisa la última versión."
        )
    approved_text = None
    approved_html = None
    native_intro = None
    if native_fragment:
        try:
            prepared = bind_native_html(native_fragment, data)
        except NativeHtmlError as exc:
            raise HTTPException(422, str(exc)) from None
        if payload.code in ORIGINAL_TEXT_CODES:
            approved_html = prepared
        else:
            native_intro = prepared
    elif payload.code in ORIGINAL_TEXT_CODES:
        body, _, _ = _text_source(db, user, payload.code)
        if not body:
            raise HTTPException(
                409, "Falta el contenido HTML verificado. Abre Editor HTML y "
                     "guarda las cláusulas originales del documento."
            )
        try:
            approved_text = render_tokens(body, data)
        except ValueError as exc:
            raise HTTPException(
                422, "Falta completar un campo requerido por el texto verificado: " + str(exc)
            ) from None
        if "{{" in approved_text or "}}" in approved_text:
            raise HTTPException(422, "El texto contiene variables sin resolver.")
    try:
        pdf = render_native_pdf(payload.code, data, matrix=matrix,
                                approved_text=approved_text,
                                approved_html=approved_html,
                                native_intro=native_intro)
    except NativeDocumentError as exc:
        raise HTTPException(422, str(exc)) from None
    return Response(
        content=pdf, media_type="application/pdf",
        headers={
            "Cache-Control": "no-store, private",
            "Content-Disposition": 'inline; filename="documento-para-firma.pdf"',
            "X-Content-Type-Options": "nosniff",
        },
    )
