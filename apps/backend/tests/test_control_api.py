"""Acceptance scenarios B-I: manual operations do not depend on the OCR queue."""
from datetime import date
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.control_scheduler import calendar_tick
from app.db import Base, get_db
from app.main import app
from app.models import Organization, User
from app.ops_models import Contractor
from app.security import hash_password


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("APP_SECRET", "s"*96)
    monkeypatch.setenv("SECURE_COOKIES", "false")
    settings.cache_clear()
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread":False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as db:
        org1, org2 = Organization(name="Principal"), Organization(name="Separada")
        db.add_all([org1,org2])
        db.flush()
        for email, org, role in (
            ("a@example.cl",org1,"admin"),
            ("b@example.cl",org1,"admin"),
            ("c@example.cl",org1,"resident"),
            ("outside@example.cl",org2,"admin"),
        ):
            db.add(User(org_id=org.id,email=email,role=role,
                        password_hash=hash_password("password-valid-2026")))
    def override():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db]=override
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        settings.cache_clear()
        engine.dispose()


def login(client,email):
    res=client.post("/api/v1/auth/login",json={"email":email,"password":"password-valid-2026"})
    assert res.status_code==200,res.text
    return {"X-CSRF-Token":client.cookies["galant_post_csrf"]}


def create_company(client,headers,site,code,name,nature="with_workers"):
    r=client.post("/api/v1/ops/contractors",headers=headers,json={
        "site_id":site,"name":name,"nature":nature,
        "historical_code":code,"frequency":"fixed","contract_status":"active"})
    assert r.status_code==201,r.text
    return r.json()


def test_manual_approvals_no_pdf_tenant_security_and_weighted_dashboard(env):
    client,sessions=env
    head=login(client,"a@example.cl")
    sites=client.get("/api/v1/ops/sites").json()
    concepcion=next(s["id"] for s in sites if s["name"]=="Concepción")
    lomas=next(s["id"] for s in sites if s["name"]=="Lomas Verdes")
    ct=create_company(client,head,concepcion,"CT","Empresa Central")
    # Same contractor in two worksites, without copying its worksite reviews.
    second=client.post("/api/v1/ops/contractors",headers=head,json={
        "site_id":lomas,"name":"Empresa Central","nature":"with_workers",
        "historical_code":"CT","frequency":"fixed"}).json()
    ci=create_company(client,head,concepcion,"CI","Independiente Persona","independent")
    other=create_company(client,head,concepcion,"X","Empresa Excluida")
    matrix=client.get("/api/v1/control/matrix",params={
        "site_id":concepcion,"period":"2026-09"}).json()
    assert matrix["summary"]["compliance"] is None, "Never show fictitious 100% without evaluable data"
    assert len(matrix["contractors"])==3
    assert len(matrix["contractors"][0]["requirements"])==7
    indep=next(x for x in matrix["contractors"] if x["code"]=="CI")
    assert next(x for x in indep["requirements"] if x["kind"]=="anticipos")["applicable"] is False
    company=next(x for x in matrix["contractors"] if x["code"]=="CT")
    assert next(x for x in company["requirements"] if x["kind"]=="declaracion_jurada")["applicable"] is False
    resp=client.post("/api/v1/control/reviews",headers=head,json={
        "association_id":ct["id"],"period":"2026-09","kind":"cotizaciones",
        "status":"approved","notes":""})
    assert resp.status_code==200,resp.text
    assert resp.json()["source"]=="manual_without_pdf"
    assert client.get("/api/v1/control/matrix",params={
        "site_id":lomas,"period":"2026-09"}).json()["summary"]["approved"]==0
    head_b=login(client,"b@example.cl")
    seen=client.get("/api/v1/control/matrix",params={
        "site_id":concepcion,"period":"2026-09"}).json()
    assert next(x for x in seen["contractors"] if x["code"]=="CT")["requirements"][0]["state"]=="approved"
    bulk=client.post("/api/v1/control/reviews/bulk",headers=head_b,json={
        "reviews":[{"association_id":ct["id"],"period":"2026-09","kind":"f30_1",
                    "status":"approved","notes":"Revisión manual"},
                   {"association_id":ci["id"],"period":"2026-09","kind":"declaracion_jurada",
                    "status":"approved","notes":""}]})
    assert bulk.status_code==200,bulk.text
    dashboard=client.get("/api/v1/control/reports/overview",params={"period":"2026-09"}).json()
    assert dashboard["totals"]["unique_companies"]==3
    assert dashboard["totals"]["associations"]==4
    assert dashboard["approved"]>=3
    login(client,"c@example.cl")
    assert client.get("/api/v1/control/matrix",params={"site_id":concepcion,"period":"2026-09"}).status_code==403
    denied=client.post("/api/v1/control/reviews",headers={"X-CSRF-Token":client.cookies["galant_post_csrf"]},
        json={"association_id":ct["id"],"period":"2026-09","kind":"asistencia",
              "status":"approved","notes":""})
    assert denied.status_code==403
    login(client,"outside@example.cl")
    assert client.get("/api/v1/control/matrix",params={"site_id":concepcion,"period":"2026-09"}).status_code==404
    foreign=client.post("/api/v1/control/reviews",headers={
        "X-CSRF-Token":client.cookies["galant_post_csrf"]},json={
        "association_id":ct["id"],"period":"2026-09","kind":"cotizaciones",
        "status":"approved","notes":""})
    assert foreign.status_code==404


def test_contributions_retention_calculation_and_CT_CI_excel(env):
    client,_=env
    headers=login(client,"a@example.cl")
    site=client.get("/api/v1/ops/sites").json()[0]["id"]
    ct=create_company(client,headers,site,"CT","Contratista CT")
    ci=create_company(client,headers,site,"CI","Independiente CI","independent")
    other=create_company(client,headers,site,"OTHER","Contratista OTRO",nature="unclassified")
    worker=client.post("/api/v1/ops/workers",headers=headers,json={
        "site_id":site,"contractor_id":ct["contractor_id"],
        "name":"Persona Empleada"}).json()
    base={"association_id":ct["id"],"period":"2026-09",
          "worker_assignment_id":worker["id"],"attendance_days":25,
          "required_days":25,"paid_days":23,"payment_confirmed":True,
          "daily_rate":4950,"justification":"","notes":"Control manual",
          "review_status":"approved","retention_status":"proposed"}
    saved=client.put("/api/v1/control/contributions",headers=headers,json=base)
    assert saved.status_code==200,saved.text
    assert saved.json()["missing_days"]==2
    assert float(saved.json()["retention_suggested"])==9900
    excess=client.put("/api/v1/control/contributions",headers=headers,json={
        **base,"paid_days":27,"review_status":"approved","retention_status":"none"})
    assert excess.status_code==200,excess.text
    assert excess.json()["missing_days"]==0
    assert float(excess.json()["retention_suggested"])==0
    saved_again=client.put("/api/v1/control/contributions",headers=headers,json={
        **base,"review_status":"approved"})
    assert saved_again.status_code==200
    # Source changed after approval must require a new review.
    changed=client.put("/api/v1/control/contributions",headers=headers,json={
        **base,"paid_days":24,"review_status":"approved"})
    assert changed.status_code==200
    assert changed.json()["review_status"]=="pending"
    assert changed.json()["missing_days"]==1
    assert float(changed.json()["retention_suggested"])==4950
    independent=client.put("/api/v1/control/contributions",headers=headers,json={
        "association_id":ci["id"],"period":"2026-09","worker_assignment_id":None,
        "attendance_days":None,"required_days":None,"paid_days":None,
        "payment_confirmed":True,"notes":"Pago CI acreditado manualmente",
        "review_status":"approved","retention_status":"none"})
    assert independent.status_code==200,independent.text
    assert independent.json()["missing_days"] is None
    assert independent.json()["retention_suggested"] is None
    invalid=client.put("/api/v1/control/contributions",headers=headers,json={
        "association_id":ci["id"],"period":"2026-09","worker_assignment_id":worker["id"]})
    assert invalid.status_code==422
    report=client.get("/api/v1/control/reports/cotizaciones.xlsx",params={"period":"2026-09"})
    assert report.status_code==200,report.text[:200]
    book=load_workbook(BytesIO(report.content),read_only=True)
    table=list(book["Cotizaciones CT y CI"].values)
    names=[r[1] for r in table[1:]]
    assert "Contratista CT" in names and "Independiente CI" in names
    assert "Contratista OTRO" not in names
    assert any(r[9]==1 and r[10]==4950 for r in table[1:])


def test_no_movements_creates_task_without_offboarding_and_calendar_scheduling(env,monkeypatch):
    client,sessions=env
    headers=login(client,"a@example.cl")
    site=client.get("/api/v1/ops/sites").json()[0]["id"]
    ct=create_company(client,headers,site,"CT","Empresa sin movimiento")
    changed=client.put("/api/v1/control/activity",headers=headers,json={
        "association_id":ct["id"],"period":"2026-09",
        "status":"no_movements","reason":"Sin labores informadas"})
    assert changed.status_code==200,changed.text
    tasks=client.get("/api/v1/control/admin/tasks",params={"site_id":site}).json()
    assert sum(t["kind"]=="review_continuity" for t in tasks)==1
    assert client.get("/api/v1/control/admin/offboarding",params={"site_id":site}).json()==[]
    assert client.put("/api/v1/control/activity",headers=headers,json={
        "association_id":ct["id"],"period":"2026-09",
        "status":"no_movements","reason":"Reconfirmado"}).status_code==200
    assert sum(t["kind"]=="review_continuity" for t in client.get(
        "/api/v1/control/admin/tasks",params={"site_id":site}).json())==1
    calendar=client.put("/api/v1/control/admin/calendar",headers=headers,json={
        "worksite_id":site,"period":"2026-10","kind":"cotizaciones",
        "request_date":"2026-11-10","due_date":"2026-11-15"})
    assert calendar.status_code==200,calendar.text
    import app.control_api as control_module
    monkeypatch.setattr(control_module,"today",lambda:date(2026,11,9))
    pre=client.get("/api/v1/control/matrix",params={"site_id":site,"period":"2026-10"}).json()
    assert next(x for x in pre["contractors"][0]["requirements"] if x["kind"]=="cotizaciones")["state"]=="not_yet_required"
    with sessions.begin() as db:
        assert calendar_tick(db,date(2026,11,9))==0
        assert calendar_tick(db,date(2026,11,10))==1
        assert calendar_tick(db,date(2026,11,10))==0
    monkeypatch.setattr(control_module,"today",lambda:date(2026,11,16))
    post=client.get("/api/v1/control/matrix",params={"site_id":site,"period":"2026-10"}).json()
    assert next(x for x in post["contractors"][0]["requirements"] if x["kind"]=="cotizaciones")["state"]=="overdue"
    monthly=client.get("/api/v1/control/admin/tasks",params={"site_id":site}).json()
    assert any(t["kind"]=="monthly_request" for t in monthly)


def _rut(number: int) -> str:
    weights=(2,3,4,5,6,7)
    total=sum(int(digit)*weights[i % len(weights)]
              for i,digit in enumerate(reversed(str(number))))
    modulus=11-(total%11)
    digit="0" if modulus==11 else "K" if modulus==10 else str(modulus)
    return f"{number}-{digit}"


def test_historical_contract_import_preview_idempotency_and_privacy(env):
    """Import contracts and annexes without copying worker/company data."""
    from app.control_models import ContractAmendment, ContractRegister
    from sqlalchemy import select
    client,sessions=env
    headers=login(client,"a@example.cl")
    site=client.get("/api/v1/ops/sites").json()[0]["id"]
    company=client.post("/api/v1/ops/contractors",headers=headers,json={
        "site_id":site,"name":"Contratista Histórico","rut":_rut(12345678),
        "nature":"with_workers","historical_code":"CT"}).json()
    text=("RUT contratista;RUT trabajador;Tipo contrato;Fecha inicio;Fecha término;"
          "Tipo registro;Fecha anexo;Referencia;Estado contrato;Observaciones\n"
          f"{_rut(12345678)};;Plazo fijo;01/09/2026;30/09/2026;"
          "Contrato;;CONTRATO-001;Activo;Inicial\n"
          f"{_rut(12345678)};;Plazo fijo;01/09/2026;31/10/2026;"
          "Anexo;25/09/2026;ANEXO-001;Activo;Prórroga\n")
    preview=client.post("/api/v1/control/import/contracts/preview",headers=headers,
        files={"file":("historico.csv",text.encode("utf-8"),"text/csv")},
        data={"site_id":site})
    assert preview.status_code==200,preview.text
    result=preview.json()
    assert result["summary"]["contracts"]==1 and result["summary"]["amendments"]==1
    assert result["summary"]["errors"]==0, result
    commit=client.post("/api/v1/control/import/contracts/commit",headers=headers,json={
        "site_id":site,"rows":result["rows"],"preview_token":result["preview_token"]})
    assert commit.status_code==200,commit.text
    assert commit.json()["created"]==1 and commit.json()["amendments"]==1
    records=client.get("/api/v1/control/admin/contracts",params={"site_id":site}).json()
    assert any(record["end_date"]=="2026-10-31" for record in records)
    with sessions() as db:
        assert len(db.scalars(select(ContractRegister)).all())==1
        assert len(db.scalars(select(ContractAmendment)).all())==1

    # Repeating the same preview must be idempotent, no extra annex or rewriting.
    repeated=client.post("/api/v1/control/import/contracts/commit",headers=headers,json={
        "site_id":site,"rows":result["rows"],"preview_token":result["preview_token"]})
    assert repeated.status_code==200,repeated.text
    assert repeated.json()["unchanged"]==2

    # An altered row not present in the signed preview is forbidden.
    bad=client.post("/api/v1/control/import/contracts/commit",headers=headers,json={
        "site_id":site,"rows":result["rows"]+[dict(result["rows"][0],row_id="invented:99")],
        "preview_token":result["preview_token"]})
    assert bad.status_code in (403,422)

    login(client,"outside@example.cl")
    assert client.get("/api/v1/control/admin/contracts",params={"site_id":site}).status_code==404


def test_historical_contract_import_rejects_unknown_rut_and_ambiguous_dates(env):
    client,_=env
    headers=login(client,"a@example.cl")
    site=client.get("/api/v1/ops/sites").json()[0]["id"]
    rows=("RUT contratista;Tipo contrato;Fecha inicio;Fecha término\n"
          f"{_rut(13579246)};Plazo fijo;31/02/2026;30/09/2026\n").encode()
    response=client.post("/api/v1/control/import/contracts/preview",headers=headers,
        files={"file":("invalid.csv",rows,"text/csv")},data={"site_id":site})
    assert response.status_code==200,response.text
    preview=response.json()
    assert preview["summary"]["errors"]==1
    assert any("Fecha" in x for x in preview["rows"][0]["errors"])
    commit=client.post("/api/v1/control/import/contracts/commit",headers=headers,json={
        "site_id":site,"rows":preview["rows"],"preview_token":preview["preview_token"]})
    assert commit.status_code==422


def test_pago_parcial_es_incompleto_y_sincroniza_control_documental(env):
    """Regresión: 16 días asistidos, 14 pagados y evidencia confirmada."""
    client, _ = env
    headers = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    company = create_company(client, headers, site, "CT", "Contratista de prueba")
    worker_response = client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": site, "contractor_id": company["contractor_id"],
        "name": "Trabajador de prueba",
    })
    assert worker_response.status_code == 201, worker_response.text
    worker = worker_response.json()
    payload = {
        "association_id": company["id"],
        "subject": worker["id"],
        "period": "2026-11",
        "required_days": 14,  # Campo legado: asistencia debe prevalecer.
        "attendance_days": 16,
        "paid_days": 14,
        "confirmed": True,
    }
    saved = client.put("/api/v1/ops/contributions", headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    response = client.get("/api/v1/ops/contributions", params={
        "site_id": site, "period": "2026-11",
    })
    assert response.status_code == 200, response.text
    result = next(row for row in response.json()["rows"] if row["subject"] == worker["id"])
    assert result["required_days"] == 16
    assert result["missing_days"] == 2
    assert result["estimated_retention"] == 9900
    assert result["state"] == "incompleto"
    monthly = client.get("/api/v1/control/contributions", params={
        "site_id": site, "period": "2026-11",
    })
    assert monthly.status_code == 200, monthly.text
    assert monthly.json()[0]["compliance_status"] == "incomplete"
    docs = client.get("/api/v1/ops/document-reviews", params={
        "site_id": site, "period": "2026-11",
    })
    assert docs.status_code == 200, docs.text
    doc = next(row for row in docs.json() if
        row["subject"] == worker["id"] and row["requirement"] == "Cotizaciones")
    assert doc["state"] == "incomplete"
    cannot_approve = client.put("/api/v1/ops/document-reviews", headers=headers, json={
        "association_id": company["id"], "subject": worker["id"],
        "period": "2026-11", "requirement": "Cotizaciones",
        "state": "approved", "observation": "",
    })
    assert cannot_approve.status_code == 422

    regularized = client.put("/api/v1/ops/contributions", headers=headers, json={
        **payload, "paid_days": 16,
    })
    assert regularized.status_code == 200, regularized.text
    result = next(row for row in client.get("/api/v1/ops/contributions", params={
        "site_id": site, "period": "2026-11",
    }).json()["rows"] if row["subject"] == worker["id"])
    assert result["state"] == "conforme"
    assert result["missing_days"] == 0
    assert result["estimated_retention"] == 0
    approved = client.put("/api/v1/ops/document-reviews", headers=headers, json={
        "association_id": company["id"], "subject": worker["id"],
        "period": "2026-11", "requirement": "Cotizaciones",
        "state": "approved", "observation": "Regularización acreditada",
    })
    assert approved.status_code == 200, approved.text

    changed = client.put("/api/v1/ops/contributions", headers=headers, json=payload)
    assert changed.status_code == 200, changed.text
    docs = client.get("/api/v1/ops/document-reviews", params={
        "site_id": site, "period": "2026-11",
    }).json()
    doc = next(row for row in docs if
        row["subject"] == worker["id"] and row["requirement"] == "Cotizaciones")
    assert doc["state"] == "incomplete"
