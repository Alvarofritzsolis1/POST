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
    # Aunque el campo nuevo venga vacío, no se debe conservar un dato ficticio.
    data["contract"]["start"] = ""
    assert source_leaks(sample_dates(), pdf_date_text("10/05/2026"), data) == ["C36"]


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


def geo_master(sample_commune="CONCEPCION", worker_commune="LOTA"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos Contrato"
    ws["C11"] = sample_commune
    ws["C23"] = worker_commune
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def test_comuna_repetida_en_obra_o_ciudad_no_es_una_fuga_de_datos():
    data = {"extra": {
        "employer_commune": "SAN PEDRO DE LA PAZ",
        "employer_city": "CONCEPCION",
        "worker_commune": "CORONEL",
    }, "site": {"name": "OBRA EN CONCEPCION"}}
    pdf = pdf_date_text("REGLAMENTO INTERNO OBRA EN CONCEPCION")
    assert source_leaks(geo_master(), pdf, data) == []


def test_comuna_fija_identificada_como_empleador_sigue_bloqueada():
    data = {"extra": {
        "employer_commune": "SAN PEDRO DE LA PAZ",
        "employer_city": "CONCEPCION",
        "worker_commune": "CORONEL",
    }, "site": {"name": "OBRA EN CONCEPCION"}}
    pdf = pdf_date_text("COMUNA DE LA EMPRESA: CONCEPCION")
    assert source_leaks(geo_master(), pdf, data) == ["C11"]


def test_comuna_obsoleta_que_no_corresponde_a_ningun_dato_se_bloquea():
    data = {"extra": {
        "employer_commune": "SAN PEDRO DE LA PAZ",
        "employer_city": "TALCAHUANO",
        "worker_commune": "CORONEL",
    }, "site": {"name": "BRISAS DE JUNQUILLAR"}}
    assert source_leaks(geo_master(), pdf_date_text("COMUNA: CONCEPCION"), data) == ["C11"]


def test_comuna_corta_no_se_confunde_con_fragmentos_de_otras_palabras():
    data = {"extra":{"employer_commune":"CORONEL","worker_commune":"SAN PEDRO"},
            "site":{"name":"BRISAS DE JUNQUILLAR"}}
    raw = geo_master(sample_commune="LOTA", worker_commune="")
    assert source_leaks(raw, pdf_date_text("JUGADOR DE PELOTA"), data) == []
    assert source_leaks(raw, pdf_date_text("COMUNA: LOTA"), data) == ["C11"]


def test_rut_no_se_fabrica_al_concatenar_numeros_distintos_en_pdf():
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos Contrato"
    ws["C6"] = "12345678-9"
    output = io.BytesIO()
    wb.save(output)
    data = {"employer": {"rut":"87654321-0"}}
    assert source_leaks(output.getvalue(), pdf_date_text("NUMEROS 1234 ABCD 56789"), data) == []
    assert source_leaks(output.getvalue(), pdf_date_text("RUT: 12.345.678-9"), data) == ["C6"]


def test_receipt_exige_comuna_antes_de_generar_pdf():
    from app.javiera_logic import LAYOUT_REQUIRED
    assert "extra.employer_commune" in LAYOUT_REQUIRED["internal_rules_receipt"]
