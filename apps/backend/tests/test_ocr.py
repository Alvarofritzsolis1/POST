import fitz
from types import SimpleNamespace
from PIL import Image
from app.ocr import _novel_ocr_lines, analyze, read_pdf_page, run_tesseract
from app.rules import REVIEW, assess_document

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


def test_sideways_scan_uses_tesseract_clockwise_rotation(monkeypatch):
    with fitz.open() as pdf:
        page = pdf.new_page()
        for i in range(5):
            page.insert_text((40, 70 + i * 45), "PREVIRED COMPROBANTE DE PAGO", fontsize=18)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    sideways = image.rotate(270, expand=True)
    monkeypatch.setattr("app.ocr.pytesseract.image_to_osd", lambda *_args, **_kwargs: {"rotate": 270})
    result = run_tesseract(sideways, 1)
    assert "COMPROBANTE DE PAGO" in result["text"]
    assert result["rotation_degrees_ccw"] == 90


def test_second_opinion_keeps_primary_and_receives_oriented_image(monkeypatch):
    primary = {"page": 1, "method": "tesseract", "confidence": 40.0,
               "text": "Cotizaciones periodo 09/2026", "tokens": [], "rotation_degrees_ccw": 90}
    seen = {}
    monkeypatch.setattr("app.ocr.settings", lambda: SimpleNamespace(ocr_secondary="rapidocr"))
    monkeypatch.setattr("app.ocr.run_tesseract", lambda *_args: primary)
    def secondary(image, _page):
        seen["size"] = image.size
        return {"page": 1, "method": "rapidocr", "confidence": 99.9,
                "text": "Otra lectura mucho más larga de cotizaciones", "tokens": []}
    monkeypatch.setattr("app.ocr.rapidocr_optional", secondary)
    from app.ocr import scanned_page
    result = scanned_page(Image.new("RGB", (100, 200)), 1)
    assert result["method"] == "tesseract"
    assert result["alternatives"][0]["method"] == "rapidocr"
    assert seen["size"] == (200, 100)


def test_hybrid_does_not_duplicate_native_lines():
    native = "Periodo: 10/2026\nEstado: Pagado"
    scanned = "Período: 10/2026\nEstado: Pagado\nFolio: ABC123456"
    assert _novel_ocr_lines(native, scanned) == ["Folio: ABC123456"]
    assert _novel_ocr_lines(native, "NO\nPAGO") == ["NO", "PAGO"]


def test_short_negative_from_hybrid_ocr_is_preserved(monkeypatch):
    native = ("PREVIRED COMPROBANTE DE PAGO\nPeriodo: 10/2026\n"
              "Folio: ABCD123456\nEstado: Pagado\nDocumento con texto digital adicional suficiente.")
    monkeypatch.setattr("app.ocr.native_page", lambda *_args: {
        "page": 1, "method": "texto-nativo", "confidence": None, "text": native,
        "tokens": [], "page_size_pt": [612, 792]})
    monkeypatch.setattr("app.ocr.image_coverage", lambda *_args: 1.0)
    monkeypatch.setattr("app.ocr.rasterize", lambda *_args: Image.new("RGB", (10, 10)))
    monkeypatch.setattr("app.ocr.scanned_page", lambda *_args: {
        "page": 1, "method": "tesseract", "confidence": 80.0,
        "text": "NO\nPAGO", "tokens": []})
    result = read_pdf_page(object(), 1)
    assert "NO\nPAGO" in result["text"]
    assert assess_document([result], "cotizaciones")["payment_status"] == REVIEW
