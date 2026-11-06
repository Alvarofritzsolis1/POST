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
}

RESTRICTED_PARTS = ("vbaproject.bin", "externallinks/", "connections.xml", "oleobjects/", "activex/")
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
        if "/worksheets/" in value:
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
            set_text(target,"A24","Nacionalidad: "+get_data(data,"extra.worker_nationality"))
            set_text(target,"F24","Estado civil: "+get_data(data,"extra.worker_marital_status"))
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
            names = [
                "Casco de Seguridad", "Calzado de Seguridad", "Lentes de Seguridad",
                "Guantes de Cabritilla", "Protección Auditiva/Mascarilla",
                "Arnés de seguridad", "Delantal de cuero", "Guantes de soldador",
            ]
            imports = __import__("unicodedata")
            def basic(text):
                normalized = imports.normalize("NFD", text.strip().lower())
                return " ".join("".join(x for x in normalized if imports.category(x)!="Mn").split())
            declared = re.split(r"[,;\n]", get_data(data, "event.epp_items"))
            quantities = [0]*len(names)
            for item in declared:
                item = basic(item)
                if not item:
                    continue
                match = re.fullmatch(r"(\d{1,2})\s*[xX]?\s+(.+)", item)
                amount, description = (int(match.group(1)), match.group(2)) if match else (1, item)
                if amount < 1 or amount > 30:
                    raise LayoutError("Cantidad EPP fuera de rango")
                matches = [i for i, name in enumerate(names)
                           if (description in basic(name) or basic(name) in description)]
                if len(matches) != 1:
                    raise LayoutError("EPP ambiguo o no contemplado en matriz original: " + item)
                quantities[matches[0]] += amount
            if not sum(quantities):
                raise LayoutError("Debes identificar el EPP efectivamente entregado")
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
        calc = book.find(Q("calcPr"))
        if calc is not None:
            calc.set("fullCalcOnLoad", "0")
            calc.set("forceFullCalc", "0")
        replacement = {
            files[selected]: ET.tostring(target, encoding="UTF-8", xml_declaration=True),
            "xl/workbook.xml": ET.tostring(book, encoding="UTF-8", xml_declaration=True),
        }
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=5) as out:
            for info in z.infolist():
                if info.filename in replacement:
                    out.writestr(copy(info), replacement[info.filename])
                else:
                    out.writestr(copy(info), z.read(info.filename))
        return buffer.getvalue()



def normalize_pdf_a4(raw: bytes) -> bytes:
    """Imprimir sin cortes y entregar todas las páginas en A4.

    La declaración jurada del Excel original tiene trazos 5 pt fuera del
    MediaBox derecho; otros documentos usan Carta. Recupera esos trazos
    expandiendo el área fuente antes de ajustar proporcionalmente al A4.
    """
    source = fitz.open(stream=raw, filetype="pdf")
    output = fitz.open()
    try:
        for index in range(source.page_count):
            page = source[index]
            original = page.rect
            # PyMuPDF no extrae glifos que queden fuera del MediaBox vigente.
            # Ampliar provisionalmente para detectar el verdadero ancho/alto
            # del texto (y restaurar luego el tamaño mínimo que lo contiene).
            page.set_mediabox(fitz.Rect(0, 0, original.width + 250,
                                       original.height + 200))
            blocks = [b for b in page.get_text("blocks")
                      if len(b) >= 5 and (b[4].strip() if isinstance(b[4], str) else True)]
            xmin = min([0, *[b[0] for b in blocks]])
            ymin = min([0, *[b[1] for b in blocks]])
            xmax = max([original.width, *[b[2] for b in blocks]])
            ymax = max([original.height, *[b[3] for b in blocks]])
            if xmin < -1 or ymin < -1:
                raise LayoutError("Texto fuera del margen superior o izquierdo del Excel; revisa la maquetación")
            if xmax > original.width + 1 or ymax > original.height + 1:
                page.set_mediabox(fitz.Rect(0, 0, xmax + 8, ymax + 8))
            else:
                page.set_mediabox(fitz.Rect(0, 0, original.width, original.height))
            target = output.new_page(width=595, height=842)
            target.show_pdf_page(fitz.Rect(12, 12, 583, 830), source, index,
                                 keep_proportion=True, overlay=True)
        for page in output:
            for block in page.get_text("blocks"):
                if (block[0] < -1 or block[1] < -1 or
                    block[2] > page.rect.width + 1 or
                    block[3] > page.rect.height + 1):
                    raise LayoutError("El PDF A4 contiene texto fuera de la página: revisar maquetación")
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
        if preview:
            for page in pdf:
                page.insert_text((32, 30), "VISTA PREVIA - NO VALIDO PARA FIRMA",
                                 fontsize=10, color=(0.8, 0.16, 0.12),
                                 overlay=True)
        return pdf.tobytes(garbage=4, deflate=True)
