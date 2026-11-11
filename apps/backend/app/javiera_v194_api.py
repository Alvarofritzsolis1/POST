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
from .javiera_irl_integrity import audit_reference_role
from .javiera_irl_corrective_drafts import corrective_draft_for_role, merged_draft_sections
from .javiera_irl_consolidation import consolidate_reference_risks, identical_variants
from .javiera_v193_api import roles as db_roles, role_detail as db_role_detail
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v194", tags=["Javiera 19.4 · 25 cargos IRL"])
DATA_FILE = Path(__file__).resolve().parent / "data" / "irl_25_cargos_excel_reference.json"
RELATED_FILE = Path(__file__).resolve().parent / "data" / "javiera_25_cargos_related_matrices.json"
RELATED_KINDS = ("PTS", "PERFILES", "PUESTOS", "SUSTANCIAS")
EXPECTED_COUNTS = {"PTS": 26, "PERFILES": 26, "PUESTOS": 27, "SUSTANCIAS": 27}
EXPECTED_SECTIONS = {"PTS": 17, "PERFILES": 1, "PUESTOS": 4, "SUSTANCIAS": 12}


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
        "source_excel_rows": list(row.get("source_excel_rows", [row["excel_row"]])),
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
        source_rows = [row for row in catalog()["rows"] if row["cargo"] == role]
        display_rows, _ = consolidate_reference_risks(source_rows, role)
        current["reference_count"] = len(display_rows)
        current["reference_source_count"] = len(source_rows)
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
    unique_rows, collapsed_groups = consolidate_reference_risks(rows, source_role)
    display_references = [_to_preview_record(row, ordinal)
                          for ordinal, row in enumerate(unique_rows, 1)]
    invalid = [row["excel_row"] for row in references if not row["structured"]]
    reference_audit = audit_reference_role(source_role, rows, related_catalog()["matrices"])
    correction = corrective_draft_for_role(source_role, rows)
    if correction["type"] == "risk_row":
        correction["editor_draft_sections"] = merged_draft_sections(rows, correction)
    data["reference_audit"] = reference_audit
    data["corrective_draft"] = correction
    data["warnings"].extend(reference_audit["warnings"])
    data.update({
        "source_excel_available": True,
        "source_excel_role": source_role,
        "source_excel_sha256": catalog()["source_sha256"],
        "reference_records": references,
        "reference_total": len(references),
        "reference_display_total": len(display_references),
        "reference_collapsed_groups": collapsed_groups,
        "reference_unstructured": len(invalid),
        "reference_incomplete_excel_rows": invalid,
        "reference_approved": False,
        "source_cannot_override_approved_matrix": True,
    })
    # Cada tipo está precargado desde su pestaña original. Solo mostrar
    # referencias cuando no exista una matriz autorizada; nunca reemplazarla.
    for kind in RELATED_KINDS:
        candidates = related_for_role(kind, cargo)
        if not candidates:
            continue
        variants = [{"row": item["source_row"], "cargo": item["cargo"]}
                    for item in candidates]
        equivalent = identical_variants(candidates)
        unresolved = len(candidates) > 1 and not equivalent
        if kind == "PTS":
            target = data["pts"]
        else:
            target = data["additional_matrices"][kind]
        target["source_variants"] = variants
        target["requires_disambiguation"] = unresolved
        target["identical_reference_variants"] = len(candidates) > 1 and equivalent
        # Las matrices aprobadas siempre tienen precedencia. El catálogo
        # histórico sirve para precompletar referencias, nunca habilitar PDF.
        if unresolved:
            data["warnings"].append(
                f"{kind}: existen {len(candidates)} variantes diferentes para {cargo}; "
                "requieren selección y revisión preventiva."
            )
            continue
        if kind == "PTS":
            if not target["approved"]:
                target["sections"] = list(candidates[0]["sections"])
                target["section_count"] = len(candidates[0]["sections"])
                target["reference_only"] = True
        elif not target["available"]:
            target.update({
                "available": True, "reference_only": True,
                "sections": list(candidates[0]["sections"]),
            })
    if not data["irl"]["approved"]:
        # El front puede estudiar la matriz original sin tener que importarla
        # a mano. Ningún documento imprimible usa este contenido hasta que
        # se cree/autorice una revisión por el circuito preventivo.
        data["irl"]["records"] = display_references
        data["irl"]["reference_only"] = True
        data["irl"]["has_unstructured"] = any(not row["structured"] for row in display_references)
        data["irl"]["source_rows_preserved"] = len(references)
        data["irl"]["display_rows"] = len(display_references)
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



@lru_cache(maxsize=1)
def related_catalog() -> dict:
    """Fuente técnica Excel: nunca altera la base de datos ni emite documentos."""
    payload = json.loads(RELATED_FILE.read_text(encoding="utf-8"))
    rows = payload.get("matrices", [])
    for kind, expected in EXPECTED_COUNTS.items():
        selected = [r for r in rows if r.get("kind") == kind]
        if len(selected) != expected:
            raise RuntimeError(f"Matriz de referencia {kind} incompleta: {len(selected)} != {expected}")
        if (len({(r["source_sheet"], r["source_row"]) for r in selected}) != expected or
                any(len(r.get("sections", [])) != EXPECTED_SECTIONS[kind] for r in selected)):
            raise RuntimeError(f"Columnas o filas de {kind} incompletas.")
    if any(row.get("kind") not in RELATED_KINDS for row in rows):
        raise RuntimeError("Tipo de matriz inesperado en el archivo fuente.")
    return payload


def related_for_role(kind: str, cargo: str) -> list[dict]:
    normalized = normalize_cargo(cargo)
    if kind not in RELATED_KINDS:
        return []
    return [dict(row) for row in related_catalog()["matrices"]
            if row["kind"] == kind and normalize_cargo(row["cargo"]) == normalized]


def reference_matrices_for_kind(kind: str) -> list[dict]:
    """Matriz completa para mostrar y editar como borrador, nunca aprobada."""
    if kind == "IRL":
        data = catalog()
        result = []
        for role in data["role_order"]:
            rows = [r for r in data["rows"] if r["cargo"] == role]
            sections = ["\n".join(f"{label}: {row[key]}" for key, label in (
                ("tarea", "Tarea"), ("peligro", "Peligro"), ("riesgo", "Riesgo"),
                ("medidas", "Medidas"))) for row in rows]
            result.append({
                "id": "excel-irl-" + str(rows[0]["excel_row"]),
                "kind": "IRL", "cargo": role, "sections": sections,
                "revision": 0, "status": "reference", "author_id": "",
                "source": "MATRIZ IRL · Excel corregido · filas " +
                          f"{rows[0]['excel_row']}–{rows[-1]['excel_row']}",
                "source_row": rows[0]["excel_row"],
                "source_approved": False, "source_revision": data["source_sha256"][:16],
            })
        return result
    return [{
        "id": "excel-" + kind.lower() + "-" + str(row["source_row"]),
        "kind": kind, "cargo": row["cargo"], "sections": list(row["sections"]),
        "revision": 0, "status": "reference", "author_id": "",
        "source": row["source_sheet"] + " · Excel corregido · fila " +
                  str(row["source_row"]),
        "source_row": row["source_row"], "source_approved": False,
        "source_revision": related_catalog()["source_sha256"][:16],
    } for row in related_catalog()["matrices"] if row["kind"] == kind]


@router.get("/reference-matrices")
def reference_matrices(kind: str = Query(..., max_length=20),
                       user: User = Depends(administrator)):
    """Disponibles desde la primera visita; NO requiere importar el Excel."""
    if kind not in (*RELATED_KINDS, "IRL"):
        raise HTTPException(422, "Categoría de matriz desconocida.")
    rows = reference_matrices_for_kind(kind)
    variants: dict[str, list[int]] = {}
    for row in rows:
        variants.setdefault(normalize_cargo(row["cargo"]), []).append(row["source_row"])
    return {
        "kind": kind, "rows": rows,
        "source_rows": len(rows),
        "source_status": "reference_only_pending_preventive_review",
        "columns": (
            ["Tarea", "Peligro", "Riesgo", "Medidas"]
            if kind == "IRL" else related_catalog()["columns"][kind]
        ),
        "variants": [
            {"cargo": cargo, "source_rows": source_rows}
            for cargo, source_rows in variants.items() if len(source_rows) > 1
        ],
        "historical_pdfs_unchanged": True,
        "editable_as_new_draft": True,
        "source_sha256": catalog()["source_sha256"] if kind == "IRL" else related_catalog()["source_sha256"],
    }
