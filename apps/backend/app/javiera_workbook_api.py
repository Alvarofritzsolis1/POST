"""Private Excel workspace, immutable revisions and reversible Javiera reset."""
from __future__ import annotations
import io
import json
import shutil
import time
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .javiera_excel import DOC_SHEETS, MAX_FILE, LayoutError
from .javiera_models import (JavieraDossier, JavieraIssue, JavieraHistory, JavieraTemplate,
    JavieraRevision, JavieraMatrix, JavieraExcelLayout, JavieraSignoff, JavieraReviewerAuthorization)
from .javiera_workbook import (MATRIX_SHEETS, cached_pdf, convert_pdf, digest, edit_workbook,
    inventory, read_sheet, resolve_sheet, roles, repair_master, clean_master, run_calc, CONVERSIONS, fill_workbook)
from .javiera_workbook_models import (JavieraWorkbook, JavieraWorkbookHead,
    JavieraWorkbookValidation, JavieraReset, JavieraArchive)
from .models import AuditEvent, User, utcnow
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/workbook", tags=["Javiera · Excel maestro"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CellEdit(Strict):
    cell: str = Field(pattern=r"^[A-Z]{1,3}[1-9]\d{0,5}$")
    value: str | float | None = Field(default=None)
    formula: str | None = Field(default=None, max_length=15000)
    style_from: str | None = Field(default=None, pattern=r"^[A-Z]{1,3}[1-9]\d{0,5}$")
    row_height: float | None = Field(default=None, ge=10, le=409)


class RevisionInput(Strict):
    expected_revision: int = Field(ge=1)
    sheet: str = Field(max_length=120)
    reason: str = Field(min_length=10, max_length=800)
    edits: list[CellEdit] = Field(min_length=1, max_length=500)


class RestoreInput(Strict):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=800)


class PreviewInput(Strict):
    code: str
    dossier_id: str


class CalculationInput(Strict):
    sheet: str = Field(max_length=120)
    start: int = Field(default=1, ge=1)
    count: int = Field(default=55, ge=1, le=100)
    dossier_id: str | None = None


class PublishInput(Strict):
    expected_revision: int = Field(ge=1)
    codes: list[str] = Field(min_length=1, max_length=10)


class ResetInput(Strict):
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=10, max_length=800)


def audit(db, user, action, ident):
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id, action=action, resource_id=ident))


def root_for(org_id: str) -> Path:
    return settings().document_dir / org_id / "javiera"


def workbook(db, user, ident: str) -> JavieraWorkbook:
    obj = db.get(JavieraWorkbook, ident)
    if not obj or obj.org_id != user.org_id: raise HTTPException(404, "Revisión Excel no encontrada")
    return obj


def raw_for(obj: JavieraWorkbook) -> bytes:
    path = Path(obj.path).resolve(); root = (root_for(obj.org_id) / "workbooks").resolve()
    if not path.is_relative_to(root) or not path.is_file(): raise HTTPException(404, "Excel privado no disponible")
    raw = path.read_bytes()
    if digest(raw) != obj.sha256: raise HTTPException(409, "La integridad del Excel cambió; restaura una revisión verificada")
    return raw


def original_for(db, obj: JavieraWorkbook) -> bytes:
    original = db.scalar(select(JavieraWorkbook).where(JavieraWorkbook.org_id == obj.org_id,
        JavieraWorkbook.sha256 == obj.original_sha256).order_by(JavieraWorkbook.revision.asc()))
    if not original:raise HTTPException(409,'No se encuentra el original inmutable para comprobar identidades')
    return raw_for(original)


def head_for(db, org_id: str):
    return db.get(JavieraWorkbookHead, org_id)


def active_workbook(db, org_id: str, published: bool = False, code: str | None = None):
    head = head_for(db, org_id)
    if not head: return None
    ident = head.publications.get(code) if published and code else head.published_id if published else head.current_id
    return db.get(JavieraWorkbook, ident) if ident else None


def unarchived(model, org_id: str, kind: str):
    return ~model.id.in_(select(JavieraArchive.resource_id).where(
        JavieraArchive.org_id == org_id, JavieraArchive.kind == kind))


def write_revision(db, user, raw, reason, expected: int, parent: JavieraWorkbook | None = None):
    report = inventory(raw); ident = str(uuid4()); revision = expected + 1
    head = head_for(db, user.org_id)
    if head is None:
        if expected != 0: raise HTTPException(409, "El libro cambió; recarga antes de guardar")
        head = JavieraWorkbookHead(org_id=user.org_id, revision=0, publications={})
        db.add(head)
        try: db.flush()
        except IntegrityError:
            db.rollback(); raise HTTPException(409, "Otro administrador importó el Excel; recarga") from None
    changed = db.execute(update(JavieraWorkbookHead).where(
        JavieraWorkbookHead.org_id == user.org_id, JavieraWorkbookHead.revision == expected
    ).values(revision=revision, current_id=ident), execution_options={"synchronize_session": False})
    if changed.rowcount != 1:
        db.rollback(); raise HTTPException(409, "Otro administrador guardó una revisión. Recarga y conserva tus cambios")
    folder = root_for(user.org_id) / "workbooks"; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / (ident + ".xlsx")
    with path.open("xb") as f: f.write(raw)
    path.chmod(0o400)
    obj = JavieraWorkbook(id=ident, org_id=user.org_id, revision=revision,
        parent_id=parent.id if parent else None, path=str(path), sha256=digest(raw),
        original_sha256=parent.original_sha256 if parent else digest(raw), inventory=report,
        reason=reason, author_id=user.id)
    db.add(obj); audit(db, user, "javiera.workbook_saved", ident)
    try: db.commit()
    except Exception:
        db.rollback(); path.unlink(missing_ok=True); raise
    db.expire_all()
    return obj


def summary(obj):
    return {"id": obj.id, "revision": obj.revision, "sha256": obj.sha256,
        "original_sha256": obj.original_sha256, "author_id": obj.author_id,
        "reason": obj.reason, "created_at": obj.created_at.isoformat(), "inventory": obj.inventory}


@router.get("")
def status(user: User = Depends(administrator), db: Session = Depends(get_db)):
    current = active_workbook(db, user.org_id); head = head_for(db, user.org_id)
    return {"current": summary(current) if current else None,
        "publications": head.publications if head else {},
        "engine": {"name": "LibreOffice Calc", "available": bool(settings().javiera_calc_url or shutil.which("libreoffice") or shutil.which("soffice")),
                   "warm": bool(settings().javiera_calc_url),
                   "max_parallel": 2},
        "documents": [{"code": code, "sheet": name} for code, name in DOC_SHEETS.items()]}


@router.post("/import")
async def import_workbook(expected_revision: int = 0, file: UploadFile = File(...),
                          user: User = Depends(administrator), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(422, "Selecciona un archivo .xlsx sin macros")
    raw = await file.read(MAX_FILE + 1)
    try:
        report = inventory(raw)
        names = {s["name"].strip() for s in report["sheets"]}
        required = {"Datos Contrato", "Contrato Imprimible", "MATRIZ IRL", "MATRIZ PTS"}
        if not required.issubset(names): raise LayoutError("Faltan hojas maestras de contratación y matrices")
        obj = write_revision(db, user, raw, "Importación íntegra del Excel maestro original", expected_revision)
        repaired, notes = repair_master(raw)
        repaired = clean_master(repaired)
        obj = write_revision(db, user, repaired,
            "Datos de ejemplo vaciados; original conservado. " + "; ".join(notes)[:730], obj.revision, obj)
    except LayoutError as e: raise HTTPException(422, str(e)) from None
    return summary(obj)


@router.get("/revisions")
def revisions(user: User = Depends(administrator), db: Session = Depends(get_db)):
    return [summary(obj) for obj in db.scalars(select(JavieraWorkbook).where(
        JavieraWorkbook.org_id == user.org_id).order_by(JavieraWorkbook.revision.desc()).limit(100))]


@router.get("/{ident}/sheet")
def get_sheet(ident: str, name: str, start: int = 1, count: int = 60,
              user: User = Depends(administrator), db: Session = Depends(get_db)):
    if start < 1 or not 1 <= count <= 100: raise HTTPException(422, "Rango de hoja fuera del límite")
    try: return read_sheet(raw_for(workbook(db, user, ident)), name, start, count)
    except LayoutError as e: raise HTTPException(422, str(e)) from None


@router.get("/{ident}/roles")
def get_roles(ident: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    return roles(raw_for(workbook(db, user, ident)))


@router.post("/{ident}/calculate-sheet")
def calculate_sheet(ident: str, payload: CalculationInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    raw = raw_for(workbook(db, user, ident))
    if payload.dossier_id:raw = fill_workbook(raw,dossier_data(db,user,payload.dossier_id),'labor_contract')
    if not CONVERSIONS.acquire(timeout=15): raise HTTPException(503, "El motor está ocupado; vuelve a intentarlo")
    try:
        with tempfile.TemporaryDirectory(prefix="galant-recalculate-") as temp:
            calculated = run_calc(raw, Path(temp))
            return read_sheet(calculated, payload.sheet, payload.start, payload.count)
    except LayoutError as exc: raise HTTPException(422, str(exc)) from None
    finally: CONVERSIONS.release()


@router.get("/{ident}/download")
def download(ident: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    obj = workbook(db, user, ident); raw = raw_for(obj)
    return Response(raw, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="GALANT_Maestro_r{obj.revision}.xlsx"'})


@router.post("/{ident}/edit")
def edit(ident: str, payload: RevisionInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    obj = workbook(db, user, ident); head = head_for(db, user.org_id)
    if head.current_id != obj.id or obj.revision != payload.expected_revision:
        raise HTTPException(409, "Abre la revisión actual antes de guardar")
    try:
        changes = [e.model_dump(exclude_unset=True) for e in payload.edits]
        if len(json.dumps(changes)) > 1_000_000: raise LayoutError("La edición supera el tamaño permitido")
        raw = edit_workbook(raw_for(obj), payload.sheet, changes)
        return summary(write_revision(db, user, raw, payload.reason, payload.expected_revision, obj))
    except LayoutError as e: raise HTTPException(422, str(e)) from None


@router.post("/{ident}/restore")
def restore(ident: str, payload: RestoreInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    obj = workbook(db, user, ident)
    return summary(write_revision(db, user, raw_for(obj), payload.reason, payload.expected_revision, obj))


def dossier_data(db, user, ident):
    from .javiera_api import dossier
    return dossier(db, user, ident).data


@router.post("/{ident}/preview")
def preview(ident: str, payload: PreviewInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    obj = workbook(db, user, ident)
    if payload.code not in DOC_SHEETS: raise HTTPException(404, "Documento desconocido")
    data = dossier_data(db, user, payload.dossier_id)
    from .javiera_api import evaluated
    check = next(item for item in evaluated(db, user, data, payload.dossier_id) if item['code'] == payload.code)
    if not check['can_preview']:
        raise HTTPException(409, check['reason'] or 'Completa los antecedentes obligatorios del documento')
    try:
        raw, report = cached_pdf(raw_for(obj), payload.code, data, user.org_id,
                                root_for(user.org_id) / "pdf-cache", True, reference=original_for(db,obj))
    except LayoutError as e: raise HTTPException(422, str(e)) from None
    existing = db.scalar(select(JavieraWorkbookValidation).where(
        JavieraWorkbookValidation.workbook_id == obj.id, JavieraWorkbookValidation.code == payload.code))
    if existing: existing.result = report
    else: db.add(JavieraWorkbookValidation(org_id=user.org_id, workbook_id=obj.id, code=payload.code, result=report))
    audit(db, user, "javiera.workbook_preview_checked", obj.id); db.commit()
    return Response(raw, media_type="application/pdf", headers={
        "X-Galant-Cache": "hit" if report["cache_hit"] else "miss",
        "X-Galant-Conversion-Ms": str(report["elapsed_ms"]),
        "Content-Disposition": 'inline; filename="GALANT_Borrador.pdf"'})


@router.get("/{ident}/validations")
def validations(ident: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    workbook(db, user, ident)
    return [{"code": v.code, "result": v.result} for v in db.scalars(select(JavieraWorkbookValidation).where(
        JavieraWorkbookValidation.org_id == user.org_id, JavieraWorkbookValidation.workbook_id == ident))]


@router.post("/{ident}/publish")
def publish(ident: str, payload: PublishInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    from .javiera_review import require_signoff, specialty_for_code
    obj = workbook(db, user, ident)
    head = db.scalar(select(JavieraWorkbookHead).where(JavieraWorkbookHead.org_id==user.org_id).with_for_update())
    if obj.id != head.current_id or obj.revision != payload.expected_revision: raise HTTPException(409, "La revisión actual cambió")
    if obj.author_id == user.id: raise HTTPException(403, "Otro administrador debe revisar y publicar el Excel")
    for code in payload.codes:
        if code not in DOC_SHEETS: raise HTTPException(422, "Documento desconocido")
        require_signoff(db, user, "workbook", obj.id, specialty_for_code(code))
        result = db.scalar(select(JavieraWorkbookValidation).where(
            JavieraWorkbookValidation.org_id == user.org_id,
            JavieraWorkbookValidation.workbook_id == obj.id, JavieraWorkbookValidation.code == code))
        if not result: raise HTTPException(409, "Primero genera y comprueba la vista previa de " + code)
    # Publishing is also a CAS operation: a simultaneous save cannot publish stale content.
    result = db.execute(update(JavieraWorkbookHead).where(
        JavieraWorkbookHead.org_id == user.org_id, JavieraWorkbookHead.revision == payload.expected_revision,
        JavieraWorkbookHead.current_id == ident).values(
            publications={**head.publications, **{code: obj.id for code in payload.codes}}, published_id=obj.id))
    if result.rowcount != 1: db.rollback(); raise HTTPException(409, "La revisión cambió durante la publicación")
    audit(db, user, "javiera.workbook_published", obj.id); db.commit()
    return {"revision": obj.revision, "codes": payload.codes}


def reset_plan(db, user):
    rows = {}
    for kind, model in (("dossier", JavieraDossier), ("issue", JavieraIssue), ("history", JavieraHistory)):
        rows[kind] = sorted(db.scalars(select(model.id).where(model.org_id == user.org_id, unarchived(model, user.org_id, kind))).all())
    head = head_for(db, user.org_id)
    versions = [(r.id, r.revision, r.updated_at.isoformat()) for r in db.scalars(select(JavieraDossier).where(
        JavieraDossier.org_id == user.org_id, unarchived(JavieraDossier, user.org_id, "dossier")))]
    plan = {"records": rows, "record_versions": sorted(versions), "current_id": head.current_id if head else None,
            "published_id": head.published_id if head else None, "publications": head.publications if head else {},
            "legacy_disabled": head.legacy_disabled if head else False,
            "mode": "archivo_reversible", "scope": "solo_javiera"}
    return {**plan, "sha256": digest(json.dumps(plan, sort_keys=True).encode()),
            "counts": {k: len(v) for k, v in rows.items()}}


@router.get("/reset/plan")
def plan_reset(user: User = Depends(administrator), db: Session = Depends(get_db)):
    return reset_plan(db, user)


@router.post("/reset/execute")
def execute_reset(payload: ResetInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    # Organization row lock serializes reset with itself. PostgreSQL dossier issue
    # locks and immutable files ensure the archive is never a destructive operation.
    head = db.scalar(select(JavieraWorkbookHead).where(JavieraWorkbookHead.org_id == user.org_id).with_for_update())
    plan = reset_plan(db, user)
    if plan["sha256"] != payload.plan_sha256: raise HTTPException(409, "Los datos cambiaron; revisa un nuevo plan de limpieza")
    if not head: raise HTTPException(409, "Importa primero el nuevo Excel maestro")
    ident = str(uuid4()); root = root_for(user.org_id).resolve(); folder = root / "reset-backups"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700); path = folder / (ident + ".zip")
    manifest = {"plan": plan, "reason": payload.reason, "files": {}, "rows": {}}
    for model in (JavieraDossier, JavieraIssue, JavieraHistory, JavieraTemplate, JavieraRevision, JavieraMatrix,
                  JavieraExcelLayout, JavieraSignoff, JavieraReviewerAuthorization, JavieraWorkbook,
                  JavieraWorkbookHead, JavieraWorkbookValidation, JavieraArchive):
        manifest["rows"][model.__tablename__] = [
            {col.name: getattr(obj, col.name).isoformat() if isinstance(getattr(obj, col.name), datetime)
             else getattr(obj, col.name) for col in model.__table__.columns}
            for obj in db.scalars(select(model).where(model.org_id == user.org_id))]
    try:
        with ZipFile(path, "x", ZIP_DEFLATED) as z:
            for f in sorted(root.rglob("*")):
                if not f.is_file() or f.is_symlink() or f.is_relative_to(folder): continue
                if not f.resolve().is_relative_to(root): raise HTTPException(409, "Archivo fuera del alcance privado")
                raw = f.read_bytes(); name = f.relative_to(root).as_posix()
                manifest["files"][name] = digest(raw); z.writestr("files/" + name, raw)
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, default=str))
        path.chmod(0o600)
        with ZipFile(path) as z:
            if z.testzip(): raise HTTPException(500, "No se pudo verificar el respaldo")
            for name, sha in manifest["files"].items():
                if digest(z.read("files/" + name)) != sha: raise HTTPException(500, "Respaldo inconsistente")
        sha = digest(path.read_bytes())
        db.add(JavieraReset(id=ident, org_id=user.org_id, path=str(path), sha256=sha, manifest=plan, author_id=user.id)); db.flush()
        for kind, ids in plan["records"].items():
            for resource in ids: db.add(JavieraArchive(org_id=user.org_id, reset_id=ident, kind=kind, resource_id=resource))
        # Keep issued records and originals under retention; remove them from the new workspace.
        head.publications = {}; head.published_id = None; head.legacy_disabled = True
        audit(db, user, "javiera.reset_archived", ident); db.commit()
    except Exception:
        db.rollback(); path.unlink(missing_ok=True); raise
    shutil.rmtree(root / "pdf-cache", ignore_errors=True)
    return {"id": ident, "backup_sha256": sha, "archived": plan["counts"], "reversible": True}


@router.get("/reset/history")
def reset_history(user: User = Depends(administrator), db: Session = Depends(get_db)):
    return [{"id": r.id, "sha256": r.sha256, "counts": r.manifest["counts"],
             "created_at": r.created_at.isoformat(), "restored": bool(r.restored_at)}
            for r in db.scalars(select(JavieraReset).where(JavieraReset.org_id == user.org_id).order_by(JavieraReset.created_at.desc()))]


@router.post("/reset/{ident}/restore")
def restore_reset(ident: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    obj = db.get(JavieraReset, ident)
    if not obj or obj.org_id != user.org_id: raise HTTPException(404, "Respaldo no encontrado")
    path = Path(obj.path).resolve()
    if not path.is_relative_to((root_for(user.org_id) / "reset-backups").resolve()) or not path.is_file():
        raise HTTPException(404, "Respaldo privado no disponible")
    if digest(path.read_bytes()) != obj.sha256: raise HTTPException(409, "El respaldo no supera la verificación SHA256")
    if obj.restored_at: raise HTTPException(409, "Este reinicio ya fue restaurado")
    newer = db.scalar(select(JavieraReset).where(JavieraReset.org_id == user.org_id,
        JavieraReset.created_at > obj.created_at, JavieraReset.restored_at.is_(None)))
    if newer: raise HTTPException(409, "Restaura primero el reinicio más reciente")
    db.execute(delete(JavieraArchive).where(JavieraArchive.org_id == user.org_id, JavieraArchive.reset_id == obj.id))
    head = head_for(db, user.org_id)
    if head:
        head.publications = obj.manifest["publications"]; head.published_id = obj.manifest["published_id"]
        head.legacy_disabled = obj.manifest.get("legacy_disabled", False)
    obj.restored_at = utcnow(); audit(db, user, "javiera.reset_restored", obj.id); db.commit()
    return {"id": obj.id, "restored": True}
