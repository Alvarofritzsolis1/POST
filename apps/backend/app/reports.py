"""Exportación Excel construida solo con campos interpretados y controles validados."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def safe_text(value: object) -> str:
    text = "" if value is None else str(value)
    # Excel interpreta '=' como fórmula y otros prefijos pueden ser peligrosos al exportar.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def _sheet(workbook: Workbook, name: str, columns: list[str]):
    sheet = workbook.create_sheet(name)
    sheet.append(columns)
    sheet.freeze_panes = "A2"
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center")
    sheet.row_dimensions[1].height = 25
    return sheet


def _finish(sheet, widths: list[int]):
    sheet.auto_filter.ref = sheet.dimensions
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def build_workbook(doc) -> bytes:
    if doc.status != "complete":
        raise ValueError("El documento no tiene resultado validado")
    extracted = doc.extracted or {}
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.creator = "GALANT"
    summary = _sheet(workbook, "Resumen", ["Campo", "Valor"])
    for field, value in (
        ("Archivo", doc.original_name),
        ("Tipo documental", doc.detected_type),
        ("Estado documental", doc.payment_status),
        ("Período de remuneraciones", extracted.get("periodo")),
        ("Páginas", doc.page_count),
        ("Verificación externa", "No"),
        ("Tiempo de procesamiento (s)", extracted.get("tiempo_procesamiento_s")),
        ("OCR reutilizado", "Sí" if extracted.get("ocr_reutilizado") else "No"),
    ):
        summary.append([safe_text(field), value if isinstance(value, (int, float)) else safe_text(value)])
    _finish(summary, [35, 72])

    identifiers = _sheet(workbook, "RUT detectados", ["RUT válido", "Asociación"])
    for rut in extracted.get("ruts_validos", []):
        identifiers.append([safe_text(rut), "Sin asociación confirmada"])
        identifiers.cell(identifiers.max_row, 1).number_format = "@"
    _finish(identifiers, [25, 38])

    controls = _sheet(workbook, "Controles por página", [
        "Página", "Período", "Comprobante", "Estado pagado", "Folio", "Señal negativa", "Evidencia suficiente", "Motivos de revisión"])
    for row in extracted.get("controles_por_pagina", []):
        controls.append([row.get("page"), safe_text(row.get("period")),
                         "Sí" if row.get("receipt") else "No", "Sí" if row.get("paid_state") else "No",
                         "Sí" if row.get("transaction") else "No", "Sí" if row.get("negative") else "No",
                         "Sí" if row.get("evidence_sufficient") else "No",
                         safe_text(", ".join(row.get("reasons", [])))])
    _finish(controls, [12, 16, 20, 20, 16, 18, 22, 58])

    observations = _sheet(workbook, "Observaciones", ["N°", "Observación"])
    for index, warning in enumerate(doc.warnings or [], 1):
        observations.append([index, safe_text(warning)])
    _finish(observations, [10, 90])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()
