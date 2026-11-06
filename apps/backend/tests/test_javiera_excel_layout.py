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
    data["C13"] = "admin@example.test"
    data["C13"].hyperlink = "mailto:admin@example.test"
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
        if code == "induction":
            doc["A119"] = "Recibí del contratista principal CONSTRUCTORA EJEMPLO LIMITADA."
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



def test_epp_quantities_never_inherited_from_excel():
    import copy
    from app.javiera_excel import shared_strings, cell_text
    raw = sample_xlsx()
    data = valid_data()
    data["event"]["epp_items"] = "Casco; Lentes de Seguridad; 2 x Arnés de seguridad"
    converted = excel_document(raw, "ppe_delivery", data,
                               changes={"D13": {"text": "9"}})
    with ZipFile(io.BytesIO(converted)) as z:
        root = ET.fromstring(z.read(sheet_files(z)["Registros Entrega EPP"]))
        def val(coord):
            cell = root.find(".//"+Q("c")+"[@r='"+coord+"']")
            return cell_text(cell, shared_strings(z)) if cell is not None else ""
        assert val("D12") == "1"
        assert val("D13") == ""  # no se entregó calzado; anula override peligroso
        assert val("D14") == "1"
        assert val("D17") == "2"
        assert val("D19") == ""
    data["event"]["epp_items"] = "Guantes"  # sin tipo concreto
    with pytest.raises(LayoutError, match="ambiguo"):
        excel_document(raw, "ppe_delivery", data)


def test_extension_requires_new_end_after_previous_end():
    data = valid_data()
    with pytest.raises(LayoutError, match="prórroga"):
        excel_document(sample_xlsx(), "extension_addendum", data)
    data["contract"]["new_end"] = "2027-01-31"
    raw = excel_document(sample_xlsx(), "extension_addendum", data)
    with ZipFile(io.BytesIO(raw)) as z:
        root = ET.fromstring(z.read(sheet_files(z)["Anexo extension contrato"]))
        cell = root.find(".//"+Q("c")+"[@r='A5']")
        assert "31/01/2027" in cell.find(Q("is")).find(Q("t")).text


def test_juramento_uses_actual_principal_and_never_worker_case():
    data = valid_data()
    data["extra"].update({
        "representative_name":"REPRESENTANTE DE PRUEBA",
        "representative_rut":"11.111.111-1",
        "representative_nationality":"CHILENA",
        "employer_address":"DIRECCIÓN DE PRUEBA",
        "employer_city":"CONCEPCIÓN",
        "site_address":"DIRECCIÓN OBRA DE PRUEBA",
        "specialty":"CARPINTERÍA",
        "principal_company":"EMPRESA MANDANTE DE PRUEBA",
        "declaration_period":"2026-10",
    })
    data["contract"]["declaration_reason"] = "Declaración aportada por la empresa para este período"
    with pytest.raises(LayoutError, match="trabajador asignado"):
        excel_document(sample_xlsx(), "sworn_declaration", data)
    data["worker"]["name"] = ""
    raw = excel_document(sample_xlsx(), "sworn_declaration", data)
    with ZipFile(io.BytesIO(raw)) as z:
        root = ET.fromstring(z.read(sheet_files(z)["DECLARACION JURADA"]))
        declaration = root.find(".//"+Q("c")+"[@r='A5']").find(Q("is")).find(Q("t")).text
        assert "OCTUBRE DEL AÑO 2026" in declaration
        assert "EMPRESA MANDANTE DE PRUEBA" in declaration


def test_published_excel_requires_original_fields():
    from app.javiera_logic import DOCUMENT_BY_CODE, LAYOUT_REQUIRED, eligibility
    data = valid_data()
    data["employment_type"] = "dependiente"
    base = DOCUMENT_BY_CODE["labor_contract"][4]
    required = list(dict.fromkeys([*base,*LAYOUT_REQUIRED["labor_contract"]]))
    doc = {d["code"]:d for d in eligibility(data, {"labor_contract":{
        "fields":required, "published_version":1, "has_body":True}})}["labor_contract"]
    assert doc["status"] == "FALTAN_DATOS"
    assert "extra.representative_name" in doc["missing_fields"]
    assert not doc["can_issue"]



def test_mandante_references_are_replaced_in_induction_and_email_link_allowed():
    from app.javiera_excel import cell_text, shared_strings, sheet_files
    raw = sample_xlsx()  # contiene mailto válido en la hoja fuente
    validate_xlsx(raw)
    data = valid_data()
    data["extra"]["principal_company"] = "MANDANTE REAL DE PRUEBA"
    updated = excel_document(raw, "induction", data)
    with ZipFile(io.BytesIO(updated)) as z:
        root = ET.fromstring(z.read(sheet_files(z)["INDUCCION PREVENCION"]))
        text = cell_text(root.find(".//" + Q("c") + "[@r='A119']"), shared_strings(z))
        assert "MANDANTE REAL DE PRUEBA" in text
        assert "CONSTRUCTORA EJEMPLO LIMITADA" not in text



@pytest.mark.skipif(shutil.which("libreoffice") is None, reason="Requiere LibreOffice Calc en CI")
@pytest.mark.parametrize("code",list(DOC_SHEETS))
def test_ten_original_document_pdfs_with_synthetic_person_only(code):
    """Una vista previa por cada tipo, evitando mostrar nombres del Excel origen."""
    from app.javiera_excel import pdf_from_workbook
    data = valid_data()
    data["extra"].update({
        "representative_name":"REPRESENTANTE SINTETICO",
        "representative_rut":"11.111.111-1",
        "representative_nationality":"CHILENA",
        "employer_city":"CONCEPCION",
        "employer_address":"DIRECCION SINTETICA",
        "site_address":"OBRA DE PRUEBA",
        "specialty":"CARPINTERIA",
        "principal_company":"MANDANTE DE PRUEBA",
        "declaration_period":"2026-10",
    })
    data["contract"]["new_end"] = "2027-01-31"
    data["contract"]["declaration_reason"] = "Declaración presentada voluntariamente por el representante"
    data["event"]["epp_items"] = "Casco de Seguridad; Lentes de Seguridad"
    if code=="sworn_declaration":
        data["worker"]["name"]=""
    matrix = [f"Medida técnica {i}" for i in range(17)] if code=="pts" else (
        ["Tarea: Trabajo\nPeligro: Caída\nRiesgo: Lesión\nMedidas: Barrera"] if code=="irl" else None)
    pdf = pdf_from_workbook(sample_xlsx(),code,data,matrix=matrix,preview=True)
    with fitz.open(stream=pdf,filetype="pdf") as document:
        assert document.page_count>=1
        pages=" ".join(p.get_text() for p in document)
        assert "DOCUMENTO DE PRUEBA" in pages
        assert "PERSONA ANTIGUA" not in pages
        assert "VISTA PREVIA" in pages



@pytest.mark.skipif(shutil.which("libreoffice") is None, reason="Requiere LibreOffice para exportar IRL")
@pytest.mark.parametrize("risk_rows", [13, 26])
def test_irl_pdf_keeps_every_approved_risk_even_past_12_rows(risk_rows):
    """El IRL original tiene capacidad para 12 filas, pero una matriz puede tener 26."""
    from app.javiera_excel import pdf_from_workbook
    data = valid_data()
    rows = [
        "Tarea: Registro de riesgo numero " + str(i) +
        "\nPeligro: Peligro sintético "+str(i)+
        "\nRiesgo: Lesión en actividad "+str(i)+
        "\nMedidas: Control obligatorio del riesgo "+str(i)
        for i in range(1, risk_rows+1)
    ]
    raw = pdf_from_workbook(sample_xlsx(), "irl", data, matrix=rows, preview=True)
    with fitz.open(stream=raw, filetype="pdf") as document:
        text = "\n".join(page.get_text() for page in document)
        assert "ANEXO INTEGRANTE" in text
        for index in range(13, risk_rows+1):
            assert f"REGISTRO {index}" in text
            assert f"Control obligatorio del riesgo {index}" in text
        assert "VISTA PREVIA" in text
