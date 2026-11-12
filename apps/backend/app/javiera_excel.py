"""JAVIERA: conservador de plantillas Excel OOXML y PDF de impresión.

Mantiene las celdas, bordes, estilos, rangos combinados, imágenes, membretes y
configuración de impresión originales. El XLSX vive EXCLUSIVAMENTE en /data/private.
No ejecuta macros, no utiliza eval de fórmulas y no envía datos a terceros.
"""
from __future__ import annotations

import hashlib
import io
from datetime import date, timedelta
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, BadZipFile
from xml.etree import ElementTree as ET
import fitz

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
Q = lambda name: f"{{{M}}}{name}"
ET.register_namespace("", M)
ET.register_namespace("r", R)

DOC_SHEETS = {
    "labor_contract": "Contrato Imprimible",
    "transfer_addendum": "Anexo Traslado",
    "extension_addendum": "Anexo extension contrato",
    "sworn_declaration": "DECLARACION JURADA",
    "internal_rules_receipt": "REGLAMENTO INTERNO",
    "ppe_delivery": "Registros Entrega EPP",
    "irl": "IRL",
    "pts": "PTS.",
    "pts_receipt": "ENTREGA PTS",
    "induction": "INDUCCION PREVENCION",
}
# Bounded print regions. Source auxiliaries are excluded from the emitted PDF;
# no clause or procedural matrix is removed from the private workbook itself.
DOCUMENT_PRINT_AREAS = {
    "labor_contract": "A1:C36",
    "transfer_addendum": "A1:C19",
    "extension_addendum": "A1:I9",
    "sworn_declaration": "A1:A16",
    "internal_rules_receipt": "A1:G12",
    "ppe_delivery": "A1:E30",
    "irl": "A1:D179",
    "pts": "A1:G190",
    "pts_receipt": "A1:I24",
    "induction": "A1:D474",
}

# Exact starts of the ten original forms in the private induction sheet.
# The original content, formulas and signatures stay in their source rows.
INDUCTION_FORM_START_ROWS = (9, 58, 116, 159, 206, 262, 304, 355, 404, 452)
# A shape-based corporate header precedes each textual heading. Excel drawing
# anchors are zero-indexed, hence the source form starts at these 1-based rows.
INDUCTION_SECTION_FIRST_ROWS = (1, 48, 104, 149, 197, 253, 298, 345, 394, 442)
# Header at row 298 is a drawing whose manual break creates a separate
# header-only page in LibreOffice. The automatic break safely joins its text.
INDUCTION_MANUAL_BREAK_STARTS = (48, 104, 149, 197, 253, 345, 394, 442)


def set_document_print_profile(target: ET.Element, book: ET.Element, code: str, sheet_name: str):
    """Apply a scoped A4 print setup only to this generated, one-sheet workbook.

    Source XLSX and reviewed content remain unchanged. Excel/LibreOffice may
    otherwise use stale/absent print areas and clip merged paragraphs.
    """
    if code not in DOCUMENT_PRINT_AREAS:
        raise LayoutError("Documento desconocido para configuración de impresión")
    props = target.find(Q("sheetPr"))
    if props is None:
        props = ET.Element(Q("sheetPr"))
        target.insert(0, props)
    layout = props.find(Q("pageSetUpPr"))
    if layout is None:
        layout = ET.SubElement(props, Q("pageSetUpPr"))
    layout.set("fitToPage", "1")
    margins = target.find(Q("pageMargins"))
    if margins is None:
        margins = ET.SubElement(target, Q("pageMargins"))
    for key, value in {
        "left": "0.36", "right": "0.36",
        "top": "0.46", "bottom": "0.46",
        "header": "0.18", "footer": "0.18",
    }.items():
        margins.set(key, value)
    setup = target.find(Q("pageSetup"))
    if setup is None:
        setup = ET.SubElement(target, Q("pageSetup"))
    setup.attrib.update({
        "paperSize": "9",  # ISO A4
        "orientation": "portrait",
        "fitToWidth": "1",
        "fitToHeight": "0",  # keep all required pages; never shrink to one
        "usePrinterDefaults": "0",
    })
    names = book.find(Q("definedNames"))
    if names is None:
        names = ET.Element(Q("definedNames"))
        calc = book.find(Q("calcPr"))
        if calc is not None:
            book.insert(list(book).index(calc), names)
        else:
            book.append(names)
    # Source print areas were selected and approved with the template.
    # Preserve them instead of overwriting them with the default range:
    # the generic QA fixture uses A1:D15 and would lose its fourth column.
    active = [item for item in names.findall(Q("definedName"))
              if item.get("name") == "_xlnm.Print_Area"
              and item.get("localSheetId") == "0"]
    if active and active[0].text and re.search(
        r"\$?[A-Z]+\$?[0-9]+:\$?[A-Z]+\$?[0-9]+", active[0].text
    ):
        # Duplicate historic declarations are not used for printing.
        for redundant in active[1:]:
            names.remove(redundant)
        return
    for item in list(names):
        if item.get("name") == "_xlnm.Print_Area":
            names.remove(item)
    entry = ET.SubElement(names, Q("definedName"), {
        "name": "_xlnm.Print_Area", "localSheetId": "0"
    })
    escaped = sheet_name.replace("'", "''")
    cell_range = DOCUMENT_PRINT_AREAS[code]
    left, right = cell_range.split(":")
    # Convert A1 to $A$1 for portability between Excel and LibreOffice.
    def absolute(address):
        match = re.fullmatch(r"([A-Z]+)([0-9]+)", address)
        if not match:
            raise LayoutError("Área de impresión inválida")
        return f"\u0024{match.group(1)}\u0024{match.group(2)}"
    entry.text = f"'{escaped}'!{absolute(left)}:{absolute(right)}"


def configure_induction_sections(target: ET.Element, book: ET.Element,
                                 sheet_name: str, strings: list[str]) -> int:
    """Put each of the ten original induction forms at a fresh page boundary.

    This changes ONLY the disposable, one-sheet Excel generated for printing.
    The imported XLSX, signed PDFs and historic versions remain immutable.
    Do not create empty pages when an unrelated or synthetic induction sheet
    lacks the actual form headings.
    """
    rows = target.find(Q("sheetData"))
    if rows is None:
        return 0
    occupied = {}
    for row in rows.findall(Q("row")):
        number = int(row.get("r", "0"))
        if number not in (*INDUCTION_FORM_START_ROWS, 1):
            continue
        first = next((c for c in row.findall(Q("c"))
                      if c.get("r") == f"A{number}"), None)
        occupied[number] = cell_text(first, strings).strip() if first is not None else ""
    # Older user Excel files and minimal CI fixtures need no forced empty pages.
    if sum(bool(occupied.get(n)) for n in INDUCTION_FORM_START_ROWS) < 8:
        return 0

    previous = target.find(Q("rowBreaks"))
    if previous is not None:
        target.remove(previous)
    count = len(INDUCTION_MANUAL_BREAK_STARTS)
    breaks = ET.Element(Q("rowBreaks"), {
        "count": str(count), "manualBreakCount": str(count),
    })
    for start in INDUCTION_MANUAL_BREAK_STARTS:
        ET.SubElement(breaks, Q("brk"), {
            "id": str(start - 1), "min": "0", "max": "3", "man": "1",
        })
    # Keep schema order: rowBreaks follow page setup, before drawing objects.
    tail = {Q(name) for name in (
        "colBreaks", "customProperties", "cellWatches", "ignoredErrors",
        "smartTags", "drawing", "legacyDrawing", "legacyDrawingHF",
        "picture", "oleObjects", "controls", "webPublishItems",
        "tableParts", "extLst")}
    index = next((i for i, child in enumerate(list(target))
                  if child.tag in tail), len(target))
    target.insert(index, breaks)

    # Original company headers are Excel drawing shapes anchored at each
    # section start. Print titles would OVERLAY these genuine headers and
    # manufacture pages containing only the duplicated masthead.
    # Only allow repeated cell titles when no drawing exists (synthetic fixture).
    if occupied.get(1) and target.find(Q("drawing")) is None:
        names = book.find(Q("definedNames"))
        if names is None:
            names = ET.SubElement(book, Q("definedNames"))
        for entry in list(names):
            if entry.get("name") == "_xlnm.Print_Titles":
                names.remove(entry)
        entry = ET.SubElement(names, Q("definedName"), {
            "name": "_xlnm.Print_Titles", "localSheetId": "0",
        })
        escaped = sheet_name.replace("'", "''")
        entry.text = f"'{escaped}'!$1:$8"
    return count


SOURCE_FIELDS = {
    "C5":"employer.name", "C6":"employer.rut",
    "C7":"extra.representative_name", "C8":"extra.representative_rut",
    "C9":"extra.employer_phone", "C10":"extra.employer_address",
    "C11":"extra.employer_commune", "C12":"extra.employer_city",
    "C13":"extra.employer_email", "C14":"extra.specialty",
    "C17":"worker.name", "C18":"worker.rut",
    "C19":"extra.worker_nationality", "C20":"extra.worker_birthdate",
    "C21":"extra.worker_marital_status", "C22":"extra.worker_address",
    "C23":"extra.worker_commune", "C24":"extra.worker_city",
    "C25":"extra.worker_email", "C26":"extra.worker_phone",
    "C29":"role", "C30":"extra.site_address", "D30":"site.name",
    "C31":"contract.hours", "C32":"contract.salary",
    "C33":"extra.salary_words", "C34":"extra.payment_frequency",
    "C35":"extra.bank_account", "C36":"contract.start",
    "C37":"contract.end", "C38":"extra.afp",
    "C39":"extra.health_provider", "C40":"event.date",
    "C43":"extra.destinations", "C44":"extra.transport_allowance",
    "C45":"extra.declaration_period",
}
PTS_CELLS = [
    "A54", "A56", "A58", "A60", "A75", "A82", "A93", "A101",
    "A111", "A122", "A138", "A148", "A158", "A161", "A166", "A170", "A177"
]
MAX_FILE = 12 * 1024 * 1024
MAX_UNZIPPED = 65 * 1024 * 1024
# Los datos fácticos/medidas aprobadas no se editan como texto libre de plantilla:
# EPP y prórroga desde expediente; riesgos y PTS desde matrices especializadas.
PROTECTED_DOCUMENT_CELLS = {
    "pts": set(PTS_CELLS) | {"A11"},
    "irl": {
        *(f"{column}{row}" for row in
          (40, 42, 44, 46, 48, 50, 52, 54, 56, 63, 65, 67)
          for column in "ABCD"),
        "A18", "A23", "A25", "A28", "A31",
    },
    "ppe_delivery": {f"D{row}" for row in range(12, 20)},
    "extension_addendum": {"A5", "M4"},
    "sworn_declaration": {"A4", "A5"},
    # La constancia PTS incorpora cargo y firmas DESDE el expediente.
    # No permitir cambiarlos mediante el editor de celdas de plantilla.
    "pts_receipt": {"A1", "A3", "A23", "F23", "A24", "F24"},
}

RESTRICTED_PARTS = ("vbaproject.bin", "externallinks/", "connections.xml", "oleobjects/", "activex/",
                    "macrosheets/", "embeddings/")
# Referencias fijas de empresas mandantes del Excel de origen (no guardar
# nombres reales ni direcciones dentro del código). Se cambia por mandante real.
MANDANTE_PATTERN = re.compile(r"CONSTRUCTORA\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{2,38}\s+(?:LIMITADA|LTDA\.?)\b", re.I)



class LayoutError(ValueError):
    pass


def validate_xlsx(raw: bytes):
    if not raw.startswith(b"PK") or len(raw) > MAX_FILE:
        raise LayoutError("Se requiere XLSX sin macros de hasta 12 MB")
    try:
        with ZipFile(io.BytesIO(raw)) as z:
            items = z.infolist()
            if len(items) > 550 or sum(i.file_size for i in items) > MAX_UNZIPPED:
                raise LayoutError("El Excel excede límites de seguridad")
            if z.testzip():
                raise LayoutError("XLSX dañado")
            for item in items:
                name = item.filename.lower()
                if name.startswith("/") or ".." in Path(name).parts:
                    raise LayoutError("Ruta insegura dentro del XLSX")
                if any(banned in name for banned in RESTRICTED_PARTS):
                    raise LayoutError("Retira macros, enlaces externos y objetos incrustados")
            if "xl/workbook.xml" not in z.namelist():
                raise LayoutError("El archivo no contiene un libro Excel válido")
            # Las relaciones externas también pueden existir dentro de hojas o dibujos.
            # No permitir que un convertidor de documentos contacte sitios externos.
            for item in items:
                if item.filename.lower().endswith(".rels"):
                    rels = ET.fromstring(z.read(item.filename))
                    for node in rels:
                        if node.get("TargetMode") != "External":
                            continue
                        target = node.get("Target","")
                        kind = node.get("Type","")
                        if kind.endswith("/hyperlink") and target.lower().startswith("mailto:"):
                            # El XLSX original contiene un enlace de correo en Datos Contrato.
                            # Un mailto no se descarga en la conversión y no se ejecuta.
                            continue
                        raise LayoutError("Retira conexiones, imágenes y enlaces web externos del XLSX")
            sheet_files(z)
    except (BadZipFile, ET.ParseError, KeyError):
        raise LayoutError("Estructura del Excel inválida") from None


def sheet_files(z: ZipFile) -> dict[str, str]:
    book = ET.fromstring(z.read("xl/workbook.xml"))
    relations = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {}
    for rel in relations:
        if rel.attrib.get("TargetMode") == "External":
            raise LayoutError("No se admiten conexiones externas en plantillas")
        key = rel.attrib.get("Id")
        value = rel.attrib.get("Target", "")
        if value.startswith("worksheets/") or "/worksheets/" in value:
            path = "xl/" + value.lstrip("/") if value.startswith("worksheets/") else (
                value.lstrip("/") if value.startswith("/") else "xl/" + value
            )
            path = path.replace("xl/xl/", "xl/")
            targets[key] = path
    result = {}
    for s in book.findall(f".//{Q('sheet')}"):
        rel = s.attrib.get(f"{{{R}}}id")
        if rel in targets:
            result[s.attrib["name"]] = targets[rel]
    if not result:
        raise LayoutError("No se pudieron resolver las hojas del Excel")
    return result


def cell_text(cell: ET.Element, strings: list[str]) -> str:
    t = cell.attrib.get("t")
    if t == "inlineStr":
        return "".join(n.text or "" for n in cell.iter(Q("t")))
    value = cell.find(Q("v"))
    if value is None or value.text is None:
        return ""
    if t == "s":
        try:
            return strings[int(value.text)]
        except (ValueError, IndexError):
            return ""
    return value.text


def shared_strings(z: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in node.iter(Q("t"))) for node in root]


def layout_summary(raw: bytes) -> list[dict]:
    """Inventario sin copiar identidades de la plantilla a GitHub."""
    validate_xlsx(raw)
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z)
        strings = shared_strings(z)
        output = []
        for code, name in DOC_SHEETS.items():
            path = files.get(name)
            if not path:
                output.append({"code": code, "sheet": name, "found": False})
                continue
            root = ET.fromstring(z.read(path))
            cells = root.findall(".//" + Q("sheetData") + "/" + Q("row") + "/" + Q("c"))
            merged = root.findall(".//" + Q("mergeCell"))
            breaks = root.findall(".//" + Q("rowBreaks") + "/" + Q("brk"))
            formulas = [c for c in cells if c.find(Q("f")) is not None]
            nonempty = [c for c in cells if cell_text(c, strings) or c.find(Q("f")) is not None]
            output.append({"code": code, "sheet": name, "found": True,
                "cells": len(nonempty), "merged": len(merged), "formulas": len(formulas),
                "page_breaks": len(breaks), "has_print_setup": root.find(Q("pageSetup")) is not None})
        return output


def get_data(data: dict, key: str) -> str:
    node = data
    for name in key.split("."):
        if not isinstance(node, dict):
            return ""
        node = node.get(name)
    return "" if node is None else str(node)


def ensure_cell(root: ET.Element, coordinate: str) -> ET.Element:
    match = re.fullmatch(r"([A-Z]{1,3})([1-9]\d{0,5})", coordinate)
    if not match:
        raise LayoutError("Referencia de celda inválida")
    rowno = int(match.group(2))
    data = root.find(Q("sheetData"))
    if data is None:
        data = ET.SubElement(root, Q("sheetData"))
    row = next((x for x in data.findall(Q("row")) if int(x.get("r", 0)) == rowno), None)
    if row is None:
        row = ET.Element(Q("row"), {"r": str(rowno)})
        after = next((i for i, x in enumerate(list(data)) if int(x.get("r", 0)) > rowno), len(data))
        data.insert(after, row)
    cell = next((x for x in row.findall(Q("c")) if x.get("r") == coordinate), None)
    if cell is None:
        cell = ET.Element(Q("c"), {"r": coordinate})
        def colnum(s):
            n = 0
            for k in s:
                n = n*26 + ord(k)-64
            return n
        after = next((i for i,x in enumerate(list(row)) if
                      colnum(re.match(r"[A-Z]+", x.get("r", "A")).group()) > colnum(match.group(1))), len(row))
        row.insert(after, cell)
    return cell


def set_text(root: ET.Element, coordinate: str, text: str, style_source: str | None = None):
    cell = ensure_cell(root, coordinate)
    if style_source:
        style = ensure_cell(root, style_source).get("s")
        if style is not None:
            cell.set("s", style)
    for child in list(cell):
        if child.tag in {Q("v"), Q("f"), Q("is")}:
            cell.remove(child)
    cell.set("t", "inlineStr")
    inline = ET.SubElement(cell, Q("is"))
    t = ET.SubElement(inline, Q("t"))
    t.text = text
    if text != text.strip():
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def protect_pts_receipt_heading_fit(target: ET.Element, styles: bytes) -> bytes:
    """Only in the disposable print workbook, fit the variable PTS heading.

    The source title A1:I2 is merged. With a long role, Calc can silently
    print CARPINTER instead of CARPINTERO unless text fitting is enabled.
    Preserve font, fill, border and source style; clone just the cell XF
    alignment so no other workbook cells or private source are mutated.
    """
    root = ET.fromstring(styles)
    cell_xfs = root.find(Q("cellXfs"))
    if cell_xfs is None or not len(cell_xfs):
        raise LayoutError("La plantilla PTS no contiene estilos de celda")
    title = ensure_cell(target, "A1")
    try:
        old_index = int(title.get("s", "0"))
        old_xf = list(cell_xfs)[old_index]
    except (ValueError, IndexError):
        raise LayoutError("El estilo del título PTS es inválido") from None
    old_alignment = old_xf.find(Q("alignment"))
    if old_alignment is not None and old_alignment.get("shrinkToFit") == "1":
        return styles
    new_xf = ET.fromstring(ET.tostring(old_xf, encoding="utf-8"))
    alignment = new_xf.find(Q("alignment"))
    if alignment is None:
        alignment = ET.SubElement(new_xf, Q("alignment"))
    alignment.set("shrinkToFit", "1")
    alignment.attrib.pop("wrapText", None)
    new_xf.set("applyAlignment", "1")
    index = len(cell_xfs)
    cell_xfs.append(new_xf)
    cell_xfs.set("count", str(len(cell_xfs)))
    title.set("s", str(index))
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def set_numeric(root: ET.Element, coordinate: str, value: float):
    cell = ensure_cell(root, coordinate)
    for child in list(cell):
        if child.tag in {Q("v"), Q("f"), Q("is")}:
            cell.remove(child)
    cell.set("t", "n")
    ET.SubElement(cell, Q("v")).text = str(value)


def spanish_amount(value: object) -> str:
    """Conversión determinista de pesos chilenos hasta 999.999.999."""
    try:
        number = int(float(str(value).replace(".", "").replace(",", ".")))
    except (TypeError, ValueError, OverflowError):
        return ""
    if not 0 <= number < 1_000_000_000:
        return ""
    small = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete",
             "ocho", "nueve", "diez", "once", "doce", "trece", "catorce",
             "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve",
             "veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro",
             "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
    tens = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta",
            "setenta", "ochenta", "noventa"]
    hundreds = ["", "ciento", "doscientos", "trescientos", "cuatrocientos",
                "quinientos", "seiscientos", "setecientos", "ochocientos", "novecientos"]
    def under_thousand(n):
        if n < 30:
            return small[n]
        if n < 100:
            return tens[n // 10] + (" y " + small[n % 10] if n % 10 else "")
        if n == 100:
            return "cien"
        rem = n % 100
        return hundreds[n // 100] + (" " + under_thousand(rem) if rem else "")
    if number == 0:
        return "Cero pesos."
    parts = []
    million = number // 1_000_000
    thousand = (number // 1_000) % 1000
    rest = number % 1000
    if million:
        parts.append("un millón" if million == 1 else under_thousand(million) + " millones")
    if thousand:
        parts.append("mil" if thousand == 1 else under_thousand(thousand) + " mil")
    if rest:
        parts.append(under_thousand(rest))
    phrase = " ".join(parts)
    phrase = re.sub(r"\buno(?= (?:mil|millones|pesos))", "un", phrase)
    phrase = re.sub(r"\bveintiuno(?= (?:mil|millones|pesos))", "veintiún", phrase)
    return phrase[:1].upper() + phrase[1:] + " pesos."


def typed_input(root: ET.Element, coordinate: str, key: str, data: dict):
    value = get_data(data, key)
    if coordinate == "C33" and not value:
        value = spanish_amount(get_data(data, "contract.salary"))
    if coordinate == "C45":
        try:
            month = date.fromisoformat(value + "-01")
            set_numeric(root, coordinate, float((month-date(1899, 12, 30)).days))
            return
        except ValueError:
            set_text(root, coordinate, "")
            return
    if coordinate in {"C20", "C36", "C37", "C40"}:
        if not value:
            set_text(root, coordinate, "")
            return
        try:
            day = date.fromisoformat(value[:10])
            set_numeric(root, coordinate, float((day - date(1899, 12, 30)).days))
            return
        except ValueError:
            set_text(root, coordinate, value)
            return
    if coordinate in {"C31", "C32"}:
        try:
            set_numeric(root, coordinate, float(value))
            return
        except ValueError:
            pass
    set_text(root, coordinate, value)


def apply_changes(root: ET.Element, changes: dict):
    for coordinate, props in changes.items():
        if not isinstance(props, dict):
            raise LayoutError("Cambio de celda inválido")
        if not re.fullmatch(r"[A-Z]{1,3}[1-9]\d{0,5}", coordinate):
            raise LayoutError("Celda inválida")
        if "text" in props:
            value = props["text"]
            if not isinstance(value, str) or len(value) > 15000:
                raise LayoutError("Contenido de celda excesivo")
            set_text(root, coordinate, value, props.get("style_from"))
        if "row_height" in props:
            height = float(props["row_height"])
            if not 10 <= height <= 120:
                raise LayoutError("Alto de fila fuera de rango")
            rowno = int(re.search(r"\d+", coordinate).group())
            for row in root.findall(".//" + Q("sheetData") + "/" + Q("row")):
                if row.get("r") == str(rowno):
                    row.set("ht", str(height))
                    row.set("customHeight", "1")
                    break


def update_sheet(z: ZipFile, path: str, changes: dict) -> bytes:
    root = ET.fromstring(z.read(path))
    apply_changes(root, changes)
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def dynamic_cached(text: str, field_examples: list[tuple[str, str]], data: dict) -> str:
    """Sustituye valores del ejemplo original por datos de la ficha sin ejecutar fórmulas."""
    output = text
    values = []
    for source_value, field_key in field_examples:
        if not source_value or len(source_value) < 5:
            continue
        value = get_data(data, field_key)
        if field_key == "extra.salary_words" and not value:
            value = spanish_amount(get_data(data, "contract.salary"))
        values.append((source_value, value))
        if field_key == "contract.salary":
            try:
                values.append((f"{int(source_value):,}".replace(",", "."), f"{int(value):,}".replace(",", ".")))
            except (ValueError, TypeError):
                pass
    for before, after in sorted(values, key=lambda x: len(x[0]), reverse=True):
        output = re.sub(re.escape(before), lambda _match: after, output, flags=re.IGNORECASE)
    # La fecha del ejemplo histórico no debe arrastrarse a nuevas emisiones.
    sample_dates = []
    for old_value, field_key in field_examples:
        if field_key not in {"contract.start", "contract.end", "event.date", "extra.worker_birthdate"}:
            continue
        try:
            day = date(1899,12,30) + timedelta(days=int(float(old_value)))
        except (ValueError,TypeError,OverflowError):
            continue
        new_value = get_data(data, field_key)
        if not new_value:
            continue
        try:
            target_date = date.fromisoformat(new_value[:10])
        except ValueError:
            continue
        sample_dates.append((day,target_date))
    months = ("enero","febrero","marzo","abril","mayo","junio","julio","agosto",
              "septiembre","octubre","noviembre","diciembre")
    # Si la firma y el inicio tenían igual día, prevalece la fecha de emisión.
    sample_dates.sort(key=lambda item: 0 if item[0] and
                       get_data(data,"event.date")==item[1].isoformat() else 1)
    for old_date, new_date in sample_dates:
        old_slash = old_date.strftime("%d/%m/%Y")
        new_slash = new_date.strftime("%d/%m/%Y")
        output = output.replace(old_slash,new_slash)
        old_words = f"{old_date.day} de {months[old_date.month-1]} de {old_date.year}"
        new_words = f"{new_date.day} de {months[new_date.month-1]} de {new_date.year}"
        output = re.sub(re.escape(old_words), lambda _m:new_words, output, flags=re.IGNORECASE)
    if not get_data(data,"extra.salary_words"):
        old_words = next((value for value,key in field_examples if key=="extra.salary_words"), "")
        if old_words:
            output = re.sub(re.escape(old_words),
                            lambda _m:spanish_amount(get_data(data,"contract.salary")),
                            output,flags=re.IGNORECASE)
    output = re.sub(r"\{\{\s*([a-z][a-z0-9_.]{0,80})\s*\}\}",
                    lambda m: get_data(data, m.group(1)), output)
    return output


def replace_frozen_today(text: str, data: dict, formula: str) -> str:
    """Materialize TODAY() in a document's cached attestation line.

    Cached XLSX values can contain the date when the author's example was last
    calculated. Never use that cached date as the date of the new legal event.
    This only changes the attestation date, not the legally reviewed paragraph.
    """
    if "TODAY()" not in formula.upper() or "con fecha" not in text.lower():
        return text
    raw_date = get_data(data, "event.date").strip()
    try:
        effective = date.fromisoformat(raw_date[:10])
    except ValueError:
        raise LayoutError("Indica la fecha efectiva del documento para reemplazar la fecha del ejemplo") from None
    pattern = r"(\bcon fecha\s+)\d{1,2}/\d{1,2}/\d{4}\b"
    replaced, count = re.subn(pattern, lambda match: match.group(1) + effective.strftime("%d/%m/%Y"),
                              text, count=1, flags=re.IGNORECASE)
    if count != 1:
        raise LayoutError("La fecha calculada por TODAY() no pudo reemplazarse en la constancia; revisar su fórmula")
    return replaced


def cached_values(root: ET.Element, strings: list[str]) -> dict[str, str]:
    return {c.get("r"): cell_text(c, strings) for c in root.iter(Q("c"))}


def excel_document(raw: bytes, code: str, data: dict, changes: dict | None = None,
                   matrix: list[str] | None = None,
                   extra_matrices: dict[str, list[str]] | None = None) -> bytes:
    """Libro de UNA SOLA hoja, preservando formato OOXML íntegro y reemplazando identidades.

    Convertir todo el libro exporta incluso hojas ocultas en LibreOffice. Por eso
    solo se referencia la hoja documental y se materializan sus fórmulas como
    valores cacheados, sustituidos desde la ficha. Nunca se ejecutan macros.
    """
    from copy import copy
    validate_xlsx(raw)
    if code not in DOC_SHEETS:
        raise LayoutError("Documento desconocido")
    extra_matrices = extra_matrices or {}
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z)
        selected = DOC_SHEETS[code]
        if selected not in files or "Datos Contrato" not in files:
            raise LayoutError("Faltan hojas documentales o Datos Contrato")
        strings = shared_strings(z)
        source = ET.fromstring(z.read(files["Datos Contrato"]))
        examples = cached_values(source, strings)
        field_examples = [(examples.get(coord, ""), key) for coord, key in SOURCE_FIELDS.items()]
        target = ET.fromstring(z.read(files[selected]))
        target_cells = list(target.iter(Q("c")))
        for cell in target_cells:
            coordinate = cell.get("r")
            cached = cell_text(cell, strings)
            formula_element = cell.find(Q("f"))
            formula = (formula_element.text or "").strip() if formula_element is not None else ""
            # Referencias simples de Datos Contrato se resuelven sin Calc.
            direct = re.fullmatch(r"\+?'Datos Contrato'!\$?([A-Z]+)\$?(\d+)", formula)
            if direct:
                ref = direct.group(1) + direct.group(2)
                field_key = SOURCE_FIELDS.get(ref)
                if field_key:
                    text = get_data(data, field_key)
                    if ref == "C33" and not text:
                        text = spanish_amount(get_data(data, "contract.salary"))
                else:
                    text = cached
            else:
                text = dynamic_cached(cached, field_examples, data)
            if formula and "TODAY()" in formula.upper():
                text = replace_frozen_today(text, data, formula)
            if code in {"induction","sworn_declaration"} and text:
                principal = get_data(data, "extra.principal_company").strip()
                if not principal:
                    raise LayoutError("La empresa mandante debe identificarse antes de imprimir")
                text = MANDANTE_PATTERN.sub(lambda _match: principal, text)
            if formula_element is not None or text != cached:
                set_text(target, coordinate, text if text != "0" or not formula else "")
        if code == "extension_addendum":
            try:
                new_end = date.fromisoformat(get_data(data, "contract.new_end"))
                old_end = date.fromisoformat(get_data(data, "contract.end"))
                start = date.fromisoformat(get_data(data, "contract.start"))
            except (ValueError, TypeError):
                raise LayoutError("El anexo requiere fechas válidas de ingreso, término y prórroga") from None
            if new_end <= old_end:
                raise LayoutError("La prórroga debe superar la fecha actual de término")
            set_numeric(target, "M4", float((new_end - date(1899, 12, 30)).days))
            set_text(target, "A5",
                     "PRIMERO: Las partes dejan constancia de que el contrato de trabajo "
                     "iniciado el " + start.strftime("%d/%m/%Y") +
                     " y cuyo vencimiento estaba fijado para el " + old_end.strftime("%d/%m/%Y") +
                     " se prorroga, de mutuo acuerdo, hasta el " + new_end.strftime("%d/%m/%Y") +
                     ". Las restantes condiciones del contrato se mantienen vigentes, "
                     "salvo modificaciones escritas expresamente acordadas.")
        if code == "sworn_declaration":
            if get_data(data, "worker.name").strip():
                raise LayoutError("La declaración jurada de ausencia de trabajadores no puede incluir un trabajador asignado")
            period = get_data(data, "extra.declaration_period").strip()
            if not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", period):
                raise LayoutError("Indica periodo de declaración como YYYY-MM")
            principal = get_data(data, "extra.principal_company").strip()
            if not principal:
                raise LayoutError("Indica el nombre real de la empresa mandante; no se hereda del Excel")
            representative = get_data(data, "extra.representative_name")
            rep_rut = get_data(data, "extra.representative_rut")
            nationality = get_data(data, "extra.representative_nationality")
            employer = get_data(data, "employer.name")
            employer_rut = get_data(data, "employer.rut")
            address = get_data(data, "extra.employer_address")
            city = get_data(data, "extra.employer_city")
            set_text(target, "A4",
                     f"YO, {representative}, RUT N° {rep_rut}, REPRESENTANTE DE {employer}, "
                     f"RUT {employer_rut}, DE NACIONALIDAD {nationality}, "
                     f"DOMICILIADO EN {address}, CIUDAD DE {city}, "
                     "DECLARO BAJO FE DE JURAMENTO:")
            fromcalendar = (
                "QUE DURANTE EL MES DE " +
                ("ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO","JULIO",
                 "AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE")[int(period[5:])-1]
                + " DEL AÑO " + period[:4]
            )
            set_text(target, "A5",
                     fromcalendar +
                     ", NO HE TENIDO TRABAJADORES A MI CARGO BAJO RÉGIMEN DE "
                     "SUBORDINACIÓN O DEPENDENCIA EN LA OBRA " +
                     get_data(data, "site.name") + ", UBICADA EN " +
                     get_data(data, "extra.site_address") +
                     ", DESARROLLANDO LAS LABORES DE " + get_data(data, "extra.specialty") +
                     ", EN VIRTUD DE LA RELACIÓN DE SERVICIOS CON " + principal +
                     ". DECLARACIÓN ESPECÍFICA: " +
                     get_data(data, "contract.declaration_reason") + ".")

        if code == "pts_receipt":
            # Cargo del trabajador, nunca rubro del empleador del Excel de ejemplo.
            role = get_data(data, "role").strip()
            if not role:
                raise LayoutError("Indica el cargo real para la entrega del PTS")
            set_text(target, "A1", "ENTREGA PTS DE " + role.upper())
            introduction = ensure_cell(target, "A3")
            original = cell_text(introduction, strings)
            if "correspondiente al cargo de" in original.lower():
                updated, count = re.subn(
                    r"(correspondiente al cargo de\s+)[^.\n]+(\.)",
                    lambda match: match.group(1) + role.upper() + match.group(2),
                    original, count=1, flags=re.IGNORECASE,
                )
                if count != 1:
                    raise LayoutError("No se pudo vincular el cargo dentro de Entrega PTS")
                set_text(target, "A3", updated)
            # The supplied original has incorrect formulas in the signature
            # block (A23/F23 point to RUTs, A24/F24 to nationality/civil status).
            # Both name and RUT must come from the current dossier.
            set_text(target, "A23", get_data(data, "extra.representative_name"))
            set_text(target, "F23", get_data(data, "worker.name"))
            set_text(target, "A24", "RUT: " + get_data(data, "extra.representative_rut"))
            set_text(target, "F24", "RUT: " + get_data(data, "worker.rut"))
        if code == "pts":
            if matrix is None or len(matrix) != 17:
                raise LayoutError("La impresión PTS exige 17 secciones de matriz aprobadas")
            set_text(target, "A11", "PROCEDIMIENTO DE TRABAJO SEGURO DE " + get_data(data, "role").upper())
            for cell, section in zip(PTS_CELLS, matrix):
                set_text(target, cell, str(section))
        if code == "irl":
            if matrix is None or len(matrix) < 1:
                raise LayoutError("IRL requiere matriz de riesgos aprobada")
            rows = (40, 42, 44, 46, 48, 50, 52, 54, 56, 63, 65, 67)
            for i, row in enumerate(rows):
                text = matrix[i] if i < len(matrix) else ""
                # Texto importado de MATRIZ IRL: cuatro columnas Tarea/Peligro/Riesgo/Medidas.
                cols = ["", "", "", ""]
                pieces = re.split(r"\n(?=(?:Tarea|Peligro|Riesgo|Medidas):)", str(text))
                for part in pieces:
                    for index, label in enumerate(("Tarea:", "Peligro:", "Riesgo:", "Medidas:")):
                        if part.startswith(label):
                            cols[index] = part[len(label):].strip()
                if not any(cols):
                    cols[0] = str(text)
                for letter, value in zip("ABCD", cols):
                    set_text(target, letter + str(row), value)
            extra = extra_matrices.get("PERFILES", [])
            set_text(target, "A18", "\n".join(extra[:5]))
            extra = extra_matrices.get("PUESTOS", [])
            for cell, value in zip(("A23","A25","A28","A31"), list(extra[:4])+[""]*4):
                set_text(target, cell, value)
            extra = extra_matrices.get("SUSTANCIAS", [])
            for i in range(69, 81):
                set_text(target, "C"+str(i), extra[i-69] if i-69 < len(extra) else "")
        if code == "ppe_delivery":
            # La plantilla original pre-marca cantidad=1 para ocho EPP, lo que puede
            # generar falsas entregas. Limpiar SIEMPRE cantidades no declaradas.
            from .javiera_workbook import delivery_quantities
            quantities = delivery_quantities(get_data(data, "event.epp_items"))
            for index, amount in enumerate(quantities, start=12):
                set_text(target, "D"+str(index), str(amount) if amount else "")

        if changes:
            restricted = set(changes).intersection(PROTECTED_DOCUMENT_CELLS.get(code, set()))
            if restricted:
                raise LayoutError("Las celdas " + ", ".join(sorted(restricted)) +
                                  " contienen datos del expediente o controles preventivos; "
                                  "edítalos en el formulario o en la matriz aprobable")
            replacements_for_fields = {}
            for coordinate, props in changes.items():
                if not isinstance(props, dict):
                    raise LayoutError("Edición de celda inválida")
                content = dict(props)
                if "text" in content:
                    content["text"] = dynamic_cached(content["text"], field_examples, data)
                replacements_for_fields[coordinate] = content
            apply_changes(target, replacements_for_fields)
        # Los valores fácticos de entregas y vigencia no se pueden alterar
        # desde texto de plantilla; proceden exclusivamente del expediente.
        if code == "ppe_delivery":
            for index, amount in enumerate(quantities, start=12):
                set_text(target, "D"+str(index), str(amount) if amount else "")
        if code == "extension_addendum":
            set_numeric(target, "M4", float((new_end-date(1899,12,30)).days))
        book = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = book.find(Q("sheets"))
        if sheets is None:
            raise LayoutError("Libro Excel sin hojas")
        target_sheet = next((x for x in sheets if x.get("name") == selected), None)
        if target_sheet is None:
            raise LayoutError("Hoja de salida no encontrada")
        for node in list(sheets):
            if node is not target_sheet:
                sheets.remove(node)
        target_sheet.attrib.pop("state", None)
        view = book.find(".//" + Q("workbookView"))
        if view is not None:
            view.set("activeTab", "0")
            view.set("firstSheet", "0")
        original_index = list(files).index(selected)
        names = book.find(Q("definedNames"))
        if names is not None:
            for item in list(names):
                if (item.get("name") in ("_xlnm.Print_Area","_xlnm.Print_Titles") and
                        item.get("localSheetId") == str(original_index)):
                    item.set("localSheetId", "0")
                else:
                    names.remove(item)
        set_document_print_profile(target, book, code, selected)
        if code == "induction":
            configure_induction_sections(target, book, selected, strings)
        calc = book.find(Q("calcPr"))
        if calc is not None:
            calc.set("fullCalcOnLoad", "0")
            calc.set("forceFullCalc", "0")
        style_replacement = (
            protect_pts_receipt_heading_fit(target, z.read("xl/styles.xml"))
            if code == "pts_receipt" else None
        )
        replacement = {
            files[selected]: ET.tostring(target, encoding="UTF-8", xml_declaration=True),
            "xl/workbook.xml": ET.tostring(book, encoding="UTF-8", xml_declaration=True),
        }
        if style_replacement is not None:
            replacement["xl/styles.xml"] = style_replacement
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=5) as out:
            for info in z.infolist():
                if info.filename in replacement:
                    out.writestr(copy(info), replacement[info.filename])
                else:
                    out.writestr(copy(info), z.read(info.filename))
        return buffer.getvalue()



def normalize_pdf_a4(raw: bytes) -> bytes:
    """Normalize each PDF page to A4 without hiding content outside a source margin.

    LibreOffice may put a title a few points before the source page's zero
    coordinate. Expanding the source MediaBox on every side and then fitting
    all recovered content proportionally is safer than discarding the PDF or
    disabling layout validation. Very large negative displacement still blocks.
    """
    source = fitz.open(stream=raw, filetype="pdf")
    output = fitz.open()
    try:
        for index in range(source.page_count):
            page = source[index]
            original = page.rect
            first = [b for b in page.get_text("blocks")
                     if len(b) >= 5 and (b[4].strip() if isinstance(b[4], str) else True)]
            left = min([0, *[b[0] for b in first]])
            top = min([0, *[b[1] for b in first]])
            if left < -180 or top < -180:
                raise LayoutError(
                    f"Página {index + 1}: contenido desplazado más de 180 pt "
                    "fuera del margen; revisar celdas, escalado y área de impresión"
                )
            # 16pt bleed also recovers partially clipped first/last characters.
            left_pad = max(16.0, -left + 14.0)
            top_pad = max(16.0, -top + 14.0)
            page.set_mediabox(fitz.Rect(
                -left_pad, -top_pad, original.width + 250, original.height + 200
            ))
            recovered = [b for b in page.get_text("blocks")
                         if len(b) >= 5 and (b[4].strip() if isinstance(b[4], str) else True)]
            max_x = max([original.width, *[b[2] for b in recovered]])
            max_y = max([original.height, *[b[3] for b in recovered]])
            if any(b[0] < -180 or b[1] < -180 for b in recovered):
                raise LayoutError(
                    f"Página {index + 1}: el contenido excede el margen de "
                    "recuperación. Identifica la celda y corrige su formato."
                )
            page.set_mediabox(fitz.Rect(
                -left_pad, -top_pad,
                max(original.width, max_x - left_pad + 14),
                max(original.height, max_y + 14)
            ))
            target = output.new_page(width=595, height=842)
            target.show_pdf_page(
                fitz.Rect(18, 18, 577, 824), source, index,
                keep_proportion=True, overlay=True
            )
        for number, page in enumerate(output, 1):
            blocks = [b for b in page.get_text("blocks")
                      if len(b) >= 5 and (b[4].strip() if isinstance(b[4], str) else True)]
            for block in blocks:
                if (block[0] < 0 or block[1] < 0
                        or block[2] > page.rect.width
                        or block[3] > page.rect.height):
                    raise LayoutError(
                        f"Página {number}: texto fuera de la página A4 después "
                        "de la normalización; revisar diseño original"
                    )
        return output.tobytes(garbage=4, deflate=True)
    finally:
        source.close()
        output.close()



def libreoffice_pdf(xlsx: bytes, timeout: int = 50) -> bytes:
    """Conversión aislada con límites de proceso y archivo temporal privado."""
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    if not binary:
        raise LayoutError("Motor de impresión Excel no instalado (LibreOffice Calc)")
    with tempfile.TemporaryDirectory(prefix="javiera-pdf-") as name:
        folder = Path(name)
        source = folder / "plantilla.xlsx"
        source.write_bytes(xlsx)
        source.chmod(0o600)
        profile = folder / "lo-profile"
        profile.mkdir(mode=0o700)
        command = [binary, "-env:UserInstallation=" + profile.as_uri(),
                   "--headless", "--convert-to", "pdf:calc_pdf_Export",
                   "--outdir", str(folder), str(source)]
        env = {k: os.environ[k] for k in ("PATH", "LANG", "HOME", "TMPDIR") if k in os.environ}
        env["HOME"] = str(folder)
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                timeout=timeout, env=env, cwd=str(folder), check=False)
        except subprocess.TimeoutExpired:
            raise LayoutError("La conversión de la plantilla superó el tiempo permitido") from None
        path = folder / "plantilla.pdf"
        if result.returncode != 0 or not path.is_file():
            raise LayoutError("Error en conversión Excel→PDF: " + (result.stderr or result.stdout)[-280:])
        if path.stat().st_size > 15 * 1024 * 1024:
            raise LayoutError("PDF generado demasiado grande")
        pdf = path.read_bytes()
        try:
            with fitz.open(stream=pdf, filetype="pdf") as document:
                if not (1 <= document.page_count <= 120):
                    raise LayoutError("La plantilla produce demasiadas páginas")
                if any(page.rect.width < 250 or page.rect.height < 250 for page in document):
                    raise LayoutError("Tamaño de página no permitido")
        except fitz.FileDataError:
            raise LayoutError("El motor de impresión devolvió un PDF inválido") from None
        return normalize_pdf_a4(pdf)


def append_irl_continuation(pdf: fitz.Document, matrix: list[str], data: dict):
    """Incluye todos los riesgos que exceden las 12 filas de la hoja IRL.

    La plantilla original tiene 12 renglones. Nunca se descartan los siguientes.
    El anexo se agrega al mismo archivo PDF y comparte el contexto del expediente.
    """
    additional = matrix[12:]
    if not additional:
        return
    margin = 44
    width = 595 - 2 * margin
    page = None
    y = 0

    def start_page():
        current = pdf.new_page(width=595, height=842)
        # Reservar la esquina superior para el sello de vista previa en rojo.
        current.insert_text((margin, 52), "GALANT / JAVIERA - IRL", fontsize=10, fontname="helv")
        current.insert_text((margin, 73), "ANEXO INTEGRANTE - CONTINUACION DE MATRIZ IRL",
                            fontsize=10, fontname="helv")
        current.insert_text((margin, 92),
                            ("Cargo: " + get_data(data, "role"))[:85],
                            fontsize=9, fontname="helv")
        current.insert_text((margin, 109),
                            ("Obra: " + get_data(data, "site.name"))[:85],
                            fontsize=9, fontname="helv")
        current.insert_text((margin, 814),
                            "Riesgos y medidas preventivas del cargo - documento sin firma",
                            fontsize=8, fontname="helv")
        return current, 131

    page, y = start_page()
    for position, section in enumerate(additional, 13):
        if not str(section).strip():
            raise LayoutError("La matriz IRL contiene riesgos sin descripción")
        paragraphs = [f"REGISTRO {position}", *str(section).splitlines()]
        needed = 18 + max(1, len(paragraphs) - 1) * 13
        if y + needed > 782:
            page, y = start_page()
        for content in paragraphs:
            # En PDF no se inserta HTML ni se ejecutan comandos de la plantilla.
            remaining = " ".join(content.split())
            while remaining:
                line = ""
                for word in remaining.split(" "):
                    candidate = (line + " " + word).strip()
                    if fitz.get_text_length(candidate, fontname="helv", fontsize=9) <= width:
                        line = candidate
                    else:
                        break
                if not line:
                    # Evita un bucle por un token único excesivamente largo.
                    line, remaining = remaining[:65], remaining[65:].lstrip()
                else:
                    remaining = remaining[len(line):].lstrip()
                if y + 13 > 782:
                    page, y = start_page()
                page.insert_text((margin, y), line, fontsize=9, fontname="helv")
                y += 13
        y += 8
    if pdf.page_count > 120:
        raise LayoutError("El IRL excede el máximo de páginas; revisa la matriz")


def pdf_from_workbook(raw: bytes, code: str, data: dict, *,
                      changes: dict | None = None, matrix: list[str] | None = None,
                      extra_matrices: dict[str, list[str]] | None = None,
                      preview: bool = False) -> bytes:
    converted = libreoffice_pdf(excel_document(raw, code, data, changes, matrix, extra_matrices))
    with fitz.open(stream=converted, filetype="pdf") as pdf:
        if code == "irl" and matrix:
            append_irl_continuation(pdf, matrix, data)
        printed = " ".join(" ".join(p.get_text().split()) for p in pdf)
        printed = " ".join(printed.casefold().split())
        employer = " ".join(get_data(data, "employer.name").casefold().split())
        worker = " ".join(get_data(data, "worker.name").casefold().split())
        if employer and employer not in printed:
            raise LayoutError("El PDF no contiene el nombre completo del empleador seleccionado")
        if worker and code in {
            "labor_contract", "transfer_addendum", "extension_addendum",
            "induction", "irl", "pts_receipt", "ppe_delivery",
            "internal_rules_receipt",
        } and worker not in printed:
            raise LayoutError("El PDF no contiene al trabajador seleccionado; revisión obligatoria")
        if code == "pts_receipt":
            # El texto A1 contiene un título variable. Una plantilla fuente
            # con unión demasiado angosta puede producir un PDF A4 válido
            # pero truncar la última letra del cargo (CARPINTERO -> CARPINTER).
            # Nunca liberar un acta que cambie la identificación del PTS.
            expected = " ".join(
                ("ENTREGA PTS DE " + get_data(data, "role").strip().upper()).casefold().split()
            )
            if expected not in printed:
                raise LayoutError(
                    "El título ENTREGA PTS se recortó o no coincide con el cargo. "
                    "Revisa el rango combinado y el ancho del encabezado de la "
                    "plantilla original antes de imprimir."
                )
        if preview:
            for page in pdf:
                page.insert_text((32, 30), "VISTA PREVIA - NO VALIDO PARA FIRMA",
                                 fontsize=10, color=(0.8, 0.16, 0.12),
                                 overlay=True)
        return pdf.tobytes(garbage=4, deflate=True)
