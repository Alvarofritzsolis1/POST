"""Previsualización y validación de contratos/anexos históricos sin escribir datos."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from openpyxl.utils.datetime import from_excel

from .ops_import import _read_sheets, _key, valid_rut, normalize_rut

ALIASES = {
    "contractor_rut": ("rut contratista", "rut empresa", "rut empleador", "rut empresa contratista"),
    "worker_rut": ("rut trabajador", "rut empleado", "rut dependiente", "rut personal"),
    "contract_type": ("tipo contrato", "tipo de contrato", "modalidad contrato", "modalidad", "tipo contrato laboral"),
    "start_date": ("fecha inicio", "inicio contrato", "fecha ingreso", "fecha de inicio", "inicio vigencia"),
    "end_date": ("fecha termino", "fecha término", "termino contrato", "fecha fin", "vencimiento", "fecha de termino"),
    "row_type": ("tipo registro", "registro", "tipo documento", "documento", "clase"),
    "amendment_date": ("fecha anexo", "fecha firma anexo", "fecha modificación", "fecha modificacion"),
    "reference": ("folio", "numero anexo", "n anexo", "referencia", "numero documento"),
    "notes": ("observaciones", "observacion", "comentarios", "motivo", "detalle"),
    "status": ("estado contrato", "estado contractual", "vigencia", "estado"),
}
ALIASES = {k: {_key(x) for x in names} for k, names in ALIASES.items()}
CONTRACT_TYPES = {
    "plazo fijo": "fixed_term", "fijo": "fixed_term", "fixed term": "fixed_term", "fixed_term": "fixed_term",
    "indefinido": "indefinite", "indefinite": "indefinite",
    "obra": "project", "obra faena": "project", "por obra": "project", "por obra o faena": "project",
    "project": "project", "servicios": "services", "prestacion servicios": "services", "services": "services",
}
STATUS = {
    "activo": "active", "vigente": "active", "active": "active",
    "terminado": "ended", "finalizado": "ended", "ended": "ended",
    "suspendido": "suspended", "suspended": "suspended",
}
AMENDMENT_MARKERS = {"anexo", "prorroga", "amendment", "extension"}


def date_from_cell(value: Any) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    # Excel serial (in some historical plans exported as numbers).
    if re.fullmatch(r"\d{5}(?:\.0+)?", raw):
        serial = int(float(raw))
        if 20000 <= serial <= 80000:
            return from_excel(serial).date()
    raw = raw.split(" 00:00:00")[0].strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def canonical(row: dict[str, Any]) -> dict[str, Any]:
    """Revalidate *edited* preview rows; never trust client-side validation alone."""
    item = dict(row)
    errors: list[str] = []
    item["kind"] = "amendment" if _key(item.get("kind")) in AMENDMENT_MARKERS else "contract"
    item["contractor_rut"] = normalize_rut(item.get("contractor_rut")) or str(item.get("contractor_rut") or "").strip()
    item["worker_rut"] = normalize_rut(item.get("worker_rut")) or str(item.get("worker_rut") or "").strip()
    if not valid_rut(item["contractor_rut"]):
        errors.append("RUT del contratista inválido; debe asociarse a empresa existente")
    if item["worker_rut"] and not valid_rut(item["worker_rut"]):
        errors.append("RUT de trabajador inválido")
    item["contract_type"] = CONTRACT_TYPES.get(_key(item.get("contract_type")), item.get("contract_type", ""))
    if item["contract_type"] not in {"fixed_term", "indefinite", "project", "services"}:
        errors.append("Tipo de contrato desconocido: confirma plazo fijo, indefinido, obra o servicios")
    item["status"] = STATUS.get(_key(item.get("status")), item.get("status") or "active")
    if item["status"] not in {"active", "ended", "suspended"}:
        errors.append("Estado contractual desconocido")
    for key in ("start_date", "end_date", "amendment_date"):
        value = date_from_cell(item.get(key))
        if item.get(key) not in (None, "") and value is None:
            errors.append(f"Fecha {key} inválida")
        item[key] = value.isoformat() if value else None
    if item["start_date"] is None:
        errors.append("Se requiere inicio del contrato para identificar su registro original")
    if item["end_date"] and item["start_date"] and item["end_date"] < item["start_date"]:
        errors.append("Fecha de término anterior al inicio")
    if item["kind"] == "contract":
        if item["contract_type"] == "fixed_term" and not item["end_date"]:
            errors.append("El contrato a plazo fijo requiere fecha de término")
        if item["contract_type"] == "indefinite" and item["end_date"]:
            errors.append("Un contrato indefinido no puede tener término automático")
    else:
        if not item["amendment_date"]:
            errors.append("El anexo necesita fecha")
        if not item["end_date"]:
            errors.append("El anexo debe señalar la nueva fecha de término")
        if not str(item.get("reference") or "").strip():
            errors.append("El anexo requiere referencia o número de folio único")
    item["reference"] = str(item.get("reference") or "").strip()[:160]
    item["notes"] = str(item.get("notes") or "").strip()[:2000]
    item["errors"] = errors
    return item


def parse_contracts(content: bytes, filename: str) -> dict[str, Any]:
    found = []
    recognized: dict[str, dict[str, str]] = {}
    for sheet, values in _read_sheets(content, filename):
        header_index = None
        mapping = {}
        best_score = 0
        for i, row in enumerate(values[:25]):
            normalized = [_key(v) for v in row]
            cols = {field: next((n for n, v in enumerate(normalized) if v in aliases), None)
                    for field, aliases in ALIASES.items()}
            cols = {k: v for k, v in cols.items() if v is not None}
            score = sum(field in cols for field in ("contractor_rut", "start_date", "contract_type", "end_date"))
            if score > best_score:
                best_score, header_index, mapping = score, i, cols
        if header_index is None or best_score < 3 or "contractor_rut" not in mapping:
            raise ValueError(f"La hoja {sheet} no contiene columnas suficientes para contratos; utiliza la plantilla")
        header = values[header_index]
        recognized[sheet] = {name: str(header[index]) for name, index in mapping.items()}
        for num, row in enumerate(values[header_index + 1:], start=header_index + 2):
            if not any(str(v or "").strip() for v in row):
                continue
            data = {key: row[index] if index < len(row) else "" for key, index in mapping.items()}
            data["row_id"] = f"{sheet}:{num}"
            raw_kind = _key(data.get("row_type"))
            data["kind"] = "amendment" if raw_kind in AMENDMENT_MARKERS else "contract"
            data["source_sheet"] = sheet
            data["source_row"] = num
            found.append(canonical(data))
    if not found:
        raise ValueError("No se encontraron contratos")
    if len(found) > 10000:
        raise ValueError("La planilla supera 10.000 contratos")
    return {"rows": found, "detected_columns": recognized,
            "summary": {"total": len(found), "contracts": sum(x["kind"] == "contract" for x in found),
                        "amendments": sum(x["kind"] == "amendment" for x in found),
                        "errors": sum(bool(x["errors"]) for x in found)}}
