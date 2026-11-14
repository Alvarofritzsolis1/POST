"""Regresión de aislamiento documental y generación de IRL.

No utiliza datos personales del entorno real: empresas y personas sintéticas.
"""
import io

import fitz
from sqlalchemy import func, select

from app import javiera_v166_api
from app.javiera_logic import normalize_cargo
from app.javiera_v194_api import lookup_role
from app.javiera_workbook import resolve_workbook_role
from app.ops_models import Contractor, ContractorWorksite, Worker, WorkerAssignment
from test_control_api import env, login
from test_platform import rut


BASE = "/api/v1/javiera/v166"


def _operational_count(db):
    return tuple(db.scalar(select(func.count(model.id))) for model in
                 (Contractor, ContractorWorksite, Worker, WorkerAssignment))


def test_new_documental_identity_cannot_register_operational_companies_or_workers(env):
    client, sessions = env
    admin = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    with sessions() as db:
        before = _operational_count(db)
    firm = client.post(BASE + "/companies", headers=admin, json={
        "site_id": site, "origin": "new", "name": "EMPRESA TECHUMBRE QA",
        "rut": rut(10888555),
    })
    assert firm.status_code == 200, firm.text
    person = client.post(BASE + "/people", headers=admin, json={
        "company_id": firm.json()["id"], "origin": "new",
        "name": "RENE EJEMPLO QA", "rut": rut(10222333),
    })
    assert person.status_code == 200, person.text
    record = client.post(BASE + "/dossiers", headers=admin, json={
        "site_id": site, "company_id": firm.json()["id"],
        "person_id": person.json()["id"], "relationship": "contractor",
        "selected_codes": ["irl"], "shared": {
            "role": "TECHUMBRE", "event": {"date": "2026-11-14"}
        }, "document_data": {"irl": {}}
    })
    assert record.status_code == 200, record.text
    with sessions() as db:
        assert _operational_count(db) == before
    assert person.json()["origin"] == firm.json()["origin"] == "documentary"


def test_documental_refresh_on_local_identity_is_safe(env):
    client, _ = env
    admin = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    firm = client.post(BASE + "/companies", headers=admin, json={
        "site_id": site, "origin": "new",
        "name": "EMPRESA SOLO DOCUMENTAL", "rut": rut(10888555)})
    assert firm.status_code == 200
    forbidden = client.post(BASE + "/companies/" + firm.json()["id"] +
                            "/refresh-source", headers=admin)
    assert forbidden.status_code == 422
    assert "edita" in forbidden.text


def test_techumbre_is_reliably_linked_to_thirteen_techador_risks():
    assert normalize_cargo("TECHUMBRE") == "TECHADOR"
    assert normalize_cargo("TECHUMBRES") == "TECHADOR"
    assert resolve_workbook_role(
        {"TECHADOR": {"IRL": [54, 55]}}, "TECHUMBRE", "IRL") == "TECHADOR"
    resolved = lookup_role("TECHUMBRE")
    assert resolved is not None
    role, risks = resolved
    assert role == "TECHADOR"
    assert len(risks) == 13
    assert len({r["excel_row"] for r in risks}) == 13
    assert all(all(r[key].strip() for key in ("tarea", "peligro", "riesgo", "medidas"))
               for r in risks)


def test_documentary_pdf_uses_published_workbook_engine(monkeypatch, tmp_path):
    marker = object()
    fake_pdf = fitz.open()
    fake_pdf.new_page().insert_text((60, 60), "IRL TECHADOR - PRUEBA")
    expected = fake_pdf.tobytes()
    fake_pdf.close()
    paths = {}
    monkeypatch.setattr(javiera_v166_api, "active_workbook", lambda *a, **k: marker)
    monkeypatch.setattr(javiera_v166_api, "raw_for", lambda obj: b"workbook-qa")
    monkeypatch.setattr(javiera_v166_api, "original_for", lambda db, obj: b"source-qa")
    monkeypatch.setattr(javiera_v166_api, "root_for", lambda org: tmp_path)
    def fake_cache(raw, code, data, org, cache, preview, reference=None):
        paths.update(raw=raw, code=code, role=data["role"],
                     preview=preview, reference=reference)
        return expected, {"matrix_verified": True}
    monkeypatch.setattr(javiera_v166_api, "cached_pdf", fake_cache)
    output, revision, engine = javiera_v166_api._build_pdf(
        None, type("User", (), {"org_id": "test"})(),
        None, "irl", {"role": "TECHUMBRE"}, preview=True)
    assert output == expected
    assert engine == "workbook"
    assert paths == {"raw": b"workbook-qa", "code": "irl", "role": "TECHUMBRE",
                     "preview": True, "reference": b"source-qa"}
