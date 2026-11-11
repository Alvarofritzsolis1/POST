"""IRL PDF A4: conserva 13 riesgos + cinco imágenes de origen sintético.

Prueba end-to-end del renderer HTML -> PyMuPDF sin la suite LibreOffice.
No almacena ni requiere imágenes de trabajadores o libro privado.
"""
from base64 import b64encode
from io import BytesIO

import fitz
from PIL import Image, ImageDraw

from app.javiera_native import render_native_pdf


def _data():
    return {
        "employer": {"name": "EMPRESA SINTETICA DE CONSTRUCCION SPA", "rut": "76000000-0"},
        "worker": {"name": "PERSONA SINTETICA PARA PRUEBAS", "rut": "20000000-0"},
        "site": {"name": "OBRA DE PRUEBAS A4"},
        "role": "PINTOR",
        "event": {"date": "2026-11-11"},
        "extra": {"irl_revision": "PRUEBA-PDF-01"},
    }


def _matrix():
    return [
        f"Tarea: Actividad de ensayo {i}\nPeligro: Fuente de riesgo {i}\n"
        f"Riesgo: Consecuencia de ensayo {i}\nMedidas: Control verificable {i}"
        for i in range(1, 14)
    ]


def _images():
    images = []
    for i in range(1, 6):
        picture = Image.new("RGB", (510, 135), "white")
        pen = ImageDraw.Draw(picture)
        pen.rectangle((3, 3, 506, 130), outline="black", width=2)
        pen.text((20, 45), f"ILUSTRACION SINTETICA NUMERO {i}", fill="black")
        with BytesIO() as buf:
            picture.save(buf, format="PNG")
            blob = buf.getvalue()
        images.append({
            "title": f"Imagen de control {i}",
            "data_uri": "data:image/png;base64," + b64encode(blob).decode("ascii"),
        })
    return images


def _read_pdf(data):
    pdf = fitz.open(stream=data, filetype="pdf")
    assert 1 <= pdf.page_count <= 40
    for number, page in enumerate(pdf, 1):
        assert abs(page.rect.width - 595.28) < 1, number
        assert abs(page.rect.height - 841.89) < 1, number
        for block in page.get_text("blocks"):
            if len(block) > 4 and isinstance(block[4], str) and block[4].strip():
                assert min(block[0], block[1]) >= -0.5, (number, block)
                assert block[2] <= page.rect.width + 0.5, (number, block)
                assert block[3] <= page.rect.height + 0.5, (number, block)
    return pdf


def test_five_png_images_survive_irl_a4_with_all_13_risks():
    payload = render_native_pdf(
        "irl", _data(), matrix=_matrix(),
        original_source={"images": _images(), "status": "approved",
                         "document_code": "DPR-IRL-03",
        "static": {"A172": "Declaración del documento: el trabajador "
                   "recibió información de riesgos en este ensayo "
                   "sintético; las firmas no son reales."},
                         "static": {"A172": "Declaración del documento: el trabajador "
                                    "recibió información de riesgos en este ensayo "
                                    "sintético; las firmas no son reales."}},
        irl_context={"PERFILES": ["Perfil sintético para comprobar impresión"]},
    )
    with _read_pdf(payload) as pdf:
        all_text = "\n".join(page.get_text() for page in pdf)
        assert "DEPARTAMENTO" in all_text, "Encabezado IRL original recortado"
        assert "PREVENCIÓN" in all_text, "Falta parte del encabezado preventivo"
        assert "Actividad de ensayo 1" in all_text
        assert "Actividad de ensayo 13" in all_text
        assert "Control verificable 13" in " ".join(all_text.split()), (
            [line for line in all_text.splitlines() if
             "Control" in line or "verific" in line or "13" in line][-30:])
        assert "Firma" in all_text
        embedded = sum(len(page.get_images(full=True)) for page in pdf)
        assert embedded >= 5, f"Imágenes originales ausentes: {embedded}"


def test_five_reviewed_html_blocks_print_as_actual_text_without_unsafe_html():
    blocks = [
        {"title": f"Normas generales {i}",
         "text": f"NORMA EDITABLE NUMERO {i}\n"
                 f"Comprobación de controles y casillas \N{BALLOT BOX} {i}\n"
                 "Contenido preventivo sintético para ensayo de impresión."}
        for i in range(1, 6)
    ]
    source = {
        "status": "approved",
        "images": _images(),
        "approved_editable_blocks": blocks,
        "approved_editor_revision": 1,
        "document_code": "DPR-IRL-03",
    }
    payload = render_native_pdf("irl", _data(), matrix=_matrix(), original_source=source)
    with _read_pdf(payload) as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        for i in range(1, 6):
            assert f"NORMA EDITABLE NUMERO {i}" in text
        assert "Control verificable 13" in " ".join(text.split()), (
            [line for line in text.splitlines() if
             "Control" in line or "verific" in line or "13" in line][-30:])
        assert "<script>" not in text
        assert "alert(" not in text
        assert "Firma" in text
