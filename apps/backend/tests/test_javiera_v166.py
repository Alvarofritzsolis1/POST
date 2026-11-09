"""Regression: document preparation must never create operational personnel or companies."""
import fitz
from sqlalchemy import func, select
from app.javiera_models import JavieraTemplate
from app.javiera_v166_models import JavieraLocalCompany, JavieraLocalPerson, JavieraLocalIssue
from app.models import User
from app.ops_models import Contractor, Worker, WorkerAssignment
from test_control_api import env, login, create_company
from test_platform import rut

BASE = "/api/v1/javiera/v166"


def setup_dossier(client, headers, company="Empresa documental de prueba"):
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    original = client.post(BASE + "/companies", headers=headers, json={
        "site_id": site, "origin": "new", "name": company, "rut": rut(10000111)})
    assert original.status_code == 200, original.text
    firm = original.json()
    employee = client.post(BASE + "/people", headers=headers, json={
        "company_id": firm["id"], "origin": "new", "name": "Persona Documental Sintética",
        "rut": rut(10000112)})
    assert employee.status_code == 200, employee.text
    person = employee.json()
    payload = {"site_id": site, "company_id": firm["id"], "person_id": person["id"],
               "relationship": "contractor", "selected_codes": [
                   "labor_contract", "transfer_addendum"],
               "shared": {"role": "CARPINTERO", "employment_type": "dependiente",
                          "contract": {"salary": "900000", "start": "2026-11-08",
                                       "hours": "42"}},
               "document_data": {"labor_contract": {"event": {"date": "2026-11-08"}},
                                 "transfer_addendum": {
                                     "contract": {"transfer_date": "2026-11-09"}}}}
    record = client.post(BASE + "/dossiers", headers=headers, json=payload)
    assert record.status_code == 200, record.text
    return firm, person, record.json(), payload


def test_documentary_identity_is_not_a_worker_or_contractor(env):
    client, sessions = env
    headers = login(client, "a@example.cl")
    with sessions() as db:
        previous = {cls.__name__: db.scalar(select(func.count(cls.id))) for cls in (
            Worker, Contractor, WorkerAssignment)}
    company, person, dossier, _ = setup_dossier(client, headers)
    with sessions() as db:
        after = {cls.__name__: db.scalar(select(func.count(cls.id))) for cls in (
            Worker, Contractor, WorkerAssignment)}
        assert db.get(JavieraLocalCompany, company["id"])
        assert db.get(JavieraLocalPerson, person["id"])
    assert previous == after
    assert dossier["person_name"] == "Persona Documental Sintética"
    assert client.get(BASE + "/dossiers/" + dossier["id"]).status_code == 200

    login(client, "outside@example.cl")
    assert client.get(BASE + "/dossiers/" + dossier["id"]).status_code == 404
    assert client.get(BASE + "/sources?company_id=" + company["id"]).status_code == 404


def test_documentary_multi_issue_packet_reuse_and_immutable_reissue(env):
    client, sessions = env
    headers = login(client, "a@example.cl")
    company, person, doc, payload = setup_dossier(client, headers)
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        for code, event, text in [
            ("labor_contract", "ingreso", "Contrato sintético de prueba"),
            ("transfer_addendum", "traslado", "Anexo sintético de prueba"),
        ]:
            db.add(JavieraTemplate(
                org_id=user.org_id, code=code, area="Zona Subcontratos",
                title=text, body=text + " de {{worker.name}} para {{employer.name}} en {{site.name}}.",
                fields=["worker.name", "employer.name", "site.name"], published_version=1))
    check = client.get(BASE + "/dossiers/" + doc["id"] + "/eligibility")
    assert check.status_code == 200, check.text
    assert all(x["can_issue"] for x in check.json()["documents"]), check.json()
    result = client.post(BASE + "/issue/batch", headers=headers,
                         json={"dossier_id": doc["id"], "codes": payload["selected_codes"]})
    assert result.status_code == 200, result.text
    assert result.json()["issued"] == 2
    pdf = client.get(result.json()["pdf_url"])
    assert pdf.status_code == 200
    with fitz.open(stream=pdf.content, filetype="pdf") as file:
        text = " ".join(page.get_text() for page in file)
        assert len(file) >= 2
        assert "Contrato sintético" in text and "Anexo sintético" in text
    initial_ids = [r["id"] for r in result.json()["results"]]
    repeat = client.post(BASE + "/issue/batch", headers=headers,
                         json={"dossier_id": doc["id"], "codes": payload["selected_codes"]})
    assert repeat.status_code == 200
    assert all(x["reused"] for x in repeat.json()["results"])
    assert [r["id"] for r in repeat.json()["results"]] == initial_ids
    edited = {**payload, "dossier_id": doc["id"], "expected_revision": doc["revision"],
              "shared": {**payload["shared"], "contract": {
                  **payload["shared"]["contract"], "salary": "910000"}}}
    revised = client.post(BASE + "/dossiers", headers=headers, json=edited)
    assert revised.status_code == 200, revised.text
    without_reason = client.post(BASE + "/issue/batch", headers=headers,
                                 json={"dossier_id": doc["id"], "codes": ["labor_contract"]})
    assert without_reason.status_code == 200
    assert without_reason.json()["failed"] == 1
    correction = client.post(BASE + "/issue/batch", headers=headers,
        json={"dossier_id": doc["id"], "codes": ["labor_contract"],
              "reissue_reasons": {"labor_contract": "Se corrigió el sueldo documentado sintético."}})
    assert correction.status_code == 200, correction.text
    assert correction.json()["issued"] == 1
    assert correction.json()["results"][0]["id"] not in initial_ids
    assert client.get(BASE + "/issues/" + initial_ids[0] + "/pdf").status_code == 200
    with sessions() as db:
        assert db.scalar(select(func.count(JavieraLocalIssue.id))) == 3


def test_declaration_is_company_only_and_requires_real_confirmation(env):
    client, _ = env
    headers = login(client, "a@example.cl")
    firm, person, doc, payload = setup_dossier(client, headers)
    impossible = client.post(BASE + "/dossiers", headers=headers, json={
        **payload, "selected_codes": ["sworn_declaration"],
        "person_id": person["id"]})
    assert impossible.status_code == 422
    only_company = client.post(BASE + "/dossiers", headers=headers, json={
        **payload, "selected_codes": ["sworn_declaration"], "person_id": None})
    assert only_company.status_code == 200
    outcome = client.get(BASE + "/dossiers/" + only_company.json()["id"] + "/eligibility")
    status = outcome.json()["documents"][0]
    assert not status["can_issue"]
    assert "ausencia de trabajadores" in status["reason"]


def test_operational_sources_are_read_only_documentary_copies(env):
    client, sessions = env
    admin = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    original = create_company(client, admin, site, "CT", "Empresa Operativa Inmutable")
    created = client.post("/api/v1/ops/workers", headers=admin, json={
        "site_id": site, "contractor_id": original["contractor_id"],
        "name": "Trabajador Operativo Inmutable", "rut": rut(11999888)})
    assert created.status_code == 201, created.text
    source = client.post(BASE + "/companies", headers=admin, json={
        "site_id": site, "origin": "operational", "source_id": original["contractor_id"]})
    assert source.status_code == 200, source.text
    company = source.json()
    person = client.post(BASE + "/people", headers=admin, json={
        "company_id": company["id"], "origin": "operational",
        "source_id": created.json()["worker_id"]})
    assert person.status_code == 200, person.text
    copied = person.json()
    changed_company = client.patch(BASE + "/companies/" + company["id"],
        headers=admin, json={"name": "Razón social solo documental", "rut": rut(76009999)})
    changed_person = client.patch(BASE + "/people/" + copied["id"],
        headers=admin, json={"name": "Identidad solo documental", "rut": rut(11999777)})
    assert changed_company.status_code == 200, changed_company.text
    assert changed_person.status_code == 200, changed_person.text
    with sessions() as db:
        assert db.get(Contractor, original["contractor_id"]).name == "Empresa Operativa Inmutable"
        assert db.get(Worker, created.json()["worker_id"]).name == "Trabajador Operativo Inmutable"
        assert db.scalar(select(func.count(WorkerAssignment.id))) == 1
        assert db.get(JavieraLocalCompany, company["id"]).name == "Razón social solo documental"
        assert db.get(JavieraLocalPerson, copied["id"]).name == "Identidad solo documental"


def test_issuance_partial_success_preserves_eligible_pdf(env):
    client, sessions = env
    admin = login(client, "a@example.cl")
    firm, person, record, payload = setup_dossier(client, admin)
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        db.add(JavieraTemplate(
            org_id=user.org_id, code="labor_contract", area="Zona Subcontratos",
            title="Contrato sintético aprobado",
            body="Contrato sintético aprobado: {{worker.name}} en {{site.name}}.",
            fields=["worker.name", "site.name"], published_version=1))
    response = client.post(BASE + "/issue/batch", headers=admin, json={
        "dossier_id": record["id"],
        "codes": ["labor_contract", "transfer_addendum"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["issued"] == 1, result
    assert result["failed"] == 1
    assert result["results"][0]["ok"] is True
    assert result["results"][1]["ok"] is False
    assert client.get(BASE + "/issues/" + result["results"][0]["id"] + "/pdf").status_code == 200
    assert client.get(result["pdf_url"]).status_code == 200


def test_delivery_requires_explicit_confirmation(env):
    client, _ = env
    admin = login(client, "a@example.cl")
    firm, person, record, payload = setup_dossier(client, admin)
    changed = client.post(BASE + "/dossiers", headers=admin, json={
        "site_id": payload["site_id"], "company_id": firm["id"],
        "person_id": person["id"], "relationship": "contractor",
        "selected_codes": ["ppe_delivery"],
        "shared": {"role": "CARPINTERO"},
        "document_data": {"ppe_delivery": {
            "event": {"date": "2026-11-09", "epp_items": "Casco y guantes"}}}})
    assert changed.status_code == 200, changed.text
    check = client.get(BASE + "/dossiers/" + changed.json()["id"] + "/eligibility")
    assert check.status_code == 200, check.text
    state = check.json()["documents"][0]
    assert not state["can_issue"]
    assert "evento realmente ocurrió" in state["reason"]
