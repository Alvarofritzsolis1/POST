"""Consolidación de vista del IRL, sin alterar el Excel ni aprobar matrices.

Solo se colapsan registros técnicos idénticos. La variación histórica
GASFITER/GASFITERIA se acepta únicamente en el nombre de la *tarea*;
no altera peligros, consecuencias ni medidas. Se conserva cada fila fuente.
"""
from __future__ import annotations

import re
import unicodedata

from .javiera_logic import normalize_cargo

RISK_FIELDS = ("tarea", "peligro", "riesgo", "medidas")


def _cell(value: object) -> str:
    """Normalización no semántica: caracteres Unicode y espacios."""
    return re.sub(r"\\s+", " ", unicodedata.normalize("NFKC", str(value or "")).strip())


def identical_variants(rows: list[dict]) -> bool:
    """Verdadero solamente cuando todas las columnas técnicas coinciden."""
    if not rows:
        return False
    first = tuple(_cell(part) for part in rows[0].get("sections", []))
    return all(tuple(_cell(part) for part in r.get("sections", [])) == first
               for r in rows[1:])


def _task_key(task: object, role: str) -> str:
    normalized = _cell(task).upper()
    # No generalizar alias de cargos a peligros o controles.
    if normalize_cargo(role) == "GASFITER":
        normalized = re.sub(r"\\bGASFITERIA\\b", "GASFITER", normalized)
    return normalized


def consolidate_reference_risks(rows: list[dict], cargo: str) -> tuple[list[dict], list[dict]]:
    """Devuelve (filas de vista, grupos colapsados con procedencia).

    Las filas originales no se mutan. El orden de la primera aparición se
    conserva y los campos técnicos permanecen unidos por excel_row.
    """
    viewed: list[dict] = []
    seen: dict[tuple[str, ...], dict] = {}
    for row in sorted(rows, key=lambda item: int(item["excel_row"])):
        if normalize_cargo(row.get("cargo")) != normalize_cargo(cargo):
            continue
        signature = (_task_key(row.get("tarea"), cargo),) + tuple(
            _cell(row.get(field)) for field in RISK_FIELDS[1:]
        )
        original = dict(row)
        original["source_excel_rows"] = [int(row["excel_row"])]
        if signature in seen:
            seen[signature]["source_excel_rows"].append(int(row["excel_row"]))
        else:
            seen[signature] = original
            viewed.append(original)
    merged = [
        {"display_excel_row": item["excel_row"],
         "source_excel_rows": list(item["source_excel_rows"]),
         "count": len(item["source_excel_rows"])}
        for item in viewed if len(item["source_excel_rows"]) > 1
    ]
    return viewed, merged
