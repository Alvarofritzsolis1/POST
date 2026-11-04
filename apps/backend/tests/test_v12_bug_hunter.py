"""GALANT 12.0 — regression tests for reproducible hidden business-rule bugs.

The tests exercise the public API with synthetic in-memory database data.
No production or external services are touched.
"""
from datetime import timedelta

from sqlalchemy import select

from app.control_api import today
from app.models import Document, User
from app.ops_models import ContractorWorksite, WorkerAssignment
from test_control_api import env, login, create_company
from test_platform import rut


def test_v12_ci_site_blocks_labor_intake_even_when_shared_company_is_ct_elsewhere(env):
    client, _ = env
    head = login(client, "a@example.cl")
    sites = client.get("/api/v1/ops/sites").json()[:2]
    assert len(sites) == 2
    company_rut = rut(24440123)
    name = "Empresa multisitio con naturaleza compartida"
    ct = client.post("/api/v1/ops/contractors", headers=head, json={
        "site_id": sites[0]["id"], "name": name, "rut": company_rut,
        "historical_code": "CT", "nature": "with_workers",
        "frequency": "fixed",
    })
    assert ct.status_code == 201, ct.text
    ci = client.post("/api/v1/ops/contractors", headers=head, json={
        "site_id": sites[1]["id"], "name": name, "rut": company_rut,
        "historical_code": "CI", "nature": "with_workers",
        "frequency": "unclassified",
    })
    assert ci.status_code == 201, ci.text
    options = client.get("/api/v1/labor/contractors", params={"site_id":sites[1]["id"]})
    assert options.status_code == 200
    independent = next(x for x in options.json() if x["contractor_id"] == ct.json()["contractor_id"])
    assert independent["classification"] == "CI"
    assert independent["nature"] == "independent"
    created = client.post("/api/v1/labor/workers", headers=head, json={
        "site_id": sites[1]["id"],
        "contractor_id": ci.json()["contractor_id"],
        "name": "Trabajador prohibido",
        "rut": rut(14556020),
        "contract": {"contract_type":"indefinite", "start_date":str(today())},
    })
    assert created.status_code == 422, created.text
    allowed = client.post("/api/v1/labor/workers", headers=head, json={
        "site_id": sites[0]["id"],
        "contractor_id": ct.json()["contractor_id"],
        "name": "Trabajador CT",
        "rut": rut(14556021),
        "contract": {"contract_type":"indefinite", "start_date":str(today())},
    })
    assert allowed.status_code == 201, allowed.text
    invalid_code = client.patch(f"/api/v1/ops/contractors/{ct.json()['id']}", headers=head,
                                json={"historical_code":"CI"})
    assert invalid_code.status_code == 409, invalid_code.text
    after = client.get("/api/v1/ops/contractors", params={"site_id":sites[0]["id"]}).json()
    assert next(x for x in after if x["id"] == ct.json()["id"])["classification"] == "CT"


def test_v12_ci_legacy_assignment_cannot_receive_a_new_contract(env):
    client, sessions = env
    head = login(client, "a@example.cl")
    site_id = client.get("/api/v1/ops/sites").json()[0]["id"]
    ct = create_company(client, head, site_id, "CT", "CT con registro heredado")
    worker = client.post("/api/v1/labor/workers", headers=head, json={
        "site_id": site_id, "contractor_id": ct["contractor_id"],
        "name": "Trabajador existente", "rut": rut(14555018),
        "contract": {"contract_type":"indefinite", "start_date":str(today()-timedelta(days=20))},
    })
    assert worker.status_code == 201, worker.text
    with sessions.begin() as db:
        association = db.get(ContractorWorksite, ct["id"])
        association.historical_code = "CI"  # Simulates a corrupt legacy import.
    response = client.post("/api/v1/labor/contracts", headers=head, json={
        "assignment_id": worker.json()["assignment_id"], "contract_type":"indefinite",
        "start_date":str(today()+timedelta(days=1)),
    })
    assert response.status_code == 422, response.text


def test_v12_inactive_current_month_cannot_link_new_monthly_document(env):
    client, sessions = env
    head = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    company = create_company(client, head, site, "CT", "Empresa dada de baja")
    with sessions.begin() as db:
        owner = db.scalar(select(User).where(User.email=="a@example.cl"))
        doc = Document(org_id=owner.org_id, user_id=owner.id,
            original_name="respaldo_sintetico.pdf", storage_path="/tmp/no-real-test.pdf",
            sha256="c"*64, declared_type="cotizaciones", status="complete",
            extracted={}, evidence=[], warnings=[])
        db.add(doc)
        db.flush()
        doc_id=doc.id
    old_period=(today().replace(day=1)-timedelta(days=1)).strftime("%Y-%m")
    current_period=today().strftime("%Y-%m")
    historical = client.post("/api/v1/ops/monthly-documents", headers=head, json={
        "association_id":company["id"], "period":old_period,
        "kind":"cotizaciones", "document_id":doc_id,
    })
    assert historical.status_code == 201, historical.text
    changed=client.patch(f"/api/v1/ops/contractors/{company['id']}", headers=head,
                         json={"contract_status":"inactive"})
    assert changed.status_code == 200, changed.text
    forbidden=client.post("/api/v1/ops/monthly-documents", headers=head, json={
        "association_id":company["id"], "period":current_period,
        "kind":"cotizaciones", "document_id":doc_id,
    })
    assert forbidden.status_code == 422, forbidden.text
    previous=client.get("/api/v1/ops/monthly-documents", params={
        "association_id":company["id"], "period":old_period,
    })
    assert previous.status_code == 200
    assert previous.json()[0]["id"] == historical.json()["id"]
    # Historical observations remain available after the offboarding.
    approved = client.patch(f"/api/v1/ops/monthly-documents/{historical.json()['id']}",
                            headers=head, json={"review_status":"approved","notes":"Histórico"})
    assert approved.status_code == 200, approved.text


def test_v12_ci_with_unclassified_legacy_frequency_does_not_trigger_false_alert(env):
    client, _ = env
    head = login(client, "a@example.cl")
    site_id = client.get("/api/v1/ops/sites").json()[0]["id"]
    ci=client.post("/api/v1/ops/contractors", headers=head, json={
        "site_id":site_id,"name":"CI sin frecuencia heredada",
        "historical_code":"CI","nature":"independent","frequency":"unclassified",
    })
    assert ci.status_code == 201, ci.text
    response = client.get("/api/v1/labor/alerts",params={"site_id":site_id,"period":today().strftime("%Y-%m")})
    assert response.status_code == 200,response.text
    assert not any(a["kind"] == "classification" and a["target_id"] == ci.json()["id"]
                   for a in response.json()["alerts"])
