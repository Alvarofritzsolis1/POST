"""Editor HTML de Proyecto Javiera: seguridad, aislamiento, revisiones y PDF A4."""
import fitz
import pytest
from sqlalchemy import func, select

from app.javiera_native_edit import (
    NativeHtmlError, bind_native_html, plain_text_to_html, validate_native_html,
)
from app.javiera_models import JavieraTemplate, JavieraRevision
from app.models import User
from app.ops_models import Worker, Contractor, WorkerAssignment
from test_javiera_v19 import _local_dossier, data, BASE, ROOT
from test_control_api import env, login


def test_html_document_editor_accepts_text_tables_and_safe_tokens():
    source = ("<h2>ACTA DE RECEPCIÓN</h2>"
              "<p>Trabajador {{worker.name}} / empresa {{employer.name}}</p>"
              "<table><tbody><tr><th>Concepto</th><td>Detalle</td></tr></tbody></table>")
    cleaned = validate_native_html(source)
    result = bind_native_html(cleaned, data())
    assert "<table>" in result and "PERSONA DOCUMENTAL" in result
    assert "{{worker.name}}" not in result
    assert "EMPRESA DOCUMENTAL" in result
    assert "&lt;script&gt;" in bind_native_html(
        "<p>Información para {{worker.name}}</p>",
        {**data(), "worker": {"name": "<script>alert(1)</script>"}}
    )
    assert "Primera" in plain_text_to_html("Primera cláusula\n\nSegunda cláusula")


@pytest.mark.parametrize("bad", [
    '<script>alert("x")</script><p>Documento de prueba válido</p>',
    '<img src="https://example.invalid/img">Texto documental largo',
    '<p onclick="alert(1)">Texto documental suficientemente largo</p>',
    '<a href="https://example.invalid">Texto documental de prueba</a>',
    '<p style="background:url(https://example.invalid)">Párrafo de prueba</p>',
    '<iframe src="https://example.invalid"></iframe>',
    '<p>Un párrafo documental que no está cerrado',
    '<p>Proyecto GALANT dentro de documento de impresión</p>',
    '<p>Variable mal formada {{worker.*}}</p>',
])
def test_html_document_editor_blocks_unsafe_markup(bad):
    with pytest.raises(NativeHtmlError):
        validate_native_html(bad)


def test_html_editor_creates_revision_and_batch_without_operational_mutations(env):
    client, sessions = env
    admin = login(client, "a@example.cl")
    with sessions() as db:
        before = {cls.__name__: db.scalar(select(func.count(cls.id)))
                  for cls in (Worker, Contractor, WorkerAssignment)}
    dossier_id = _local_dossier(client, admin)
    url = ROOT + "/editor/internal_rules_receipt"
    editor = client.get(url, headers=admin)
    assert editor.status_code == 200
    assert editor.json()["mode"] == "supplement"
    bad = client.put(url, headers=admin, json={
        "html": '<script>alert(1)</script><p>Contenido de referencia</p>',
        "reason": "Prueba de seguridad"
    })
    assert bad.status_code == 422
    saved = client.put(url, headers=admin, json={
        "html": "<h2>CONSTANCIA DOCUMENTAL</h2>"
                "<p>Empleador {{employer.name}} y trabajador {{worker.name}}</p>",
        "reason": "Reordenar constancia para impresión A4"
    })
    assert saved.status_code == 200, saved.text
    revision = saved.json()["revision"]
    assert saved.json()["state"] == "draft"
    status = {item["code"]: item["status"] for item in
              client.get(ROOT + "/formats", headers=admin).json()["formats"]}
    assert status["internal_rules_receipt"] == "requires_review"

    blocked = client.post(ROOT + "/preview", headers=admin,
                          json={"dossier_id": dossier_id,
                                "code": "internal_rules_receipt"})
    assert blocked.status_code == 409

    no_check = client.post(url + "/enable-preview", headers=admin,
                           json={"revision": revision, "confirmed_content": False})
    assert no_check.status_code == 422
    enabled = client.post(url + "/enable-preview", headers=admin,
                          json={"revision": revision, "confirmed_content": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["preview_only"] is True

    pdf = client.post(ROOT + "/preview", headers=admin,
                      json={"dossier_id": dossier_id,
                            "code": "internal_rules_receipt"})
    assert pdf.status_code == 200, pdf.text[:500]
    with fitz.open(stream=pdf.content, filetype="pdf") as doc:
        text = " ".join(page.get_text() for page in doc)
        assert "CONSTANCIA DOCUMENTAL" in text
        assert "EMPRESA DE PRUEBA" in text
        assert "GALANT" not in text

    packet = client.post(ROOT + "/preview/batch", headers=admin, json={
        "dossier_id": dossier_id, "codes": ["internal_rules_receipt", "induction"]})
    assert packet.status_code == 200, packet.text[:500]
    assert packet.headers["content-type"] == "application/pdf"
    with fitz.open(stream=packet.content, filetype="pdf") as doc:
        assert len(doc) >= 2
        assert all(abs(page.rect.width - 595.3) < 1 for page in doc)
        all_text = " ".join(page.get_text() for page in doc)
        assert "CONSTANCIA DOCUMENTAL" in all_text
        assert "REGISTRO DE INDUCCIÓN" in all_text
    repeated = client.post(ROOT + "/preview/batch", headers=admin, json={
        "dossier_id": dossier_id,
        "codes": ["internal_rules_receipt", "internal_rules_receipt"]})
    assert repeated.status_code == 422

    with sessions() as db:
        after = {cls.__name__: db.scalar(select(func.count(cls.id)))
                 for cls in (Worker, Contractor, WorkerAssignment)}
        assert before == after
        account = db.scalar(select(User).where(User.email == "a@example.cl"))
        template = db.scalar(select(JavieraTemplate).where(
            JavieraTemplate.org_id == account.org_id,
            JavieraTemplate.code == "internal_rules_receipt"))
        assert template.published_version == 0
        native = db.scalar(select(JavieraRevision).where(
            JavieraRevision.template_id == template.id,
            JavieraRevision.revision == revision))
        assert native.state == "pilot_print"
        assert native.reviewer_id is None


def test_native_html_revision_is_organization_scoped(env):
    client, _ = env
    first = login(client, "a@example.cl")
    url = ROOT + "/editor/extension_addendum"
    sample = "<h2>ANEXO DE PRUEBA</h2><p>Texto de prueba con empresa {{employer.name}}</p>"
    outcome = client.put(url, headers=first, json={
        "html": sample, "reason": "Texto del anexo documental"})
    assert outcome.status_code == 200
    login(client, "outside@example.cl")
    isolated = client.get(url)
    assert isolated.status_code == 200
    assert sample not in isolated.json()["html"]
