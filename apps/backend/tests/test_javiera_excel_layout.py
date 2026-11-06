"""Pruebas sin datos reales: importación, maquetación y revisión GALANT JAVIERA."""
import io
import shutil
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import fitz
import pytest
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.javiera_excel import (
    DOC_SHEETS, LayoutError, Q, excel_document, layout_summary,
    libreoffice_pdf, sheet_files, spanish_amount, validate_xlsx,
)
from app.javiera_layout_api import source_leaks
from app.javiera_review import CHECKLISTS, specialty_for_code


def sample_xlsx() -> bytes:
    wb = Workbook()
    data = wb.active
    data.title = "Datos Contrato"
    for cell, value in {
        "C5": "EMPRESA ANTIGUA", "C6": "11.111.111-1",
        "C7": "REPRESENTANTE ANTIGUO", "C8": "11.111.111-1",
        "C17": "PERSONA ANTIGUA", "C18": "11.111.111-1",
        "C29": "CARPINTERO", "C31": 42, "C32": 600000
    }.items():
        data[cell] = value
    for code, title in DOC_SHEETS.items():
        doc = wb.create_sheet(title)
        doc["A1"] = "DOCUMENTO DE PRUEBA"  # No hay datos personales reales.
        doc["A1"].font = Font(name="Arial", size=15, bold=True, color="FFFFFF")
        doc["A1"].fill = PatternFill("solid", fgColor="25466B")
        doc.merge_cells("A1:D1")
        doc["A3"] = "NOMBRE DE TRABAJADOR:"
        doc["B3"] = "='Datos Contrato'!C17"
        doc["B4"] = "='Datos Contrato'!C5"
        doc["A5"] = "TABLA"
        doc["B5"] = "RUT"
        doc.print_area = "A1:D15"
        doc.sheet_properties.pageSetUpPr.fitToPage = True
        doc.page_setup.fitToWidth = 1
        doc.page_setup.fitToHeight = 0
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def valid_data():
    return {"employer":{"name":"EMPRESA DE PRUEBA","rut":"11.111.111-1"},
            "worker":{"name":"PERSONA NUEVA DE PRUEBA","rut":"11.111.111-1"},
            "site":{"name":"OBRA DEMOSTRACIÓN"},"role":"CARPINTERO",
            "contract":{"start":"2026-11-01","end":"2026-12-30",
                        "salary":"600000","hours":"42"},
            "event":{"date":"2026-11-06"},"extra":{}}


def test_inventory_documents_and_original_layout_metadata():
    raw = sample_xlsx()
    validate_xlsx(raw)
    report = layout_summary(raw)
    assert len(report) == 10
    assert all(entry["found"] for entry in report)
    assert all(entry["merged"] >= 1 for entry in report)
    assert all(entry["has_print_setup"] for entry in report)


def test_no_loss_of_original_styles_merges_print_areas():
    raw = sample_xlsx()
    updated = excel_document(raw, "labor_contract", valid_data(), {
        "A5":{"text":"TEXTO CORREGIDO"},
        "A1":{"style_from":"A1"}
    })
    with ZipFile(io.BytesIO(raw)) as old, ZipFile(io.BytesIO(updated)) as new:
        sheets = sheet_files(old)
        path = sheets["Contrato Imprimible"]
        original = ET.fromstring(old.read(path))
        patched = ET.fromstring(new.read(path))
        assert original.findall(".//" + Q("mergeCell"))[0].get("ref") == patched.findall(".//" + Q("mergeCell"))[0].get("ref")
        assert original.find(".//" + Q("c") + "[@r='A1']").get("s") == patched.find(".//" + Q("c") + "[@r='A1']").get("s")
        assert patched.find(".//" + Q("c") + "[@r='A5']").find(Q("is")).find(Q("t")).text == "TEXTO CORREGIDO"
        assert old.read("xl/styles.xml") == new.read("xl/styles.xml")
        assert old.read("xl/workbook.xml") != new.read("xl/workbook.xml")
        from app.javiera_excel import shared_strings, cell_text
        assert cell_text(patched.find(".//" + Q("c") + "[@r='B3']"), shared_strings(new)) == "PERSONA NUEVA DE PRUEBA"
        assert len(ET.fromstring(new.read("xl/workbook.xml")).findall(".//" + Q("sheet"))) == 1


def test_pts_17_approved_sections_replace_cached_excel():
    raw = sample_xlsx()
    sections = ["Medida preventiva aprobada " + str(i) for i in range(17)]
    updated = excel_document(raw, "pts", valid_data(), matrix=sections)
    with ZipFile(io.BytesIO(updated)) as z:
        root = ET.fromstring(z.read(sheet_files(z)["PTS."]))
        item = root.find(".//" + Q("c") + "[@r='A54']")
        assert item is not None
        assert item.find(Q("is")).find(Q("t")).text == sections[0]
    with pytest.raises(LayoutError):
        excel_document(raw, "pts", valid_data(), matrix=["Solo una sección"])


def test_amount_words_and_reviewer_specialties():
    assert spanish_amount("600000") == "Seiscientos mil pesos."
    assert spanish_amount("0") == "Cero pesos."
    assert specialty_for_code("labor_contract") == "laboral"
    assert specialty_for_code("irl") == "prevencion"
    assert len(CHECKLISTS["laboral"]) >= 5
    assert len(CHECKLISTS["prevencion"]) >= 5


def test_reject_bad_excel_data():
    with pytest.raises(LayoutError):
        validate_xlsx(b"no xlsx")


@pytest.mark.skipif(shutil.which("libreoffice") is None, reason="LO instalado en contenedor, no necesariamente en test local")
def test_real_pdf_recalculation_no_example_identity():
    raw = sample_xlsx()
    modified = excel_document(raw, "labor_contract", valid_data())
    pdf = libreoffice_pdf(modified, timeout=50)
    with fitz.open(stream=pdf, filetype="pdf") as document:
        assert 1 <= document.page_count <= 3
        text = " ".join(p.get_text() for p in document)
        assert "DOCUMENTO DE PRUEBA" in text
        assert "PERSONA NUEVA DE PRUEBA" in text
        assert "PERSONA ANTIGUA" not in text
        assert source_leaks(raw, pdf, valid_data()) == []
