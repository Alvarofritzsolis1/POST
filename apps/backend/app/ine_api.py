"""GALANT INE: transcripción exacta, edición con permisos y respaldo independiente."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from io import BytesIO
from hashlib import sha256
import re
import unicodedata
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_db
from .ine_models import IneChange, IneOriginal, IneRow, IneSheet
from .models import User, utcnow
from .network_models import NetworkMember, NetworkMembership
from .ops_models import Worksite
from .security import administrator, authorized_user

router = APIRouter(prefix="/api/v1/ine", tags=["INE"])
FIELDS = ("cct", "cesp", "ind", "th", "tm")
CHILE = ZoneInfo("America/Santiago")


class SheetEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0)
    cct: int | None = Field(default=None, ge=0, le=1000000)
    cesp: int | None = Field(default=None, ge=0, le=1000000)
    ind: int | None = Field(default=None, ge=0, le=1000000)
    th: int | None = Field(default=None, ge=0, le=1000000)
    tm: int | None = Field(default=None, ge=0, le=1000000)


class NewSheetRow(SheetEdit):
    site_id: str
    period: str


class LinkSite(BaseModel):
    site_id: str | None = None


def period_of(value: str) -> str:
    if not re.fullmatch(r"(19|20|21)\d{2}-(0[1-9]|1[0-2])", value):
        raise HTTPException(422, "Mes no válido. Usa AAAA-MM")
    return value


def current_month() -> str:
    return datetime.now(CHILE).strftime("%Y-%m")


def previous_month() -> str:
    now = datetime.now(CHILE)
    return f"{now.year - (1 if now.month == 1 else 0):04d}-{12 if now.month == 1 else now.month - 1:02d}"


def can_edit(user: User, period: str, site_id: str | None, assigned: set[str]) -> bool:
    if user.role == "admin":
        return True
    return bool(user.role == "ine_supervisor" and site_id in assigned
                and period in {current_month(), previous_month()})


def access(user: User) -> None:
    if user.role not in {"admin", "ine_supervisor"}:
        raise HTTPException(403, "Solo administradores y supervisores INE")


def assigned_sites(db: Session, user: User) -> set[str]:
    if user.role == "admin":
        return set(db.scalars(select(Worksite.id).where(Worksite.org_id == user.org_id)))
    return set(db.scalars(
        select(NetworkMembership.site_id).join(
            Worksite, NetworkMembership.site_id == Worksite.id
        ).where(NetworkMembership.user_id == user.id, Worksite.org_id == user.org_id)
    ))


def actor(db: Session, user: User) -> str:
    member = db.get(NetworkMember, user.id)
    return (member.name.strip() if member and member.name.strip() else user.email)


def snapshot(row: IneRow) -> dict:
    return {key: getattr(row, key) for key in FIELDS}


def row_view(row: IneRow, user: User, allowed: set[str]) -> dict:
    values = snapshot(row)
    complete = all(v is not None for v in values.values())
    return {
        "id": row.id, "period": row.period, "site_id": row.site_id,
        "site_name": row.site_name, "supervisor": row.supervisor,
        **values,
        "complete": complete, "editable": can_edit(user, row.period, row.site_id, allowed),
        "version": row.version, "source_sheet": row.source_sheet,
        "source_row": row.source_row,
        "source_status": row.original_values.get("status") if row.original_values else None,
        "source_total": row.original_values.get("total") if row.original_values else None,
        "source_percent": row.original_values.get("percent") if row.original_values else None,
    }


def serialize(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (float,)):
        return value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


def normalized(name: str) -> str:
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    value = re.sub(r"^\s*OBRA\s+", "", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip().upper()


def number_or_none(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 and int(value) == value:
        return int(value)
    return None


def save_changes(db: Session, row: IneRow, user: User, before: dict, after: dict, action="edit") -> None:
    if before == after:
        return
    db.add(IneChange(
        org_id=user.org_id, row_id=row.id, user_id=user.id, actor_name=actor(db, user),
        action=action, previous=before, current=after,
    ))
    row.updated_by = user.id
    row.updated_at = utcnow()
    row.version += 1


@router.get("/config")
def config(user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    access(user)
    allowed = assigned_sites(db, user)
    sites = db.scalars(select(Worksite).where(Worksite.org_id == user.org_id).order_by(Worksite.name)).all()
    original = db.scalar(select(IneOriginal).where(IneOriginal.org_id == user.org_id).order_by(IneOriginal.created_at.desc()))
    return {
        "role": user.role, "current_month": current_month(), "previous_month": previous_month(),
        "sites": [{"id": s.id, "name": s.name} for s in sites if user.role == "admin" or s.id in allowed],
        "source": ({"name": original.filename, "sha256": original.sha256, "id": original.id}
                   if original and user.role == "admin" else None),
    }


@router.get("/rows")
def rows(period: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    access(user)
    period = period_of(period)
    allowed = assigned_sites(db, user)
    items = db.scalars(select(IneRow).where(IneRow.org_id == user.org_id, IneRow.period == period)
                       .order_by(IneRow.source_row, IneRow.site_name)).all()
    if user.role != "admin":
        items = [r for r in items if r.site_id in allowed]
    result = [row_view(r, user, allowed) for r in items]
    known_ids = {r.site_id for r in items if r.site_id}
    site_query = select(Worksite).where(Worksite.org_id == user.org_id).order_by(Worksite.name)
    for site in db.scalars(site_query):
        if site.id in known_ids or (user.role != "admin" and site.id not in allowed):
            continue
        result.append({
            "id": None, "period": period, "site_id": site.id, "site_name": site.name,
            "supervisor": "", **{key: None for key in FIELDS},
            "complete": False, "editable": can_edit(user, period, site.id, allowed),
            "version": 0, "source_sheet": "", "source_row": 0,
            "source_status": None, "source_total": None, "source_percent": None,
        })
    return {"period": period, "rows": result}


@router.put("/rows/{row_id}")
def edit_row(row_id: str, body: SheetEdit, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    access(user)
    allowed = assigned_sites(db, user)
    row = db.scalar(select(IneRow).where(IneRow.id == row_id, IneRow.org_id == user.org_id).with_for_update())
    if not row:
        raise HTTPException(404, "Fila no encontrada")
    if not can_edit(user, row.period, row.site_id, allowed):
        raise HTTPException(403, "Solo puedes editar tus obras del mes actual o anterior")
    if row.version != body.version:
        raise HTTPException(409, "Esta fila fue actualizada por otra persona. Recarga antes de guardar")
    before = snapshot(row)
    after = {key: getattr(body, key) for key in FIELDS}
    for key, value in after.items():
        setattr(row, key, value)
    save_changes(db, row, user, before, after)
    db.commit()
    return row_view(row, user, allowed)


@router.post("/rows", status_code=201)
def create_row(body: NewSheetRow, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    access(user)
    period = period_of(body.period)
    allowed = assigned_sites(db, user)
    site = db.scalar(select(Worksite).where(Worksite.id == body.site_id, Worksite.org_id == user.org_id))
    if not site:
        raise HTTPException(404, "Obra no encontrada")
    if not can_edit(user, period, site.id, allowed):
        raise HTTPException(403, "Solo puedes editar tus obras del mes actual o anterior")
    existing = db.scalar(select(IneRow.id).where(IneRow.org_id == user.org_id,
                          IneRow.period == period, IneRow.site_id == site.id))
    if existing:
        raise HTTPException(409, "Esta obra ya tiene un registro para ese mes. Actualiza la vista")
    row = IneRow(
        org_id=user.org_id, period=period, site_id=site.id, site_name=site.name,
        source_sheet="APP:" + site.id, source_row=0,
        **{key: getattr(body, key) for key in FIELDS},
    )
    db.add(row)
    db.flush()
    db.add(IneChange(org_id=user.org_id, row_id=row.id, user_id=user.id, actor_name=actor(db, user),
                     action="create", previous={}, current=snapshot(row)))
    db.commit()
    return row_view(row, user, allowed)


@router.put("/rows/{row_id}/link")
def link_row(row_id: str, body: LinkSite, user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = db.scalar(select(IneRow).where(IneRow.id == row_id, IneRow.org_id == user.org_id).with_for_update())
    if not row:
        raise HTTPException(404, "Fila no encontrada")
    if body.site_id:
        site = db.scalar(select(Worksite).where(Worksite.org_id == user.org_id, Worksite.id == body.site_id))
        if not site:
            raise HTTPException(404, "Obra inexistente")
        other = db.scalar(select(IneRow.id).where(
            IneRow.org_id == user.org_id, IneRow.period == row.period,
            IneRow.site_id == site.id, IneRow.id != row.id))
        if other:
            raise HTTPException(409, "Ya existe una fila del mes vinculada a esta obra")
    before = {"site_id": row.site_id}
    row.site_id = body.site_id
    save_changes(db, row, user, before, {"site_id": body.site_id}, "link")
    db.commit()
    return row_view(row, user, assigned_sites(db, user))


@router.get("/history")
def history(period: str | None = None, limit: int = 100, user: User = Depends(administrator),
            db: Session = Depends(get_db)):
    query = select(IneChange, IneRow).join(IneRow, IneRow.id == IneChange.row_id).where(
        IneChange.org_id == user.org_id, IneRow.org_id == user.org_id)
    if period:
        query = query.where(IneRow.period == period_of(period))
    logs = db.execute(query.order_by(IneChange.created_at.desc(), IneChange.id.desc())
                      .limit(min(max(limit, 1), 300))).all()
    return [{"id": h.id, "actor_name": h.actor_name, "action": h.action,
             "period": row.period, "site_name": row.site_name,
             "previous": h.previous, "current": h.current,
             "created_at": h.created_at.isoformat()} for h, row in logs]


@router.get("/summary")
def summary(year: int, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    access(user)
    if not 1900 <= year <= 2199:
        raise HTTPException(422, "Año no válido")
    allowed = assigned_sites(db, user)
    by_month = defaultdict(list)
    data = db.scalars(select(IneRow).where(IneRow.org_id == user.org_id,
                                           IneRow.period >= f"{year}-01", IneRow.period <= f"{year}-12")).all()
    for row in data:
        if user.role == "admin" or row.site_id in allowed:
            by_month[row.period].append(row)
    items = []
    for month in range(1, 13):
        period = f"{year}-{month:02d}"
        records = by_month[period]
        sums = {k: sum(getattr(r, k) or 0 for r in records) for k in FIELDS}
        items.append({
            "period": period, **sums, "rows": len(records),
            "complete": sum(all(getattr(r, k) is not None for k in FIELDS) for r in records),
            "pending": sum(any(getattr(r, k) is None for k in FIELDS) for r in records),
        })
    return {"year": year, "months": items}


@router.post("/import")
async def import_source(
    file: UploadFile = File(...), year: int = Form(2026),
    user: User = Depends(administrator), db: Session = Depends(get_db),
):
    """Importación sin correcciones: respaldo binario exacto y celdas originales intactas."""
    if not 1900 <= year <= 2199:
        raise HTTPException(422, "Año no válido")
    name = file.filename or "INE.xlsx"
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(415, "Solo archivos .xlsx")
    raw = await file.read(12 * 1024 * 1024 + 1)
    await file.close()
    if not raw or len(raw) > 12 * 1024 * 1024 or not raw.startswith(b"PK"):
        raise HTTPException(422, "Excel inválido o demasiado grande (máximo 12 MB)")
    digest = sha256(raw).hexdigest()
    old = db.scalar(select(IneOriginal).where(IneOriginal.org_id == user.org_id, IneOriginal.sha256 == digest))
    if old:
        raise HTTPException(409, "Este Excel original ya fue transcrito. No se modifica ni importa dos veces")
    try:
        workbook = load_workbook(BytesIO(raw), data_only=False, read_only=True, keep_links=False)
        cached = load_workbook(BytesIO(raw), data_only=True, read_only=True, keep_links=False)
    except Exception:
        raise HTTPException(422, "No fue posible leer el Excel original") from None
    source = IneOriginal(org_id=user.org_id, sha256=digest, filename=name[:240],
                         content=raw, uploaded_by=user.id)
    db.add(source)
    db.flush()
    all_sites = db.scalars(select(Worksite).where(Worksite.org_id == user.org_id)).all()
    names = defaultdict(list)
    for site in all_sites:
        names[normalized(site.name)].append(site)
    count = 0
    try:
        for position, worksheet in enumerate(workbook.worksheets):
            if worksheet.max_row > 3000 or worksheet.max_column > 120:
                raise HTTPException(422, "Una hoja excede el límite de seguridad")
            literal_rows = []
            for row in worksheet.iter_rows():
                values = {cell.column_letter: serialize(cell.value) for cell in row if cell.value is not None}
                if values:
                    literal_rows.append({"row": row[0].row, "cells": values})
            db.add(IneSheet(org_id=user.org_id, original_id=source.id,
                            position=position, sheet_name=worksheet.title, cells=literal_rows))
            if worksheet.title not in {str(i) for i in range(1, 13)}:
                continue
            period = f"{year}-{int(worksheet.title):02d}"
            cached_sheet = cached[worksheet.title]
            status = serialize(cached_sheet["I1"].value)
            supervisor = ""
            for line in range(3, cached_sheet.max_row + 1):
                name = cached_sheet.cell(line, 3).value
                label = cached_sheet.cell(line, 1).value
                if isinstance(label, str) and label.strip():
                    supervisor = label.strip()
                if not isinstance(name, str) or not name.strip():
                    continue
                values = {field: cached_sheet.cell(line, col).value for field, col in zip(FIELDS, range(4, 9))}
                exact = names.get(normalized(name), [])
                # Nunca se corrige ni se deduce una obra ambigua.
                site_id = exact[0].id if len(exact) == 1 else None
                if site_id and db.scalar(select(IneRow.id).where(
                    IneRow.org_id == user.org_id, IneRow.period == period, IneRow.site_id == site_id)):
                    site_id = None
                db.add(IneRow(
                    org_id=user.org_id, period=period, site_id=site_id,
                    site_name=name, supervisor=supervisor,
                    source_sheet=worksheet.title, source_row=line,
                    original_values={
                        "status": status,
                        "total": serialize(cached_sheet.cell(line, 9).value),
                        "percent": serialize(cached_sheet.cell(line, 11).value),
                        "cells": {key: serialize(val) for key, val in values.items()},
                    },
                    **{key: number_or_none(val) for key, val in values.items()},
                ))
                count += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        workbook.close()
        cached.close()
    return {"ok": True, "sha256": digest, "sheets": len(workbook.sheetnames),
            "transcribed_rows": count, "filename": source.filename}


@router.get("/original")
def original(user: User = Depends(administrator), db: Session = Depends(get_db)):
    source = db.scalar(select(IneOriginal).where(IneOriginal.org_id == user.org_id)
                       .order_by(IneOriginal.created_at.desc()))
    if not source:
        raise HTTPException(404, "No hay Excel original importado")
    return Response(content=source.content,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="INE-original-sin-modificaciones.xlsx"',
                             "Cache-Control": "no-store", "X-Content-SHA256": source.sha256})


@router.get("/archive")
def archive(user: User = Depends(administrator), db: Session = Depends(get_db)):
    source = db.scalar(select(IneOriginal).where(IneOriginal.org_id == user.org_id)
                       .order_by(IneOriginal.created_at.desc()))
    if not source:
        return {"sheets": []}
    records = db.scalars(select(IneSheet).where(IneSheet.original_id == source.id)
                         .order_by(IneSheet.position)).all()
    return {"original_id": source.id,
            "sheets": [{"id": r.id, "name": r.sheet_name, "rows": len(r.cells)} for r in records]}


@router.get("/archive/{sheet_id}")
def archive_sheet(sheet_id: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    sheet = db.scalar(select(IneSheet).where(IneSheet.id == sheet_id, IneSheet.org_id == user.org_id))
    if not sheet:
        raise HTTPException(404, "Hoja no encontrada")
    return {"name": sheet.sheet_name, "rows": sheet.cells}


@router.get("/export")
def export_current(year: int, user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Crea otro Excel de respaldo, sin abrir ni alterar el archivo fuente."""
    if not 1900 <= year <= 2199:
        raise HTTPException(422, "Año no válido")
    workbook = Workbook()
    workbook.remove(workbook.active)
    for month in range(1, 13):
        ws = workbook.create_sheet(str(month))
        ws.append(["Supervisor", "Obras", "CCT", "CESP", "IND", "TH", "TM",
                   "Total original Excel", "% original Excel", "Origen", "Fila original"])
        period = f"{year}-{month:02d}"
        data = db.scalars(select(IneRow).where(IneRow.org_id == user.org_id,
                                               IneRow.period == period)
                          .order_by(IneRow.source_row, IneRow.site_name)).all()
        for row in data:
            original = row.original_values or {}
            ws.append([
                row.supervisor, row.site_name, *[getattr(row, key) for key in FIELDS],
                original.get("total"), original.get("percent"), row.source_sheet, row.source_row,
            ])
        ws.freeze_panes = "C2"
        for col, width in {"A": 24, "B": 44, "C": 12, "D": 12, "E": 12,
                           "F": 12, "G": 12, "H": 22, "I": 20, "J": 14, "K": 18}.items():
            ws.column_dimensions[col].width = width
    data = BytesIO()
    workbook.save(data)
    return Response(content=data.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="GALANT-INE-respaldo-{year}.xlsx"',
                             "Cache-Control": "no-store"})
