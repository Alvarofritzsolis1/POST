"""Cross-module acceptance cases for the 0.6 labor and reconciliation release."""
from datetime import timedelta

import fitz
from sqlalchemy import select, func, create_engine, inspect
from sqlalchemy.orm import Session

from app.config import settings
from app.control_api import today
from app.models import Document, User
from app.ops_models import Contractor, ContractorWorksite, OpsChange, Worker, WorkerAssignment
from app.platform_models import BackupCheckpoint, WorkerTermination
from app.platform_models import SchemaVersion
from app.db import Base
from app.cli import migrate
from app.models import Organization
from test_control_api import env, login, create_company
from test_platform import review, commit, rut


def test_explicit_classification_legacy_preservation_and_ci_obligations(env):
    client, sessions = env
    head = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]
    row = {"site": site["name"], "name": "Empresa CT verificable", "rut": rut(21000123),
           "historical_code": "CT", "nature": "Contratista con trabajadores",
           "frequency": "Fijo", "status": "ACTIVO"}
    prepared = review(client, head, "contractors", [row])
    assert prepared["rows"][0]["category"] == "new"
    assert commit(client, head, prepared).status_code == 200
    record = client.get("/api/v1/ops/contractors", params={"site_id": site["id"]}).json()[0]
    assert (record["historical_code"], record["nature"], record["frequency"], record["contract_status"]) == (
        "CT", "with_workers", "fixed", "active")
    legacy = {key: value for key, value in row.items() if key not in {"nature", "frequency"}}
    again = review(client, head, "contractors", [legacy])
    assert again["rows"][0]["category"] == "existing"
    assert commit(client, head, again).status_code == 200
    record = client.get("/api/v1/ops/contractors", params={"site_id": site["id"]}).json()[0]
    assert record["nature"] == "with_workers" and record["frequency"] == "fixed"
    independent = {**row, "name": "Profesional independiente", "rut": rut(21000124),
                   "historical_code": "CI", "nature": "Independiente", "frequency": "Esporádico"}
    assert commit(client, head, review(client, head, "contractors", [independent])).status_code == 200
    ci = next(c for c in client.get("/api/v1/ops/contractors", params={"site_id": site["id"]}).json()
              if c["historical_code"] == "CI")
    assert ci["nature"] == "independent" and ci["frequency"] == "unclassified"  # CI no define frecuencia
    ci_alerts = client.get("/api/v1/labor/alerts", params={"site_id": site["id"]}).json()
    assert not any(a["severity"] == "red" and a["kind"] == "document_overdue" and
                   a["target_id"] == ci["id"] for a in ci_alerts["alerts"])
    assert client.post("/api/v1/labor/workers", headers=head, json={
        "site_id": site["id"], "contractor_id": ci["contractor_id"],
        "name": "Persona no permitida", "rut": rut(12000124),
        "contract": {"contract_type": "indefinite", "start_date": str(today())},
    }).status_code == 422


def test_reconciliation_requires_backup_and_preserves_relationships(env):
    client, sessions = env
    head = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]
    company = client.post("/api/v1/ops/contractors", headers=head, json={
        "site_id": site["id"], "name": "Empresa histórica", "rut": rut(22000101),
        "historical_code": "CT", "nature": "unclassified", "frequency": "unclassified",
    }).json()
    worker = client.post("/api/v1/ops/workers", headers=head, json={
        "site_id": site["id"], "contractor_id": company["contractor_id"],
        "name": "Trabajadora relacionada", "rut": rut(12000101),
    }).json()
    with sessions.begin() as db:
        admin = db.scalar(select(User).where(User.email == "a@example.cl"))
        db.add(OpsChange(org_id=admin.org_id, user_id=admin.id, entity_type="contractors",
                         entity_id=company["contractor_id"], changes={
                             "imported": True, "relationship_id": company["id"],
                             "values": {"site": site["name"], "nature": "Con trabajadores",
                                        "frequency": "Fijo", "historical_code": "CT"}}))
        doc = Document(org_id=admin.org_id, user_id=admin.id, original_name="respaldo.pdf",
                       storage_path="/tmp/respaldo-test.pdf", sha256="a" * 64, declared_type="auto")
        db.add(doc)
        db.flush()
        document_id = doc.id
    preview = client.get("/api/v1/admin/reconciliation/preview").json()
    target = next(r for r in preview["records"] if r["association_id"] == company["id"])
    assert target["category"] == "recoverable"
    assert target["changes"]["nature"]["to"] == "with_workers"
    assert target["changes"]["frequency"]["to"] == "fixed"
    assert client.post("/api/v1/admin/reconciliation/commit", headers=head,
                       json={"token": preview["token"], "backup_id": "missing"}).status_code == 422
    with sessions.begin() as db:
        admin = db.scalar(select(User).where(User.email == "a@example.cl"))
        backup = BackupCheckpoint(org_id=admin.org_id, sha256="b" * 64)
        db.add(backup)
        db.flush()
        backup_id = backup.id
    applied = client.post("/api/v1/admin/reconciliation/commit", headers=head,
                          json={"token": preview["token"], "backup_id": backup_id})
    assert applied.status_code == 200, applied.text
    assert applied.json()["corrected"] >= 1
    with sessions() as db:
        assert db.get(Contractor, company["contractor_id"]).nature == "with_workers"
        assert db.get(ContractorWorksite, company["id"]).frequency == "fixed"
        assert db.get(WorkerAssignment, worker["id"]).contractor_id == company["contractor_id"]
        assert db.get(Document, document_id)
        assert db.scalar(select(func.count()).select_from(Worker)) == 1


def test_worker_first_contract_expiry_termination_pdf_review_and_history(env, monkeypatch, tmp_path):
    client, sessions = env
    head = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]
    company = create_company(client, head, site["id"], "CT", "Empleador", "with_workers")
    start, end = today() - timedelta(days=20), today() - timedelta(days=1)
    created = client.post("/api/v1/labor/workers", headers=head, json={
        "site_id": site["id"], "contractor_id": company["contractor_id"],
        "name": "Trabajador con plazo", "rut": rut(11000123),
        "contract": {"contract_type": "fixed_term", "start_date": str(start),
                     "end_date": str(end), "notes": "Prueba de vencimiento"},
    })
    assert created.status_code == 201, created.text
    assignment_id, contract_id = created.json()["assignment_id"], created.json()["contract_id"]
    list_result = client.get("/api/v1/labor/workers", params={"site_id": site["id"]}).json()
    assert list_result["summary"]["total"] == 1
    row = list_result["rows"][0]
    assert row["assignment_id"] == assignment_id and row["contract_type"] == "fixed_term"
    assert row["labor_state"] == "expired_needs_review" and row["severity"] == "red"
    assert row["finiquito_state"] == "not_applicable"
    alerts = client.get("/api/v1/labor/alerts", params={"site_id": site["id"]}).json()
    assert alerts["summary"]["workers_expired"] == 1
    assert any(a["kind"] == "contract_expired" and a["severity"] == "red" for a in alerts["alerts"])
    finished = client.post(f"/api/v1/labor/contracts/{contract_id}/termination", headers=head,
                           json={"effective_date": str(today()), "cause": "fixed_term_expiry"})
    assert finished.status_code == 201, finished.text
    term_id = finished.json()["id"]
    assert client.get("/api/v1/labor/workers", params={"site_id": site["id"]}).json()["rows"][0]["finiquito_state"] == "missing"
    pdf = fitz.open()
    pdf.new_page()
    file_content = pdf.tobytes()
    pdf.close()
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path))
    settings.cache_clear()
    uploaded = client.post("/api/v1/documents", headers=head,
                           files={"file": ("finiquito.pdf", file_content, "application/pdf")})
    assert uploaded.status_code == 202, uploaded.text
    document_id = uploaded.json()["id"]
    delivered = client.post(f"/api/v1/labor/terminations/{term_id}/document", headers=head,
                            json={"document_id": document_id, "ratification_mode": "electronic"})
    assert delivered.status_code == 200 and delivered.json()["review_state"] == "delivered"
    # V8.1 has exactly three roles. An administrative without this site's
    # assignment cannot create a worker or review document evidence.
    new_user = client.post("/api/v1/admin/users", headers=head, json={
        "email": "administrativo.qa@example.cl", "password": "password-valid-2026",
        "role": "administrative", "name": "Administrativo sin acceso",
        "site_ids": [next(x["id"] for x in client.get("/api/v1/ops/sites").json()
                     if x["id"] != site["id"])]})
    assert new_user.status_code == 201
    administrative = login(client, "administrativo.qa@example.cl")
    assert client.post("/api/v1/labor/workers", headers=administrative, json={
        "site_id": site["id"], "contractor_id": company["contractor_id"],
        "name": "Prohibida", "rut": rut(11000124),
        "contract": {"contract_type": "indefinite", "start_date": str(today())},
    }).status_code == 403
    assert client.post(f"/api/v1/labor/terminations/{term_id}/review",
                       headers=administrative,
                       json={"state": "approved", "observation": "Sin autorización"}).status_code == 403
    head = login(client, "a@example.cl")
    approved = client.post(f"/api/v1/labor/terminations/{term_id}/review", headers=head,
                           json={"state": "approved", "observation": "PDF conforme"})
    assert approved.status_code == 200, approved.text
    detail = client.get("/api/v1/labor/workers/" + assignment_id).json()
    assert detail["contracts"][0]["termination"]["review_state"] == "approved"
    assert detail["contracts"][0]["termination"]["document_id"] == document_id
    assert any(h["entity_type"] == "worker_termination" for h in detail["history"])
    head = login(client, "a@example.cl")
    next_contract = client.post("/api/v1/labor/contracts", headers=head, json={
        "assignment_id": assignment_id, "contract_type": "indefinite", "start_date": str(today())})
    assert next_contract.status_code == 201, next_contract.text
    detail = client.get("/api/v1/labor/workers/" + assignment_id).json()
    assert len(detail["contracts"]) == 2
    assert detail["contracts"][1]["termination"]["document_id"] == document_id
    assert detail["current"]["finiquito_state"] == "not_applicable"
    login(client, "outside@example.cl")
    assert client.get("/api/v1/labor/workers/" + assignment_id).status_code == 404
    settings.cache_clear()


def test_receipt_with_verified_shortfall_is_incomplete_not_missing(env):
    client, sessions = env
    head = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]
    company = create_company(client, head, site["id"], "CT", "Empresa cotizaciones")
    worker = client.post("/api/v1/ops/workers", headers=head, json={
        "site_id": site["id"], "contractor_id": company["contractor_id"],
        "name": "Persona aportes", "rut": rut(13000222),
    }).json()
    period = today().strftime("%Y-%m")
    with sessions.begin() as db:
        admin = db.scalar(select(User).where(User.email == "a@example.cl"))
        receipt = Document(org_id=admin.org_id, user_id=admin.id,
                           original_name="cotizaciones.pdf", storage_path="/tmp/receipt.pdf",
                           sha256="c" * 64, declared_type="cotizaciones")
        db.add(receipt)
        db.flush()
        receipt_id = receipt.id
    linked = client.put("/api/v1/ops/document-reviews", headers=head, json={
        "association_id": company["id"], "subject": worker["id"], "period": period,
        "requirement": "Cotizaciones", "state": "pending", "document_id": receipt_id,
    })
    assert linked.status_code == 200, linked.text
    paid = client.put("/api/v1/ops/contributions", headers=head, json={
        "association_id": company["id"], "subject": worker["id"], "period": period,
        "required_days": 20, "paid_days": 19, "confirmed": True,
    })
    assert paid.status_code == 200, paid.text
    result = client.get("/api/v1/ops/contributions", params={"period": period,
                                                                "site_id": site["id"]}).json()
    row = result["rows"][0]
    assert row["document_state"] == "incomplete"
    assert row["receipt_document_id"] == receipt_id
    assert row["missing_days"] == 1 and row["estimated_retention"] == 4950
    finding = client.put("/api/v1/labor/contributions/" + row["control_id"] + "/finding",
                         headers=head, json={"state": "insufficient", "document_id": receipt_id,
                                             "documented_amount": 9000, "expected_amount": 10000,
                                             "observation": "Revisión de comprobante"})
    assert finding.status_code == 200, finding.text
    after = client.get("/api/v1/ops/contributions", params={"period": period,
                                                              "site_id": site["id"]}).json()["rows"][0]
    assert after["monetary_difference"] == 1000 and after["payment_finding"] == "insufficient"
    alert = client.get("/api/v1/labor/alerts", params={"period": period, "site_id": site["id"]}).json()
    assert any(a["kind"] == "payment_difference" and a["severity"] == "red" for a in alert["alerts"])
    changed = client.put("/api/v1/ops/contributions", headers=head, json={
        "association_id": company["id"], "subject": worker["id"], "period": period,
        "required_days": 20, "paid_days": 20, "confirmed": True,
    })
    assert changed.status_code == 200, changed.text
    after = client.get("/api/v1/ops/contributions", params={"period": period,
                                                              "site_id": site["id"]}).json()["rows"][0]
    assert after["payment_finding"] == "unverified"
    unpaid_control = client.put("/api/v1/ops/contributions", headers=head, json={
        "association_id": company["id"], "subject": worker["id"], "period": period,
        "required_days": 20, "paid_days": None, "confirmed": False,
    })
    assert unpaid_control.status_code == 200, unpaid_control.text
    unpaid = client.put("/api/v1/labor/contributions/" + row["control_id"] + "/finding",
                        headers=head, json={"state": "declared_unpaid", "document_id": receipt_id,
                                            "observation": "Declaración sin comprobante de pago"})
    assert unpaid.status_code == 200, unpaid.text
    alert = client.get("/api/v1/labor/alerts", params={"period": period, "site_id": site["id"]}).json()
    assert alert["summary"]["declared_unpaid"] == 1
    assert any(a["kind"] == "declared_unpaid" and a["severity"] == "red" for a in alert["alerts"])


def test_additive_migration_idempotent_and_persistent_after_reopen(tmp_path):
    path = tmp_path / "old.sqlite"
    engine = create_engine("sqlite+pysqlite:///" + str(path))
    new_tables = {"worker_terminations", "contract_attachments", "backup_checkpoints", "schema_versions", "payment_findings",
                  "attendance_rosters", "attendance_weeks", "attendance_worker_weeks"}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in new_tables and not t.name.startswith("network_")])
    with Session(engine) as db:
        db.add(Organization(id="legacy-org", name="Organización histórica"))
        db.commit()
    with Session(engine) as db:
        migrate(db)
        db.commit()
    with Session(engine) as db:
        migrate(db)
        db.commit()
    assert new_tables.issubset(set(inspect(engine).get_table_names()))
    engine.dispose()
    reopened = create_engine("sqlite+pysqlite:///" + str(path))
    with Session(reopened) as db:
        assert db.get(Organization, "legacy-org").name == "Organización histórica"
        assert set(db.scalars(select(SchemaVersion.version))) == {"0.6.0-rc1", "0.7.0", "8.1.0", "13.1.0_documentary_configuration", "16.0.0", "16.0.1_excel_print_and_professional_review"}
    reopened.dispose()
