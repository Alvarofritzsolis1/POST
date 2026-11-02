import hashlib
import json
import stat

import fitz
import pytest

from app.pipeline import extraction_path, process_document


def test_ocr_is_persisted_and_reanalysis_uses_saved_text(tmp_path, monkeypatch):
    path = tmp_path / "cotizaciones.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        for i, line in enumerate(("PREVIRED COMPROBANTE DE PAGO", "Periodo: 10/2026",
                                  "Folio: ABCD123456", "Estado: Pagado")):
            page.insert_text((30, 60 + 30 * i), line)
        pdf.save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    first = process_document(path, "cotizaciones", digest)
    cache = extraction_path(path)
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["source_sha256"] == digest
    assert data["pages"][0]["text"].startswith("PREVIRED")
    assert data["pages"][0]["tokens"]
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    assert first["extracted"]["ocr_reutilizado"] is False

    def no_ocr(*_args, **_kwargs):
        raise AssertionError("El OCR se ejecutó de nuevo")

    monkeypatch.setattr("app.pipeline.extract_document", no_ocr)
    second = process_document(path, "cotizaciones", digest)
    assert second["extracted"]["ocr_reutilizado"] is True
    assert second["payment_status"] == first["payment_status"]
    assert second["extracted"]["tiempo_ocr_s"] == 0
    assert process_document(path, "f30_1", digest)["payment_status"] == "Documento incorrecto"
    with pytest.raises(ValueError, match="cambió"):
        process_document(path, "cotizaciones", "0" * 64)


def test_invalid_cache_reextracts(tmp_path, monkeypatch):
    path = tmp_path / "doc.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((30, 50), "F30-1 Certificado de cumplimiento de obligaciones laborales")
        pdf.save(path)
    process_document(path)
    data = json.loads(extraction_path(path).read_text(encoding="utf-8"))
    data["engine_version"] = -1
    extraction_path(path).write_text(json.dumps(data), encoding="utf-8")
    result = process_document(path)
    assert result["extracted"]["ocr_reutilizado"] is False
    data = json.loads(extraction_path(path).read_text(encoding="utf-8"))
    data["pages"] = [{}]
    extraction_path(path).write_text(json.dumps(data), encoding="utf-8")
    result = process_document(path)
    assert result["extracted"]["ocr_reutilizado"] is False
    assert result["page_count"] == 1
