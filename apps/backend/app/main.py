"""API GALANT POST. Ficheros privados, acceso por organización y procesamiento diferido."""
from __future__ import annotations
import hashlib
import logging
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from uuid import uuid4
import fitz
from PIL import Image, UnidentifiedImageError
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, load_only

from .config import settings
from .db import get_db
from .models import AuditEvent, Document, User, utcnow
from .ops_api import router as ops_router
from .control_api import router as control_router
from .control_admin import router as control_admin_router
from .control_reports import router as control_reports_router
from .contract_import_api import router as contract_import_router
from .monthly_api import router as monthly_router
from .ops_import_api import router as ops_import_router
from . import bulk_import
from .pipeline import extraction_path
from .reports import build_workbook
from .schemas import Dashboard, DocumentSummary, DocumentView, Login, Profile
from .security import CSRF, SESSION, authorized_user, editor, document_uploader, new_session, verify_password
from .version import VERSION, SOURCE_COMMIT
from .admin_api import router as admin_router
from .reconciliation import router as reconciliation_router
from .labor_api import router as labor_router
from .attendance_api import router as attendance_router
from .v81_api import router as attendance_v81_router
from .compliance_api import router as compliance_router
from . import platform_models
from .network_accounts import router as network_accounts_router
from .network_api import router as network_router
from .network_files import router as network_files_router
from .configuration_api import router as configuration_router
from .javiera_api import router as javiera_router
from .javiera_v166_api import router as javiera_v166_router
from .javiera_v17_api import router as javiera_v17_router
from .javiera_v18_api import router as javiera_v18_router
from .javiera_review import router as javiera_reviews_router
from .javiera_layout_api import router as javiera_layouts_router

app = FastAPI(title="GALANT POST — Document Intelligence", version=VERSION, docs_url=None, redoc_url=None)
app.include_router(configuration_router)
app.include_router(javiera_router)
app.include_router(javiera_v166_router)
app.include_router(javiera_v17_router)
app.include_router(javiera_v18_router)
app.include_router(javiera_reviews_router)
app.include_router(javiera_layouts_router)
app.include_router(compliance_router)
app.include_router(admin_router)
app.include_router(reconciliation_router)
app.include_router(labor_router)
app.include_router(attendance_router)
app.include_router(attendance_v81_router)
app.include_router(ops_router)
app.include_router(control_router)
app.include_router(control_admin_router)
app.include_router(control_reports_router)
app.include_router(contract_import_router)
app.include_router(monthly_router)
app.include_router(ops_import_router)
app.include_router(network_accounts_router)
app.include_router(network_router)
app.include_router(network_files_router)
@app.middleware("http")
async def private_cache_policy(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


logger = logging.getLogger("galant.post.api")
API = "/api/v1"
attempts: dict[str, deque] = defaultdict(deque)
SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
TYPES = {"auto", "cotizaciones", "f30_1"}


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
    return {"status": "ok", "service": "galant-post-api", "version": VERSION,
            "commit": SOURCE_COMMIT}


@app.get(API + "/version")
def version():
    return {"version": VERSION, "commit": SOURCE_COMMIT}


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
    token, csrf = new_session(user, db)
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
    from .network_accounts import revoke_sessions
    revoke_sessions(db, user)
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


@app.get(API + "/documents", response_model=list[DocumentSummary])
def documents(category: str | None = None, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    query = select(Document).options(load_only(
        Document.id, Document.original_name, Document.declared_type, Document.detected_type,
        Document.status, Document.payment_status, Document.created_at,
    )).where(Document.org_id == user.org_id)
    if category in TYPES - {"auto"}:
        query = query.where((Document.declared_type == category) | (Document.detected_type == category))
    return db.scalars(query.order_by(Document.created_at.desc()).limit(200)).all()


@app.post(API + "/documents", response_model=DocumentView, status_code=202)
async def upload(file: UploadFile = File(...), category: str = Form("auto"),
                 user: User = Depends(document_uploader), db: Session = Depends(get_db)):
    started = time.perf_counter()
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
        if db.get_bind().dialect.name == "postgresql":
            lock_material = f"{user.org_id}:{digest.hexdigest()}:{category}".encode()
            lock_key = int.from_bytes(hashlib.sha256(lock_material).digest()[:8], "big", signed=True)
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        already = db.scalar(select(Document).where(Document.org_id == user.org_id,
                                                   Document.sha256 == digest.hexdigest(),
                                                   Document.declared_type == category))
        if already:
            path.unlink(missing_ok=True)
            logger.info("Carga duplicada %s bytes=%d validacion_s=%.4f", already.id, size,
                        time.perf_counter() - started)
            return already
        doc = Document(id=doc_id, org_id=user.org_id, user_id=user.id,
                       original_name=name, storage_path=str(path), sha256=digest.hexdigest(),
                       declared_type=category, status="queued", extracted={}, evidence=[], warnings=[])
        db.add(doc)
        audit(db, user, "document.uploaded", doc_id)
        db.commit()
        db.refresh(doc)
        logger.info("Carga recibida %s bytes=%d validacion_s=%.4f", doc_id, size,
                    time.perf_counter() - started)
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


@app.get(API + "/documents/{doc_id}/extraction")
def document_extraction(doc_id: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    doc = document_for(db, user, doc_id)
    if doc.status != "complete":
        raise HTTPException(409, "La extracción aún no está disponible")
    path = extraction_path(doc.storage_path)
    if not path.is_file():
        raise HTTPException(404, "Extracción no disponible para este documento")
    return FileResponse(path, media_type="application/json", filename=f"galant-{doc_id}-ocr.json",
                        headers={"Cache-Control": "no-store"})


@app.post(API + "/documents/{doc_id}/retry", response_model=DocumentView)
def retry(doc_id: str, user: User = Depends(editor), db: Session = Depends(get_db)):
    doc = document_for(db, user, doc_id)
    if doc.status not in {"error", "complete"}:
        raise HTTPException(409, "Ya se encuentra procesando")
    doc.status = "queued"
    doc.error = None
    doc.detected_type = None
    doc.payment_status = None
    doc.page_count = 0
    doc.extracted = {}
    doc.evidence = []
    doc.warnings = []
    doc.updated_at = utcnow()
    audit(db, user, "document.retry", doc_id)
    db.commit()
    db.refresh(doc)
    return doc


@app.get(API + "/documents/{doc_id}/report")
def export(doc_id: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    started = time.perf_counter()
    doc = document_for(db, user, doc_id)
    if doc.status != "complete":
        raise HTTPException(409, "El procesamiento aún no ha terminado")
    content = build_workbook(doc)
    audit(db, user, "document.export", doc_id)
    db.commit()
    logger.info("Excel generado %s bytes=%d exportacion_s=%.4f", doc_id, len(content),
                time.perf_counter() - started)
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="galant-{doc_id}.xlsx"',
                             "Cache-Control": "no-store"})
