"""GALANT 19.2: impacto de matrices; lectura aislada y sin alterar documentos."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db
from .javiera_logic import normalize_cargo
from .javiera_matrices import latest_approved_matrix, next_matrix_revision
from .javiera_models import JavieraDossier, JavieraMatrix
from .javiera_v166_models import JavieraLocalDossier
from .javiera_v192_workbook import inspect_matrix_workbook, MAX_FILE_BYTES
from .models import AuditEvent, User
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
    legacy = db.scalars(select(JavieraDossier).where(
        JavieraDossier.org_id == user.org_id
    ).limit(2001)).all()
    current = db.scalars(select(JavieraLocalDossier).where(
        JavieraLocalDossier.org_id == user.org_id
    ).limit(2001)).all()
    affected_legacy = sum(
        normalize_cargo(str((row.data or {}).get("role") or "")) == role
        for row in legacy[:2000]
    )
    affected_current = sum(
        normalize_cargo(str((row.shared or {}).get("role") or "")) == role
        for row in current[:2000]
    )
    irl = latest_approved_matrix(db, user.org_id, "IRL", role)
    pts = latest_approved_matrix(db, user.org_id, "PTS", role)
    related = (["pts", "pts_receipt"] if kind != "PTS" else ["irl"])
    return {
        "kind": kind, "cargo": role,
        "new_pdf_formats": FORMATS[kind],
        "affected_dossiers": affected_legacy + affected_current,
        "affected_by_origin": {
            "historical_workflow": affected_legacy,
            "current_documentary_workflow": affected_current,
        },
        "count_is_partial": len(legacy) > 2000 or len(current) > 2000,
        "related_formats_for_review": related,
        "related_matrix_versions": {
            "irl": irl.revision if irl else None,
            "pts": pts.revision if pts else None,
        },
        "related_formats_are_advisory": True,
        "current_approved_revision": approved.revision if approved else None,
        "latest_revision": versions[0].revision if versions else None,
        "pending_revisions": [row.revision for row in versions if row.status == "draft"],
        "historical_pdfs_unchanged": True,
        "needs_explicit_review": True,
        "message": ("Crear un borrador no modifica PDF históricos ni publica nuevos riesgos. "
                    "La revisión exige habilitación expresa y controles preventivos."),
    }


async def _read_uploaded_xlsx(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(415, "Selecciona un archivo Excel .xlsx.")
    raw = await file.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(413, "Archivo Excel mayor a 8 MB.")
    return raw


@router.post("/workbook-preview")
async def preview_matrix_workbook(file: UploadFile = File(...),
                                  user: User = Depends(administrator),
                                  db: Session = Depends(get_db)):
    """No muta registros. Reporta TODAS las omisiones verificadas."""
    raw = await _read_uploaded_xlsx(file)
    report, _ = inspect_matrix_workbook(raw, db, user.org_id)
    return report


@router.post("/workbook-commit")
async def commit_matrix_workbook(
    file: UploadFile = File(...),
    sha256: str = Form(...),
    baseline_sha256: str = Form(...),
    confirmed: bool = Form(False),
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    """Importación atómica: sin omisiones ni sobreescritura histórica."""
    if not confirmed:
        raise HTTPException(422, "Confirma las diferencias y el impacto antes de importar.")
    raw = await _read_uploaded_xlsx(file)
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != actual_sha256:
        raise HTTPException(409, "El Excel cambió desde la vista previa; vuelve a revisarlo.")
    report, staged = inspect_matrix_workbook(raw, db, user.org_id)
    if baseline_sha256 != report["baseline_sha256"]:
        raise HTTPException(409, "Las matrices se modificaron después de la vista previa; repite la comparación.")
    if not report["can_import"]:
        raise HTTPException(422, {
            "error": "Importación bloqueada. No se guardó ninguna matriz.",
            "warnings": report["warnings"][:20],
            "omissions": report["omissions"][:20],
        })
    changed_keys = {(entry["kind"], entry["cargo"]) for entry in report["matrices"]
                    if entry["change"] != "unchanged"}
    # Versiones nuevas en borrador; nunca UPDATE/DELETE de las aprobadas o expedientes.
    counts: dict[str, int] = {}
    try:
        for (kind, cargo), sections in staged.items():
            if (kind, cargo) not in changed_keys:
                continue
            revision = next_matrix_revision(db, user.org_id, kind, cargo)
            db.add(JavieraMatrix(
                org_id=user.org_id, kind=kind, cargo=cargo,
                revision=revision, sections=list(sections), status="draft",
                source="GALANT 19.2 XLSX · " + actual_sha256[:20], author_id=user.id,
            ))
            counts[kind] = counts.get(kind, 0) + 1
        db.add(AuditEvent(
            org_id=user.org_id, user_id=user.id,
            action="javiera.v192_workbook_import", resource_id=actual_sha256[:36]
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Otra revisión se guardó simultáneamente. Compara de nuevo el Excel.") from None
    except Exception:
        db.rollback()
        raise
    return {
        "sha256": actual_sha256, "drafts": counts,
        "created": sum(counts.values()), "unchanged": report["unchanged"],
        "omissions": [],
        "historical_pdfs_unchanged": True, "status": "draft_only",
        "message": "Importación completada sin omisiones. Las matrices requieren revisión.",
    }
