"""Validación sin pérdida de matrices: previsualizar y confirmar contra misma fuente.

El archivo Excel no se guarda en GitHub ni se integra a las tablas operativas.
Las 423 fórmulas se INVENTARIAN (no se recalculan ni certifican equivalentes).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from collections import Counter
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import select

from .javiera_logic import normalize_cargo
from .javiera_models import JavieraMatrix

SHEETS = {
    "MATRIZ IRL": "IRL",
    "MATRIZ PTS": "PTS",
    "MATRIZ DESCRIPCION DE CARGO IRL": "PERFILES",
    "Matriz IRL Optimizada": "PUESTOS",
    "Base_Datos_Sustancias": "SUSTANCIAS",
}
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
MAX_SOURCE_ROWS = 2500
MAX_FORMULA_ROWS = 5000
MAX_FORMULA_COLUMNS = 100
MAX_MATRICES = 500
MAX_SECTION_BYTES = 220_000
MAX_IRL_SECTIONS = 1500
MAX_OTHER_SECTIONS = 500
REFS = re.compile(r"(?<![A-Za-z0-9_])\$?[A-Za-z]{1,3}\$?[0-9]{1,7}(?![A-Za-z0-9_])")
FUNCTION = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z_0-9.]*)\s*\(")


def _open(raw: bytes):
    if not raw.startswith(b"PK") or len(raw) > MAX_FILE_BYTES:
        raise HTTPException(415, "XLSX inválido o superior a 8 MB.")
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > 2500 or sum(item.file_size for item in members) > MAX_UNCOMPRESSED_BYTES:
                raise HTTPException(413, "El XLSX excede los límites de descompresión permitidos.")
            if any(item.flag_bits & 1 for item in members):
                raise HTTPException(422, "No se permiten libros Excel cifrados.")
        return load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
    except HTTPException:
        raise
    except (BadZipFile, OSError, ValueError, KeyError, TypeError):
        raise HTTPException(422, "No fue posible analizar el archivo Excel.") from None


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _snapshot(db, org_id: str) -> dict:
    # La base tiene una revisión por (tipo, cargo) y puede tener varias históricas.
    existing = db.scalars(select(JavieraMatrix).where(
        JavieraMatrix.org_id == org_id
    ).order_by(JavieraMatrix.revision.desc()).limit(10001)).all()
    if len(existing) > 10000:
        raise HTTPException(409, "El historial supera el límite verificable; se requiere revisión de base.")
    latest = {}
    for row in existing:
        key = (row.kind, normalize_cargo(row.cargo))
        latest.setdefault(key, row)
    return latest


def baseline_fingerprint(latest: dict) -> str:
    rows = sorted([kind, cargo, row.id, str(row.revision), row.status]
                  for (kind, cargo), row in latest.items())
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _classify(formula: str) -> str:
    upper = formula.upper()
    if any(x in upper for x in ("BUSCARV(", "VLOOKUP(", "XLOOKUP(", "INDICE(", "INDEX(", "MATCH(", "COINCIDIR(")):
        return "búsqueda"
    if any(x in upper for x in ("CONCAT(", "CONCATENATE(", "CONCATENAR(", "TEXTJOIN(", "&")):
        return "concatenación"
    if any(x in upper for x in ("SI(", "IF(", "SI.ERROR(", "IFERROR(", "Y(", "AND(")):
        return "validación"
    if any(x in upper for x in ("SUM(", "SUMA(", "ROUND(", "REDONDEAR(", "PRODUCT(")):
        return "cálculo"
    return "referencia/otra"


def inspect_matrix_workbook(raw: bytes, db, org_id: str) -> tuple[dict, dict]:
    book = _open(raw)
    staged: dict[tuple[str, str], list[str]] = {}
    omissions: list[str] = []
    duplicate_conflicts: list[str] = []
    counts = Counter()
    warnings: list[str] = []
    missing = [name for name in SHEETS if name not in book.sheetnames]

    def collect(kind: str, cargo, content: list[str], sheet: str, row_number: int):
        raw_cargo = _text(cargo)
        role = normalize_cargo(raw_cargo)
        if not role or len(role) > 160:
            omissions.append(f"{sheet}!{row_number}: cargo vacío o inválido.")
            return
        if kind == "PTS" and (len(content) != 17 or any(not x for x in content)):
            omissions.append(f"{sheet}!{row_number}: PTS de {role} sin sus 17 apartados.")
            return
        if not content or not any(content):
            omissions.append(f"{sheet}!{row_number}: sección técnica vacía para {role}.")
            return
        key = (kind, role)
        if key not in staged:
            staged[key] = list(content)
        elif kind == "PTS":
            if staged[key] != content:
                duplicate_conflicts.append(f"{sheet}!{row_number}: {role} posee varios PTS distintos.")
        else:
            staged[key].extend(content)

    try:
        if "MATRIZ IRL" in book.sheetnames:
            ws = book["MATRIZ IRL"]
            if ws.max_row > MAX_SOURCE_ROWS:
                omissions.append("MATRIZ IRL supera 2.500 filas verificables.")
            for row_number, row in enumerate(ws.iter_rows(
                    min_row=2, max_row=min(ws.max_row, MAX_SOURCE_ROWS),
                    max_col=6, values_only=True), start=2):
                if not any(value is not None for value in row[:6]):
                    continue
                if row[1] is None and any(value is not None for value in row[2:6]):
                    omissions.append(f"MATRIZ IRL!{row_number}: riesgo sin cargo.")
                    continue
                if row[1] is None:
                    continue
                counts["IRL"] += 1
                parts = [_text(value) for value in row[2:6]]
                if any(not part for part in parts):
                    omissions.append(f"MATRIZ IRL!{row_number}: faltan campos Tarea/Peligro/Riesgo/Medidas.")
                section = "\n".join(f"{label}: {value}" for label, value in
                                    zip(("Tarea", "Peligro", "Riesgo", "Medidas"), parts))
                collect("IRL", row[1], [section], "MATRIZ IRL", row_number)

        if "MATRIZ PTS" in book.sheetnames:
            ws = book["MATRIZ PTS"]
            if ws.max_row > MAX_SOURCE_ROWS:
                omissions.append("MATRIZ PTS supera 2.500 filas verificables.")
            for row_number, row in enumerate(ws.iter_rows(
                    min_row=2, max_row=min(ws.max_row, MAX_SOURCE_ROWS),
                    max_col=20, values_only=True), start=2):
                if not any(value is not None for value in row):
                    continue
                if row[0] is None:
                    omissions.append(f"MATRIZ PTS!{row_number}: fila sin cargo.")
                    continue
                counts["PTS"] += 1
                collect("PTS", row[0], [_text(v) for v in row[3:20]],
                        "MATRIZ PTS", row_number)

        for sheet, kind, cargo_col, start_col, max_col in (
                ("Matriz IRL Optimizada", "PUESTOS", 0, 1, 5),
                ("MATRIZ DESCRIPCION DE CARGO IRL", "PERFILES", 1, 2, 3),
                ("Base_Datos_Sustancias", "SUSTANCIAS", 0, 1, 12)):
            if sheet not in book.sheetnames:
                continue
            ws = book[sheet]
            if ws.max_row > MAX_SOURCE_ROWS:
                omissions.append(f"{sheet} supera 2.500 filas verificables.")
            for number, row in enumerate(ws.iter_rows(
                    min_row=2, max_row=min(ws.max_row, MAX_SOURCE_ROWS),
                    max_col=max_col, values_only=True), start=2):
                if not any(value is not None for value in row):
                    continue
                if row[cargo_col] is None:
                    omissions.append(f"{sheet}!{number}: fila técnica sin cargo.")
                    continue
                counts[kind] += 1
                collect(kind, row[cargo_col], [_text(v) for v in row[start_col:max_col]
                                                if v is not None and _text(v)], sheet, number)
    finally:
        book.close()

    if not staged:
        raise HTTPException(422, "El libro no contiene matrices compatibles.")
    if len(staged) > MAX_MATRICES:
        omissions.append("Se detectaron más de 500 matrices distintas; no se importarán parcialmente.")

    for (kind, cargo), sections in staged.items():
        max_sections = MAX_IRL_SECTIONS if kind == "IRL" else (
            17 if kind == "PTS" else MAX_OTHER_SECTIONS)
        if len(sections) > max_sections or len(json.dumps(sections, ensure_ascii=False).encode("utf-8")) > MAX_SECTION_BYTES:
            omissions.append(f"{kind}: {cargo} supera la capacidad verificable; no se omitirá ningún registro.")

    # Fórmulas: inventario seguro sin ejecución ni suposición de paridad funcional.
    try:
        formulas_book = load_workbook(io.BytesIO(raw), read_only=True,
                                      data_only=False, keep_links=False)
    except Exception:
        raise HTTPException(422, "No se pudieron inventariar las fórmulas.") from None
    formulas = []
    partial = False
    matrix_formula_cells = []
    formula_distribution = Counter()
    try:
        for ws in formulas_book:
            if ws.max_row > MAX_FORMULA_ROWS or ws.max_column > MAX_FORMULA_COLUMNS:
                partial = True
                omissions.append(f"{ws.title}: dimensiones superiores a los límites del inventario de fórmulas.")
            for row in ws.iter_rows(min_row=1,
                                    max_row=min(ws.max_row, MAX_FORMULA_ROWS),
                                    max_col=min(ws.max_column, MAX_FORMULA_COLUMNS)):
                for cell in row:
                    if cell.data_type != "f":
                        continue
                    expression = str(cell.value or "")
                    formula_distribution[ws.title] += 1
                    formulas.append({
                        "sheet": ws.title, "cell": cell.coordinate,
                        "type": _classify(expression),
                        "dependencies_a1_detected": sorted(set(REFS.findall(expression)))[:50],
                        "expression": expression,
                    })
                    if ws.title in SHEETS:
                        matrix_formula_cells.append(ws.title + "!" + cell.coordinate)
    finally:
        formulas_book.close()
    if matrix_formula_cells:
        omissions.append("Hay fórmulas en las matrices importadas: no se debe reutilizar un resultado almacenado sin validar.")

    if missing:
        warnings.append("Faltan hojas requeridas: " + ", ".join(missing))
    if counts["IRL"] != 338:
        warnings.append(f"Referencial IRL: 338 filas; en el Excel hay {counts['IRL']}.")
    if counts["PTS"] != 26:
        warnings.append(f"Referencial PTS: 26 filas; en el Excel hay {counts['PTS']}.")
    if len(formulas) != 423:
        warnings.append(f"Referencial de fórmulas: 423; se inventariaron {len(formulas)}.")
    if partial:
        warnings.append("El inventario de fórmulas está incompleto.")
    warnings.extend(duplicate_conflicts)
    omissions.extend(duplicate_conflicts)

    latest = _snapshot(db, org_id)
    updates = []
    for (kind, role), sections in staged.items():
        previous = latest.get((kind, role))
        diff = sum(1 for n in range(max(len(sections), len(previous.sections) if previous else 0))
                   if n >= len(sections) or previous is None or
                   n >= len(previous.sections) or previous.sections[n] != sections[n])
        updates.append({
            "kind": kind, "cargo": role,
            "change": "new" if not previous else
                     "unchanged" if previous.sections == sections else "changed",
            "different_sections": diff,
            "current_revision": previous.revision if previous else None,
        })
    # Mínimos del archivo histórico: si falta alguno, no podemos afirmar integridad.
    count_guard = counts["IRL"] >= 338 and counts["PTS"] >= 26 and len(formulas) >= 423
    if not count_guard:
        warnings.append("Las cantidades son inferiores al archivo histórico de referencia. Importación bloqueada.")
    warnings.extend(omissions[:25])
    report = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "baseline_sha256": baseline_fingerprint(latest),
        "sheets_found": [s for s in SHEETS if s not in missing],
        "sheets_missing": missing,
        "irl_source_rows": counts["IRL"], "pts_source_rows": counts["PTS"],
        "formula_count": len(formulas), "formula_count_partial": partial,
        "formulas_by_sheet": dict(formula_distribution),
        "formula_inventory": formulas[:2000],
        "formula_equivalence_verified": False,
        "matrices": updates, "new": sum(x["change"] == "new" for x in updates),
        "changed": sum(x["change"] == "changed" for x in updates),
        "unchanged": sum(x["change"] == "unchanged" for x in updates),
        "omissions": omissions[:150], "warnings": warnings,
        "can_import": count_guard and not partial and not missing and not omissions and
                      len(staged) <= MAX_MATRICES,
        "preview_only": True,
        "message": "Análisis previo: no se ha guardado ni aprobado ningún registro.",
    }
    return report, staged
