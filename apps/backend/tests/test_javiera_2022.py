"""GALANT 20.2.2: errores de plantilla antes de la emisión y fechas no ambiguas.
Se usan exclusivamente expedientes y PDFs sintéticos.
"""
import io
from datetime import date
from types import SimpleNamespace

import fitz
from openpyxl import Workbook

from app.javiera_excel import LayoutError
from app.javiera_layout_api import source_leaks
from app import javiera_api
from test_control_api import env, login
from test_javiera_full_workflow import _dossier


def sample_dates():
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos Contrato"
    ws["C36"] = (date(2026, 5, 10) - date(1899, 12, 30)).days
    ws["C40"] = (date(2026, 6, 15) - date(1899, 12, 30)).days
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def pdf_date_text(value):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), value, fontsize=12)
    result = doc.tobytes()
    doc.close()
    return result


def test_legitimate_repeated_date_is_not_a_false_sample_leak():
    data = {
        "contract": {"start": "2026-05-01", "end": "2026-06-15"},
        "event": {"date": "2026-05-10"},
        "extra": {},
    }
    assert source_leaks(sample_dates(), pdf_date_text("10/05/2026 y 15/06/2026"), data) == []


def test_unexplained_old_date_is_still_blocked():
    data = {
        "contract": {"start": "2026-05-01", "end": "2026-06-01"},
        "event": {"date": "2026-05-02"},
        "extra": {},
    }
    assert source_leaks(sample_dates(), pdf_date_text("10/05/2026"), data) == ["C36"]
    assert source_leaks(sample_dates(), pdf_date_text("15/06/2026"), data) == ["C40"]


def test_preflight_reports_exact_cells_without_issuing(env, monkeypatch):
    client, sessions = env
    headers = login(client, "a@example.cl")
    ident = _dossier(client, headers)
    sample = {"code": "internal_rules_receipt", "status": "LISTO_PARA_EMITIR",
              "can_issue": True, "reason": "", "missing_fields": [],
              "blocking_errors": [], "can_preview": True}
    monkeypatch.setattr(javiera_api, "evaluated", lambda *a, **kw: [sample])
    monkeypatch.setattr(javiera_api, "active_workbook",
                        lambda *a, **kw: SimpleNamespace(sha256="test", id="master"))
    monkeypatch.setattr(javiera_api, "raw_for", lambda *a: b"x")
    monkeypatch.setattr(javiera_api, "original_for", lambda *a: b"x")
    def fails(*args, **kwargs):
        raise LayoutError(
            "El PDF conserva datos del ejemplo en Datos Contrato!C36, C40. Revisa sus referencias.")
    monkeypatch.setattr(javiera_api, "cached_pdf", fails)
    result = client.post("/api/v1/javiera/eligibility/preflight", headers=headers,
                         json={"dossier_id": ident, "codes": ["internal_rules_receipt"]})
    assert result.status_code == 200, result.text
    item = result.json()["documents"][0]
    assert item["status"] == "BLOQUEADO_PLANTILLA"
    assert item["can_issue"] is False
    assert item["source_cells"] == ["C36", "C40"]
    # La comprobación no registra una emisión.
    assert client.get("/api/v1/javiera/dossiers/" + ident).json()["issues"] == []


def test_preflight_validates_selection_and_preserves_incomplete_status(env, monkeypatch):
    client, sessions = env
    headers = login(client, "a@example.cl")
    ident = _dossier(client, headers)
    item = {"code": "internal_rules_receipt", "status": "FALTAN_DATOS",
            "can_issue": False, "reason": "Falta event.date",
            "missing_fields": ["event.date"], "blocking_errors": []}
    monkeypatch.setattr(javiera_api, "evaluated", lambda *a, **kw: [item])
    blocked = client.post("/api/v1/javiera/eligibility/preflight", headers=headers,
                          json={"dossier_id": ident, "codes": ["internal_rules_receipt"]})
    assert blocked.status_code == 200
    assert blocked.json()["documents"][0]["status"] == "FALTAN_DATOS"
    duplicate = client.post("/api/v1/javiera/eligibility/preflight", headers=headers,
                            json={"dossier_id": ident, "codes": ["internal_rules_receipt",
                                                                "internal_rules_receipt"]})
    assert duplicate.status_code == 422
