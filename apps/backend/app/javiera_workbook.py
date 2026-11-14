"""OOXML is the only content store. Calc calculates a disposable full workbook.

Never save a master with openpyxl/Calc: graphic resources, relationships and
formulas stay byte-for-byte in the original package except explicitly edited XML.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
import weakref
from copy import copy, deepcopy
import base64
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import URLError
from urllib.parse import urlsplit
from collections import Counter
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET
import fitz
from .javiera_excel import (DOC_SHEETS, SOURCE_FIELDS, PTS_CELLS, LayoutError, Q, R,
    apply_changes, cell_text, ensure_cell, set_numeric, set_text, shared_strings,
    sheet_files, typed_input, validate_xlsx, validate_cell_text, get_data, MANDANTE_PATTERN, protect_induction_evaluation_header)
from .xlsx_package import preserve_namespaces
from datetime import date

MATRIX_SHEETS = {"IRL": ("MATRIZ IRL", "B"), "PTS": ("MATRIZ PTS", "A"),
    "PUESTOS": ("Matriz IRL Optimizada", "A"),
    "PERFILES": ("MATRIZ DESCRIPCION DE CARGO IRL", "B"),
    "SUSTANCIAS": ("Base_Datos_Sustancias", "A")}
CONVERSIONS = threading.BoundedSemaphore(2)
_locks: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
_locks_guard = threading.Lock()
ERRORS = {"#REF!", "#VALUE!", "#NAME?", "#DIV/0!", "#N/A", "#NUM!", "#SPILL!", "#NULL!"}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def resolve_sheet(files: dict, name: str) -> str:
    matches = [key for key in files if key.strip().casefold() == name.strip().casefold()]
    if len(matches) != 1:
        raise LayoutError("Hoja ausente o ambigua: " + name)
    return matches[0]


def pack(z: ZipFile, changes: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as result:
        for item in z.infolist():
            original = z.read(item.filename)
            changed = changes.get(item.filename)
            if changed is not None and item.filename.endswith((".xml", ".rels")):
                changed = preserve_namespaces(changed, original)
            result.writestr(copy(item), changed if changed is not None else original)
        for name, raw in changes.items():
            if name not in z.namelist(): result.writestr(name, raw)
    return out.getvalue()


def xml(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def inventory(raw: bytes) -> dict:
    validate_xlsx(raw)
    with ZipFile(io.BytesIO(raw)) as z:
        book = ET.fromstring(z.read("xl/workbook.xml"))
        files = sheet_files(z)
        sheets = []; pending = []; strings = shared_strings(z)
        for index, (name, path) in enumerate(files.items()):
            root = ET.fromstring(z.read(path))
            cells = root.findall(".//" + Q("c"))
            formulas = [c for c in cells if c.find(Q("f")) is not None]
            if any(re.search(r"\||\b(?:WEBSERVICE|HYPERLINK|DDE|RTD|CALL|EXEC|SHELL|REGISTER(?:\.ID)?|SQL\.REQUEST|IMAGE)\s*\(|\[[^]]+\][^!]*!",
                             re.sub(r'"(?:[^"]|"")*"','""',c.find(Q("f")).text or ""), re.I) for c in formulas):
                raise LayoutError("El libro contiene fórmulas con conexiones externas no autorizadas")
            dependencies = sorted({m for c in formulas for m in re.findall(
                r"'([^']+)'!", c.find(Q("f")).text or "")})
            defined = [n.text for n in book.findall(".//" + Q("definedName"))
                       if n.get("name") == "_xlnm.Print_Area" and n.get("localSheetId") == str(index)]
            setup = root.find(Q("pageSetup"))
            margins = root.find(Q("pageMargins"))
            sheets.append({"name": name, "cells": len(cells), "formulas": len(formulas),
                "editable_cells": sum(1 for c in cells if c.find(Q("f")) is None and
                                      (c.find(Q("v")) is not None or c.find(Q("is")) is not None)),
                "merged": [n.get("ref") for n in root.findall(".//" + Q("mergeCell"))],
                "dependencies": dependencies, "print_areas": defined,
                "page_setup": setup.attrib if setup is not None else {},
                "margins": margins.attrib if margins is not None else {},
                "breaks": [n.attrib for n in root.findall(".//" + Q("brk"))],
                "drawings": len(root.findall(Q("drawing"))),
                "purpose": ("matriz" if name.strip() in {v[0] for v in MATRIX_SHEETS.values()}
                            else "documento" if name.strip() in DOC_SHEETS.values() or name.startswith("IND ")
                            else "datos" if name == "Datos Contrato" else "auxiliar")})
            if name.strip() == 'MATRIZ IRL':
                for row in root.findall('.//'+Q('row')):
                    n = int(row.get('r'))
                    if n < 2: continue
                    values = {re.match(r'[A-Z]+',c.get('r')).group():c for c in row.findall(Q('c'))}
                    role_cell = values.get('B'); role = cell_text(role_cell,strings).strip() if role_cell is not None else ''
                    if not role: continue
                    missing = [col for col in 'CDEF' if col not in values or
                               values[col].find(Q('f')) is None and not cell_text(values[col],strings).strip()]
                    if missing:pending.append({'sheet':name,'row':n,'role':role,'columns':missing})
        media = [{"part": n, "sha256": digest(z.read(n)), "bytes": len(z.read(n))}
                 for n in z.namelist() if n.startswith("xl/media/")]
        return {"sha256": digest(raw), "sheet_count": len(sheets), "sheets": sheets,
            "formula_count": sum(s["formulas"] for s in sheets), "media": media,
            "media_count": len(media), "emf_count": sum(m["part"].lower().endswith(".emf") for m in media),
            "print_area_count": sum(len(s["print_areas"]) for s in sheets), 'matrix_pending':pending}


def read_sheet(raw: bytes, name: str, start: int = 1, count: int = 60) -> dict:
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z); name = resolve_sheet(files, name)
        root = ET.fromstring(z.read(files[name])); strings = shared_strings(z)
        cells = []
        for c in root.findall(".//" + Q("c")):
            row = int(re.search(r"\d+", c.get("r")).group())
            if start <= row < start + count:
                formula = c.find(Q("f"))
                cells.append({"cell": c.get("r"), "row": row,
                    "value": cell_text(c, strings), "formula": formula.text if formula is not None else None,
                    "style": c.get("s", "0"), "type": c.get("t", "n")})
        styles = ET.fromstring(z.read("xl/styles.xml"))
        def items(tag):
            n = styles.find(Q(tag)); return list(n) if n is not None else []
        fonts, fills, borders, xfs = [items(n) for n in ("fonts", "fills", "borders", "cellXfs")]
        css = []
        for xf in xfs:
            font = fonts[int(xf.get("fontId", 0))]; fill = fills[int(xf.get("fillId", 0))]
            align = xf.find(Q("alignment")); size = font.find(Q("sz")); color = font.find(Q("color"))
            fg = fill.find(".//" + Q("fgColor"))
            border = borders[int(xf.get("borderId", 0))]
            style = {"fontSize": min(72, float(size.get("val", 11))) if size is not None else 11,
                     "fontWeight": "bold" if font.find(Q("b")) is not None and font.find(Q("b")).get("val", "1") != "0" else "normal",
                     "fontStyle": "italic" if font.find(Q("i")) is not None and font.find(Q("i")).get("val", "1") != "0" else "normal"}
            if color is not None and color.get("rgb"): style["color"] = "#" + color.get("rgb")[-6:]
            if fg is not None and fg.get("rgb"): style["backgroundColor"] = "#" + fg.get("rgb")[-6:]
            if align is not None:
                style["textAlign"] = align.get("horizontal", "left").replace("general", "left")
            for edge in ("top", "bottom", "left", "right"):
                n = border.find(Q(edge))
                if n is not None and n.get("style"): style["border" + edge.title()] = "1px solid #7c8da0"
            css.append(style)
        return {"name": name, "cells": cells, "styles": css,
            "merged": [n.get("ref") for n in root.findall(".//" + Q("mergeCell"))],
            "columns": [n.attrib for n in root.findall(".//" + Q("col"))],
            "heights": {r.get("r"): r.get("ht") for r in root.findall(".//" + Q("row")) if r.get("ht")},
            "last_row": max([1, *[int(r.get("r")) for r in root.findall(".//" + Q("row"))]]),
            "start": start, "count": count}


def cell_format(styles: ET.Element, cell: ET.Element, changes: dict) -> None:
    """Clone a cell style so formatting one cell never changes its neighbours."""
    xfs = styles.find(Q("cellXfs")); fonts = styles.find(Q("fonts")); fills = styles.find(Q("fills"))
    xf = deepcopy(xfs[int(cell.get("s", "0"))])
    font = deepcopy(fonts[int(xf.get("fontId", "0"))])
    for key, tag in (("bold", "b"), ("italic", "i")):
        if key in changes:
            for old in list(font.findall(Q(tag))): font.remove(old)
            if changes[key]: ET.SubElement(font, Q(tag))
    if "font_size" in changes:
        n = font.find(Q("sz"))
        if n is None: n = ET.SubElement(font, Q("sz"))
        n.set("val", str(changes["font_size"]))
    if any(key in changes for key in ("bold", "italic", "font_size")):
        fonts.append(font); fonts.set("count", str(len(fonts)))
        xf.set("fontId", str(len(fonts)-1)); xf.set("applyFont", "1")
    if "fill_color" in changes:
        fill = ET.Element(Q("fill")); pattern = ET.SubElement(fill, Q("patternFill"), {"patternType":"solid"})
        ET.SubElement(pattern, Q("fgColor"), {"rgb":"FF"+changes["fill_color"].lstrip("#").upper()})
        ET.SubElement(pattern, Q("bgColor"), {"indexed":"64"})
        fills.append(fill); fills.set("count", str(len(fills)))
        xf.set("fillId", str(len(fills)-1)); xf.set("applyFill", "1")
    if any(key in changes for key in ("align", "wrap")):
        align = xf.find(Q("alignment"))
        if align is None:
            align = ET.Element(Q("alignment"))
            index = next((i for i, child in enumerate(xf) if child.tag in {Q("protection"), Q("extLst")}), len(xf))
            xf.insert(index, align)
        if "align" in changes: align.set("horizontal", changes["align"])
        if "wrap" in changes: align.set("wrapText", "1" if changes["wrap"] else "0")
        xf.set("applyAlignment", "1")
    # Reuse identical styles, including when pasting the same format repeatedly.
    serialized = xml(xf)
    index = next((i for i, old in enumerate(xfs) if xml(old) == serialized), None)
    if index is None:
        index = len(xfs); xfs.append(xf); xfs.set("count", str(len(xfs)))
    cell.set("s", str(index))


def edit_workbook(raw: bytes, sheet: str, edits: list[dict]) -> bytes:
    """Edits materialize into a new XLSX; no JSON overrides or shadow content."""
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z); sheet = resolve_sheet(files, sheet)
        root = ET.fromstring(z.read(files[sheet]))
        styles = ET.fromstring(z.read("xl/styles.xml")); format_changed = False
        merges = []
        def column_number(value):
            return sum((ord(c)-64)*26**i for i,c in enumerate(reversed(value)))
        for node in root.findall(".//"+Q("mergeCell")):
            first, _, last = node.get("ref", "").partition(":")
            a=re.fullmatch(r"([A-Z]+)([1-9]\d*)",first); b=re.fullmatch(r"([A-Z]+)([1-9]\d*)",last or first)
            if a and b: merges.append((first,column_number(a[1]),int(a[2]),column_number(b[1]),int(b[2])))
        for edit in edits:
            coord = edit["cell"]
            match = re.fullmatch(r"([A-Z]{1,3})([1-9]\d{0,5})",coord)
            if not match: raise LayoutError("Referencia de celda inválida")
            col,row = column_number(match[1]),int(match[2])
            if any(first!=coord and left<=col<=right and top<=row<=bottom for first,left,top,right,bottom in merges):
                raise LayoutError("Edita la celda principal del rango combinado, no una celda cubierta")
            cell = ensure_cell(root, coord)
            column = re.match(r"[A-Z]+", coord).group()
            if sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(column))) > 16384:
                raise LayoutError("La columna excede el límite de Excel")
            if "formula" in edit and edit["formula"] is not None:
                formula = edit["formula"].lstrip("=")
                validate_cell_text(formula)
                if re.search(r"\[|\||\b(?:DDE|WEBSERVICE|HYPERLINK|RTD|CALL|EXEC|SHELL|REGISTER(?:\.ID)?|SQL\.REQUEST|IMAGE)\s*\(",
                             re.sub(r'"(?:[^"]|"")*"','""',formula), re.I):
                    raise LayoutError("Las fórmulas no pueden abrir conexiones externas")
                for child in list(cell): cell.remove(child)
                cell.attrib.pop("t", None); ET.SubElement(cell, Q("f")).text = formula
            elif "value" in edit:
                # Formula replacement must be explicit, never an accidental edit.
                if cell.find(Q("f")) is not None:
                    raise LayoutError("Esta celda es calculada. Edita su fórmula explícitamente")
                value = edit["value"]
                if isinstance(value, (float, int)) and not isinstance(value, bool): set_numeric(root, coord, value)
                else: set_text(root, coord, str(value or ""))
            if edit.get("style_from"):
                source = root.find(".//"+Q("c")+"[@r='"+edit["style_from"]+"']")
                if source is None: raise LayoutError("La celda de origen del estilo no existe")
                cell.set("s", source.get("s", "0"))
            if edit.get("format"):
                cell_format(styles, cell, edit["format"]); format_changed = True
            if edit.get("row_height"):
                row = root.find(".//" + Q("row") + "[@r='" + re.search(r"\d+", coord).group() + "']")
                row.set("ht", str(edit["row_height"])); row.set("customHeight", "1")
        book = ET.fromstring(z.read("xl/workbook.xml"))
        calc = book.find(Q("calcPr"))
        if calc is None:
            calc = ET.Element(Q("calcPr"))
            following = {Q(name) for name in ("oleSize", "customWorkbookViews", "pivotCaches", "smartTagPr", "smartTagTypes", "webPublishing", "fileRecoveryPr", "webPublishObjects", "extLst")}
            index = next((i for i, child in enumerate(book) if child.tag in following), len(book))
            book.insert(index, calc)
        calc.set("fullCalcOnLoad", "1"); calc.set("forceFullCalc", "1"); calc.set("calcMode", "auto")
        # Invalidate all cached formula results while keeping every formula intact.
        changes = {files[sheet]: xml(root), "xl/workbook.xml": xml(book)}
        if format_changed: changes["xl/styles.xml"] = xml(styles)
        for path in files.values():
            current = root if path == files[sheet] else ET.fromstring(z.read(path))
            changed = path == files[sheet]
            for c in current.findall(".//" + Q("c")):
                if c.find(Q("f")) is not None:
                    v = c.find(Q("v"))
                    if v is not None: c.remove(v); changed = True
            if changed: changes[path] = xml(current)
        return pack(z, changes)


def roles(raw: bytes) -> dict:
    """Exact workbook keys; no fuzzy matching or invented associations."""
    result: dict[str, dict] = {}
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z); strings = shared_strings(z)
        for kind, (wanted, col) in MATRIX_SHEETS.items():
            try: name = resolve_sheet(files, wanted)
            except LayoutError: continue
            root = ET.fromstring(z.read(files[name]))
            for row in root.findall(".//" + Q("row")):
                n = int(row.get("r"))
                if n < 2: continue
                c = row.find(Q("c") + "[@r='" + col + str(n) + "']")
                cargo = cell_text(c, strings).strip() if c is not None else ""
                if cargo and len(cargo) < 160:
                    result.setdefault(cargo, {}).setdefault(kind, []).append(n)
    return result


# Equivalencias documentadas entre las DOS matrices de la plantilla de GALANT.
# Sólo se aplica al resumen de condiciones, nunca a la matriz de peligros.
# No se equipara IMPERMEABILIZADOR con MEMBRANA ASFALTICA: podría usar otro sistema.
_IRL_SUMMARY_ALIASES = {
    "TECHADOR": "TECHUMBRE",
    "OPERARIO DE HORMIGON": "OPERARIO DE HORMIGON",
    "ALUMINERO": "ALUMINIOS",
    "OPERARIO DE URBANIZACION": "URBANIZACION",
    "ESTRUCTURERO METALICO": "ESTRUCTURAS METALICAS",
    "HOJALATERO": "HOJALATERIA",
    "ALBANIL": "ALBANILERIA",
    "INSTALADOR DE EIFS": "INS EIFS",
    "INSTALADOR DE PANDERETAS / VIBRADOS": "VIBRADOS (PANDERETAS)",
    "MUEBLISTA": "INST DE MUEBLES",
    "PAISAJISTA": "PAISAJISMO",
    "OPERARIO DE OBRA GRUESA": "OBRA GRUESA",
}


def _irl_role_key(value: str) -> str:
    plain = unicodedata.normalize("NFD", str(value or "").upper())
    return re.sub(r"\s+", " ", "".join(c for c in plain if not unicodedata.combining(c))).strip()


def bind_irl_summary_lookup(z: ZipFile, files: dict, target: ET.Element, role: str) -> bool:
    """Repara referencias VLOOKUP rotas en la COPIA desechable del Excel.

    Las cabeceras del IRL y de sus páginas de continuación quedan unidas a las
    cuatro celdas exactas del puesto en Matriz IRL Optimizada. Las filas de
    peligros siguen dependiendo exclusivamente de MATRIZ IRL y se verifican
    contra el PDF generado; nunca se simula un cálculo exitoso.
    """
    columns = {"A23": "B", "A25": "C", "A28": "D", "A31": "E"}
    summary_cells = {
        coord: target.find(".//" + Q("c") + "[@r='" + coord + "']")
        for coord in columns
    }
    lookup_present = any(
        cell is not None and (formula := cell.find(Q("f"))) is not None
        and ("VLOOKUP(" in (formula.text or "").upper() or "#REF!" in (formula.text or "").upper())
        for cell in summary_cells.values()
    )
    if not lookup_present:
        return False

    source_name = resolve_sheet(files, "Matriz IRL Optimizada")
    source = ET.fromstring(z.read(files[source_name]))
    strings = shared_strings(z)
    key = _irl_role_key(role)
    target_key = _IRL_SUMMARY_ALIASES.get(key, key)
    matches = []
    for row in source.findall(".//" + Q("row")):
        number = int(row.get("r", "0"))
        if number < 2:
            continue
        cell = row.find(Q("c") + "[@r='A" + str(number) + "']")
        if cell is not None and _irl_role_key(cell_text(cell, strings)) == target_key:
            matches.append((number, row))

    if len(matches) != 1:
        raise LayoutError(
            "El cargo " + (role or "sin seleccionar") +
            " no tiene una correspondencia única y verificada en "
            "'Matriz IRL Optimizada'. Revisa las condiciones del puesto y "
            "agrega una fila para el cargo exacto antes de emitir el IRL."
        )
    row_no, record = matches[0]
    for coordinate, column in columns.items():
        source_cell = record.find(Q("c") + "[@r='" + column + str(row_no) + "']")
        raw_value = cell_text(source_cell, strings).strip() if source_cell is not None else ""
        if not raw_value or raw_value in ERRORS:
            raise LayoutError(
                "El cargo " + role + " no tiene completas las condiciones de "
                "trabajo del IRL: Matriz IRL Optimizada!" + column + str(row_no)
            )
        cell = summary_cells[coordinate]
        if cell is not None and cell.find(Q("f")) is None:
            old = cell_text(cell, strings).strip()
            if old and old not in {"REVISAR CARGO EN MATRIZ", "#N/A", "#REF!"}:
                raise LayoutError(
                    "La cabecera IRL!" + coordinate +
                    " contiene texto fijo; revisa el formato antes de recalcular."
                )
        cell = ensure_cell(target, coordinate)
        for child in list(cell):
            cell.remove(child)
        cell.attrib.pop("t", None)
        ET.SubElement(cell, Q("f")).text = (
            "'Matriz IRL Optimizada'!$" + column + "$" + str(row_no)
        )
    return True


def fill_workbook(raw: bytes, data: dict, code: str) -> bytes:
    if code not in DOC_SHEETS: raise LayoutError("Documento desconocido")
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z); name = resolve_sheet(files, "Datos Contrato")
        root = ET.fromstring(z.read(files[name]))
        for coordinate, field in SOURCE_FIELDS.items():
            # Salary-in-words stays a live Excel formula when the master has one.
            cell = ensure_cell(root, coordinate)
            if coordinate == "C33" and cell.find(Q("f")) is not None: continue
            typed_input(root, coordinate, field, data)
        changes = {}
        target_name = resolve_sheet(files, DOC_SHEETS[code]); target = ET.fromstring(z.read(files[target_name]))
        if code == 'extension_addendum':
            try:
                new_end = date.fromisoformat(get_data(data, 'contract.new_end'))
                old_end = date.fromisoformat(get_data(data, 'contract.end'))
                if new_end <= old_end: raise ValueError()
            except ValueError: raise LayoutError('La prórroga debe ser posterior al término del contrato') from None
            set_numeric(target, 'M4', (new_end - date(1899, 12, 30)).days)
        if code == 'sworn_declaration':
            if get_data(data, 'worker.name'): raise LayoutError('La declaración sin trabajadores no admite un trabajador asignado')
            period = get_data(data, 'extra.declaration_period')
            try:
                if not re.fullmatch(r'\d{4}-\d{2}', period): raise ValueError()
                period_date = date.fromisoformat(period + '-01')
            except ValueError: raise LayoutError('Indica el período real de la declaración (AAAA-MM)') from None
            if not get_data(data, 'extra.principal_company'): raise LayoutError('Falta la empresa mandante real')
            set_numeric(root, 'C45', (period_date - date(1899, 12, 30)).days)
            if 'GALANT Datos' not in files: raise LayoutError('Importa la revisión con vínculos de declaración corregidos')
        if 'GALANT Datos' in files:
            context = ET.fromstring(z.read(files['GALANT Datos']))
            set_text(context, 'B2', get_data(data, 'extra.principal_company'))
            set_text(context, 'B4', get_data(data, 'extra.representative_nationality'))
            changes[files['GALANT Datos']] = xml(context)
        if code == 'induction': protect_induction_evaluation_header(target, shared_strings(z))
        if code == 'ppe_delivery':
            for index, amount in enumerate(delivery_quantities(get_data(data, 'event.epp_items')), 12):
                set_text(target, 'D' + str(index), str(amount) if amount else '')
        if code == "irl":
            bind_irl_summary_lookup(z, files, target, get_data(data, "role"))
        # Every supplied context is written including blanks, so examples cannot leak.
        changes.update({files[name]: xml(root), files[target_name]: xml(target)})
        return pack(z, changes)


def delivery_quantities(text: str) -> list[int]:
    """Usa el mismo catálogo que el formulario y las reglas del backend."""
    from .javiera_epp import EppInputError, epp_quantities
    try:
        return epp_quantities(text)
    except EppInputError as exc:
        raise LayoutError(str(exc)) from None



def clean_master(raw: bytes) -> bytes:
    """Empty example inputs and cached document results; keep matrices and formulas.

    Unused shared strings are removed too, so a downloaded clean master does not
    carry an invisible copy of the old cached names. The original is retained
    separately for audit and sample-leak checks.
    """
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z); changes = {}
        shared = ET.fromstring(z.read('xl/sharedStrings.xml')) if 'xl/sharedStrings.xml' in z.namelist() else None
        string_nodes = list(shared) if shared is not None else []
        for name,path in files.items():
            root = ET.fromstring(z.read(path))
            if name == 'Datos Contrato':
                for ref in [*SOURCE_FIELDS,'C45']:
                    cell = ensure_cell(root,ref)
                    if cell.find(Q('f')) is None:set_text(root,ref,'')
                links = root.find(Q('hyperlinks')); removed = set()
                if links is not None:
                    for link in list(links):
                        if link.get('ref') in SOURCE_FIELDS:
                            removed.add(link.get('{'+R+'}id'));links.remove(link)
                    if not len(links):root.remove(links)
                rel_path = posixpath.dirname(path)+'/_rels/'+posixpath.basename(path)+'.rels'
                if removed and rel_path in z.namelist():
                    relationships = ET.fromstring(z.read(rel_path))
                    for rel in list(relationships):
                        if rel.get('Id') in removed:relationships.remove(rel)
                    changes[rel_path] = xml(relationships)
            if name.strip() == DOC_SHEETS['extension_addendum']:set_text(root,'M4','')
            if name.strip() == DOC_SHEETS['ppe_delivery']:
                for row in range(12,20):set_text(root,'D'+str(row),'')
            for cell in root.findall('.//'+Q('c')):
                if cell.find(Q('f')) is not None:
                    value = cell.find(Q('v'))
                    if value is not None:cell.remove(value)
                elif cell.get('t') == 's':
                    value = cell.find(Q('v'))
                    if value is not None:
                        try: node=string_nodes[int(value.text)]
                        except (ValueError,TypeError,IndexError):raise LayoutError('Referencia de texto compartido inválida') from None
                        cell.remove(value);cell.set('t','inlineStr');inline=ET.SubElement(cell,Q('is'))
                        for child in node:inline.append(deepcopy(child))
            changes[path]=xml(root)
        if shared is not None:changes['xl/sharedStrings.xml']=xml(ET.Element(Q('sst'),{'count':'0','uniqueCount':'0'}))
        result = pack(z,changes)
    return edit_workbook(result,'Datos Contrato',[])


def repair_master(raw: bytes) -> tuple[bytes, list[str]]:
    """Proven defects only; original remains an immutable, separately stored revision."""
    notes = []; changes = {}
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z); strings = shared_strings(z)
        try:
            name = resolve_sheet(files, "IRL"); root = ET.fromstring(z.read(files[name]))
            for col in "ABCD":
                target = root.find(".//" + Q("c") + "[@r='" + col + "61']")
                source = root.find(".//" + Q("c") + "[@r='" + col + "63']")
                f = source.find(Q("f")) if source is not None else None
                if target is not None and target.find(Q("f")) is None and f is not None and ",0)+9" in (f.text or ""):
                    for child in list(target): target.remove(child)
                    target.attrib.pop("t", None)
                    ET.SubElement(target, Q("f")).text = f.text.replace(",0)+9", ",0)+8")
                    notes.append("IRL!" + col + "61: vínculo al registro 9 del cargo; se conserva el registro 10 en " + col + "63")
            changes[files[name]] = xml(root)
        except LayoutError: pass
        # Contract literals hard-code the example city even when Datos Contrato
        # changes. Replace only that locality inside formula string literals.
        data_root = ET.fromstring(z.read(files[resolve_sheet(files, "Datos Contrato")]))
        c = data_root.find(".//" + Q("c") + "[@r='C12']")
        old_city = cell_text(c, strings) if c is not None else ""
        if len(old_city.strip()) >= 6:
            plain_city = "".join(c for c in unicodedata.normalize("NFD", old_city) if not unicodedata.combining(c))
            accents = {"A": "[AÁÀÄÂ]", "E": "[EÉÈËÊ]", "I": "[IÍÌÏÎ]", "O": "[OÓÒÖÔ]", "U": "[UÚÙÜÛ]", "N": "[NÑ]"}
            city_pattern = "".join(accents.get(c.upper(), re.escape(c)) for c in plain_city)
            for code in ("labor_contract", "transfer_addendum", "extension_addendum"):
                try: sheet = resolve_sheet(files, DOC_SHEETS[code])
                except LayoutError: continue
                target_root = ET.fromstring(z.read(files[sheet])); changed = False
                for c in target_root.findall(".//" + Q("c")):
                    f = c.find(Q("f"))
                    if f is None: continue
                    def replace_literal(match):
                        text = match.group()[1:-1]
                        parts = re.split(city_pattern, text, flags=re.I)
                        if len(parts) == 1: return match.group()
                        return "&'Datos Contrato'!C12&".join('"' + p + '"' for p in parts)
                    updated = re.sub(r'"(?:[^"]|"")*"', replace_literal, f.text or "")
                    if updated != f.text:
                        f.text = updated; changed = True; notes.append(sheet + "!" + c.get("r") + ": ciudad vinculada a Datos Contrato")
                if changed: changes[files[sheet]] = xml(target_root)
        # The original declaration hard-codes the principal and takes the
        # representative nationality from the worker. Bind these explicit inputs.
        try:
            decl_name = resolve_sheet(files, DOC_SHEETS['sworn_declaration'])
            declaration = ET.fromstring(z.read(files[decl_name])); changed = False
            for c in declaration.findall('.//' + Q('c')):
                f = c.find(Q('f'))
                if f is None: continue
                updated = f.text or ''
                if c.get('r') == 'A4':
                    updated = re.sub(r"'Datos Contrato'!\$?C\$?19", "'GALANT Datos'!$B$4", updated)
                if c.get('r') == 'A5':
                    def replace_principal(match):
                        literal = match.group()[1:-1]; parts = MANDANTE_PATTERN.split(literal)
                        return "&'GALANT Datos'!$B$2&".join('"' + p + '"' for p in parts)
                    updated = re.sub(r'"(?:[^"]|"")*"', replace_principal, updated)
                if updated != f.text:
                    f.text = updated; changed = True; notes.append(decl_name + '!' + c.get('r') + ': antecedente real de empresa')
            if changed:
                changes[files[decl_name]] = xml(declaration)
                if 'GALANT Datos' not in files:
                    book = ET.fromstring(z.read('xl/workbook.xml')); sheets = book.find(Q('sheets'))
                    sid = max(int(s.get('sheetId')) for s in sheets) + 1; rid = 'rIdGalantContext'
                    ET.SubElement(sheets, Q('sheet'), {'name':'GALANT Datos','sheetId':str(sid),'state':'hidden','{'+R+'}id':rid})
                    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
                    ET.SubElement(rels, '{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',
                        {'Id':rid,'Type':R+'/worksheet','Target':'worksheets/galant_context.xml'})
                    types = ET.fromstring(z.read('[Content_Types].xml'))
                    ET.SubElement(types, '{http://schemas.openxmlformats.org/package/2006/content-types}Override',
                        {'PartName':'/xl/worksheets/galant_context.xml','ContentType':'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'})
                    context = ET.Element(Q('worksheet')); ET.SubElement(context,Q('sheetData'))
                    for cell, text in {'A1':'Antecedentes del expediente','A2':'Empresa mandante','A4':'Nacionalidad del representante'}.items(): set_text(context,cell,text)
                    changes.update({'xl/workbook.xml':xml(book),'xl/_rels/workbook.xml.rels':xml(rels),
                        '[Content_Types].xml':xml(types),'xl/worksheets/galant_context.xml':xml(context)})
        except LayoutError: pass
        # Additional template literals also contain example cities/worksites.
        # Turn only exact original fact matches into native cell references.
        source_values = {c.get('r'):cell_text(c,strings) for c in data_root.findall('.//'+Q('c'))}
        candidates = []
        for coordinate in ('C12', 'D30'):
            value = source_values.get(coordinate,'').strip()
            if len(value) < 6: continue
            plain = ''.join(c for c in unicodedata.normalize('NFD', value) if not unicodedata.combining(c))
            chars = {'A':'[AÁÀÄÂ]','E':'[EÉÈËÊ]','I':'[IÍÌÏÎ]','O':'[OÓÒÖÔ]','U':'[UÚÙÜÛ]','N':'[NÑ]'}
            candidates.append((''.join(chars.get(c.upper(),re.escape(c)) for c in plain), "'Datos Contrato'!"+coordinate))
        for wanted in DOC_SHEETS.values():
            try: name = resolve_sheet(files,wanted)
            except LayoutError: continue
            path = files[name]; target = ET.fromstring(changes.get(path,z.read(path))); changed = False
            for cell in target.findall('.//'+Q('c')):
                formula = cell.find(Q('f')); text = formula.text if formula is not None else cell_text(cell,strings)
                if not text: continue
                expression = text if formula is not None else '"'+text.replace('"','""')+'"'
                for pattern, reference in candidates:
                    def replace_fact(match):
                        parts = re.split(pattern, match.group()[1:-1], flags=re.I)
                        return ('&'+reference+'&').join('"'+p+'"' for p in parts)
                    expression = re.sub(r'"(?:[^"]|"")*"',replace_fact,expression)
                if name.strip() == 'INDUCCION PREVENCION':
                    def replace_mandante(match):
                        parts = MANDANTE_PATTERN.split(match.group()[1:-1])
                        return "&'GALANT Datos'!$B$2&".join('"'+p+'"' for p in parts)
                    expression = re.sub(r'"(?:[^"]|"")*"',replace_mandante,expression)
                original_expression = text if formula is not None else '"'+text.replace('"','""')+'"'
                if expression != original_expression:
                    if formula is None:
                        for child in list(cell):cell.remove(child)
                        cell.attrib.pop('t',None); formula = ET.SubElement(cell,Q('f'))
                    formula.text = expression; changed = True
                    notes.append(name+'!'+cell.get('r')+': dato fijo vinculado al expediente')
            if name.strip() == 'INDUCCION PREVENCION' and protect_induction_evaluation_header(target, strings):
                changed = True; notes.append(name+': salto antes de fila 468 para conservar el encabezado completo de la evaluación')
            if changed:changes[path]=xml(target)
        return pack(z, changes), notes


def matrix_records(raw: bytes, role: str, kind: str) -> list[dict]:
    wanted, col = MATRIX_SHEETS[kind]
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z); name = resolve_sheet(files, wanted); strings = shared_strings(z)
        root = ET.fromstring(z.read(files[name])); rows = []
        for row in root.findall(".//" + Q("row")):
            if int(row.get("r")) < 2: continue
            values = {re.match(r"[A-Z]+", c.get("r")).group(): cell_text(c, strings) for c in row.findall(Q("c"))}
            if values.get(col, "").strip() == role: rows.append({"row": int(row.get("r")), "values": values})
        if not rows: raise LayoutError("No existe información " + kind + " para la clave exacta del cargo seleccionado")
        return rows


# Localizaciones reales de los 12 primeros riesgos en el IRL de GALANT.
# Las filas pares 40, 42, 44, 46, etc., contienen encabezados y NUNCA
# deben ser sobrescritas por actividades ni medidas preventivas.
IRL_PRINT_RISK_ROWS = (39, 41, 43, 45, 47, 49, 52, 54, 56, 63, 65, 67)


def irl_risk_print_rows(root: ET.Element) -> tuple[tuple[int, ...], bool]:
    """Identifica la maqueta IRL real sin adivinar posiciones de filas.

    Se conserva compatibilidad con las plantillas sintéticas antiguas en que
    sólo se usa A45. En una plantilla real parcialmente alterada se bloquea
    en lugar de imprimir la matriz desfasada.
    """
    detected: list[int] = []
    for cell in root.findall(".//" + Q("c")):
        address = cell.get("r", "")
        match = re.fullmatch(r"A([1-9]\d*)", address)
        formula = cell.find(Q("f"))
        if (match and formula is not None and
                "MATRIZ IRL" in (formula.text or "").upper() and
                35 <= int(match[1]) <= 70):
            detected.append(int(match[1]))
    if sorted(set(detected)) == list(IRL_PRINT_RISK_ROWS):
        return IRL_PRINT_RISK_ROWS, True
    if detected == [45]:
        # Fixtures legados: sólo A45 enlaza a la matriz; no tienen la maqueta
        # completa del archivo original. Nunca aplicar este camino al libro real.
        return tuple(45 + 2 * i for i in range(12)), False
    if detected:
        raise LayoutError(
            "La plantilla IRL tiene filas de riesgos incompletas o desordenadas "
            f"({sorted(set(detected))}). Corrige la distribución original antes de imprimir."
        )
    return tuple(45 + 2 * i for i in range(12)), False


def put_irl_risks(root: ET.Element, matrix: list[dict], rows: tuple[int, ...]) -> None:
    """Vincula cada campo a su FILA EXACTA en MATRIZ IRL, incluso entre cargos."""
    for index, target_row in enumerate(rows):
        record = matrix[index] if index < len(matrix) else None
        for dest_col, src_col in zip("ABCD", "CDEF"):
            address = dest_col + str(target_row)
            if record is None:
                set_text(root, address, "")
                continue
            source_row = record["row"]
            source_role = (
                "IF('MATRIZ IRL'!$B$" + str(source_row) +
                "='Datos Contrato'!$C$29,"
                "'MATRIZ IRL'!$" + src_col + "$" + str(source_row) + ', "")'
            )
            cell = ensure_cell(root, address)
            for child in list(cell):
                cell.remove(child)
            cell.attrib.pop("t", None)
            ET.SubElement(cell, Q("f")).text = source_role


def irl_continuations(raw: bytes, role: str) -> tuple[bytes, list[str]]:
    """Paginar las 13+ filas de riesgos sobre la disposición ORIGINAL del IRL.

    La primera hoja imprime riesgos 1-12. Las continuaciones imprimen sólo
    riesgos restantes, con membretes, bordes y encabezados sin sobrescribir.
    Todos los campos siguen siendo fórmulas que referencian la matriz aprobada.
    """
    records = matrix_records(raw, role, "IRL")
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z)
        main_name = resolve_sheet(files, "IRL")
        source_path = files[main_name]
        original = ET.fromstring(z.read(source_path))
        rows, actual_template = irl_risk_print_rows(original)

        # La plantilla real se repara siempre, también con 1-12 riesgos.
        if not actual_template and len(records) <= 12:
            return raw, []
        first = deepcopy(original)
        put_irl_risks(first, records[:12], rows)
        changes = {source_path: xml(first)}
        if len(records) <= 12:
            return pack(z, changes), []

        book = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        types = ET.fromstring(z.read("[Content_Types].xml"))
        sheets_node = book.find(Q("sheets"))
        definitions = book.find(Q("definedNames"))
        if definitions is None:
            definitions = ET.SubElement(book, Q("definedNames"))
        max_id = max(int(sheet.get("sheetId")) for sheet in sheets_node)
        names: list[str] = []
        rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        type_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
        for chunk, offset in enumerate(range(12, len(records), 12), 1):
            name = "IRL continuación " + str(chunk)
            names.append(name)
            path = "xl/worksheets/galant_cont_" + str(chunk) + ".xml"
            count = min(12, len(records) - offset)
            page = deepcopy(first)
            put_irl_risks(page, records[offset:offset + count], rows)
            if actual_template:
                # A37 es el título, D40 es un ENCABEZADO ORIGINAL y no se toca.
                set_text(page, "A37", "2 - RIESGOS Y MEDIDAS PREVENTIVAS · CONTINUACIÓN " + str(chunk))
                first_print_row, last_print_row = 34, rows[count - 1]
            else:
                # Compatibilidad con fixtures históricos que sólo definen A45.
                first_print_row, last_print_row = 39, 44 + 2 * count
            changes[path] = xml(page)

            rid = "rIdGalantCont" + str(chunk)
            ET.SubElement(sheets_node, Q("sheet"), {
                "name": name, "sheetId": str(max_id + chunk),
                "state": "visible", "{" + R + "}id": rid
            })
            ET.SubElement(rels, "{" + rel_ns + "}Relationship", {
                "Id": rid, "Type": R + "/worksheet",
                "Target": "worksheets/galant_cont_" + str(chunk) + ".xml"
            })
            ET.SubElement(types, "{" + type_ns + "}Override", {
                "PartName": "/" + path,
                "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
            })
            ET.SubElement(definitions, Q("definedName"), {
                "name": "_xlnm.Print_Area", "localSheetId": str(len(files) + chunk - 1)
            }).text = ("'" + name + "'!$A$" + str(first_print_row) +
                      ":$D$" + str(last_print_row))
            rel_path = (posixpath.dirname(source_path) + "/_rels/" +
                        posixpath.basename(source_path) + ".rels")
            if rel_path in z.namelist():
                changes["xl/worksheets/_rels/" + posixpath.basename(path) + ".rels"] = z.read(rel_path)

        changes.update({
            "xl/workbook.xml": xml(book),
            "xl/_rels/workbook.xml.rels": xml(rels),
            "[Content_Types].xml": xml(types)
        })
        return pack(z, changes), names


def validate_matrix_results(calculated: bytes, role: str, code: str, continuations: list[str]) -> None:
    if code not in {"irl", "pts", "pts_receipt"}: return
    kind = "IRL" if code == "irl" else "PTS"; records = matrix_records(calculated, role, kind)
    first = records
    # PTS is one logical record. Repeated keys must resolve to identical content.
    if kind == "PTS": first = first[:1]
    columns = list("CDEF") if kind == "IRL" else [chr(i) for i in range(ord("D"), ord("T") + 1)]
    expected = [[r['values'].get(c, '') for c in columns] for r in first]
    missing = [r['row'] for r, values in zip(first, expected) if any(not str(v).strip() for v in values)]
    if missing:
        raise LayoutError('Matriz '+kind+' pendiente para '+role+': faltan antecedentes preventivos en filas '+', '.join(map(str,missing)))
    normalize = lambda text: " ".join(str(text).split())
    remaining = records[len(first):] if kind == 'PTS' else []
    if remaining:
        if len(remaining) % len(first) or any(
            [normalize(r['values'].get(c, '')) for c in columns] != [normalize(v) for v in expected[i % len(first)]]
            for i, r in enumerate(remaining)):
            raise LayoutError("La clave del cargo tiene matrices duplicadas con contenido diferente; revisión obligatoria")
    if code == "pts_receipt": return
    with ZipFile(io.BytesIO(calculated)) as z:
        files = sheet_files(z); strings = shared_strings(z)
        if code == "pts":
            root = ET.fromstring(z.read(files[resolve_sheet(files, "PTS.")]))
            for coordinate, value in zip(PTS_CELLS, expected[0]):
                c = root.find(".//" + Q("c") + "[@r='" + coordinate + "']")
                if c is None or normalize(cell_text(c, strings)) != normalize(value):
                    raise LayoutError("El PTS no coincide con la matriz Excel en " + coordinate)
        else:
            names = [resolve_sheet(files, "IRL"), *continuations]
            original_root = ET.fromstring(z.read(files[names[0]]))
            print_rows, actual_template = irl_risk_print_rows(original_root)
            for i, values in enumerate(expected):
                if i // 12 >= len(names):
                    raise LayoutError("Faltan páginas Excel para los riesgos del cargo")
                root = ET.fromstring(z.read(files[names[i // 12]]))
                row = print_rows[i % 12]
                for col, value in zip("ABCD", values):
                    cell = root.find(".//" + Q("c") + "[@r='" + col + str(row) + "']")
                    if cell is None or normalize(cell_text(cell, strings)) != normalize(value):
                        raise LayoutError(
                            "El IRL no coincide con la matriz exacta del cargo: " +
                            names[i // 12] + "!" + col + str(row)
                        )
            if actual_template:
                for j, name in enumerate(names[1:], 1):
                    count = max(0, min(12, len(expected) - 12 * j))
                    root = ET.fromstring(z.read(files[name]))
                    for row in print_rows[count:]:
                        for col in "ABCD":
                            cell = root.find(".//" + Q("c") + "[@r='" + col + str(row) + "']")
                            if cell is not None and cell_text(cell, strings).strip():
                                raise LayoutError(
                                    "El IRL contiene datos residuales en una página de continuación: " +
                                    name + "!" + col + str(row)
                                )


def run_calc(raw: bytes, folder: Path, timeout: int = 70) -> bytes:
    from .config import settings
    if settings().javiera_calc_url:
        return base64.b64decode(warm_convert(raw, [])['calculated'], validate=True)
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    if not binary: raise LayoutError("Instala LibreOffice Calc para recalcular el Excel")
    # Calc can otherwise trust pre-existing Excel cache values even after inputs
    # changed. Removing every formula cache forces import-time calculation.
    raw = edit_workbook(raw, "Datos Contrato", [])
    source = folder / "source.xlsx"; source.write_bytes(raw); source.chmod(0o600)
    out = folder / "calculated"; out.mkdir()
    command = [binary, "-env:UserInstallation=" + (folder / "profile").as_uri(),
               "--headless", "--convert-to", "xlsx:Calc MS Excel 2007 XML", "--outdir", str(out), str(source)]
    try:
        p = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise LayoutError("El recálculo Excel superó el tiempo permitido") from None
    target = out / "source.xlsx"
    if p.returncode or not target.is_file(): raise LayoutError("Calc no pudo recalcular el libro Excel")
    return target.read_bytes()


def warm_convert(raw: bytes, sheets: list[str]) -> dict:
    from .config import settings
    config = settings()
    if len(config.javiera_calc_secret) < 32: raise LayoutError("Configura el secreto del motor Calc privado")
    endpoint = urlsplit(config.javiera_calc_url)
    if endpoint.scheme not in {'http','https'} or endpoint.username or endpoint.password:
        raise LayoutError('La dirección del motor Calc privado no es válida')
    internal = endpoint.hostname in {'javiera-calc','localhost','127.0.0.1','::1'}
    if not internal and endpoint.scheme != 'https':raise LayoutError('Utiliza el motor privado de Docker o una dirección HTTPS')
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    # Only loopback and our internal Docker service bypass HTTP proxy routing.
    # Remote HTTPS keeps the environment's proxy and certificate verification.
    opener = build_opener(ProxyHandler({}) if internal else ProxyHandler(),NoRedirect())
    request = Request(config.javiera_calc_url.rstrip('/') + '/convert', method='POST',
        data=json.dumps({'xlsx': base64.b64encode(raw).decode(), 'sheets': sheets}).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + config.javiera_calc_secret})
    try:
        with opener.open(request, timeout=90) as response:
            result = json.loads(response.read(45 * 1024 * 1024))
        if 'calculated' not in result or sheets and 'pdf' not in result: raise ValueError()
        return result
    except (URLError, ValueError, TimeoutError, OSError):
        raise LayoutError("El motor Calc privado no pudo completar la conversión; revisa su disponibilidad") from None


def validate_calculated(raw: bytes, selected: str | list[str]) -> dict:
    """Trace actual cell dependencies; unrelated control-sheet warnings do not block a document."""
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z)
        selected = [resolve_sheet(files,name) for name in ([selected] if isinstance(selected,str) else selected)]
        strings = shared_strings(z)
        cells = {name: {c.get("r"): c for c in ET.fromstring(z.read(path)).findall(".//" + Q("c"))}
                 for name, path in files.items()}
        def point(ref):
            match = re.fullmatch(r"([A-Z]+)(\d+)", ref.replace("$", ""))
            col = 0
            for letter in match.group(1): col = col * 26 + ord(letter) - 64
            return col, int(match.group(2))
        def references(name, first, last):
            if name not in cells: return []
            if last is None: return [(name, first.replace("$", ""))]
            a, b = point(first), point(last)
            return [(name, ref) for ref in cells[name] if
                    a[0] <= point(ref)[0] <= b[0] and a[1] <= point(ref)[1] <= b[1]]
        qualified = re.compile(r"(?:'([^']+)'|([A-Za-z_][A-Za-z_0-9]*))!(\$?[A-Z]{1,3}\$?\d+)(?::(\$?[A-Z]{1,3}\$?\d+))?")
        local = re.compile(r"(?<![A-Za-z_0-9.])([A-Z]{1,3}\$?\d+)(?::(\$?[A-Z]{1,3}\$?\d+))?(?![A-Za-z_0-9.(])")
        queue = [(name, ref) for name in selected for ref in cells[name]]; visited = set(); errors = []; formulas = 0
        while queue:
            name, ref = queue.pop()
            if (name, ref) in visited: continue
            visited.add((name, ref)); cell = cells.get(name, {}).get(ref)
            if cell is None: continue
            formula = cell.find(Q("f")); value = cell.find(Q("v")); text = cell_text(cell, strings)
            if cell.get("t") == "e" or text in ERRORS: errors.append(name + "!" + ref + ": " + text)
            if formula is None: continue
            formulas += 1
            if value is None: errors.append(name + "!" + ref + ": fórmula sin recalcular")
            expression = re.sub(r'"(?:[^"]|"")*"', '""', formula.text or "")
            for match in qualified.finditer(expression):
                queue.extend(references(match.group(1) or match.group(2), match.group(3), match.group(4)))
            expression = qualified.sub("", expression)
            for match in local.finditer(expression): queue.extend(references(name, match.group(1), match.group(2)))
        if errors: raise LayoutError("Errores Excel: " + "; ".join(errors[:12]))
        return {"sheets_calculated": sorted({name for name, _ in visited}), "formulas_checked": formulas, "errors": []}


def select_print_sheet(raw: bytes, selected: str | list[str]) -> bytes:
    """Formula calculation already happened. Only sheet visibility/print scope changes.

    Dependencies remain in the workbook; there is no formula-to-text conversion.
    Calc PDF export honors hidden sheets (verified by the integration test).
    """
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z)
        names = {resolve_sheet(files, n) for n in ([selected] if isinstance(selected, str) else selected)}
        book = ET.fromstring(z.read("xl/workbook.xml")); index = 0; indices = set()
        for i, sheet in enumerate(book.findall(".//" + Q("sheet"))):
            sheet.set("state", "visible" if sheet.get("name") in names else "hidden")
            if sheet.get("name") in names:
                if not indices: index = i
                indices.add(str(i))
        for view in book.findall(".//" + Q("workbookView")):
            view.set("activeTab", str(index)); view.set("firstSheet", str(index))
        # Remove only other print areas so conversion cannot include helper sheets.
        defined = book.find(Q("definedNames"))
        if defined is not None:
            for node in list(defined):
                if node.get("name") == "_xlnm.Print_Area" and node.get("localSheetId") not in indices:
                    defined.remove(node)
        return pack(z, {"xl/workbook.xml": xml(book)})


def convert_pdf(raw: bytes, sheet: str, *, preview: bool = False,
                extra_sheets: list[str] | None = None, role: str = "", code: str = "") -> tuple[bytes, dict]:
    started = time.perf_counter()
    if not CONVERSIONS.acquire(timeout=15): raise LayoutError("El motor está ocupado; vuelve a intentarlo")
    try:
        with tempfile.TemporaryDirectory(prefix="galant20-") as tmp:
            from .config import settings
            folder = Path(tmp)
            selected_sheets = [sheet, *(extra_sheets or [])]
            if settings().javiera_calc_url:
                result = warm_convert(raw, selected_sheets); calculated = base64.b64decode(result['calculated'], validate=True)
                validation = validate_calculated(calculated, selected_sheets)
                pdf = base64.b64decode(result['pdf'], validate=True)
            else:
                calculated = run_calc(raw, folder)
                validation = validate_calculated(calculated, selected_sheets)
                scoped = select_print_sheet(calculated, selected_sheets)
                source = folder / "document.xlsx"; source.write_bytes(scoped)
                binary = shutil.which("libreoffice") or shutil.which("soffice")
                try:
                    p = subprocess.run([binary, "-env:UserInstallation=" + (folder / "profile").as_uri(),
                        "--headless", "--convert-to", "pdf:calc_pdf_Export", "--outdir", str(folder), str(source)],
                        capture_output=True, timeout=70, check=False)
                except subprocess.TimeoutExpired:
                    raise LayoutError("La conversión PDF superó el tiempo permitido") from None
                pdf_path = folder / "document.pdf"
                if p.returncode or not pdf_path.is_file(): raise LayoutError("No se pudo convertir la hoja seleccionada")
                pdf = pdf_path.read_bytes()
            validate_matrix_results(calculated, role, code, extra_sheets or [])
            validation['continuation_sheets'] = extra_sheets or []
            validation['matrix_verified'] = code in {'irl', 'pts', 'pts_receipt'}
            with fitz.open(stream=pdf, filetype="pdf") as doc:
                if not 1 <= len(doc) <= 120: raise LayoutError("Cantidad de páginas fuera del límite")
                empty = [i + 1 for i, page in enumerate(doc) if not page.get_text().strip() and not page.get_images()]
                if empty: raise LayoutError("Páginas sin contenido: " + str(empty))
                # Reject content extending outside the original paper; never normalize to A4.
                clipped = []
                for i, page in enumerate(doc):
                    for b in page.get_text("blocks"):
                        if b[0] < -1 or b[1] < -1 or b[2] > page.rect.width + 1 or b[3] > page.rect.height + 1:
                            clipped.append(i + 1)
                if clipped: raise LayoutError("Contenido recortado en páginas " + str(sorted(set(clipped))))
                if code == 'irl':
                    normalize = lambda value: re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',value).casefold())
                    printed_content = normalize(' '.join(page.get_text() for page in doc)); checked = 0
                    for record in matrix_records(calculated,role,'IRL'):
                        for column in 'CDEF':
                            value = record['values'].get(column,'')
                            if value and normalize(value) not in printed_content:
                                raise LayoutError('El PDF no reproduce íntegro el contenido preventivo de la matriz en '+column+str(record['row']))
                            checked += 1
                    validation['printed_matrix_fields'] = checked
                if preview:
                    for page in doc:
                        page.insert_text((12, 12), "BORRADOR - SIN FIRMA - REQUIERE REVISION", fontsize=7, color=(0.65, 0.15, 0.1))
                    pdf = doc.tobytes(garbage=4, deflate=True)
                validation.update({"pages": len(doc), "page_sizes": [[round(p.rect.width, 2), round(p.rect.height, 2)] for p in doc],
                    "images": sum(len(p.get_images()) for p in doc), "engine": "LibreOffice Calc",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
            return pdf, validation
    finally:
        CONVERSIONS.release()


def cached_pdf(raw: bytes, code: str, data: dict, org_id: str, cache: Path, preview: bool,
               reference: bytes | None = None) -> tuple[bytes, dict]:
    from .config import settings
    # Los documentos marcados en pantalla cambian el flujo de emisión, pero
    # no alteran el contenido ni las fórmulas del PDF de un mismo documento.
    # Excluir esa preferencia del hash evita recalcular Calc al cambiar la selección.
    printable_data = {k: v for k, v in data.items() if k != "requested_documents"}
    key = digest(json.dumps({"org": org_id, "workbook": digest(raw), "code": code,
        "data": printable_data, "preview": preview, 'reference':digest(reference or raw), "engine": "calc-v20.9-irl-print-map-" + ('uno' if settings().javiera_calc_url else 'cli')}, sort_keys=True, ensure_ascii=False).encode())
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        path = cache / (key + ".pdf"); meta = cache / (key + ".json")
        if path.is_file() and meta.is_file():
            report = json.loads(meta.read_text()); pdf = path.read_bytes()
            if report.get("sha256") == digest(pdf): return pdf, {**report, "cache_hit": True}
        filled = fill_workbook(raw, data, code)
        continuation_sheets = []
        if code == 'irl': filled, continuation_sheets = irl_continuations(filled, data.get('role', ''))
        pdf, report = convert_pdf(filled, DOC_SHEETS[code], preview=preview,
                                 extra_sheets=continuation_sheets, role=data.get('role', ''), code=code)
        with fitz.open(stream=pdf,filetype='pdf') as document:
            printed = ' '.join(' '.join(page.get_text().casefold().split()) for page in document)
        if 'no emitir:' in printed:raise LayoutError('El Excel solicita antecedentes pendientes; emisión bloqueada')
        employer = ' '.join(get_data(data,'employer.name').casefold().split())
        worker = ' '.join(get_data(data,'worker.name').casefold().split())
        if employer and employer not in printed:raise LayoutError('El PDF no contiene al empleador seleccionado')
        if worker and code not in {'sworn_declaration','pts'} and worker not in printed:
            raise LayoutError('El PDF no contiene al trabajador seleccionado')
        from .javiera_layout_api import source_leaks
        leaks = source_leaks(reference or raw, pdf, data)
        # Specialty words are part of the source matrix for the exact verified
        # role (e.g. carpintería). They are not sample identities in IRL/PTS.
        if code in {'irl','pts'}: leaks = [ref for ref in leaks if ref != 'C14']
        if leaks: raise LayoutError(
            "El PDF conserva datos del ejemplo en Datos Contrato!" +
            ", ".join(leaks) + ". Revisa las fórmulas o los valores fijos de la hoja imprimible.")
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        report.update({"sha256": digest(pdf), "cache_key": key, "cache_hit": False})
        for target, content in ((path, pdf), (meta, json.dumps(report).encode())):
            temp = target.with_suffix(target.suffix + ".tmp")
            temp.write_bytes(content); temp.chmod(0o600); temp.replace(target)
        return pdf, report
