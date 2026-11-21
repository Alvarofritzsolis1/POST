"""Readable, verifiable, authorization-scoped GALANT internal report exports.

Uses only deterministic internal_reply facts. Never exposes underlying records or
persists sensitive report files on disk; all formats are built in memory.
"""
from datetime import datetime
from io import BytesIO
import textwrap
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

import fitz
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .galancito_internal_live import internal_reply
from .network_service import today

SUPPORTED_REPORTS = {"overview", "publications", "followups", "contractors", "documents", "training", "metrics"}
MIME_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def internal_report(db, user, question: str):
    if not question.strip():
        raise ValueError("La consulta del informe no puede estar vacía.")
    answer, intent = internal_reply(db, user, question)
    if intent not in SUPPORTED_REPORTS:
        raise ValueError("Esta pregunta no produce un informe verificable con los datos disponibles.")
    return {
        "title": "GALANT | Informe interno de consulta",
        "date": str(today()), "scope": question.strip()[:150],
        "summary": answer, "intent": intent,
        "source": "Registros internos consultados según permisos del usuario",
        "limitations": ("Resumen de consulta, no auditoría ni certificación laboral. "
                        "El contenido refleja los registros disponibles al momento de generarlo."),
    }


def _paragraphs(report: dict):
    return [
        report["title"],
        "Fecha de emisión: " + report["date"],
        "Consulta: " + report["scope"],
        "Resumen verificable",
        report["summary"],
        "Fuente",
        report["source"],
        "Alcance y limitaciones",
        report["limitations"],
    ]


def _excel(report: dict) -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Informe GALANT"
    sheet.column_dimensions["A"].width = 27
    sheet.column_dimensions["B"].width = 103
    sheet.freeze_panes = "B5"
    rows = [
        ("GALANT", report["title"]), ("Fecha", report["date"]),
        ("Consulta", report["scope"]), ("Categoría", report["intent"]),
        ("Resumen", report["summary"]), ("Fuente", report["source"]),
        ("Limitaciones", report["limitations"]),
    ]
    for index, (label, value) in enumerate(rows, 1):
        sheet.cell(index, 1, label)
        cell = sheet.cell(index, 2, value)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.cell(index, 1).font = Font(bold=True, color="FFFFFF")
        sheet.cell(index, 1).fill = PatternFill("solid", fgColor="145750")
        sheet.row_dimensions[index].height = max(29, min(156, 22 * (1 + len(value) // 110)))
    wb.properties.title = report["title"]
    wb.properties.subject = "Reporte interno verificable GALANT"
    wb.properties.creator = "GALANT"
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def _pdf(report: dict) -> bytes:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    cursor = 55
    for index, paragraph in enumerate(_paragraphs(report)):
        is_title = index == 0
        is_section = index in (3, 5, 7)
        fontsize = 16 if is_title else 12 if is_section else 10
        max_chars = 63 if is_title else 98
        for line in textwrap.wrap(paragraph, width=max_chars, break_long_words=True,
                                  replace_whitespace=True) or [""]:
            if cursor >= 775:
                page = document.new_page(width=595, height=842)
                cursor = 55
            page.insert_text((49, cursor), line, fontsize=fontsize,
                             fontname="hebo" if is_title or is_section else "helv",
                             color=(0.05, 0.27, 0.27) if is_title or is_section else (0.13, 0.20, 0.24))
            cursor += fontsize * 1.48
        cursor += 12
    binary = document.tobytes(garbage=4, deflate=True)
    document.close()
    return binary


def _docx(report: dict) -> bytes:
    def paragraph(value, *, bold=False):
        text = escape(value)
        # Each value is model-free, escaped plain text. No active links, scripts or macros.
        properties = "<w:rPr><w:b/></w:rPr>" if bold else ""
        return ("<w:p><w:r>" + properties +
                "<w:t xml:space=\"preserve\">" + text + "</w:t></w:r></w:p>")
    body = "".join(paragraph(text, bold=(i in (0, 3, 5, 7)))
                   for i, text in enumerate(_paragraphs(report)))
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>" + body + "<w:sectPr/></w:body></w:document>")
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" '
             'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>')
    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as zipout:
        zipout.writestr("[Content_Types].xml", types)
        zipout.writestr("_rels/.rels", rels)
        zipout.writestr("word/document.xml", document)
    return output.getvalue()


def export_internal_report(report: dict, kind: str) -> bytes:
    if kind == "xlsx":
        return _excel(report)
    if kind == "pdf":
        return _pdf(report)
    if kind == "docx":
        return _docx(report)
    raise ValueError("Formato de informe no admitido.")
