from app.rules import PAID, REVIEW, WRONG, assess_document, document_type, extract_ruts, period_from_text, valid_rut

def page(text, confidence=None, n=1):
    return {"page": n, "method": "synthetic", "confidence": confidence, "text": text, "tokens": []}

def test_rut():
    assert valid_rut("12.345.678-5")
    assert not valid_rut("12.345.678-4")
    assert "12345678-5" in extract_ruts("RUT 12.345.678-5")

def test_periodo():
    assert period_from_text("Periodo de remuneraciones: 10/2026") == "2026-10"
    assert period_from_text("Mes de cotizaciones: octubre de 2026") == "2026-10"
    assert period_from_text("Fecha de pago: 25/11/2026") is None

def test_comprobante():
    text = "PREVIRED COMPROBANTE DE PAGO\nPeriodo: 10/2026\nFolio: A123456\nEstado: Pagado\n"
    result = assess_document([page(text)], "cotizaciones")
    assert result["payment_status"] == PAID
    assert result["extracted"]["verificacion_externa"] is False

def test_solo_palabra_pagado_es_insuficiente():
    assert assess_document([page("AFP Cotizaciones\nEstado: Pagado\nPeriodo: 10/2026")], "cotizaciones")["payment_status"] == REVIEW

def test_evidencia_de_paginas_distintas_no_aprueba():
    a = page("PREVIRED COMPROBANTE DE PAGO\nPeriodo: 10/2026")
    b = page("Folio: ABC12345\nEstado: Pagado AFP", n=2)
    assert assess_document([a, b], "cotizaciones")["payment_status"] == REVIEW

def test_declaracion_sin_pago():
    text = "PREVIRED COMPROBANTE DE PAGO\nFolio: 123456\nPeriodo: 10/2026\nEstado: Pagado\nDECLARACION Y NO PAGO"
    assert assess_document([page(text)], "cotizaciones")["payment_status"] == REVIEW

def test_confianza_baja():
    text = "PREVIRED COMPROBANTE DE PAGO\nFolio: 123456\nPeriodo: 10/2026\nEstado: Pagado"
    assert assess_document([page(text, 52)], "cotizaciones")["payment_status"] == REVIEW

def test_f301_separado():
    text = "Certificado de cumplimiento de obligaciones laborales F30-1 Periodo: 10/2026"
    assert document_type(text) == "f30_1"
    assert assess_document([page(text)], "f30_1")["payment_status"] == REVIEW
    assert assess_document([page(text)], "cotizaciones")["payment_status"] == WRONG
