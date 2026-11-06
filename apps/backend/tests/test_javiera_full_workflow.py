"""JAVIERA v16: aceptación de API, revisión humana simulada y PDFs inmutables.

Datos 100 % sintéticos. No se cargan documentos laborales reales en GitHub.
"""
from hashlib import sha256

from sqlalchemy import select
from app.models import User
from test_control_api import env, login, create_company
from test_platform import rut


def _draft(client, headers, name, reason):
    body = (
        "Contrato de trabajo de {{worker.name}}, RUT {{worker.rut}}, "
        "para {{employer.name}} en {{site.name}}. "
        + name + ". Este texto es sintético y solo sirve para probar el sistema."
    )
    reply = client.put("/api/v1/javiera/admin/templates/labor_contract",
        headers=headers, json={
            "title":"Contrato de prueba", "area":"Zona Subcontratos",
            "body":body,
            "fields":["worker.name","worker.rut","employer.name","site.name"],
            "rule":{}, "layout":{}, "reason":reason,
        })
    assert reply.status_code==200,reply.text
    item=next(x for x in client.get(
        "/api/v1/javiera/admin/templates").json() if x["code"]=="labor_contract")
    pending=next(x for x in item["revisions"] if x["state"]=="draft")
    return pending["revision"],pending["id"]


def _sign(client, headers, rev_id, specialties):
    check=next(x for x in specialties if x["specialty"]=="laboral")
    payload={
        "resource_kind":"template","resource_id":rev_id,"specialty":"laboral",
        "verdict":"approved",
        "checklist":{k:True for k in check["requirements"]},
        "comments":("Se verificaron datos sintéticos, redacción y campos obligatorios. "
                    "Esta acta es únicamente de prueba automatizada, sin valor laboral."),
        "regulatory_basis":check["legal_reference"],
    }
    reply=client.post("/api/v1/javiera/admin/reviews/signoff",
                      headers=headers,json=payload)
    assert reply.status_code==200,reply.text


def _dossier(client, headers):
    site=client.get("/api/v1/ops/sites").json()[0]["id"]
    company=create_company(client,headers,site,"CT","Empleador Sintético")
    worker=client.post("/api/v1/ops/workers",headers=headers,json={
        "site_id":site,"contractor_id":company["contractor_id"],
        "name":"Persona Sintética","rut":rut(10000123),
    })
    assert worker.status_code==201,worker.text
    entry=client.post("/api/v1/javiera/dossiers",headers=headers,json={
        "site_id":site,"employer_id":company["contractor_id"],
        "worker_id":worker.json()["worker_id"],
        "relationship":"contractor",
        "data":{
            "role":"CARPINTERO",
            "employment_type":"dependiente",
            "event_type":"ingreso",
            "contract":{"start":"2026-11-01","salary":"850000","hours":"42"},
            "event":{"date":"2026-11-06"},
        },
    })
    assert entry.status_code==200,entry.text
    return entry.json()["id"]


def test_javiera_review_publication_batch_and_immutable_reissue(env):
    client,sessions=env
    admin_a=login(client,"a@example.cl")
    dossier_id=_dossier(client,admin_a)
    revision1,id1=_draft(client,admin_a,"Contenido versión inicial","Creación de plantilla sintética")
    assert revision1==1
    assert client.post("/api/v1/javiera/admin/templates/labor_contract/approve/1",
                       headers=admin_a).status_code==403
    catalog=client.get("/api/v1/javiera/admin/reviews/checklists").json()
    with sessions() as db:
        b_id=db.scalar(select(User.id).where(User.email=="b@example.cl"))
    admin_b=login(client,"b@example.cl")
    before=client.post("/api/v1/javiera/admin/reviews/signoff",
        headers=admin_b,json={
            "resource_kind":"template","resource_id":id1,
            "specialty":"laboral","verdict":"approved",
            "checklist":{k:True for k in next(x for x in catalog if x["specialty"]=="laboral")["requirements"]},
            "comments":"Sin designación no se permite revisión de documentos legales de prueba.",
            "regulatory_basis":next(x for x in catalog if x["specialty"]=="laboral")["legal_reference"],
        })
    assert before.status_code==403
    admin_a=login(client,"a@example.cl")
    designation=client.put("/api/v1/javiera/admin/reviews/reviewers",
        headers=admin_a,json={"user_id":b_id,"specialty":"laboral",
          "designation":"Revisor laboral de pruebas técnicas automatizadas","active":True})
    assert designation.status_code==200,designation.text
    admin_b=login(client,"b@example.cl")
    _sign(client,admin_b,id1,catalog)
    published=client.post("/api/v1/javiera/admin/templates/labor_contract/approve/1",
                          headers=admin_b)
    assert published.status_code==200,published.text
    status=client.post("/api/v1/javiera/eligibility/evaluate",
        headers=admin_b,json={"dossier_id":dossier_id})
    contract=next(x for x in status.json()["documents"] if x["code"]=="labor_contract")
    assert contract["status"]=="LISTO_PARA_EMITIR",contract
    # Lote parcial: el contrato puede emitirse; el PTS necesita matriz y plantilla.
    batch=client.post("/api/v1/javiera/issue/batch",headers=admin_b,json={
        "dossier_id":dossier_id,"codes":["labor_contract","pts"]})
    assert batch.status_code==200,batch.text
    results=batch.json()
    assert results["issued"]==1 and results["failed"]==1
    assert results["results"][0]["ok"] and not results["results"][1]["ok"]
    first_id=results["results"][0]["id"]
    original=client.get(f"/api/v1/javiera/issued/{first_id}/pdf")
    assert original.status_code==200 and original.content.startswith(b"%PDF-")
    original_digest=sha256(original.content).hexdigest()
    # Segunda petición no duplica el PDF.
    repeated=client.post("/api/v1/javiera/issue",headers=admin_b,json={
        "dossier_id":dossier_id,"code":"labor_contract"})
    assert repeated.status_code==200,repeated.text
    assert repeated.json()["reused"] and repeated.json()["id"]==first_id
    # Misma versión de documento, otro autor y nueva revisión.
    admin_a=login(client,"a@example.cl")
    revision2,id2=_draft(client,admin_a,"Contenido versión corregida","Corrección del texto aprobado")
    assert revision2==2
    admin_b=login(client,"b@example.cl")
    _sign(client,admin_b,id2,catalog)
    published=client.post("/api/v1/javiera/admin/templates/labor_contract/approve/2",
                          headers=admin_b)
    assert published.status_code==200,published.text
    checking=client.post("/api/v1/javiera/eligibility/evaluate",headers=admin_b,
                         json={"dossier_id":dossier_id})
    current=next(x for x in checking.json()["documents"] if x["code"]=="labor_contract")
    assert current["status"]=="EXISTENTE_POR_VERIFICAR",current
    blocked=client.post("/api/v1/javiera/issue",headers=admin_b,
                        json={"dossier_id":dossier_id,"code":"labor_contract"})
    assert blocked.status_code==409
    reissued=client.post("/api/v1/javiera/issue",headers=admin_b,json={
        "dossier_id":dossier_id,"code":"labor_contract",
        "reissue_reason":"Se corrigió una cláusula y se autorizó otra versión completa."})
    assert reissued.status_code==200,reissued.text
    assert reissued.json()["id"]!=first_id
    final_pdf=client.get(f"/api/v1/javiera/issued/{reissued.json()['id']}/pdf")
    assert final_pdf.status_code==200
    assert sha256(final_pdf.content).hexdigest()!=original_digest
    untouched=client.get(f"/api/v1/javiera/issued/{first_id}/pdf")
    assert untouched.status_code==200
    assert sha256(untouched.content).hexdigest()==original_digest
    # Lectura cruzada de organizaciones bloqueada por backend (IDOR).
    login(client,"outside@example.cl")
    assert client.get(f"/api/v1/javiera/dossiers/{dossier_id}").status_code==404
    assert client.get(f"/api/v1/javiera/issued/{first_id}/pdf").status_code==404
    assert client.post("/api/v1/javiera/issue/batch",
                       headers={"X-CSRF-Token":client.cookies["galant_post_csrf"]},
                       json={"dossier_id":dossier_id,"codes":["labor_contract"]}).status_code==404
    # Perfil residente no puede acceder al panel ni API de documentos.
    login(client,"c@example.cl")
    assert client.get("/api/v1/javiera/catalog").status_code==403
    assert client.get("/api/v1/javiera/admin/templates").status_code==403
    assert client.get("/api/v1/javiera/admin/reviews/checklists").status_code==403


def test_javiera_batch_duplicate_or_unknown_code_is_rejected(env):
    client,_=env
    admin=login(client,"a@example.cl")
    record=_dossier(client,admin)
    for codes in (["labor_contract","labor_contract"],["labor_contract","unexpected"]):
        response=client.post("/api/v1/javiera/issue/batch",
                             headers=admin,json={"dossier_id":record,"codes":codes})
        assert response.status_code==422,response.text
