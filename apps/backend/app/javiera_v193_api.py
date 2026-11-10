"""GALANT 19.3: consulta documental IRL/PTS desde matrices aprobadas.

Solo lectura. No crea trabajadores, no altera registros y nunca inventa
riesgos para labores escritas manualmente.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .javiera_logic import normalize_cargo
from .javiera_irl import parse_irl_section
from .javiera_matrices import latest_approved_matrix
from .javiera_models import JavieraMatrix
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v193", tags=["Javiera 19.3 · IRL y PTS"])

TYPES = ("IRL", "PTS", "PERFILES", "PUESTOS", "SUSTANCIAS")
@router.get("/roles")
def roles(query: str = Query("", max_length=160),
          user: User = Depends(administrator), db: Session = Depends(get_db)):
    rows = db.scalars(select(JavieraMatrix).where(
        JavieraMatrix.org_id == user.org_id,
        JavieraMatrix.kind.in_(TYPES),
    ).order_by(JavieraMatrix.created_at.desc()).limit(10001)).all()
    if len(rows) > 10000:
        raise HTTPException(409, "Catálogo demasiado extenso; solicita una revisión.")
    found: dict[str, dict] = {}
    for row in rows:
        role = normalize_cargo(row.cargo)
        if not role or (query and query.casefold() not in role.casefold()):
            continue
        result = found.setdefault(role, {
            "cargo": role, "has_approved_irl": False,
            "has_approved_pts": False, "has_draft": False,
        })
        if row.status == "approved" and row.kind == "IRL":
            result["has_approved_irl"] = True
        if row.status == "approved" and row.kind == "PTS":
            result["has_approved_pts"] = True
        if row.status != "approved":
            result["has_draft"] = True
    result = sorted(found.values(), key=lambda item: item["cargo"])
    return {"roles": result[:200], "total_matching": len(result), "partial": len(result) > 200}


@router.get("/role")
def role_detail(cargo: str = Query(..., min_length=1, max_length=160),
                user: User = Depends(administrator), db: Session = Depends(get_db)):
    canonical = normalize_cargo(cargo)
    if not canonical:
        raise HTTPException(422, "Indica un cargo o una labor real.")
    irl = latest_approved_matrix(db, user.org_id, "IRL", canonical)
    pts = latest_approved_matrix(db, user.org_id, "PTS", canonical)
    related = {
        kind: latest_approved_matrix(db, user.org_id, kind, canonical)
        for kind in ("PERFILES", "PUESTOS", "SUSTANCIAS")
    }
    entries = [parse_irl_section(value, version=irl.revision, ordinal=index, cargo=canonical)
               for index, value in enumerate(irl.sections, 1)] if irl else []
    problems = []
    if not irl:
        problems.append("Este cargo no tiene una matriz IRL aprobada. El dato manual se conserva como borrador.")
    elif not entries:
        problems.append("La matriz IRL aprobada no contiene tareas.")
    elif any(not entry["structured"] for entry in entries):
        problems.append("Existen registros IRL sin los cuatro campos técnicos completos.")
    if not pts:
        problems.append("El cargo no dispone de un PTS aprobado.")
    elif len(pts.sections) != 17 or any(not str(part).strip() for part in pts.sections):
        problems.append("El PTS requiere revisar sus 17 apartados.")
    return {
        "cargo": canonical,
        "irl": {
            "approved": bool(irl),
            "revision": irl.revision if irl else None,
            "matrix_id": irl.id if irl else None,
            "records": entries,
            "has_unstructured": any(not row["structured"] for row in entries),
        },
        "pts": {
            "approved": bool(pts), "revision": pts.revision if pts else None,
            "sections_complete": bool(pts and len(pts.sections) == 17 and
                                      all(str(part).strip() for part in pts.sections)),
            "section_count": len(pts.sections) if pts else 0,
            "sections": list(pts.sections) if pts else [],
            "source_columns": [chr(68 + i) for i in range(len(pts.sections))] if pts else [],
        },
        "additional_matrices": {
            kind: {"revision": item.revision if item else None,
                   "available": bool(item),
                   "sections": list(item.sections) if item else []}
            for kind, item in related.items()
        },
        "can_preview_irl": bool(irl and entries and all(row["structured"] for row in entries)),
        "warnings": problems,
        "manual_labor_policy": "save_as_draft_then_preventive_review",
        "historical_pdfs_unchanged": True,
    }
