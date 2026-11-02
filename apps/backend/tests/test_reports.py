from io import BytesIO

from openpyxl import load_workbook

from app.models import Document
from app.reports import build_workbook


def test_excel_roundtrip_uses_structured_fields_and_escapes_formula():
    doc = Document(original_name="=malicioso.pdf", status="complete", detected_type="cotizaciones",
                   payment_status="Pendiente de revisión", page_count=2,
                   extracted={"periodo": "2026-10", "ruts_validos": ["12345678-5"],
                              "controles_por_pagina": [{"page": 1, "period": "2026-10", "receipt": True,
                                                       "paid_state": False, "transaction": True,
                                                       "negative": False, "evidence_sufficient": False,
                                                       "reasons": ["estado de pago"]}],
                              "tiempo_procesamiento_s": 1.25},
                   warnings=["Revisar estado"], evidence=[{"extracto": "TEXTO OCR NO EXPORTABLE"}])
    workbook = load_workbook(BytesIO(build_workbook(doc)), data_only=False)
    assert workbook.sheetnames == ["Resumen", "RUT detectados", "Controles por página", "Observaciones"]
    summary = {row[0]: row[1] for row in workbook["Resumen"].iter_rows(min_row=2, values_only=True)}
    assert summary["Archivo"] == "'=malicioso.pdf"
    assert summary["Estado documental"] == "Pendiente de revisión"
    assert summary["Tiempo de procesamiento (s)"] == 1.25
    rut = workbook["RUT detectados"]["A2"]
    assert rut.value == "12345678-5" and rut.number_format == "@"
    assert workbook["Controles por página"]["C2"].value == "Sí"
    assert workbook["Observaciones"]["B2"].value == "Revisar estado"
    assert all("TEXTO OCR NO EXPORTABLE" not in str(cell.value)
               for sheet in workbook for row in sheet for cell in row)


def test_f30_1_report_keeps_its_own_type():
    doc = Document(original_name="certificado.pdf", status="complete", detected_type="f30_1",
                   payment_status="Pendiente de revisión", page_count=1,
                   extracted={"periodo": "2026-10", "ruts_validos": [], "controles_por_pagina": []},
                   warnings=["F30-1 no prueba una transacción previsional"], evidence=[])
    workbook = load_workbook(BytesIO(build_workbook(doc)), read_only=True)
    summary = {row[0]: row[1] for row in workbook["Resumen"].iter_rows(min_row=2, values_only=True)}
    assert summary["Tipo documental"] == "f30_1"
    assert summary["Estado documental"] == "Pendiente de revisión"
