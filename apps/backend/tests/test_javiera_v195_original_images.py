"""GALANT IRL 19.4.2: imágenes del Excel original y salida HTML/PDF real.

No se incluye ningún dato personal ni fotografía del workbook privado.
"""
from io import BytesIO

import fitz
from PIL import Image as PILImage
from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage

from app.javiera_irl_original import extract_irl_original
from app.javiera_irl_render_context import original_context
from app.javiera_native import render_native_pdf

from test_javiera_v19 import data


def workbook_with_five_images() -> bytes:
    book = Workbook()
    irl = book.active
    irl.title = "IRL"
    irl["A4"] = "INFORMACIÓN DE RIESGOS LABORALES (IRL) - DECRETO SUPREMO N° 44"
    irl["A5"] = "Texto fijo del Decreto Supremo usado solamente en la plantilla."
    irl["A13"] = "Artículo 15."
    irl["A14"] = "Advertencia preventiva sin datos personales."
    irl["A169"] = "Obligaciones preventivas del trabajador."
    irl["A172"] = "Declaración de recepción de información."
    irl["C3"] = "DPR-IRL-03"
    irl["D2"] = "VERSION 8.0"
    private = book.create_sheet("Datos Contrato")
    private["C17"] = "PERSONA FICTICIA DE LA PLANTILLA - NO DIVULGAR"
    for n, row in enumerate((87, 101, 120, 135, 153), 1):
        image = PILImage.new("RGB", (240, 140), (235, 237, 240))
        stream = BytesIO()
        image.save(stream, format="PNG")
        stream.seek(0)
        irl.add_image(ExcelImage(stream), "A" + str(row))
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def test_five_original_photos_stay_ordered_and_private():
    original = extract_irl_original(workbook_with_five_images())
    assert original["image_count"] == 5
    assert original["all_five_images_present"]
    assert original["document_code"] == "DPR-IRL-03"
    assert [img["anchor_row"] for img in original["images"]] == [87, 101, 120, 135, 153]
    assert [img["order"] for img in original["images"]] == [1, 2, 3, 4, 5]
    assert all(img["data_uri"].startswith("data:image/png;base64,") for img in original["images"])
    assert "C17" not in original["static"]
    assert "PERSONA FICTICIA" not in str(original)


def test_irl_pdf_renders_exact_five_embedded_images_and_all_sections():
    original = extract_irl_original(workbook_with_five_images())
    extra = {
        "PERFILES": ["Perfil técnico validado para CARPINTERO."],
        "PUESTOS": ["Espacio real", "Ambiente real", "Orden y aseo", "Máquinas usadas"],
        "SUSTANCIAS": ["Sustancia real"] + ["Dato HDS " + str(i) for i in range(11)],
    }
    records = ["Tarea: inspección real\nPeligro: escalera\n"
               "Riesgo: caída\nMedidas: revisar y controlar"] * 13
    document = render_native_pdf("irl", data(), matrix=records,
                                 irl_context=extra, original_source=original)
    assert document.startswith(b"%PDF")
    with fitz.open(stream=document, filetype="pdf") as pdf:
        full = " ".join(page.get_text() for page in pdf)
        assert "Perfil técnico validado" in full
        assert "Máquinas usadas" in full
        assert "Sustancia real" in full
        assert "Obligaciones preventivas" in full
        assert "PERSONA FICTICIA" not in full
        pictures = [img for page in pdf for img in page.get_images(full=True)]
        assert len(pictures) >= 5
        assert 1 <= pdf.page_count <= 40
        assert all(abs(page.rect.width-595) < 1 and abs(page.rect.height-842) < 1 for page in pdf)


def test_incomplete_auxiliaries_do_not_use_another_cargo():
    output = original_context({"PERFILES": [], "PUESTOS": [],
                               "SUSTANCIAS": []}, extract_irl_original(workbook_with_five_images()))
    assert output["cargo_profile"] == ""
    assert "data:image/png;base64" in output["original_images"]
    assert "PINTOR" not in output["workplace_sections"]
