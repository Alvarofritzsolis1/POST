"""GALANT 19.2: impacto de matrices; lectura aislada y sin alterar documentos."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
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
