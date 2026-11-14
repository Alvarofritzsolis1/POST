"""Regresión de aislamiento documental y generación de IRL.

No utiliza datos personales del entorno real: empresas y personas sintéticas.
"""
from types import SimpleNamespace

import fitz
from sqlalchemy import func, select

from app import javiera_v166_api
from app.javiera_logic import normalize_cargo
from app.javiera_v194_api import lookup_role
from app.javiera_workbook import resolve_workbook_role
from app.ops_models import Contractor, ContractorWorksite, Worker, WorkerAssignment
from test_control_api import env, login, create_company
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
    marker = SimpleNamespace(revision=7)
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



def test_corrected_existing_contractor_and_worker_refresh_without_duplicate_registration(env):
    """Regression for an existing company/worker corrected after first preparation."""
    client, sessions = env
    admin = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    op_company = create_company(client, admin, site, "CT", "EMPRESA EXISTENTE QA")
    op_person = client.post("/api/v1/ops/workers", headers=admin, json={
        "site_id": site, "contractor_id": op_company["contractor_id"],
        "name": "RENE ANTIGUO QA", "rut": rut(11333555),
    })
    assert op_person.status_code == 201
    company_request = {"site_id": site, "origin": "operational",
                       "source_id": op_company["contractor_id"]}
    linked_company = client.post(BASE + "/companies", headers=admin, json=company_request)
    assert linked_company.status_code == 200
    person_request = {"company_id": linked_company.json()["id"],
                      "origin": "operational",
                      "source_id": op_person.json()["worker_id"]}
    linked_person = client.post(BASE + "/people", headers=admin, json=person_request)
    assert linked_person.status_code == 200

    with sessions.begin() as db:
        company = db.get(Contractor, op_company["contractor_id"])
        person = db.get(Worker, op_person.json()["worker_id"])
        company.name = "EMPRESA CORREGIDA QA"
        person.name = "RENE CORREGIDO QA"
    with sessions() as db:
        before = _operational_count(db)
    company_again = client.post(BASE + "/companies", headers=admin, json=company_request)
    person_again = client.post(BASE + "/people", headers=admin, json=person_request)
    assert company_again.status_code == person_again.status_code == 200
    assert company_again.json()["id"] == linked_company.json()["id"]
    assert person_again.json()["id"] == linked_person.json()["id"]
    assert company_again.json()["name"] == "EMPRESA CORREGIDA QA"
    assert person_again.json()["name"] == "RENE CORREGIDO QA"
    with sessions() as db:
        assert _operational_count(db) == before



def test_existing_legacy_dossier_fields_survive_documental_copy_and_second_edit(env):
    client, _ = env
    admin = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    company = create_company(client, admin, site, "CT", "EMPRESA PREVIA QA")
    worker = client.post("/api/v1/ops/workers", headers=admin, json={
        "site_id": site, "contractor_id": company["contractor_id"],
        "name": "RENE PREVIO QA", "rut": rut(11333444)})
    assert worker.status_code == 201
    legacy = client.post("/api/v1/javiera/dossiers", headers=admin, json={
        "site_id": site, "employer_id": company["contractor_id"],
        "worker_id": worker.json()["worker_id"], "relationship": "contractor",
        "data": {
            "role": "TECHUMBRE", "extra": {"employer_commune": "CONCEPCION"},
            "contract": {"salary": "750000", "start": "2026-11-01"},
        },
    })
    assert legacy.status_code == 200, legacy.text
    local_company = client.post(BASE + "/companies", headers=admin, json={
        "site_id": site, "origin": "operational", "source_id": company["contractor_id"]})
    assert local_company.status_code == 200
    local_worker = client.post(BASE + "/people", headers=admin, json={
        "company_id": local_company.json()["id"], "origin": "operational",
        "source_id": worker.json()["worker_id"]})
    assert local_worker.status_code == 200
    values = {
        "site_id": site, "company_id": local_company.json()["id"],
        "person_id": local_worker.json()["id"], "relationship": "contractor",
        "selected_codes": ["irl"], "shared": {
            "role": "TECHUMBRE", "event": {"date": "2026-11-14"},
        }, "document_data": {"irl": {}},
    }
    local = client.post(BASE + "/dossiers", headers=admin, json=values)
    assert local.status_code == 200, local.text
    assert local.json()["shared"]["contract"]["salary"] == "750000"
    assert local.json()["shared"]["extra"]["employer_commune"] == "CONCEPCION"
    changed = client.post(BASE + "/dossiers", headers=admin, json={
        **values, "dossier_id": local.json()["id"],
        "expected_revision": local.json()["revision"],
        "shared": {"role": "TECHUMBRE", "event": {"date": "2026-11-15"}},
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["shared"]["extra"]["employer_commune"] == "CONCEPCION"
    assert changed.json()["shared"]["contract"]["salary"] == "750000"
    assert client.get("/api/v1/javiera/dossiers/" + legacy.json()["id"]).status_code == 200



def test_provisional_company_created_by_legacy_javiera_can_be_formalized_once(env):
    """Existing accidental registration becomes a formal CT without duplicates."""
    client, sessions = env
    admin = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    company_data = {
        "site_id": site, "name": "EMPRESA DOCUMENTAL PROVISIONAL QA",
        "rut": rut(78444777), "nature": "unclassified",
        "frequency": "unclassified", "historical_code": "",
        "contract_status": "active",
    }
    provisional = client.post("/api/v1/ops/contractors", headers=admin, json=company_data)
    assert provisional.status_code == 201, provisional.text
    identity = provisional.json()["contractor_id"]
    worker = client.post("/api/v1/ops/workers", headers=admin, json={
        "site_id": site, "contractor_id": identity,
        "name": "RENE DOCUMENTAL QA", "rut": rut(11444999),
    })
    assert worker.status_code == 201
    dossier = client.post("/api/v1/javiera/dossiers", headers=admin, json={
        "site_id": site, "employer_id": identity,
        "worker_id": worker.json()["worker_id"], "relationship": "contractor",
        "data": {"role": "TECHUMBRE", "event": {"date": "2026-11-14"}},
    })
    assert dossier.status_code == 200, dossier.text
    with sessions() as db:
        before = _operational_count(db)

    formal = client.post("/api/v1/ops/contractors", headers=admin, json={
        **company_data, "name": "EMPRESA DOCUMENTAL CORREGIDA QA",
        "nature": "with_workers", "frequency": "fixed",
        "historical_code": "QA-FORMAL-1",
    })
    assert formal.status_code == 201, formal.text
    assert formal.json()["contractor_id"] == identity
    assert formal.json()["name"] == "EMPRESA DOCUMENTAL CORREGIDA QA"
    assert formal.json()["historical_code"] == "QA-FORMAL-1"
    with sessions() as db:
        assert _operational_count(db) == before
    duplicate = client.post("/api/v1/ops/contractors", headers=admin, json={
        **company_data, "nature": "with_workers", "frequency": "fixed",
        "historical_code": "QA-FORMAL-1",
    })
    assert duplicate.status_code == 409


def test_without_legacy_dossier_no_automatic_formalization(env):
    client, _ = env
    admin = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    data = {
        "site_id": site, "name": "PROVISORIA SIN EXPEDIENTE QA",
        "rut": rut(78444776), "nature": "unclassified",
        "frequency": "unclassified", "historical_code": "",
        "contract_status": "active",
    }
    provisional = client.post("/api/v1/ops/contractors", headers=admin, json=data)
    assert provisional.status_code == 201
    formal = client.post("/api/v1/ops/contractors", headers=admin, json={
        **data, "nature": "with_workers", "frequency": "fixed",
    })
    assert formal.status_code == 409
