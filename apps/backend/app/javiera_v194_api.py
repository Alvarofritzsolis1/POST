"""GALANT 19.4 — 25 cargos y 338 tareas del IRL fuente, sin carga manual.

El paquete de referencia se obtiene exclusivamente de MATRIZ IRL del libro
corregido; no incluye información personal de otros formularios del Excel.
La referencia NO equivale a una revisión preventiva aprobada ni se imprime
como documentación vigente sin aprobación en la base transaccional.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .db import get_db
from .javiera_logic import normalize_cargo
from .javiera_v193_api import roles as db_roles, role_detail as db_role_detail
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v194", tags=["Javiera 19.4 · 25 cargos IRL"])
DATA_FILE = Path(__file__).resolve().parent / "data" / "irl_25_cargos_excel_reference.json"


@lru_cache(maxsize=1)
def catalog() -> dict:
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    rows = payload.get("rows", [])
    roles = payload.get("role_order", [])
    if (len(roles) != 25 or len(rows) != 338 or len(set(roles)) != 25 or
            len({row["excel_row"] for row in rows}) != 338 or
            sorted({row["cargo"] for row in rows}) != sorted(roles)):
        raise RuntimeError("La referencia IRL no coincide con 25 cargos / 338 riesgos del Excel.")
    if any(row["cargo"] not in roles for row in rows):
        raise RuntimeError("Riesgo IRL con cargo no reconocido.")
    return payload


def lookup_role(role: str) -> tuple[str, list[dict]] | None:
    canonical = normalize_cargo(role)
    matches = [
        source for source in catalog()["role_order"]
        if normalize_cargo(source) == canonical
    ]
    if not matches:
        return None
    return matches[0], [dict(row) for row in catalog()["rows"] if row["cargo"] == matches[0]]


def _to_preview_record(row: dict, ordinal: int) -> dict:
    fields = ("tarea", "peligro", "riesgo", "medidas")
    return {
        "id": "excel-irl-" + str(row["excel_row"]),
        "ordinal": ordinal,
        "source_number": row["n"],
        "excel_row": row["excel_row"],
        "labor": row["tarea"],
        "peligro": row["peligro"],
        "riesgo": row["riesgo"],
        "medidas": row["medidas"],
        "structured": all(bool(str(row[key]).strip()) for key in fields),
        "original": "\n".join(
            f"{label}: {row[key]}"
            for key, label in (("tarea", "Tarea"), ("peligro", "Peligro"),
                               ("riesgo", "Riesgo"), ("medidas", "Medidas"))
        ),
    }


@router.get("/roles")
def reference_roles(query: str = Query("", max_length=160),
                    user: User = Depends(administrator),
                    db: Session = Depends(get_db)):
    existing = db_roles(query="", user=user, db=db)["roles"]
    found = {normalize_cargo(item["cargo"]): dict(item) for item in existing}
    for role in catalog()["role_order"]:
        key = normalize_cargo(role)
        current = found.setdefault(key, {
            "cargo": role,
            "has_approved_irl": False, "has_approved_pts": False,
            "has_draft": False,
        })
        current["source_excel_available"] = True
        current["reference_count"] = catalog()["risk_counts"][role]
        current["source_preventive_approval"] = "not_approved_automatically"
    values = sorted(
        (item for item in found.values()
         if not query or query.casefold() in item["cargo"].casefold()),
        key=lambda item: item["cargo"],
    )
    return {
        "roles": values[:200], "total_matching": len(values),
        "partial": len(values) > 200,
        "source_irl_roles": 25, "source_irl_records": 338,
        "source_status": "reference_only_until_preventive_review",
    }


@router.get("/role")
def reference_detail(cargo: str = Query(..., min_length=1, max_length=160),
                     user: User = Depends(administrator),
                     db: Session = Depends(get_db)):
    data = db_role_detail(cargo=cargo, user=user, db=db)
    source = lookup_role(cargo)
    if source is None:
        data.update(source_excel_available=False, reference_records=[],
                    reference_total=0, reference_unstructured=0)
        return data
    source_role, rows = source
    references = [_to_preview_record(row, ordinal) for ordinal, row in enumerate(rows, 1)]
    invalid = [row["excel_row"] for row in references if not row["structured"]]
    data.update({
        "source_excel_available": True,
        "source_excel_role": source_role,
        "source_excel_sha256": catalog()["source_sha256"],
        "reference_records": references,
        "reference_total": len(references),
        "reference_unstructured": len(invalid),
        "reference_incomplete_excel_rows": invalid,
        "reference_approved": False,
        "source_cannot_override_approved_matrix": True,
    })
    if not data["irl"]["approved"]:
        # El front puede estudiar la matriz original sin tener que importarla
        # a mano. Ningún documento imprimible usa este contenido hasta que
        # se cree/autorice una revisión por el circuito preventivo.
        data["irl"]["records"] = references
        data["irl"]["reference_only"] = True
        data["irl"]["has_unstructured"] = bool(invalid)
        data["warnings"].insert(0,
            "Matriz original de Excel disponible para consulta, sin aprobación preventiva."
            " Se requiere revisión autorizada antes de imprimir.")
    elif len(data["irl"]["records"]) != len(references):
        data["warnings"].append(
            "La revisión aprobada difiere del total del Excel de referencia: "
            f"{len(data['irl']['records'])} frente a {len(references)} registros. "
            "No se cambian documentos históricos ni matrices vigentes automáticamente."
        )
    return data


@router.get("/summary")
def reference_summary(user: User = Depends(administrator)):
    data = catalog()
    return {
        "source_book": data["source_book"],
        "source_sha256": data["source_sha256"],
        "roles": data["role_order"],
        "counts": data["risk_counts"],
        "total_cargos": len(data["role_order"]),
        "total_records": len(data["rows"]),
        "incomplete_rows": data["incomplete_excel_rows"],
        "approval_status": "pending_preventive_review",
    }
