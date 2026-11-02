"""API GALANT POST. Ficheros privados, acceso por organización y procesamiento diferido."""
from __future__ import annotations
import csv
import hashlib
import io
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from uuid import uuid4
import fitz
from PIL import Image, UnidentifiedImageError
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuditEvent, Document, User, utcnow
from .schemas import Dashboard, DocumentView, Login, Profile
from .security import CSRF, SESSION, authorized_user, editor, new_session, verify_password

app = FastAPI(title="GALANT POST — Document Intelligence", version="0.1.0", docs_url=None, redoc_url=None)
API = "/api/v1"
attempts: dict[str, deque] = defaultdict(deque)
SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
TYPES = {"auto", "cotizaciones", "f30_1", "independientes"}


def audit(db: Session, user: User, action: str, target: str | None = None):
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id, action=action, resource_id=target))


def document_for(db: Session, user: User, doc_id: str) -> Document:
    record = db.scalar(select(Document).where(Document.id == doc_id, Document.org_id == user.org_id))
    if record is None:
        raise HTTPException(404, "Documento no encontrado")
    return record


@app.get(API + "/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "Servicio temporalmente no disponible") from None
    return {"status": "ok", "service": "galant-post-api"}


@app.post(API + "/auth/login", response_model=Profile)
def login(data: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    remote = request.client.host if request.client else "unknown"
    identifier = remote + ":" + data.email.strip().lower()
    tries = attempts[identifier]
    t = time.monotonic()
    while tries and t - tries[0] > 600:
        tries.popleft()
    if len(tries) >= 8:
        raise HTTPException(429, "Demasiados intentos de acceso")
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if not user or not user.enabled or not verify_password(data.password, user.password_hash):
        tries.append(t)
        raise HTTPException(401, "Credenciales incorrectas")
    tries.clear()
    token, csrf = new_session(user)
    secure = settings().secure_cookies
    ttl = settings().session_hours * 3600
    response.set_cookie(SESSION, token, httponly=True, secure=secure, samesite="strict", path="/", max_age=ttl)
    response.set_cookie(CSRF, csrf, httponly=False, secure=secure, samesite="strict", path="/", max_age=ttl)
    audit(db, user, "login")
    db.commit()
    return user


@app.get(API + "/auth/me", response_model=Profile)
def me(user: User = Depends(authorized_user)):
    return user


@app.post(API + "/auth/logout")
def logout(response: Response, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    audit(db, user, "logout")
    db.commit()
    response.delete_cookie(SESSION, path="/")
    response.delete_cookie(CSRF, path="/")
    return {"ok": True}


@app.get(API + "/dashboard", response_model=Dashboard)
def dashboard(user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Document.status, Document.payment_status, func.count(Document.id))
                      .where(Document.org_id == user.org_id)
                      .group_by(Document.status, Document.payment_status)).all()
    return Dashboard(
        total=sum(n for _, _, n in rows),
        finished=sum(n for state, _, n in rows if state == "complete"),
        queued=sum(n for state, _, n in rows if state in {"queued", "processing"}),
        accredited=sum(n for state, payment, n in rows if state == "complete" and payment == "Pago acreditado documentalmente"),
        review=sum(n for state, payment, n in rows if state == "complete" and payment == "Pendiente de revisión"),
        errors=sum(n for state, _, n in rows if state == "error"),
    )


@app.get(API + "/documents", response_model=list[DocumentView])
def documents(category: str | None = None, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    query = select(Document).where(Document.org_id == user.org_id)
    if category in TYPES - {"auto"}:
        query = query.where((Document.declared_type == category) | (Document.detected_type == category))
    return db.scalars(query.order_by(Document.created_at.desc()).limit(200)).all()


@app.post(API + "/documents", response_model=DocumentView, status_code=202)
async def upload(file: UploadFile = File(...), category: str = Form("auto"),
                 user: User = Depends(editor), db: Session = Depends(get_db)):
    if category not in TYPES:
        raise HTTPException(422, "Módulo inválido")
    name = re.sub(r"[^\w .()\-_]", "_", Path(file.filename or "documento.pdf").name)[:240]
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(415, "Solo se aceptan PDF e imágenes")
    private = settings().document_dir / user.org_id
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    doc_id = str(uuid4())
    path = private / (doc_id + suffix)
    digest = hashlib.sha256()
    size = 0
    signature = b""
    try:
        with path.open("xb") as output:
            path.chmod(0o600)
            while fragment := await file.read(1024 * 1024):
                size += len(fragment)
                if size > settings().max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, "Archivo demasiado grande")
                signature += fragment[:max(0, 16 - len(signature))]
                digest.update(fragment)
                output.write(fragment)
        if size == 0:
            raise HTTPException(422, "Archivo vacío")
        if suffix == ".pdf":
            if not signature.startswith(b"%PDF-"):
                raise HTTPException(415, "El archivo no es un PDF válido")
            try:
                with fitz.open(path) as pdf:
                    if pdf.is_encrypted or not 1 <= len(pdf) <= settings().max_pdf_pages:
                        raise HTTPException(422, "PDF cifrado o con número de páginas no permitido")
            except (fitz.FileDataError, fitz.FileNotFoundError):
                raise HTTPException(422, "El PDF está dañado") from None
        else:
            try:
                with Image.open(path) as img:
                    img.verify()
                with Image.open(path) as img:
                    if img.width * img.height > 22_000_000:
                        raise HTTPException(413, "Resolución demasiado alta")
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                raise HTTPException(422, "Imagen inválida") from None
        already = db.scalar(select(Document).where(Document.org_id == user.org_id,
                                                   Document.sha256 == digest.hexdigest()))
        if already:
            path.unlink(missing_ok=True)
            return already
        doc = Document(id=doc_id, org_id=user.org_id, user_id=user.id,
                       original_name=name, storage_path=str(path), sha256=digest.hexdigest(),
                       declared_type=category, status="queued", extracted={}, evidence=[], warnings=[])
        db.add(doc)
        audit(db, user, "document.uploaded", doc_id)
        db.commit()
        db.refresh(doc)
        return doc
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.get(API + "/documents/{doc_id}", response_model=DocumentView)
def read_document(doc_id: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    return document_for(db, user, doc_id)


@app.get(API + "/documents/{doc_id}/file")
def document_file(doc_id: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    doc = document_for(db, user, doc_id)
    path = Path(doc.storage_path)
    if not path.is_file():
        raise HTTPException(404, "Archivo no encontrado en disco")
    mime = "application/pdf" if path.suffix.lower() == ".pdf" else "image/" + path.suffix.lstrip(".")
    return FileResponse(path, media_type=mime, filename=doc.original_name,
                        content_disposition_type="inline",
                        headers={"Cache-Control": "no-store", "Content-Security-Policy": "sandbox"})


@app.post(API + "/documents/{doc_id}/retry", response_model=DocumentView)
def retry(doc_id: str, user: User = Depends(editor), db: Session = Depends(get_db)):
    doc = document_for(db, user, doc_id)
    if doc.status not in {"error", "complete"}:
        raise HTTPException(409, "Ya se encuentra procesando")
    doc.status = "queued"
    doc.error = None
    doc.updated_at = utcnow()
    audit(db, user, "document.retry", doc_id)
    db.commit()
    db.refresh(doc)
    return doc


def safe_csv(value):
    out = str(value) if value is not None else ""
    if out.startswith(("=", "+", "-", "@", "\t", "\r")):
        out = "'" + out
    return out


@app.get(API + "/documents/{doc_id}/report")
def export(doc_id: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    doc = document_for(db, user, doc_id)
    if doc.status != "complete":
        raise HTTPException(409, "El procesamiento aún no ha terminado")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["CAMPO", "VALOR"])
    writer.writerow(["Archivo", safe_csv(doc.original_name)])
    writer.writerow(["Estado", safe_csv(doc.payment_status)])
    writer.writerow(["Tipo", safe_csv(doc.detected_type)])
    writer.writerow(["Período", safe_csv(doc.extracted.get("periodo"))])
    writer.writerow(["RUT válidos", safe_csv(", ".join(doc.extracted.get("ruts_validos", [])))])
    writer.writerow(["Verificación ante institución", "NO"])
    for item in doc.evidence:
        writer.writerow(["Evidencia página " + str(item.get("pagina")), safe_csv(item.get("extracto", ""))])
    for note in doc.warnings:
        writer.writerow(["Observación", safe_csv(note)])
    buf.seek(0)
    audit(db, user, "document.export", doc_id)
    db.commit()
    return StreamingResponse(iter([buf.getvalue().encode("utf-8-sig")]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="galant-{doc_id}.csv"',
                                      "Cache-Control": "no-store"})
