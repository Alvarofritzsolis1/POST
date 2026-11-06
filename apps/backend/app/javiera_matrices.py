"""Selección compatible de matrices aprobadas, sin modificar sus revisiones históricas."""
from sqlalchemy import func, select

from .javiera_logic import CARGO_ALIASES, normalize_cargo
from .javiera_models import JavieraMatrix


def cargo_variants(cargo: str) -> set[str]:
    canonical = normalize_cargo(cargo)
    return {canonical, *(alias for alias, target in CARGO_ALIASES.items()
                         if target == canonical)}


def latest_approved_matrix(db, org_id: str, kind: str, cargo: str):
    # Antes de 16.5 cada variante tenía un contador separado. Por ello una
    # revisión canónica 1 puede ser posterior a la revisión histórica 5.
    return db.scalar(select(JavieraMatrix).where(
        JavieraMatrix.org_id == org_id,
        JavieraMatrix.kind == kind,
        JavieraMatrix.cargo.in_(cargo_variants(cargo)),
        JavieraMatrix.status == "approved",
    ).order_by(JavieraMatrix.created_at.desc(), JavieraMatrix.revision.desc(),
               JavieraMatrix.id.desc()))


def next_matrix_revision(db, org_id: str, kind: str, cargo: str) -> int:
    previous = db.scalar(select(func.max(JavieraMatrix.revision)).where(
        JavieraMatrix.org_id == org_id,
        JavieraMatrix.kind == kind,
        JavieraMatrix.cargo.in_(cargo_variants(cargo)),
    )) or 0
    return previous + 1
