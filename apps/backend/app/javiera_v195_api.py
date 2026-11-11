"""GALANT 19.4.2: acceso autenticado a las imágenes del IRL original privado."""
from fastapi import APIRouter, Depends, Response, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from .javiera_models import (JavieraTemplate, JavieraRevision, JavieraSignoff,
                             JavieraReviewerAuthorization)
from .models import AuditEvent, utcnow

from sqlalchemy.orm import Session

from .db import get_db
from .javiera_irl_original import load_original_for_user
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v195", tags=["Javiera · IRL original A4"])


@router.get("/irl-original")
def irl_original(response: Response, user: User = Depends(administrator),
                 db: Session = Depends(get_db)):
    """La foto y el texto fijo se toman del XLSX de la organización; nunca del GitHub.

    La consulta no genera trabajadores ni modifica los otros módulos.
    """
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return load_original_for_user(db, user, approved_only=False)


# Edición de los cinco bloques gráficos originales: datos privados por
# organización. El catálogo de texto no se sube al GitHub público.
BLOCK_TITLES = (
    "Antecedentes generales y otras consideraciones",
    "Normas generales de seguridad, puntos 1–3",
    "Normas generales de seguridad, puntos 4–6",
    "Normas generales de seguridad, puntos 7–9",
    "Normas generales de seguridad, puntos 10–13",
)
BLOCK_TEMPLATE_CODE = "irl_visual_blocks"


class GraphicBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(ge=1, le=5)
    text: str = Field(min_length=30, max_length=18000)
    reviewed: bool = False


class GraphicRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_hashes: list[str] = Field(min_length=5, max_length=5)
    blocks: list[GraphicBlock] = Field(min_length=5, max_length=5)
    reason: str = Field(min_length=12, max_length=800)


def _graphic_template(db: Session, org_id: str) -> JavieraTemplate | None:
    return db.scalar(select(JavieraTemplate).where(
        JavieraTemplate.org_id == org_id,
        JavieraTemplate.code == BLOCK_TEMPLATE_CODE))


def _latest_graphic(db: Session, template_id: str) -> JavieraRevision | None:
    return db.scalar(select(JavieraRevision).where(
        JavieraRevision.template_id == template_id).order_by(
            JavieraRevision.revision.desc()))


def _authorized_signoff(db: Session, org_id: str,
                        row: JavieraRevision) -> JavieraSignoff | None:
    """Sólo un revisor independiente designado y vigente puede autorizar.
    
    El administrador puede ejecutar una publicación YA aprobada; no es
    necesario que el publicador sea también un prevencionista. La aprobación
    técnica pertenece al acta, no al botón Publicar.
    """
    signoff = db.scalar(select(JavieraSignoff).where(
        JavieraSignoff.org_id == org_id,
        JavieraSignoff.resource_kind == "template",
        JavieraSignoff.resource_id == row.id,
        JavieraSignoff.specialty == "prevencion",
        JavieraSignoff.verdict == "approved"))
    if not signoff or signoff.reviewer_id == row.author_id:
        return None
    granted = db.scalar(select(JavieraReviewerAuthorization).where(
        JavieraReviewerAuthorization.org_id == org_id,
        JavieraReviewerAuthorization.user_id == signoff.reviewer_id,
        JavieraReviewerAuthorization.specialty == "prevencion",
        JavieraReviewerAuthorization.active.is_(True)))
    return signoff if granted else None


def _authorized_original(db: Session, user: User) -> dict:
    source = load_original_for_user(db, user, approved_only=False)
    if not source.get("available") or len(source.get("images") or []) != 5:
        raise HTTPException(409, "Antes de editar importa el IRL original con sus cinco imágenes.")
    return source


@router.get("/irl-blocks")
def irl_visual_blocks(response: Response,
                      user: User = Depends(administrator),
                      db: Session = Depends(get_db)):
    """Mostrar estado real; nunca aceptar como aprobación la carga del Excel."""
    response.headers["Cache-Control"] = "private, no-store"
    source = _authorized_original(db, user)
    template = _graphic_template(db, user.org_id)
    latest = _latest_graphic(db, template.id) if template else None
    approved = (db.scalar(select(JavieraRevision).where(
        JavieraRevision.template_id == template.id,
        JavieraRevision.revision == template.published_version,
        JavieraRevision.state == "approved")) if template and
        template.published_version else None)
    contents = latest.contents if latest else {}
    valid_approval = _authorized_signoff(db, user.org_id, latest) if latest else None
    preventive_review = (db.scalar(select(JavieraSignoff).where(
        JavieraSignoff.org_id == user.org_id,
        JavieraSignoff.resource_kind == "template",
        JavieraSignoff.resource_id == latest.id,
        JavieraSignoff.specialty == "prevencion"))
        if latest else None)
    return {
        "source_sha256": source["source_sha256"],
        "source_layout_status": source.get("status", "not_approved"),
        "image_hashes": [image["sha256"] for image in source["images"]],
        "titles": list(BLOCK_TITLES),
        "latest": {
            "id": latest.id if latest else None,
            "revision": latest.revision if latest else None,
            "status": latest.state if latest else "not_started",
            "blocks": contents.get("blocks", []),
            "source_matches": bool(latest and contents.get("source_sha256") ==
                                   source["source_sha256"] and
                                   contents.get("image_hashes") ==
                                   [i["sha256"] for i in source["images"]]),
            "preventive_verdict": (preventive_review.verdict
                                    if preventive_review else "pending"),
            "preventive_authorization_valid": bool(valid_approval),
            "author_is_current_user": bool(latest and latest.author_id == user.id),
            "can_publish": bool(latest and latest.state == "draft" and
                source.get("status") == "approved" and valid_approval and
                contents.get("source_sha256") == source["source_sha256"] and
                contents.get("image_hashes") ==
                [i["sha256"] for i in source["images"]] and
                len(contents.get("blocks") or []) == 5 and
                all(block.get("reviewed") for block in
                    contents.get("blocks") or [])),
        },
        "approved_revision": approved.revision if approved else None,
        "approved_source_matches": bool(approved and
             approved.contents.get("source_sha256") == source["source_sha256"] and
             approved.contents.get("image_hashes") ==
             [i["sha256"] for i in source["images"]]),
        "requires_preventive_signoff": True,
        "manual_review_cannot_be_assumed": True,
    }


@router.post("/irl-blocks")
def save_irl_visual_blocks(payload: GraphicRevisionInput,
                           user: User = Depends(administrator),
                           db: Session = Depends(get_db)):
    """Crea revisión INMUTABLE en borrador; no publica ni imprime."""
    source = _authorized_original(db, user)
    actual_hashes = [item["sha256"] for item in source["images"]]
    if payload.source_sha256 != source["source_sha256"] or payload.image_hashes != actual_hashes:
        raise HTTPException(409, "Las imágenes originales cambiaron: vuelve a cotejar el contenido.")
    if {item.id for item in payload.blocks} != {1, 2, 3, 4, 5}:
        raise HTTPException(422, "Debes incluir los cinco bloques, sin duplicar ni omitir ninguno.")
    template = _graphic_template(db, user.org_id)
    if template is None:
        template = JavieraTemplate(
            org_id=user.org_id, code=BLOCK_TEMPLATE_CODE, area="prevencion",
            title="IRL - cinco bloques visuales editables",
            body="", fields=[], rule={}, layout={})
        db.add(template)
        db.flush()
    number = (db.scalar(select(func.max(JavieraRevision.revision)).where(
        JavieraRevision.template_id == template.id)) or 0) + 1
    row = JavieraRevision(
        org_id=user.org_id, template_id=template.id, revision=number,
        contents={
            "source_sha256": payload.source_sha256,
            "image_hashes": list(payload.image_hashes),
            "blocks": [obj.model_dump() for obj in sorted(payload.blocks, key=lambda x: x.id)],
        },
        state="draft", author_id=user.id, reason=payload.reason)
    db.add(row)
    db.flush()
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="javiera.irl_visual_draft", resource_id=row.id))
    db.commit()
    return {"id": row.id, "revision": number, "state": row.state,
            "message": "Borrador guardado. Debe aprobarse mediante acta preventiva independiente."}


@router.post("/irl-blocks/{revision_id}/publish")
def publish_irl_visual_blocks(revision_id: str,
                              user: User = Depends(administrator),
                              db: Session = Depends(get_db)):
    """Publicar solo revisión completa, cotejada, aprobada por otro revisor."""
    row = db.get(JavieraRevision, revision_id)
    template = _graphic_template(db, user.org_id)
    if not row or not template or row.template_id != template.id or row.org_id != user.org_id:
        raise HTTPException(404, "Revisión privada de bloques IRL no encontrada.")
    if row.state != "draft":
        raise HTTPException(409, "Esta revisión no es un borrador publicable.")
    if _latest_graphic(db, template.id).id != row.id:
        raise HTTPException(409, "La aprobación corresponde a una revisión anterior.")
    source = _authorized_original(db, user)
    if source.get("status") != "approved":
        raise HTTPException(409, "Primero aprueba el formato Excel IRL original "
                            "antes de publicar los cinco bloques editables.")
    content = row.contents
    if (content.get("source_sha256") != source["source_sha256"] or
        content.get("image_hashes") != [i["sha256"] for i in source["images"]]):
        raise HTTPException(409, "Fuente IRL modificada; revisa los cinco bloques de nuevo.")
    blocks = content.get("blocks", [])
    if len(blocks) != 5 or {x.get("id") for x in blocks} != {1,2,3,4,5} or any(
        not x.get("reviewed") or not str(x.get("text") or "").strip() for x in blocks
    ):
        raise HTTPException(422, "Los cinco bloques deben estar cotejados y completos.")
    signoff = _authorized_signoff(db, user.org_id, row)
    if not signoff:
        raise HTTPException(409, "Falta acta preventiva aprobada por un revisor "
                            "distinto del autor y con designación vigente.")
    row.state = "approved"
    row.reviewer_id = signoff.reviewer_id
    row.reviewed_at = utcnow()
    template.published_version = row.revision
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="javiera.irl_visual_publish", resource_id=row.id))
    db.commit()
    return {"id": row.id, "revision": row.revision, "state": row.state,
            "message": "Bloques editoriales aprobados mediante acta preventiva de otro usuario."}


def attach_approved_irl_visual(db: Session, user: User, source: dict) -> dict:
    """Reemplazo impreso solo de fuente exacta y versión PUBLICADA por revisor."""
    if (not source.get("available") or source.get("status") != "approved" or
        len(source.get("images") or []) != 5):
        return source
    template = _graphic_template(db, user.org_id)
    if not template or not template.published_version:
        return source
    revision = db.scalar(select(JavieraRevision).where(
        JavieraRevision.template_id == template.id,
        JavieraRevision.revision == template.published_version,
        JavieraRevision.state == "approved"))
    if not revision:
        return source
    content = revision.contents
    hashes = [i["sha256"] for i in source["images"]]
    if (content.get("source_sha256") != source.get("source_sha256") or
        content.get("image_hashes") != hashes or
        len(content.get("blocks") or []) != 5 or
        not all(x.get("reviewed") for x in content["blocks"])):
        return source
    prepared = dict(source)
    prepared["approved_editable_blocks"] = [
        {"title": BLOCK_TITLES[i-1], "text": block["text"]}
        for i, block in enumerate(sorted(content["blocks"], key=lambda b:b["id"]), 1)
    ]
    prepared["approved_editor_revision"] = revision.revision
    prepared["approved_editor_signoff_id"] = revision.id
    return prepared
