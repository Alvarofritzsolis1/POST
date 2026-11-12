"""GALANT 19 — pruebas del piloto HTML/CSS -> PDF.

Pruebas con identidades sintéticas; ninguna plantilla original se borra ni
se generan evidencias de firma/entrega inexistentes.
"""
import fitz
import pytest
from sqlalchemy import func, select

from app.javiera_models import JavieraMatrix
from app.javiera_native import NativeDocumentError, render_native_pdf
from app.models import User
from app.ops_models import Contractor, Worker, WorkerAssignment
from test_control_api import env, login
from test_platform import rut

ROOT = "/api/v1/javiera/v19"
BASE = "/api/v1/javiera/v166"


def data():
    return {
        "employer": {"name": "EMPRESA DOCUMENTAL DE PRUEBA", "rut": rut(10000111)},
        "worker": {"name": "PERSONA DOCUMENTAL SINTÉTICA", "rut": rut(10000112)},
        "site": {"name": "OBRA DE PRUEBA"},
        "role": "CARPINTERO",
        "event": {"date": "2026-11-09",
                  "induction_topics": "Riesgos de caídas\nUso de equipos de protección\nAviso de emergencias"},
        "extra": {"regulation_version": "Revisión interna 2026"},
    }


def test_three_native_formats_render_without_excel_and_page_overflow():
    records = [
        ("internal_rules_receipt", None),
        ("irl", ["Tarea: inspección\nPeligro: altura\nRiesgo: caída\nMedidas: barandas"] * 32),
        ("induction", None),
    ]
    for code, matrix in records:
        output = render_native_pdf(code, data(), matrix=matrix)
        assert output.startswith(b"%PDF")
        with fitz.open(stream=output, filetype="pdf") as pdf:
            assert pdf.page_count >= 1
            text = "\n".join(p.get_text() for p in pdf)
            # Las tablas pueden partir la razón social en dos líneas de PDF.
            # Validar contenido presente sin depender de saltos de línea.
            flattened = " ".join(text.split())
            assert all(word in flattened for word in ("EMPRESA", "DOCUMENTAL", "PRUEBA"))
            assert "PERSONA DOCUMENTAL" in text
            assert "Firma trabajador" in text
            assert "GALANT" not in text
            assert all(abs(page.rect.width-595) < 1 and abs(page.rect.height-842) < 1
                       for page in pdf)
            assert all(page.get_text().strip() for page in pdf)
            for page in pdf:
                for block in page.get_text("blocks"):
                    if len(block) > 4 and isinstance(block[4], str) and block[4].strip():
                        assert block[0] >= -0.5 and block[1] >= -0.5
                        assert block[2] <= page.rect.width+0.5
                        assert block[3] <= page.rect.height+0.5
    assert fitz.open(stream=render_native_pdf("irl", data(), matrix=records[1][1]),
                     filetype="pdf").page_count > 1


def test_native_template_requires_verified_content_and_does_not_run_html():
    form = data()
    form["event"]["induction_topics"] = ""
    with pytest.raises(NativeDocumentError, match="temas reales"):
        render_native_pdf("induction", form)
    with pytest.raises(NativeDocumentError, match="matriz IRL"):
        render_native_pdf("irl", data())
    form = data()
    form["extra"]["regulation_version"] = ""
    with pytest.raises(NativeDocumentError, match="regulation_version"):
        render_native_pdf("internal_rules_receipt", form)
    form = data()
    form["event"]["induction_topics"] = '<a href="https://example.invalid">Contenido de prueba</a>'
    output = render_native_pdf("induction", form)
    with fitz.open(stream=output, filetype="pdf") as pdf:
        assert not any(page.get_links() for page in pdf)
        assert "Contenido de prueba" in pdf[0].get_text()


def _local_dossier(client, headers):
    site = client.get("/api/v1/ops/sites").json()[0]["id"]
    company = client.post(BASE + "/companies", headers=headers, json={
        "site_id": site, "origin": "new",
        "name": "EMPRESA DE PRUEBA DOCUMENTAL", "rut": rut(10000111)})
    assert company.status_code == 200, company.text
    person = client.post(BASE + "/people", headers=headers, json={
        "company_id": company.json()["id"], "origin": "new",
        "name": "PERSONA DOCUMENTAL SINTÉTICA", "rut": rut(10000112)})
    assert person.status_code == 200, person.text
    draft = client.post(BASE + "/dossiers", headers=headers, json={
        "site_id": site, "company_id": company.json()["id"],
        "person_id": person.json()["id"], "relationship": "contractor",
        "selected_codes": ["internal_rules_receipt", "induction", "irl"],
        "shared": {"role": "CARPINTERO"},
        "document_data": {
            "internal_rules_receipt": {
                "event": {"date": "2026-11-09"},
                "extra": {"regulation_version": "Reglamento 2026"}},
            "induction": {"event": {"date": "2026-11-09",
                "induction_topics": "Uso de EPP\nRiesgos del cargo\nEmergencias"}},
            "irl": {"event": {"date": "2026-11-09"}},
        },
    })
    assert draft.status_code == 200, draft.text
    return draft.json()["id"]


def test_native_preview_reads_only_local_dossier_and_never_changes_operational_users(env):
    client, sessions = env
    admin = login(client, "a@example.cl")
    before = {}
    with sessions() as db:
        before = {cls.__name__: db.scalar(select(func.count(cls.id))) for cls in (
            Worker, Contractor, WorkerAssignment)}
    dossier = _local_dossier(client, admin)
    formats = client.get(ROOT + "/formats", headers=admin)
    assert formats.status_code == 200
    assert formats.json()["mode"] == "preview_only"
    assert len(formats.json()["formats"]) == 10
    pending = {x["code"] for x in formats.json()["formats"]
               if x["status"] == "requires_published_text"}
    assert pending == {
        "labor_contract", "transfer_addendum", "extension_addendum",
        "sworn_declaration", "ppe_delivery", "pts", "pts_receipt",
    }
    for code in ("internal_rules_receipt", "induction"):
        response = client.post(ROOT + "/preview", headers=admin,
                               json={"dossier_id": dossier, "code": code})
        assert response.status_code == 200, response.text[:500]
        assert response.headers["content-type"] == "application/pdf"
        with fitz.open(stream=response.content, filetype="pdf") as pdf:
            assert len(pdf) >= 1
    missing = client.post(ROOT + "/preview", headers=admin,
                          json={"dossier_id": dossier, "code": "irl"})
    assert missing.status_code == 409
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        db.add(JavieraMatrix(org_id=user.org_id, kind="IRL", cargo="CARPINTERO",
                             revision=1, sections=[
                                 "Tarea: inspección\nPeligro: caída\nRiesgo: lesión\nMedida: barandas"],
                             status="approved", author_id=user.id, reviewer_id=user.id,
                             source="Ensayo técnico"))
    response = client.post(ROOT + "/preview", headers=admin,
                           json={"dossier_id": dossier, "code": "irl"})
    assert response.status_code == 200, response.text[:500]
    with sessions() as db:
        after = {cls.__name__: db.scalar(select(func.count(cls.id))) for cls in (
            Worker, Contractor, WorkerAssignment)}
        assert before == after
    login(client, "outside@example.cl")
    foreign = client.post(ROOT + "/preview", json={
        "dossier_id": dossier, "code": "induction"})
    assert foreign.status_code in (403, 404)


def test_seven_additional_native_formats_use_published_text_not_made_up_clauses():
    record = data()
    record["event"]["epp_items"] = "Casco: 1\nGuantes: 2 pares"
    record["event"]["pts_version"] = "PTS-2026 revision aprobada"
    record["extra"]["representative_name"] = "REPRESENTANTE DOCUMENTAL"
    record["extra"]["representative_rut"] = rut(10000113)
    approved = "CLÁUSULA PRIMERA: contenido registrado y aprobado.\n\nCLÁUSULA SEGUNDA: se conservará la redacción original."
    codes = ("labor_contract", "transfer_addendum", "extension_addendum",
             "sworn_declaration", "ppe_delivery", "pts", "pts_receipt")
    for code in codes:
        form = {**record, "worker": {"name": "", "rut": ""}} if code == "sworn_declaration" else record
        matrix = ["Sección aprobada 1", "Sección aprobada 2"] if code == "pts" else None
        pdf_bytes = render_native_pdf(code, form, matrix=matrix,
                                      approved_text=approved)
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            assert pdf.page_count >= 1
            text = " ".join(page.get_text() for page in pdf)
            assert "CLÁUSULA PRIMERA" in text
            assert "CLÁUSULA SEGUNDA" in text
            assert "GALANT" not in text
            if code == "sworn_declaration":
                assert "Firma declarante" in text
                assert "Firma trabajador" not in text
            if code == "ppe_delivery":
                assert "Casco" in text and "Guantes" in text
            if code == "pts":
                assert "Sección aprobada 1" in text


def test_seven_formats_fail_closed_without_original_text_or_pts_matrix():
    d = data()
    for code in ("labor_contract", "transfer_addendum", "extension_addendum",
                 "sworn_declaration", "ppe_delivery", "pts", "pts_receipt"):
        with pytest.raises(NativeDocumentError, match="texto original publicado"):
            render_native_pdf(code, d)
    with pytest.raises(NativeDocumentError, match="matriz PTS"):
        render_native_pdf("pts", d, approved_text="Texto original aprobado")
    d["event"]["epp_items"] = ""
    with pytest.raises(NativeDocumentError, match="event.epp_items"):
        render_native_pdf("ppe_delivery", d, approved_text="Texto original aprobado")
    d["event"]["pts_version"] = ""
    with pytest.raises(NativeDocumentError, match="event.pts_version"):
        render_native_pdf("pts_receipt", d, approved_text="Texto original aprobado")


def test_native_layout_escapes_approved_text_without_external_links():
    d = data()
    approved = "<script>alert('x')</script><a href='https://invalid.example'>Solo texto</a>"
    pdf_bytes = render_native_pdf("labor_contract", d, approved_text=approved)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        assert not any(page.get_links() for page in pdf)
        assert "Solo texto" in " ".join(page.get_text() for page in pdf)


def test_single_admin_can_enable_preview_without_publishing_legacy_approval(
        env, monkeypatch):
    from app.config import settings
    from app.javiera_models import JavieraTemplate, JavieraRevision

    client, sessions = env
    monkeypatch.setenv("JAVIERA_SOLO_PILOT", "true")
    settings.cache_clear()
    admin = login(client, "a@example.cl")
    code = "labor_contract"
    created = client.put("/api/v1/javiera/admin/templates/" + code,
                         headers=admin, json={
                             "title": "Contrato de prueba controlado",
                             "area": "Zona Subcontratos",
                             "body": "Cláusula sintética para {{worker.name}} y "
                                     "{{employer.name}}. Texto de comprobación.",
                             "fields": ["worker.name", "employer.name"],
                             "rule": {}, "layout": {},
                             "reason": "Corregir edición del piloto A4"})
    assert created.status_code == 200, created.text
    revision = created.json()["revision"]
    target = ROOT + "/templates/" + code + "/enable-preview"
    denied = client.post(target, headers=admin,
                         json={"revision": revision, "confirmed_content": False})
    assert denied.status_code == 422
    enabled = client.post(target, headers=admin,
                          json={"revision": revision, "confirmed_content": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["preview_only"] is True
    status = client.get(ROOT + "/formats", headers=admin).json()["formats"]
    assert next(row for row in status if row["code"] == code)["status"] == "ready"
    with sessions() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        original = db.scalar(select(JavieraTemplate).where(
            JavieraTemplate.org_id == user.org_id,
            JavieraTemplate.code == code))
        assert original.published_version == 0
        assert original.body in ("", None)
        revision_row = db.scalar(select(JavieraRevision).where(
            JavieraRevision.template_id == original.id,
            JavieraRevision.revision == revision))
        assert revision_row.state == "pilot_print"
        assert revision_row.reviewer_id is None
    settings.cache_clear()



@pytest.mark.parametrize("code", [
    "internal_rules_receipt", "irl", "induction",
    "labor_contract", "transfer_addendum", "extension_addendum",
    "sworn_declaration", "ppe_delivery", "pts", "pts_receipt",
])
def test_printed_a4_documents_have_no_preview_or_internal_system_messages(code):
    """La vista previa puede identificarse en la UI, NUNCA en el PDF físico."""
    synthetic = data()
    synthetic["event"]["epp_items"] = "Casco 1\nGuantes 1 par"
    synthetic["event"]["pts_version"] = "PTS-2026"
    synthetic["extra"]["representative_name"] = "REPRESENTANTE DOCUMENTAL"
    synthetic["extra"]["representative_rut"] = rut(10000113)
    if code == "sworn_declaration":
        synthetic["worker"] = {"name": "", "rut": ""}
    matrix = (["Sección preventiva de prueba para confirmar estructura de riesgos."] * 4
              if code in {"pts", "irl"} else None)
    text_source = (
        "PRIMERA: Cláusula documental original de ensayo.\n\n"
        "SEGUNDA: Los antecedentes y las firmas corresponden a este formulario."
        if code in {
            "labor_contract", "transfer_addendum", "extension_addendum",
            "sworn_declaration", "ppe_delivery", "pts", "pts_receipt",
        } else None
    )
    output = render_native_pdf(code, synthetic, matrix=matrix,
                               approved_text=text_source)
    with fitz.open(stream=output, filetype="pdf") as pdf:
        document = " ".join(page.get_text() for page in pdf).casefold()
        normalized = " ".join(document.split())
        banned = (
            "vista previa", "no acredita", "formato para completar",
            "espacios para firma física", "firmar físicamente",
            "este pdf", "generado por galant", "contenido del formato aprobado",
            "documento que se prepara", "observaciones para revisión",
        )
        assert not any(value in normalized for value in banned), (code, normalized)
        assert ("firma trabajador" if code == "irl" else "firmas") in normalized, code
        assert "firma" in normalized, code
        assert 1 <= len(pdf) <= 40
        assert all(abs(page.rect.width - 595.28) < 1 for page in pdf)
        if code == "internal_rules_receipt":
            assert "constancia de recepción" in normalized
            assert "dejo constancia de haber recibido" in normalized
