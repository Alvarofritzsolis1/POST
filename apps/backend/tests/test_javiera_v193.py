"""GALANT 19.3 — catálogo de labores IRL, PDF real y bloqueo preventivo.

Datos sintéticos; ninguna prueba escribe en trabajadores operativos.
"""
import fitz
import unicodedata
from sqlalchemy import func, select

from app.javiera_irl import parse_irl_section
from app.javiera_models import JavieraMatrix
from app.javiera_native import render_native_pdf
from app.models import User
from app.ops_models import Contractor, Worker, WorkerAssignment
from test_control_api import env, login
from test_javiera_v19 import _local_dossier, data

ROOT = "/api/v1/javiera/v193"
FORM = "/api/v1/javiera/v166"

SECTION = ("Tarea: Aplicar pintura sobre muros\n"
           "Peligro: Solvente inflamable\n"
           "Riesgo: Exposición e incendio\n"
           "Medidas: Ventilar y utilizar controles aprobados")


def test_parser_preserves_all_irl_fields_and_legacy_medida():
    section = parse_irl_section(SECTION, version=4, ordinal=1, cargo="PINTOR")
    assert section["structured"] is True
    assert section["labor"] == "Aplicar pintura sobre muros"
    assert section["peligro"] == "Solvente inflamable"
    assert section["riesgo"] == "Exposición e incendio"
    assert section["medidas"] == "Ventilar y utilizar controles aprobados"
    legacy = parse_irl_section("Tarea: inspeccionar\nPeligro: altura\nRiesgo: caída\n"
                               "Medida: barandas", version=1, ordinal=2, cargo="PINTOR")
    assert legacy["structured"] is True
    assert legacy["medidas"] == "barandas"
    malformed = parse_irl_section("Revisar puesto de trabajo", version=1,
                                   ordinal=1, cargo="PINTOR")
    assert malformed["structured"] is False
    assert malformed["original"] == "Revisar puesto de trabajo"


def test_irl_pdf_is_generated_from_structured_preventive_matrix():
    form = data()
    form["role"] = "PINTOR"
    pdf_bytes = render_native_pdf("irl", form, matrix=[SECTION])
    assert pdf_bytes.startswith(b"%PDF")
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        text = unicodedata.normalize("NFKC", " ".join(" ".join(page.get_text().split()) for page in pdf))
        for expected in ("Labor o tarea", "Peligro", "Riesgo",
                         "Medidas preventivas", "Aplicar pintura",
                         "Solvente", "inflamable", "Ventilar"):
            assert expected in text, expected
        assert not any(page.get_links() for page in pdf)
        assert "GALANT" not in text


def test_role_search_only_uses_organization_matrices_and_reports_approval(env):
    client, sessions = env
    headers = login(client, "a@example.cl")
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        db.add(JavieraMatrix(org_id=user.org_id, kind="IRL", cargo="PINTOR",
                             revision=1, sections=[SECTION], status="approved",
                             author_id=user.id, reviewer_id=user.id,
                             source="Datos sintéticos de prueba"))
        db.add(JavieraMatrix(org_id=user.org_id, kind="PTS", cargo="PINTOR",
                             revision=1, sections=["PTS sintético"]*17,
                             status="draft", author_id=user.id,
                             source="Datos sintéticos de prueba"))
    result = client.get(ROOT + "/roles?query=pint", headers=headers)
    assert result.status_code == 200, result.text
    items = result.json()["roles"]
    assert len(items) == 1
    assert items[0]["cargo"] == "PINTOR"
    assert items[0]["has_approved_irl"] is True
    assert items[0]["has_approved_pts"] is False
    detail = client.get(ROOT + "/role?cargo=PINTOR", headers=headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["irl"]["approved"] is True
    assert payload["irl"]["records"][0]["medidas"] == "Ventilar y utilizar controles aprobados"
    assert payload["can_preview_irl"] is True
    assert payload["pts"]["approved"] is False
    assert payload["historical_pdfs_unchanged"] is True
    missing = client.get(ROOT + "/role?cargo=CARGO NO CATALOGADO", headers=headers)
    assert missing.status_code == 200
    assert missing.json()["irl"]["records"] == []
    assert missing.json()["can_preview_irl"] is False


def test_manual_labor_is_saved_in_documentary_draft_but_blocks_printing(env):
    client, sessions = env
    headers = login(client, "a@example.cl")
    before = {}
    with sessions() as db:
        before = {cls.__name__: db.scalar(select(func.count(cls.id)))
                  for cls in (Worker, Contractor, WorkerAssignment)}
    dossier_id = _local_dossier(client, headers)
    dossier = client.get(FORM + "/dossiers/" + dossier_id, headers=headers).json()
    body = {
        "dossier_id": dossier_id, "expected_revision": dossier["revision"],
        "site_id": dossier["site_id"], "company_id": dossier["company_id"],
        "person_id": dossier["person_id"], "relationship": dossier["relationship"],
        "selected_codes": dossier["selected_codes"], "shared": dossier["shared"],
        "document_data": {**dossier["document_data"],
                          "irl": {"event": {"date": "2026-11-09",
                                            "irl_manual_labor": "Labores inexistentes en el catálogo"}}},
    }
    result = client.post(FORM + "/dossiers", headers=headers, json=body)
    assert result.status_code == 200, result.text
    saved = client.get(FORM + "/dossiers/" + dossier_id, headers=headers).json()
    assert saved["document_data"]["irl"]["event"]["irl_manual_labor"]
    # Guardar un borrador nunca equivale a aprobación preventiva.
    preview = client.post("/api/v1/javiera/v19/preview", headers=headers,
                          json={"dossier_id": dossier_id, "code": "irl"})
    assert preview.status_code == 409
    assert "labor manual" in preview.json()["detail"].lower()
    eligibility = client.get(FORM + "/dossiers/" + dossier_id + "/eligibility",
                             headers=headers)
    assert eligibility.status_code == 200, eligibility.text
    irl = next(item for item in eligibility.json()["documents"] if item["code"] == "irl")
    assert irl["can_issue"] is False
    assert "labor manual" in irl["reason"].lower()
    with sessions() as db:
        after = {cls.__name__: db.scalar(select(func.count(cls.id)))
                 for cls in (Worker, Contractor, WorkerAssignment)}
        assert before == after



def test_approved_but_incomplete_irl_is_rejected_for_new_pdf(env):
    client, sessions = env
    admin = login(client, "a@example.cl")
    dossier_id = _local_dossier(client, admin)
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        db.add(JavieraMatrix(org_id=user.org_id, kind="IRL", cargo="CARPINTERO",
                             revision=1, sections=[
                                 "Tarea: corte\nPeligro: filo\nRiesgo: herida\nMedida: "
                             ], status="approved", author_id=user.id,
                             reviewer_id=user.id, source="Prueba de migración histórica"))
    info = client.get(ROOT+"/role", headers=admin, params={"cargo": "CARPINTERO"})
    assert info.status_code == 200
    assert info.json()["irl"]["approved"] is True
    assert info.json()["can_preview_irl"] is False
    preview = client.post("/api/v1/javiera/v19/preview",
                          headers=admin, json={"dossier_id": dossier_id, "code": "irl"})
    assert preview.status_code == 409, preview.text
    assert "medida preventiva" in preview.json()["detail"].lower()
    eligibility = client.get(FORM + "/dossiers/" + dossier_id + "/eligibility", headers=admin)
    item = next(d for d in eligibility.json()["documents"] if d["code"] == "irl")
    assert item["can_issue"] is False
    assert any("medida preventiva" in e.lower() for e in item["blocking_errors"])


def test_irl_pdf_binds_approved_matrix_revision_not_entered_text(env):
    client, sessions = env
    admin = login(client, "a@example.cl")
    dossier_id = _local_dossier(client, admin)
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        db.add(JavieraMatrix(org_id=user.org_id, kind="IRL", cargo="CARPINTERO",
                             revision=7, sections=[SECTION], status="approved",
                             author_id=user.id, reviewer_id=user.id,
                             source="Revisión sintética 7"))
    pdf = client.post("/api/v1/javiera/v19/preview", headers=admin,
                      json={"dossier_id": dossier_id, "code": "irl"})
    assert pdf.status_code == 200, pdf.text[:500]
    with fitz.open(stream=pdf.content, filetype="pdf") as pages:
        text = unicodedata.normalize("NFKC", " ".join(" ".join(page.get_text().split()) for page in pages))
        assert "IRL revisión 7" in text
        assert "Solvente" in text and "inflamable" in text


def test_irl_table_writer_does_not_truncate_at_eighty_rows():
    from app.javiera_native import _irl_table_rows
    source = [SECTION.replace("Aplicar pintura", "Labor "+str(n))
              for n in range(1, 103)]
    content = _irl_table_rows(source, "PINTOR")
    assert content.count("<tr>") == 102
    assert "Labor 102" in content
    assert "Labor 1 " in content



def test_pts_prints_real_seventeen_technical_headings():
    """El PDF PTS identifica todos los apartados D:T de su fuente."""
    from app.javiera_native import _pts_table_rows
    from app.javiera_pts_headers import PTS_TECHNICAL_HEADINGS
    assert len(PTS_TECHNICAL_HEADINGS) == 17
    values = [f"Procedimiento controlado {i}" for i in range(1, 18)]
    rows = _pts_table_rows(values)
    assert rows.count("<tr>") == 17
    for heading in PTS_TECHNICAL_HEADINGS:
        assert heading in rows
    assert "Procedimiento controlado 17" in rows
    with fitz.open(stream=render_native_pdf(
        "pts", data(), matrix=values, approved_text="Texto original técnico de ensayo verificado."
    ), filetype="pdf") as pdf:
        content = " ".join(" ".join(page.get_text().split()) for page in pdf)
        assert "OBJETIVO" in content and "GLOSARIO" in content
        assert "Procedimiento controlado 17" in content
        assert all(page.get_text().strip() for page in pdf)
