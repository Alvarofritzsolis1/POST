"""Regresiones GALANT 10.10: periodos, ficha multiobra y datos seguros."""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.platform_models import ContractorDetails
from app.ops_models import ContractorWorksite
from test_control_api import env, login, create_company


def this_month():
    return datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m")


def requirement(rows, association_id, kind="cotizaciones"):
    company = next(row for row in rows if row["association_id"] == association_id)
    return next(row for row in company["requirements"] if row["kind"] == kind)


def test_v1010_inactive_excluded_from_current_documents_and_historical_kept(env):
    client, sessions = env
    head = login(client, "a@example.cl")
    sites = client.get("/api/v1/ops/sites").json()
    a, b = sites[0]["id"], sites[1]["id"]
    first = create_company(client, head, a, "CT", "Empresa pruebas 1010")
    other = client.post("/api/v1/ops/contractors", headers=head, json={
        "site_id": b, "name": "Empresa pruebas 1010",
        "nature": "with_workers", "historical_code": "CT", "contract_status": "active",
    })
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]

    # La evidencia previa se conserva cuando cambia el estado.
    historic = "2026-09"
    approved = client.post("/api/v1/control/reviews", headers=head, json={
        "association_id": first["id"], "period": historic, "kind": "cotizaciones",
        "status": "approved", "notes": "Aprobación histórica registrada",
    })
    assert approved.status_code == 200, approved.text
    changed = client.patch("/api/v1/ops/contractors/" + first["id"], headers=head,
                           json={"contract_status": "inactive"})
    assert changed.status_code == 200, changed.text
    current = client.get("/api/v1/control/matrix", params={
        "site_id": a, "period": this_month(),
    }).json()
    assert all(r["applicable"] is not True for
               r in next(c for c in current["contractors"]
                         if c["association_id"] == first["id"])["requirements"])
    assert current["summary"]["applicable"] == 0
    assert requirement(client.get("/api/v1/control/matrix", params={
        "site_id": a, "period": historic,
    }).json()["contractors"], first["id"])["state"] == "approved"
    active_other = client.get("/api/v1/ops/contractors", params={"site_id": b}).json()
    assert next(c for c in active_other if c["id"] == other_id)["contract_status"] == "active"
    assert client.get("/api/v1/control/matrix", params={
        "site_id": b, "period": this_month(),
    }).json()["contractors"][0]["status"] == "active"

    denied = client.post("/api/v1/control/reviews", headers=head, json={
        "association_id": first["id"], "period": this_month(), "kind": "f30_1",
        "status": "approved", "notes": "No debe permitirse",
    })
    assert denied.status_code == 422, denied.text
    denied_doc = client.post("/api/v1/ops/monthly-documents", headers=head, json={
        "association_id": first["id"], "period": this_month(),
        "kind": "f30_1", "not_applicable": True,
    })
    assert denied_doc.status_code == 422, denied_doc.text
    history_edit = client.post("/api/v1/control/reviews", headers=head, json={
        "association_id": first["id"], "period": historic, "kind": "cotizaciones",
        "status": "observed", "notes": "Corrección histórica documentada",
    })
    assert history_edit.status_code == 200, history_edit.text


def test_v1010_inactive_month_without_evidence_needs_human_override(env):
    client, sessions = env
    head = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    inactive = create_company(client, head, site, "CT", "Sin información histórica")
    assert client.patch("/api/v1/ops/contractors/" + inactive["id"],
        headers=head, json={"contract_status": "inactive"}).status_code == 200

    historic = "2026-09"
    matrix = client.get("/api/v1/control/matrix", params={"site_id": site,
                                                            "period": historic}).json()
    assert requirement(matrix["contractors"], inactive["id"])["applicable"] is False
    denied = client.post("/api/v1/control/reviews", headers=head, json={
        "association_id": inactive["id"], "period": historic,
        "kind": "cotizaciones", "status": "approved", "notes": "",
    })
    assert denied.status_code == 422, denied.text
    override = client.put("/api/v1/control/applicability", headers=head, json={
        "association_id": inactive["id"], "period": historic,
        "kind": "cotizaciones", "applicable": True,
        "justification": "Contrato y asistencia verifican labores en el mes",
    })
    assert override.status_code == 200, override.text
    after = client.get("/api/v1/control/matrix", params={
        "site_id": site, "period": historic,
    }).json()
    assert requirement(after["contractors"], inactive["id"])["applicable"] is True
    approved = client.post("/api/v1/control/reviews", headers=head, json={
        "association_id": inactive["id"], "period": historic,
        "kind": "cotizaciones", "status": "approved", "notes": "",
    })
    assert approved.status_code == 200, approved.text
    denied_current = client.put("/api/v1/control/applicability", headers=head, json={
        "association_id": inactive["id"], "period": this_month(),
        "kind": "cotizaciones", "applicable": True, "justification": "No debe permitirlo",
    })
    assert denied_current.status_code == 422, denied_current.text


def test_v1010_details_flattened_per_site_without_cross_site_leak(env):
    client, sessions = env
    head = login(client, "a@example.cl")
    sites = client.get("/api/v1/ops/sites").json()
    a, b = sites[0]["id"], sites[1]["id"]
    first = create_company(client, head, a, "CT", "Empresa anidada")
    second = client.post("/api/v1/ops/contractors", headers=head, json={
        "site_id": b, "name": "Empresa anidada",
        "historical_code": "CT", "nature": "with_workers",
    })
    assert second.status_code == 201, second.text
    with sessions.begin() as db:
        db.add(ContractorDetails(contractor_id=first["contractor_id"], values={
            "phone": "912345678", "worksites": {
                a: {"specialty": "Carpintería", "external_id": "001"},
                b: {"specialty": "Electricidad", "external_id": "002"},
            },
        }))
    a_row = next(row for row in client.get("/api/v1/ops/contractors",
        params={"site_id": a}).json() if row["id"] == first["id"])
    b_row = next(row for row in client.get("/api/v1/ops/contractors",
        params={"site_id": b}).json() if row["id"] == second.json()["id"])
    assert a_row["details"]["specialty"] == "Carpintería"
    assert b_row["details"]["specialty"] == "Electricidad"
    assert a_row["details"]["phone"] == b_row["details"]["phone"]
    assert "worksites" not in a_row["details"]
    assert all(isinstance(value, str) for value in a_row["details"].values())
