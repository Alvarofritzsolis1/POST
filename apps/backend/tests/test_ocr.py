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
