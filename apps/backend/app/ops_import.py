"""Validated spreadsheet import for the operational register.

Preview is deliberately stateless: the edited rows are validated again before
any database write.  Historical spreadsheet marks are preserved as provenance,
never turned into a verified document approval.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

MAX_IMPORT_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
MAX_COLUMNS = 160
MAX_SHEETS = 10
HISTORICAL_MARKS = {"OK", "P", "NA"}
MAPPED_STATES = {"historical_approved", "historical_pending", "historical_not_applicable"}


def _plain(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _plain(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_rut(value: Any) -> str:
    text = _plain(value)
    if not re.fullmatch(r"[0-9kK.\-\s]+", text):
        return ""
    raw = re.sub(r"[.\-\s]", "", text).upper()
    if not 2 <= len(raw) <= 10 or not raw[:-1].isdigit():
        return ""
    return f"{int(raw[:-1])}-{raw[-1]}"


def valid_rut(value: Any) -> bool:
    rut = normalize_rut(value)
    if not rut:
        return False
    number, check = rut.split("-")
    total = sum(int(digit) * factor for digit, factor in zip(reversed(number), (2, 3, 4, 5, 6, 7) * 2))
    expected = 11 - total % 11
    return check == ("0" if expected == 11 else "K" if expected == 10 else str(expected))


ALIASES = {
    "kind": {"tipo", "tipo fila", "tipo registro", "registro", "clase"},
    "name": {"nombre", "razon social", "nombre razon social", "nombre contratista", "nombre trabajador", "empresa contratista"},
    "rut": {"rut", "r u t"},
    "contractor_name": {"contratista", "empresa", "razon social contratista", "nombre empresa"},
    "contractor_rut": {"rut contratista", "rut empresa contratista", "rut empresa", "rut empleador", "rut_contratista"},
    "worker_name": {"trabajador", "nombre trabajador", "personal", "empleado", "nombre empleado"},
    "worker_rut": {"rut trabajador", "rut empleado", "rut personal"},
    "historical_code": {"codigo", "codigo historico", "codigo contratista", "cod", "clasificacion", "ct ci", "codigo_historico"},
    "nature": {"naturaleza"},
    "frequency": {"frecuencia"},
    "contract_status": {"estado contractual", "estado_contractual"},
}
ALIASES = {field: {_key(alias) for alias in values} for field, values in ALIASES.items()}


def _read_sheets(content: bytes, filename: str) -> list[tuple[str, list[list[str]]]]:
    if not content or len(content) > MAX_IMPORT_BYTES:
        raise ValueError("Archivo vacío o mayor a 8 MB")
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded = content.decode("cp1252")
        sample = decoded[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ";" if sample.count(";") > sample.count(",") else ","
        rows = [row for row in csv.reader(io.StringIO(decoded), delimiter=delimiter)]
        if len(rows) > MAX_ROWS or any(len(row) > MAX_COLUMNS for row in rows):
            raise ValueError("La planilla supera el límite de filas o columnas")
        return [("CSV", rows)]
    if suffix != ".xlsx":
        raise ValueError("Formato no admitido. Utiliza .xlsx o .csv")
    if not content.startswith(b"PK\x03\x04"):
        raise ValueError("El archivo no es un XLSX válido")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            members = package.infolist()
            if len(members) > 200 or sum(member.file_size for member in members) > 32 * 1024 * 1024:
                raise ValueError("El XLSX supera el límite de contenido descomprimido")
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
        if len(workbook.worksheets) > MAX_SHEETS:
            raise ValueError("La planilla supera el límite de hojas")
        sheets = []
        for sheet in workbook.worksheets:
            if (sheet.max_row or 0) > MAX_ROWS or (sheet.max_column or 0) > MAX_COLUMNS:
                raise ValueError("La planilla supera el límite de filas o columnas")
            rows = [[_plain(value) for value in row] for row in sheet.iter_rows(values_only=True)]
            sheets.append((sheet.title, rows))
        workbook.close()
        return sheets
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise ValueError(f"No se pudo leer el XLSX: {exc}") from exc


def _header(rows: list[list[str]], mapping: dict[str, str | int] | None) -> tuple[int, dict[str, int]]:
    if not rows:
        raise ValueError("Planilla sin filas")
    best_index, best_columns, best_score = -1, {}, -1
    for i, row in enumerate(rows[:25]):
        columns = {}
        normalized = [_key(value) for value in row]
        for field, aliases in ALIASES.items():
            for column, heading in enumerate(normalized):
                if heading in aliases:
                    columns[field] = column
                    break
        score = sum(field in columns for field in ("kind", "name", "rut", "contractor_name", "worker_name", "historical_code"))
        if mapping:
            score += 2 * sum(_key(locator) in normalized for locator in mapping.values() if isinstance(locator, str))
        if score > best_score:
            best_index, best_columns, best_score = i, columns, score
    if best_score < 2 and not mapping:
        raise ValueError("No se identificaron encabezados; indica un mapeo de columnas o usa una plantilla")
    if mapping:
        headers = [_key(value) for value in rows[best_index]]
        for field, locator in mapping.items():
            if field not in ALIASES:
                raise ValueError(f"Columna de destino desconocida: {field}")
            if isinstance(locator, int) and not isinstance(locator, bool):
                index = locator
            else:
                needle = _key(locator)
                if needle not in headers:
                    raise ValueError(f"Encabezado no encontrado: {locator}")
                index = headers.index(needle)
            if not 0 <= index < MAX_COLUMNS:
                raise ValueError(f"Índice de columna inválido: {locator}")
            best_columns[field] = index
    if "name" not in best_columns and "contractor_name" not in best_columns and "worker_name" not in best_columns:
        raise ValueError("Falta una columna con el nombre de empresa o trabajador")
    return best_index, best_columns


def _cell(row: list[str], columns: dict[str, int], field: str) -> str:
    column = columns.get(field)
    return _plain(row[column]) if column is not None and column < len(row) else ""


def _status_values(row: list[str], header: list[str], columns: dict[str, int], sheet: str) -> dict[str, str]:
    claimed = set(columns.values())
    found = {}
    for index, value in enumerate(row):
        raw = _plain(value).upper()
        if index in claimed or raw not in HISTORICAL_MARKS:
            continue
        title = _plain(header[index]) if index < len(header) else ""
        found[f"{sheet}: {title or 'Columna'} [{get_column_letter(index + 1)}]"] = raw
    return found


MONTHS = {
    "ene": 1, "enero": 1, "feb": 2, "febrero": 2, "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4, "may": 5, "mayo": 5, "jun": 6, "junio": 6,
    "jul": 7, "julio": 7, "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "set": 9, "septiembre": 9, "setiembre": 9,
    "oct": 10, "octubre": 10, "nov": 11, "noviembre": 11,
    "dic": 12, "diciembre": 12,
}


def _column_metadata(column: str) -> dict[str, str | None]:
    """Extract metadata from a source heading without interpreting its mark."""
    match = re.fullmatch(r"[^:]+: (.*) \[[A-Z]+\]", column)
    header = match.group(1) if match else column
    normalized = _key(header)
    year_month = re.search(r"\b(20\d{2})\s*[-/. ]\s*(0?[1-9]|1[0-2])\b", header)
    month_year = re.search(r"\b(0?[1-9]|1[0-2])\s*[-/. ]\s*(20\d{2})\b", header)
    period = None
    if year_month:
        period = f"{year_month.group(1)}-{int(year_month.group(2)):02d}"
    elif month_year:
        period = f"{month_year.group(2)}-{int(month_year.group(1)):02d}"
    else:
        year = re.search(r"\b20\d{2}\b", normalized)
        month = next((MONTHS[token] for token in normalized.split() if token in MONTHS), None)
        if year and month:
            period = f"{year.group(0)}-{month:02d}"
    requirement = None
    if "cotizac" in normalized or "previred" in normalized:
        requirement = "cotizaciones"
    elif re.search(r"\bf\s*30\s*1\b|\bf30\s*1\b", normalized):
        requirement = "f30_1"
    elif "liquidacion" in normalized and "firmad" in normalized:
        requirement = "liquidacion_firmada"
    elif "asistencia" in normalized:
        requirement = "libro_asistencia"
    elif "porteria" in normalized:
        requirement = "informe_porteria"
    elif "declaracion" in normalized and "jurada" in normalized:
        requirement = "declaracion_jurada"
    elif "anticipos" in normalized:
        requirement = "listado_anticipos"
    return {"source_header": header, "period": period, "requirement": requirement}


def _new_row(sheet: str, row_number: int, kind: str, name: str, rut: str,
             contractor_rut: str, historical_code: str, statuses: dict[str, str],
             nature: str = "", frequency: str = "", contract_status: str = "") -> dict[str, Any]:
    return {
        "row_id": f"{sheet}:{row_number}:{'C' if kind == 'contractor' else 'W'}",
        "sheet": sheet, "row_number": row_number, "kind": kind, "name": name,
        "rut": normalize_rut(rut) or _plain(rut),
        "contractor_rut": normalize_rut(contractor_rut) or _plain(contractor_rut),
        "historical_code": historical_code.strip().upper(),
        "nature": nature.strip().lower(), "frequency": frequency.strip().lower(),
        "contract_status": contract_status.strip().lower(),
        "historical_statuses": statuses, "errors": [], "warnings": [],
    }


def validate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Revalidate edited preview rows and annotate all ambiguous/invalid records."""
    if not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("La importación debe contener entre 1 y 10000 registros")
    result = []
    seen_contractors: dict[str, dict[str, Any]] = {}
    seen_workers: dict[tuple[str, str], dict[str, Any]] = {}
    contractor_ruts = {normalize_rut(row.get("rut")) for row in rows if row.get("kind") == "contractor"}
    for incoming in rows:
        row = {**incoming, "errors": [], "warnings": []}
        kind = row.get("kind")
        name = _plain(row.get("name"))
        rut = normalize_rut(row.get("rut"))
        parent = normalize_rut(row.get("contractor_rut"))
        row["name"], row["rut"], row["contractor_rut"] = name, rut or _plain(row.get("rut")), parent or _plain(row.get("contractor_rut"))
        if len(name) > 180:
            row["errors"].append("El nombre supera 180 caracteres")
        code = _plain(row.get("historical_code")).upper()
        if len(code) > 20:
            row["errors"].append("El código histórico supera 20 caracteres")
        row["historical_code"] = code
        enums = {
            "nature": {"independent": "independent", "independiente": "independent",
                       "with workers": "with_workers", "con trabajadores": "with_workers",
                       "unclassified": "unclassified", "sin clasificar": "unclassified"},
            "frequency": {"fixed": "fixed", "fijo": "fixed", "sporadic": "sporadic",
                          "esporadico": "sporadic", "unclassified": "unclassified",
                          "sin clasificar": "unclassified"},
            "contract_status": {"active": "active", "activo": "active",
                                "offboarding": "offboarding", "en proceso de baja": "offboarding",
                                "inactive": "inactive", "dado de baja": "inactive"},
        }
        for field, options in enums.items():
            raw = _plain(row.get(field))
            if raw and _key(raw) not in options:
                row["errors"].append(f"Valor no admitido para {field}: {raw[:50]}")
            row[field] = options.get(_key(raw), "")
        if kind not in {"contractor", "worker"}:
            row["errors"].append("Tipo de fila ambiguo: elige empresa o trabajador")
        if not name:
            row["errors"].append("Falta el nombre")
        if not valid_rut(row["rut"]):
            row["errors"].append("RUT inválido o ausente")
        if kind == "contractor" and rut:
            if rut in seen_contractors:
                row["warnings"].append("Empresa repetida en la planilla; se importará una vez")
        if kind == "worker":
            if not valid_rut(row["contractor_rut"]):
                row["errors"].append("RUT de contratista inválido o ausente")
            elif parent not in contractor_ruts:
                row["warnings"].append("La empresa no está en esta planilla; debe existir en la obra")
            marker = (parent, rut)
            if marker in seen_workers:
                row["warnings"].append("Trabajador repetido para el mismo contratista; se importará una vez")
        statuses = row.get("historical_statuses") or {}
        if not isinstance(statuses, dict):
            row["errors"].append("Los estados históricos deben ser un objeto por columna")
            row["historical_statuses"] = {}
        else:
            row["historical_statuses"] = {str(k)[:120]: _plain(v).upper()[:40] for k, v in statuses.items() if _plain(v)}
        row["historical_statuses_meta"] = {}
        for column in row["historical_statuses"]:
            metadata = _column_metadata(column)
            row["historical_statuses_meta"][column] = metadata
            if metadata["period"] is None:
                row["warnings"].append(f"No se reconoce el período de {metadata['source_header']}")
            if metadata["requirement"] is None:
                row["warnings"].append(f"No se reconoce el requisito de {metadata['source_header']}")
        previous = seen_contractors.get(rut) if kind == "contractor" else seen_workers.get((parent, rut)) if kind == "worker" else None
        if previous:
            if _key(previous["name"]) != _key(name):
                row["errors"].append("RUT duplicado con distinto nombre")
            for field in (("historical_code", "nature", "frequency", "contract_status") if kind == "contractor" else ()):
                if previous.get(field) and row.get(field) and previous[field] != row[field]:
                    row["errors"].append(f"Registro duplicado con {field} incompatible")
            for column, value in row["historical_statuses"].items():
                if column in previous["historical_statuses"] and previous["historical_statuses"][column] != value:
                    row["errors"].append(f"Estado histórico incompatible en {column}")
        elif kind == "contractor" and rut:
            seen_contractors[rut] = row
        elif kind == "worker" and rut and parent:
            seen_workers[(parent, rut)] = row
        result.append(row)
    return result


def parse_import(content: bytes, filename: str, column_map: dict[str, str | int] | None = None) -> dict[str, Any]:
    parsed: list[dict[str, Any]] = []
    detected: dict[str, dict[str, str]] = {}
    for sheet, rows in _read_sheets(content, filename):
        if not any(any(_plain(cell) for cell in row) for row in rows):
            continue
        header_index, columns = _header(rows, column_map)
        headings = rows[header_index]
        detected[sheet] = {field: _plain(headings[index]) if index < len(headings) else get_column_letter(index + 1)
                           for field, index in columns.items()}
        parent_rut = ""
        known_companies: set[str] = set()
        for row_index, cells in enumerate(rows[header_index + 1:], start=header_index + 2):
            if not any(_plain(cell) for cell in cells):
                continue
            raw_kind = _key(_cell(cells, columns, "kind"))
            name = _cell(cells, columns, "name")
            rut = _cell(cells, columns, "rut")
            company_name = _cell(cells, columns, "contractor_name")
            company_rut = _cell(cells, columns, "contractor_rut")
            worker_name = _cell(cells, columns, "worker_name")
            worker_rut = _cell(cells, columns, "worker_rut")
            code = _cell(cells, columns, "historical_code")
            nature = _cell(cells, columns, "nature")
            frequency = _cell(cells, columns, "frequency")
            contract_status = _cell(cells, columns, "contract_status")
            statuses = _status_values(cells, headings, columns, sheet)
            explicit_company = raw_kind in {"empresa", "contratista", "contractor", "ct", "ci"}
            explicit_worker = raw_kind in {"trabajador", "worker", "empleado", "personal"}
            if company_name and worker_name:
                normalized_company = normalize_rut(company_rut)
                if normalized_company not in known_companies:
                    parsed.append(_new_row(sheet, row_index, "contractor", company_name, company_rut, "", code, {}, nature, frequency, contract_status))
                    known_companies.add(normalized_company)
                parsed.append(_new_row(sheet, row_index, "worker", worker_name, worker_rut, company_rut, "", statuses))
                parent_rut = company_rut
            elif explicit_worker or worker_name:
                parsed.append(_new_row(sheet, row_index, "worker", worker_name or name, worker_rut or rut,
                                       company_rut or parent_rut, "", statuses))
            elif explicit_company or (company_name and not worker_name) or (code and _key(code) not in {"ok", "p", "na"}):
                contractor = _new_row(sheet, row_index, "contractor", company_name or name, company_rut or rut,
                                      "", code, statuses, nature, frequency, contract_status)
                parsed.append(contractor)
                parent_rut = contractor["rut"]
                known_companies.add(normalize_rut(parent_rut))
            elif parent_rut and name:
                parsed.append(_new_row(sheet, row_index, "worker", name, rut, parent_rut, "", statuses))
            else:
                ambiguous = _new_row(sheet, row_index, "ambiguous", name or company_name, rut or company_rut,
                                     company_rut, code, statuses)
                parsed.append(ambiguous)
    if not parsed:
        raise ValueError("No se encontraron registros para importar")
    rows = validate_rows(parsed)
    return {
        "rows": rows, "detected_columns": detected,
        "summary": {"contractors": sum(row["kind"] == "contractor" for row in rows),
                    "workers": sum(row["kind"] == "worker" for row in rows),
                    "errors": sum(bool(row["errors"]) for row in rows),
                    "warnings": sum(bool(row["warnings"]) for row in rows),
                    "historical_marks": dict(Counter(value for row in rows for value in row["historical_statuses"].values()))},
    }
