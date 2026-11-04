"""Private operational attachments never expose the labor-document repository."""

import hashlib
import re
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User
from .network_models import NetworkAttachment
from .network_service import (
    event,
    lock_org,
    notify,
    participant_for,
    record_for,
    requirement_for,
)
from .network_models import NetworkParticipant
from .security import authorized_user

router = APIRouter(prefix="/api/v1/network", tags=["Adjuntos de coordinación"])
MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def attachment_view(row):
    return {
        "id": row.id,
        "filename": row.filename,
        "size": row.size,
        "uploaded_by": row.uploaded_by,
        "created_at": row.created_at,
    }


@router.get("/attachments")
def attachments(
    requirement_id: str | None = None,
    conversation_id: str | None = None,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    if bool(requirement_id) == bool(conversation_id):
        raise HTTPException(422, "Selecciona un requerimiento o conversación")
    query = select(NetworkAttachment).where(NetworkAttachment.org_id == user.org_id)
    if requirement_id:
        requirement_for(db, user, requirement_id, detail=True)
        query = query.where(NetworkAttachment.requirement_id == requirement_id)
    else:
        participant_for(db, user, conversation_id)
        query = query.where(NetworkAttachment.conversation_id == conversation_id)
    return [
        attachment_view(row)
        for row in db.scalars(query.order_by(NetworkAttachment.created_at).limit(200))
    ]


@router.post("/attachments", status_code=201)
async def upload_attachment(
    file: UploadFile = File(...),
    requirement_id: str | None = Form(None),
    conversation_id: str | None = Form(None),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    if bool(requirement_id) == bool(conversation_id):
        raise HTTPException(422, "Selecciona un requerimiento o conversación")
    if requirement_id:
        requirement_for(db, user, requirement_id, write=True)
    else:
        participant_for(db, user, conversation_id)
    filename = re.sub(r"[^\w .()\-_]", "_", Path(file.filename or "adjunto").name)[:240]
    suffix = Path(filename).suffix.lower()
    if suffix not in MIME:
        raise HTTPException(415, "Adjunta un PDF, JPG o PNG")
    folder = settings().document_dir / user.org_id / "network"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / (str(uuid4()) + suffix)
    digest, size = hashlib.sha256(), 0
    try:
        with path.open("xb") as output:
            path.chmod(0o600)
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings().max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, "El archivo supera el tamaño permitido")
                digest.update(chunk)
                output.write(chunk)
        if size == 0:
            raise HTTPException(422, "Archivo vacío")
        if suffix == ".pdf":
            try:
                with fitz.open(path) as pdf:
                    if (
                        pdf.is_encrypted
                        or not 1 <= len(pdf) <= settings().max_pdf_pages
                    ):
                        raise HTTPException(422, "PDF cifrado o con demasiadas páginas")
                    if pdf.is_form_pdf or pdf.embfile_count():
                        raise HTTPException(
                            415,
                            "Adjunta un PDF sin formularios ni archivos incrustados",
                        )
                    if any(
                        "/JavaScript" in pdf.xref_object(x)
                        or "/Launch" in pdf.xref_object(x)
                        for x in range(1, pdf.xref_length())
                    ):
                        raise HTTPException(
                            415, "El PDF contiene acciones no autorizadas"
                        )
            except (fitz.FileDataError, RuntimeError):
                raise HTTPException(422, "PDF dañado o inválido") from None
        else:
            try:
                with Image.open(path) as img:
                    if img.width * img.height > 22_000_000 or img.format not in {
                        "JPEG",
                        "PNG",
                    }:
                        raise HTTPException(
                            415, "Formato o resolución de imagen no permitido"
                        )
                    img.verify()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                raise HTTPException(422, "Imagen inválida") from None
        lock_org(db, user)
        # Recheck authorization after streaming the file and acquiring the write lock.
        if requirement_id:
            requirement_for(db, user, requirement_id, write=True)
        else:
            participant_for(db, user, conversation_id)
        row = NetworkAttachment(
            org_id=user.org_id,
            requirement_id=requirement_id,
            conversation_id=conversation_id,
            uploaded_by=user.id,
            filename=filename,
            path=str(path),
            mime=MIME[suffix],
            size=size,
            sha256=digest.hexdigest(),
        )
        db.add(row)
        db.flush()
        event(
            db,
            user,
            "attachment",
            requirement_id or conversation_id,
            None,
            {"attachment_id": row.id, "filename": filename, "sha256": row.sha256},
        )
        if conversation_id:
            notify(
                db,
                user,
                db.scalars(
                    select(NetworkParticipant.user_id).where(
                        NetworkParticipant.conversation_id == conversation_id
                    )
                ),
                "attachment:" + row.id,
                "Nuevo archivo en la conversación",
                "conversation",
                conversation_id,
            )
        db.commit()
        return attachment_view(row)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("/attachments/{record_id}/file")
def download_attachment(
    record_id: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)
):
    row = record_for(db, NetworkAttachment, user, record_id)
    if row.requirement_id:
        requirement_for(db, user, row.requirement_id, detail=True)
    else:
        participant_for(db, user, row.conversation_id)
    if not Path(row.path).is_file():
        raise HTTPException(404, "Archivo no disponible")
    return FileResponse(
        row.path,
        media_type=row.mime,
        filename=row.filename,
        content_disposition_type="attachment",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )
