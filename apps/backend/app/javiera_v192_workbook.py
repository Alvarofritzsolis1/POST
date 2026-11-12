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
from posixpath import basename, dirname, normpath, join
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import select

from .javiera_logic import normalize_cargo
from .javiera_pts_headers import PTS_TECHNICAL_HEADINGS, PTS_REFERENCE_SHA256
from .javiera_models import JavieraMatrix

SHEETS = {
    "MATRIZ IRL": "IRL",
    "MATRIZ PTS": "PTS",
    "MATRIZ DESCRIPCION DE CARGO IRL": "PERFILES",
    "Matriz IRL Optimizada": "PUESTOS",
    "Base_Datos_Sustancias": "SUSTANCIAS",
}
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_SOURCE_ROWS = 2500
MAX_FORMULA_ROWS = 5000
MAX_FORMULA_COLUMNS = 100
MAX_MATRICES = 500
MAX_SECTION_BYTES = 220_000
MAX_IRL_SECTIONS = 1500
MAX_OTHER_SECTIONS = 500
XML_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XML_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
XML_P = "{http://schemas.openxmlformats.org/package/2006/relationships}"
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


def _real_content_after_limit(raw: bytes, sheet_name: str, limit: int) -> bool:
    """Comprueba XML de filas reales, no la dimensión declarada por Excel.

    Una plantilla puede declarar A1:AN1048576 con un millón de celdas
    meramente formateadas; eso NO significa que tenga un millón de datos.
    """
    try:
        with ZipFile(io.BytesIO(raw)) as zf:
            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
            relationships = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            targets = {}
            for rel in relationships.findall(XML_P + "Relationship"):
                value = rel.get("Target", "")
                targets[rel.get("Id", "")] = (
                    value.lstrip("/") if value.startswith("/") else
                    normpath(join("xl", value)))
            target = None
            for element in workbook.findall("./" + XML_M + "sheets/" + XML_M + "sheet"):
                if element.get("name") == sheet_name:
                    target = targets.get(element.get(XML_R + "id", ""))
                    break
            if not target:
                raise ValueError("Hoja sin ruta OOXML")
            with zf.open(target) as stream:
                rows = ET.iterparse(stream, events=("start", "end"))
                _, root = next(rows)
                for event, element in rows:
                    if event == "end" and element.tag == XML_M + "row":
                        row_number = int(element.get("r") or "0")
                        if row_number > limit:
                            for cell in element.findall(XML_M + "c"):
                                for child in cell:
                                    if child.tag == XML_M + "f":
                                        return True
                                    if child.tag in {XML_M + "v", XML_M + "is"}:
                                        if "".join(child.itertext()).strip():
                                            return True
                        element.clear()
                        root.clear()
        return False
    except (KeyError, ValueError, ET.ParseError, OSError, BadZipFile):
        # Si no podemos demostrar que el resto está vacío, fallar cerrado.
        return True



def _sheet_image_count(raw: bytes, sheet_name: str) -> int | None:
    """Cuenta imágenes OOXML de una hoja; no presume haberlas convertido a HTML.

    No basta contar xl/media, ya que el libro puede tener imágenes ajenas al IRL.
    Se sigue el enlace hoja -> drawing -> xdr:pic. None = no verificable.
    """
    try:
        with ZipFile(io.BytesIO(raw)) as zf:
            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
            root_rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            targets = {item.get("Id"): item.get("Target", "")
                       for item in root_rels.findall(XML_P + "Relationship")}
            sheet_path = None
            for sheet in workbook.findall("./" + XML_M + "sheets/" + XML_M + "sheet"):
                if sheet.get("name") == sheet_name:
                    target = targets.get(sheet.get(XML_R + "id"))
                    if not target:
                        return None
                    sheet_path = (target.lstrip("/") if target.startswith("/")
                                  else normpath(join("xl", target)))
                    break
            if sheet_path is None:
                return None
            sheet_xml = ET.fromstring(zf.read(sheet_path))
            drawings = sheet_xml.findall(XML_M + "drawing")
            if not drawings:
                return 0
            sheet_rels_path = join(dirname(sheet_path), "_rels",
                                   basename(sheet_path) + ".rels")
            relations = ET.fromstring(zf.read(sheet_rels_path))
            drawing_targets = {item.get("Id"): item.get("Target", "")
                               for item in relations.findall(XML_P + "Relationship")}
            image_count = 0
            xdr_picture = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}pic"
            for drawing in drawings:
                target = drawing_targets.get(drawing.get(XML_R + "id"))
                if not target:
                    return None
                path = target.lstrip("/") if target.startswith("/") else normpath(
                    join(dirname(sheet_path), target))
                drawing_xml = ET.fromstring(zf.read(path))
                image_count += sum(1 for element in drawing_xml.iter()
                                   if element.tag == xdr_picture)
            return image_count
    except (OSError, KeyError, ValueError, ET.ParseError, BadZipFile):
        return None


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
    incomplete_pts: list[str] = []
    incomplete_irl: list[str] = []
    oversized_dimensions: list[str] = []
    missing = [name for name in SHEETS if name not in book.sheetnames]

    def collect(kind: str, cargo, content: list[str], sheet: str, row_number: int):
        raw_cargo = _text(cargo)
        role = normalize_cargo(raw_cargo)
        if not role or len(role) > 160:
            omissions.append(f"{sheet}!{row_number}: cargo vacío o inválido.")
            return
        if kind == "PTS" and len(content) != 17:
            omissions.append(f"{sheet}!{row_number}: se requieren 17 posiciones PTS.")
            return
        if kind == "PTS" and any(not item for item in content):
            incomplete_pts.append(f"{sheet}!{row_number}: {role} tiene secciones sin completar.")
        if not content or not any(content):
            # Conservar una fila histórica incompleta como borrador,
            # no publicarla ni descartarla durante el ingreso.
            incomplete_irl.append(f"{sheet}!{row_number}: {role} sin contenido técnico.")
            content = ["" if kind != "PTS" else item for item in content] or [""]
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
                oversized_dimensions.append("MATRIZ IRL")
                if _real_content_after_limit(raw, "MATRIZ IRL", MAX_SOURCE_ROWS):
                    omissions.append("MATRIZ IRL contiene datos después de 2.500 filas y requiere migración ampliada.")
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
                    incomplete_irl.append(f"MATRIZ IRL!{row_number}: faltan campos Tarea/Peligro/Riesgo/Medidas.")
                section = "\n".join(f"{label}: {value}" for label, value in
                                    zip(("Tarea", "Peligro", "Riesgo", "Medidas"), parts))
                collect("IRL", row[1], [section], "MATRIZ IRL", row_number)

        if "MATRIZ PTS" in book.sheetnames:
            ws = book["MATRIZ PTS"]
            header = next(ws.iter_rows(min_row=1, max_row=1, max_col=20, values_only=True))
            def canonical(text):
                return " ".join(str(text or "").upper().split())
            # La estructura técnica D:T debe corresponder al archivo real.
            # Sin estos encabezados no podemos mostrar las secciones correctamente.
            wrong = [chr(68 + i) for i, expected in enumerate(PTS_TECHNICAL_HEADINGS)
                     if canonical(header[i + 3]) != canonical(expected)]
            if wrong:
                omissions.append("MATRIZ PTS: encabezados D:T incompatibles en "
                                 + ", ".join(wrong) + ". No se importan bajo etiquetas erróneas.")
            if ws.max_row > MAX_SOURCE_ROWS:
                oversized_dimensions.append("MATRIZ PTS")
                if _real_content_after_limit(raw, "MATRIZ PTS", MAX_SOURCE_ROWS):
                    omissions.append("MATRIZ PTS contiene datos después de 2.500 filas.")
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
                ("Base_Datos_Sustancias", "SUSTANCIAS", 0, 1, 13)):
            if sheet not in book.sheetnames:
                continue
            ws = book[sheet]
            if ws.max_row > MAX_SOURCE_ROWS:
                oversized_dimensions.append(sheet)
                if _real_content_after_limit(raw, sheet, MAX_SOURCE_ROWS):
                    omissions.append(f"{sheet} contiene datos después de 2.500 filas.")
            for number, row in enumerate(ws.iter_rows(
                    min_row=2, max_row=min(ws.max_row, MAX_SOURCE_ROWS),
                    max_col=max_col, values_only=True), start=2):
                if not any(value is not None for value in row):
                    continue
                if row[cargo_col] is None:
                    omissions.append(f"{sheet}!{number}: fila técnica sin cargo.")
                    continue
                counts[kind] += 1
                collect(kind, row[cargo_col], [_text(v) for v in row[start_col:max_col]],
                        sheet, number)
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
            if ws.max_column > MAX_FORMULA_COLUMNS or (
                ws.max_row > MAX_FORMULA_ROWS and
                _real_content_after_limit(raw, ws.title, MAX_FORMULA_ROWS)
            ):
                partial = True
                omissions.append(f"{ws.title}: fórmulas potencialmente fuera del rango inventariado.")
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
        warnings.append("Hay fórmulas dentro de hojas técnicas: el contenido almacenado es provisional y requiere revisión antes de aprobar.")

    if missing:
        warnings.append("Faltan hojas requeridas: " + ", ".join(missing))
    if oversized_dimensions:
        warnings.append("Dimensiones Excel sobredimensionadas (se inspeccionaron filas reales): " +
                        ", ".join(oversized_dimensions))
    if incomplete_pts:
        warnings.append(f"{len(incomplete_pts)} registros PTS están incompletos; se conservarán como borradores, no aprobados.")
    if incomplete_irl:
        warnings.append(f"{len(incomplete_irl)} registros IRL / auxiliares tienen campos vacíos; revisión preventiva requerida.")
    if counts["IRL"] != 338:
        warnings.append(f"Referencial IRL: 338 filas; en el Excel hay {counts['IRL']}.")
    if counts["PTS"] != 26:
        warnings.append(f"Referencial PTS: 26 filas; en el Excel hay {counts['PTS']}.")
    irl_images = _sheet_image_count(raw, "IRL") if "IRL" in book.sheetnames else None
    if irl_images is None:
        warnings.append("No se pudo confirmar el contenido gráfico de la hoja IRL.")
    elif irl_images:
        warnings.append(
            f"La hoja IRL contiene {irl_images} imágenes incrustadas. "
            "Importar matrices no reconstruye ni valida su texto o casillas en HTML/PDF."
        )
    source_sha = hashlib.sha256(raw).hexdigest()
    if source_sha == PTS_REFERENCE_SHA256:
        if len(formulas) != 324:
            warnings.append("El Excel corregido reconocido no conserva las 324 fórmulas inventariadas.")
        else:
            warnings.append("Fuente corregida reconocida: 324 fórmulas inventariadas, "
                            "sin equivalencia funcional certificada.")
    elif len(formulas) not in (261, 324, 423):
        warnings.append(f"El libro contiene {len(formulas)} fórmulas. Las referencias históricas "
                        "261 / 324 / 423 corresponden a versiones distintas; validar el archivo fuente.")
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
    # Fórmulas: las auditorías históricas no coinciden (261 / 423). No
    # usar este total para ocultar matrices ni fingir paridad funcional.
    count_guard = counts["IRL"] >= 338 and counts["PTS"] >= 26
    if not count_guard:
        warnings.append("Faltan filas respecto a las 338 IRL y 26 PTS de referencia; importación bloqueada.")
    if len(formulas) != 423:
        warnings.append("El recuento de fórmulas no acredita equivalencia: validar contra la versión real del Excel.")
    warnings.extend(omissions[:25])
    report = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "baseline_sha256": baseline_fingerprint(latest),
        "sheets_found": [s for s in SHEETS if s not in missing],
        "sheets_missing": missing,
        "irl_source_rows": counts["IRL"], "pts_source_rows": counts["PTS"],
        "irl_embedded_images": irl_images,
        "irl_formula_count": formula_distribution["IRL"],
        "formula_count": len(formulas), "formula_count_partial": partial,
        "formulas_by_sheet": dict(formula_distribution),
        "formula_inventory": formulas[:2000],
        "formula_equivalence_verified": False,
        "incomplete_pts": incomplete_pts[:150],
        "incomplete_irl": incomplete_irl[:150],
        "draft_only_for_incomplete": True,
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
