"""GALANT 19.2: impacto de matrices; lectura aislada y sin alterar documentos."""
from __future__ import annotations

import hashlib
import io
import json

from openpyxl import load_workbook

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .javiera_logic import normalize_cargo
from .javiera_matrices import latest_approved_matrix
from .javiera_models import JavieraDossier, JavieraMatrix
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v192", tags=["Javiera 19.2 · Matrices visuales"])

KINDS = frozenset({"IRL", "PTS", "PUESTOS", "PERFILES", "SUSTANCIAS"})
FORMATS = {
    "IRL": ["irl"], "PTS": ["pts", "pts_receipt"],
    "PUESTOS": ["irl"], "PERFILES": ["irl"],
    "SUSTANCIAS": ["irl"],
}

@router.get("/matrix-impact")
def matrix_impact(kind: str, cargo: str, user: User = Depends(administrator),
                  db: Session = Depends(get_db)):
    """Vista PREVIA para confirmar una revisión. Nunca actualiza emisiones."""
    if kind not in KINDS:
        raise HTTPException(422, "Tipo de matriz desconocido.")
    role = normalize_cargo(cargo)
    if len(role) < 2 or len(role) > 160:
        raise HTTPException(422, "Selecciona un cargo reconocido.")
    versions = db.scalars(select(JavieraMatrix).where(
        JavieraMatrix.org_id == user.org_id,
        JavieraMatrix.kind == kind,
        JavieraMatrix.cargo == role,
    ).order_by(JavieraMatrix.revision.desc()).limit(100)).all()
    approved = latest_approved_matrix(db, user.org_id, kind, role)
    dossier_rows = db.scalars(select(JavieraDossier).where(
        JavieraDossier.org_id == user.org_id
    ).limit(2001)).all()
    affected = sum(
        normalize_cargo(str((row.data or {}).get("role") or "")) == role
        for row in dossier_rows[:2000]
    )
    return {
        "kind": kind, "cargo": role,
        "new_pdf_formats": FORMATS[kind],
        "affected_dossiers": affected,
        "count_is_partial": len(dossier_rows) > 2000,
        "current_approved_revision": approved.revision if approved else None,
        "latest_revision": versions[0].revision if versions else None,
        "pending_revisions": [row.revision for row in versions if row.status == "draft"],
        "historical_pdfs_unchanged": True,
        "needs_explicit_review": True,
        "message": ("Crear un borrador no modifica PDF históricos ni publica nuevos riesgos. "
                    "La revisión exige habilitación expresa y controles preventivos."),
    }


@router.post("/workbook-preview")
async def preview_matrix_workbook(file: UploadFile = File(...),
                                  user: User = Depends(administrator),
                                  db: Session = Depends(get_db)):
    """Preflight XLSX SIN modificar datos; compara con el importador heredado."""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(415, "Selecciona un archivo .xlsx.")
    raw = await file.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, "Archivo mayor a 8 MB.")
    if not raw.startswith(b"PK"):
        raise HTTPException(415, "El archivo no es un XLSX válido.")
    try:
        book = load_workbook(io.BytesIO(raw), read_only=True,
                             data_only=True, keep_links=False)
    except Exception:
        raise HTTPException(422, "No se pudo abrir el Excel.") from None
    staged = {}
    omissions = []
    total_irl = 0
    total_pts = 0
    sheets = [
        "MATRIZ IRL", "MATRIZ PTS", "MATRIZ DESCRIPCION DE CARGO IRL",
        "Matriz IRL Optimizada", "Base_Datos_Sustancias",
    ]
    missing = [name for name in sheets if name not in book.sheetnames]

    def collect(kind: str, cargo, sections):
        role = normalize_cargo(str(cargo or ""))
        values = [str(value).strip() for value in sections
                  if value is not None and str(value).strip()]
        if not role or len(role) > 160:
            return
        if kind == "PTS" and len(values) != 17:
            omissions.append("PTS: " + role + " tiene menos de 17 secciones.")
            return
        if not values:
            return
        key = (kind, role)
        if key not in staged:
            staged[key] = values
        elif kind == "IRL":
            staged[key].extend(values)

    try:
        if "MATRIZ PTS" in book.sheetnames:
            ws = book["MATRIZ PTS"]
            for row in ws.iter_rows(min_row=2, max_row=min(ws.max_row, 200),
                                    max_col=20, values_only=True):
                if row[0]:
                    total_pts += 1
                    collect("PTS", row[0], row[3:20])
        if "MATRIZ IRL" in book.sheetnames:
            ws = book["MATRIZ IRL"]
            for row in ws.iter_rows(min_row=2, max_row=min(ws.max_row, 1500),
                                    max_col=6, values_only=True):
                if row[1]:
                    total_irl += 1
                    task, hazard, risk, prevention = row[2:6]
                    text = "Tarea: " + str(task or "") + "\nPeligro: " + str(hazard or "")
                    text += "\nRiesgo: " + str(risk or "") + "\nMedidas: " + str(prevention or "")
                    collect("IRL", row[1], [text])
        for sheet, kind, cargo_col, start_col, max_col in (
            ("Matriz IRL Optimizada", "PUESTOS", 0, 1, 5),
            ("MATRIZ DESCRIPCION DE CARGO IRL", "PERFILES", 1, 2, 3),
            ("Base_Datos_Sustancias", "SUSTANCIAS", 0, 1, 12),
        ):
            if sheet not in book.sheetnames:
                continue
            ws = book[sheet]
            for row in ws.iter_rows(min_row=2, max_row=min(ws.max_row, 500),
                                    max_col=max_col, values_only=True):
                if row[cargo_col]:
                    collect(kind, row[cargo_col], row[start_col:max_col])
    finally:
        book.close()
    for (kind,role),sections in staged.items():
        if len(sections) > 35 or len(json.dumps(sections,ensure_ascii=False)) > 50000:
            omissions.append(kind+": "+role+" excede el máximo importable.")
    if len(staged) > 250:
        omissions.append("El Excel contiene más de 250 matrices distintas.")
    if not staged:
        raise HTTPException(422, "No se reconocieron matrices del Excel.")
    existing = db.scalars(select(JavieraMatrix).where(
        JavieraMatrix.org_id == user.org_id
    ).order_by(JavieraMatrix.revision.desc()).limit(5000)).all()
    latest = {}
    for row in existing:
        latest.setdefault((row.kind,row.cargo),row)
    updates = []
    for (kind,role),sections in staged.items():
        previous = latest.get((kind,role))
        differences = sum(
            index >= len(previous.sections) or old != previous.sections[index]
            for index,old in enumerate(sections)
        ) if previous else len(sections)
        if previous:
            differences += max(0,len(previous.sections)-len(sections))
        updates.append({"kind":kind,"cargo":role,
                        "change":"new" if not previous else
                                 "unchanged" if previous.sections==sections else "changed",
                        "different_sections":differences,
                        "current_revision":previous.revision if previous else None})
    # Formula count is an inventory, NOT a dynamic formula-parity certificate.
    try:
        formulas_book=load_workbook(io.BytesIO(raw),read_only=True,
                                    data_only=False,keep_links=False)
    except Exception:
        raise HTTPException(422,"No se pudieron inventariar fórmulas.") from None
    formula_count=0
    incomplete_formula_count=False
    try:
        for ws in formulas_book:
            if ws.max_row>2000 or ws.max_column>50:
                incomplete_formula_count=True
            for row in ws.iter_rows(min_row=1,max_row=min(ws.max_row,2000),
                                    max_col=min(ws.max_column,50)):
                formula_count+=sum(cell.data_type=="f" for cell in row)
    finally:
        formulas_book.close()
    warnings=[]
    if missing:
        warnings.append("Faltan hojas requeridas: "+", ".join(missing))
    if total_irl!=338:
        warnings.append("Se esperaban 338 registros IRL según la referencia; se detectaron "+str(total_irl)+".")
    if total_pts!=26:
        warnings.append("Se esperaban 26 filas PTS según la referencia; se detectaron "+str(total_pts)+".")
    if formula_count!=423 or incomplete_formula_count:
        warnings.append("Fórmulas detectadas: "+str(formula_count)+
                        (" (inventario parcial)." if incomplete_formula_count else
                         "; no equivale a las 423 de la referencia."))
    warnings.extend(omissions[:20])
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sheets_found": [sheet for sheet in sheets if sheet in formulas_book.sheetnames],
        "sheets_missing": missing, "irl_source_rows":total_irl,
        "pts_source_rows":total_pts,"formula_count":formula_count,
        "formula_count_partial":incomplete_formula_count,
        "matrices":updates[:250],
        "new":sum(row["change"]=="new" for row in updates),
        "changed":sum(row["change"]=="changed" for row in updates),
        "unchanged":sum(row["change"]=="unchanged" for row in updates),
        "omissions":omissions[:80],"warnings":warnings,
        "can_import": not missing and not omissions and len(staged)<=250,
        "preview_only": True,
        "message": "Solo se revisó el Excel. Aún no se ha guardado ninguna revisión.",
    }
