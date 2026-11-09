"""GALANT JAVIERA 16.5: segregación de áreas y equivalencias explícitas de cargos."""
import pytest
from datetime import datetime, timezone

import fitz
from sqlalchemy import select

from app.javiera_logic import (
    DOCUMENTS, CARGO_ALIASES, eligibility, normalize_cargo,
    validate_requirements
)
from app.javiera_layout_api import matrix_sections
from app.javiera_models import JavieraMatrix, JavieraTemplate
from app.models import User
from test_control_api import env, login, create_company


@pytest.mark.parametrize("raw,expected",[
    ("PINTOR","PINTOR"),("Pintura","PINTOR"),("pinturas","PINTOR"),
    ("Maestro pintor","PINTOR"),("CARPINTERÍA","CARPINTERO"),
    ("Carpintero","CARPINTERO"),("gasfitería","GASFITER"),
    ("cerámica","CERAMISTA"),("impermeabilización","IMPERMEABILIZADOR"),
    ("hormigonado","OPERARIO DE HORMIGON"),
])
def test_matriz_comparte_cargo_canonico_con_labor_empresa(raw,expected):
    assert normalize_cargo(raw)==expected


def test_no_identifica_automaticamente_un_cargo_no_equivalente():
    # No usar semejanza estadística para asignar matrices preventivas.
    assert normalize_cargo("SOLDADOR")=="SOLDADOR"
    assert normalize_cargo("OPERADOR MAQUINARIA")=="OPERADOR MAQUINARIA"


def test_prevencion_no_depende_de_contrato_incompleto_o_erroneo():
    data={
      "employer":{"name":"Empresa sintética"},
      "worker":{"name":"Trabajador sintético","rut":"11.111.111-1"},
      "site":{"name":"Brisas de Junquillar"},
      "role":"PINTOR","employment_type":"",
      "event_type":"ingreso",
      "event":{"date":"2026-11-06"},
      "contract":{"salary":"no-numérico","hours":"99","end":"2025-11-06","start":"2026-11-06"},
    }
    # Los campos contractuales no forman parte de la IRL, PTS o EPP.
    missing, errors=validate_requirements(data,
        ["employer.name","worker.name","worker.rut","site.name","role","event.date"])
    assert missing==[]
    assert errors==[]
    # Cuando se prepara un contrato sí deben comprobarse.
    _,contract_errors=validate_requirements(data,
        ["contract.salary","contract.hours","contract.start","contract.end"])
    assert contract_errors


def test_prevencion_no_requiere_confirmacion_de_vinculo_laboral():
    data={
        "employer":{"name":"Empresa sintética","rut":"11.111.111-1"},
        "worker":{"name":"Trabajador sintético","rut":"11.111.111-1"},
        "site":{"name":"Obra sintética"},"role":"PINTURA",
        "employment_type":"","event_type":"ingreso",
        "event":{"date":"2026-11-06"},"contract":{},
    }
    templates={"pts":{"published_version":1,"has_body":True}}
    out={x["code"]:x for x in eligibility(data,templates,{"PTS:PINTOR"})}
    assert out["pts"]["status"]=="LISTO_PARA_EMITIR"
    assert out["labor_contract"]["status"]=="POR_DETERMINAR"


def test_areas_del_excel_son_dos_y_documentos_diez():
    assert len(DOCUMENTS)==10
    assert sum(x[1]=="Zona Subcontratos" for x in DOCUMENTS)==4
    assert sum(x[1]=="Prevención de Riesgos" for x in DOCUMENTS)==6


def test_reglamento_interno_no_solicita_datos_contractuales():
    reg=next(x for x in DOCUMENTS if x[0]=="internal_rules_receipt")
    assert not any(x in reg[4] for x in
        ["contract.start","contract.end","contract.salary","contract.hours"])
    assert "event.date" in reg[4]
    # The verified original REGLAMENTO INTERNO sheet contains no version field.
    assert "extra.regulation_version" not in reg[4]


def test_aliases_solo_equivalencias_declaradas():
    assert len(CARGO_ALIASES)==len(set(CARGO_ALIASES))
    assert CARGO_ALIASES["PINTURA"]=="PINTOR"


def _worker_dossier(client, headers):
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    company = create_company(client, headers, site, "CT", "Empresa sintética")
    worker = client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": site, "contractor_id": company["contractor_id"],
        "name": "Persona sintética", "rut": "11.111.111-1",
    })
    assert worker.status_code == 201, worker.text
    payload = {
        "site_id": site, "employer_id": company["contractor_id"],
        "worker_id": worker.json()["worker_id"], "relationship": "contractor",
        "data": {"role": "PINTURA", "event_type": "ingreso", "contract": {},
                 "event": {"date": "2026-11-06"}},
    }
    saved = client.post("/api/v1/javiera/dossiers", headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    return payload, saved.json()


def test_historical_alias_matrices_keep_working_and_latest_equivalent_wins(env):
    client, sessions = env
    headers = login(client, "a@example.cl")
    _, saved = _worker_dossier(client, headers)
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        foreign = db.scalar(select(User).where(User.email == "outside@example.cl"))
        user_id, org_id, foreign_id, foreign_org = user.id, user.org_id, foreign.id, foreign.org_id
        db.add(JavieraTemplate(org_id=org_id, code="pts", area="Prevención de Riesgos",
            title="PTS sintético", body="PTS para {{worker.name}} en {{site.name}}. Cargo {{role}}.",
            fields=["worker.name", "worker.rut", "site.name", "role"], published_version=1))
        db.add(JavieraMatrix(org_id=org_id, kind="PTS", cargo="PINTURA", revision=7,
            status="approved", author_id=user_id, sections=["Medida histórica aprobada"] * 17,
            created_at=datetime(2026, 11, 1, tzinfo=timezone.utc)))
    result = client.post("/api/v1/javiera/eligibility/evaluate", headers=headers,
                         json={"dossier_id": saved["id"]})
    pts = next(row for row in result.json()["documents"] if row["code"] == "pts")
    assert pts["can_issue"], pts
    # Vista previa estructurada y motor Excel deben usar la misma matriz histórica.
    preview = client.post("/api/v1/javiera/preview", headers=headers,
                          json={"dossier_id": saved["id"], "code": "pts"})
    assert preview.status_code == 200, preview.text
    with fitz.open(stream=preview.content, filetype="pdf") as pdf:
        assert "Medida histórica aprobada" in " ".join(page.get_text() for page in pdf)
    with sessions() as db:
        user = db.get(User, user_id)
        assert matrix_sections(db, user, "PTS", "PINTOR") == ["Medida histórica aprobada"] * 17
    with sessions.begin() as db:
        # El contador canónico pudo reiniciarse antes de esta corrección.
        for org, author, cargo, revision, status, day, text in (
            (org_id, user_id, "PINTOR", 1, "approved", 2, "Medida canónica vigente"),
            (org_id, user_id, "PINTOR", 9, "draft", 3, "Borrador no aprobado"),
            (foreign_org, foreign_id, "PINTOR", 50, "approved", 4, "Otra organización"),
        ):
            db.add(JavieraMatrix(org_id=org, kind="PTS", cargo=cargo, revision=revision,
                status=status, author_id=author, sections=[text] * 17,
                created_at=datetime(2026, 11, day, tzinfo=timezone.utc)))
    with sessions() as db:
        assert matrix_sections(db, db.get(User, user_id), "PTS", "PINTURA") == ["Medida canónica vigente"] * 17
    issued = client.post("/api/v1/javiera/issue", headers=headers,
                         json={"dossier_id": saved["id"], "code": "pts"})
    assert issued.status_code == 200, issued.text
    pdf_reply = client.get("/api/v1/javiera/issued/" + issued.json()["id"] + "/pdf")
    assert pdf_reply.status_code == 200
    assert pdf_reply.headers["content-type"] == "application/pdf"
    assert pdf_reply.headers["content-disposition"].startswith("inline;")
    assert "no-store" in pdf_reply.headers["cache-control"]
    with fitz.open(stream=pdf_reply.content, filetype="pdf") as pdf:
        text = " ".join(page.get_text() for page in pdf)
        assert "Medida canónica vigente" in text
        assert "Medida histórica aprobada" not in text
        assert "Borrador no aprobado" not in text
        assert "Otra organización" not in text
    revision = client.post("/api/v1/javiera/admin/matrices", headers=headers, json={
        "kind": "PTS", "cargo": "Pintura", "sections": ["Nueva sección sintética"] * 17,
    })
    assert revision.status_code == 200, revision.text
    assert revision.json()["revision"] == 10
    login(client, "outside@example.cl")
    assert client.get("/api/v1/javiera/issued/" + issued.json()["id"] + "/pdf").status_code == 404


def test_worker_dossier_cannot_be_moved_into_company_declaration(env):
    client, _ = env
    headers = login(client, "a@example.cl")
    payload, saved = _worker_dossier(client, headers)
    changed = {**payload, "worker_id": None, "expected_revision": saved["revision"],
               "data": {**payload["data"], "_dossier_id": saved["id"], "event_type": "declaracion"}}
    rejected = client.post("/api/v1/javiera/dossiers", headers=headers, json=changed)
    assert rejected.status_code == 409, rejected.text
    original = client.get("/api/v1/javiera/dossiers/" + saved["id"]).json()
    assert original["worker_id"] == payload["worker_id"]
    assert original["revision"] == saved["revision"]
    assert original["data"]["event_type"] == "ingreso"
    # El documento de empresa debe tener su propio expediente e historial.
    changed["data"].pop("_dossier_id")
    changed["expected_revision"] = None
    created = client.post("/api/v1/javiera/dossiers", headers=headers, json=changed)
    assert created.status_code == 200, created.text
    assert created.json()["id"] != saved["id"]


def test_sources_provide_assignment_ids_to_complete_missing_ruts(env):
    client, _ = env
    headers = login(client, "a@example.cl")
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    company = create_company(client, headers, site, "CT", "Empresa sin RUT")
    worker = client.post("/api/v1/ops/workers", headers=headers, json={
        "site_id": site, "contractor_id": company["contractor_id"], "name": "Persona sin RUT",
    }).json()
    params = {"site_id": site, "contractor_id": company["contractor_id"]}
    source = client.get("/api/v1/javiera/sources", params=params).json()
    company_row = next(row for row in source["contractors"] if row["id"] == company["contractor_id"])
    worker_row = next(row for row in source["workers"] if row["id"] == worker["worker_id"])
    assert company_row["association_id"] == company["id"]
    assert worker_row["association_id"] == worker["id"]
    for path, association in (("contractors", company_row), ("workers", worker_row)):
        updated = client.patch("/api/v1/ops/" + path + "/" + association["association_id"],
                               headers=headers, json={"rut": "11.111.111-1"})
        assert updated.status_code == 200, updated.text
    completed = client.get("/api/v1/javiera/sources", params=params).json()
    assert all(row["rut"] for row in completed["contractors"] + completed["workers"])
    login(client, "outside@example.cl")
    assert client.get("/api/v1/javiera/sources", params=params).status_code == 404
