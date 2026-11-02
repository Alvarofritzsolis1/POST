import fitz
from app.ocr import analyze

def test_native_pdf(tmp_path):
    target = tmp_path / "recibo.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        for i, line in enumerate([
            "PREVIRED COMPROBANTE DE PAGO DE COTIZACIONES PREVISIONALES",
            "Periodo de remuneraciones: 10/2026",
            "Folio: A123456789",
            "Estado: Pagado",
            "RUT empleador: 12.345.678-5",
            "Documento digital con texto seleccionable para verificacion documental."
        ]):
            page.insert_text((30, 55 + i * 24), line)
        pdf.save(target)
    result = analyze(target, "cotizaciones")
    assert result["page_count"] == 1
    assert result["detected_type"] == "cotizaciones"
    assert result["extracted"]["periodo"] == "2026-10"
    assert "12345678-5" in result["extracted"]["ruts_validos"]
    assert result["extracted"]["verificacion_externa"] is False
    assert result["evidence"][0]["pagina"] == 1


def test_scanned_pdf_uses_real_tesseract(tmp_path):
    """PDF raster: no tiene texto seleccionable y debe recorrer OCR real."""
    target = tmp_path / "scan.pdf"
    with fitz.open() as original:
        page = original.new_page()
        page.insert_text((45, 80), "PREVIRED COMPROBANTE DE PAGO", fontsize=19)
        page.insert_text((45, 130), "Periodo: 10/2026", fontsize=19)
        page.insert_text((45, 180), "Folio: ABCD123456", fontsize=19)
        page.insert_text((45, 230), "Estado: Pagado", fontsize=19)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB, alpha=False)
        image_bytes = pix.tobytes("png")
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_image(page.rect, stream=image_bytes)
        pdf.save(target)
    with fitz.open(target) as pdf:
        assert not pdf[0].get_text("text").strip()
    result = analyze(target, "cotizaciones")
    assert result["page_count"] == 1
    assert "tesseract" in result["evidence"][0]["motor"]
    assert len(result["evidence"][0]["extracto"]) > 20
    assert result["extracted"]["verificacion_externa"] is False
