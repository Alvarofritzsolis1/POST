"""Existing Excel source: no manual approval workflow, full safety checks."""
from app.javiera_excel import DOC_SHEETS
from app.javiera_workbook import audit_preventive_master
from app.javiera_workbook_api import raw_for, active_workbook
from test_control_api import env, login
from test_javiera_workbook import prepare
from test_javiera_all_roles_contract import all_roles_master
import test_javiera_workbook as workbook_test_data


def test_existing_excel_documents_available_without_approval_clicks(env, monkeypatch, tmp_path):
    monkeypatch.setattr(workbook_test_data, "master",
                        lambda: all_roles_master.__wrapped__())
    client, sessions, headers, imported = prepare(env, monkeypatch, tmp_path)
    source = "/api/v1/javiera/workbook"
    status = client.get(source, headers=headers).json()
    assert status["current"]["id"] == imported["id"]
    assert status["publications"] == {
        code: imported["id"] for code in DOC_SHEETS
    }
    # Former approval endpoint is gone, and no extra acta is created.
    assert client.post(source + "/" + imported["id"] +
                       "/activate-approved-master", headers=headers,
                       json={"expected_revision": imported["revision"],
                             "confirmation": "PLANTILLAS_PREVIAMENTE_APROBADAS"}
                       ).status_code == 404
    newer = client.post(source + "/" + imported["id"] + "/edit",
                        headers=headers, json={
        "expected_revision": imported["revision"],
        "sheet": "Contrato Imprimible",
        "reason": "Actualizar el formato existente para pruebas",
        "edits": [{"cell": "A1", "value": "FORMATO ACTUALIZADO QA"}],
    })
    assert newer.status_code == 200, newer.text
    result = newer.json()
    state = client.get(source, headers=headers).json()
    assert state["current"]["id"] == result["id"]
    assert state["publications"] == {code: result["id"] for code in DOC_SHEETS}
    with sessions() as db:
        active = active_workbook(db, imported["org_id"] if "org_id" in imported
            else db.get(__import__("app.javiera_workbook_models",
                     fromlist=["JavieraWorkbook"]).JavieraWorkbook,
                     result["id"]).org_id, published=True, code="irl")
        assert active.id == result["id"]


def test_existing_document_registration_respects_permissions(env, monkeypatch, tmp_path):
    client, _, headers, imported = prepare(env, monkeypatch, tmp_path)
    login(client, "c@example.cl")
    assert client.get("/api/v1/javiera/workbook").status_code == 403
    assert client.post("/api/v1/javiera/workbook/" + imported["id"] + "/edit",
        json={"expected_revision": imported["revision"], "sheet": "Contrato Imprimible",
              "reason": "No autorizado para editar este documento",
              "edits": [{"cell":"A1","value":"NO AUTORIZADO"}]}).status_code == 403


def test_incomplete_source_stays_identifiable_without_approval_form(env, monkeypatch, tmp_path):
    client, sessions, headers, imported = prepare(env, monkeypatch, tmp_path)
    state = client.get("/api/v1/javiera/workbook",headers=headers).json()
    assert state["publications"]["irl"] == imported["id"]
    inspection = client.get("/api/v1/javiera/workbook/" +
                            imported["id"] + "/audit/preventive", headers=headers)
    assert inspection.status_code == 200, inspection.text
    assert inspection.json()["blocking_count"] > 0
    assert inspection.json()["findings"]
    # A known incomplete role must not be silently considered content-complete
    # merely because the imported Excel is available as a source.



def test_legacy_master_on_vps_becomes_available_without_reupload_or_user_action(
    env, monkeypatch, tmp_path
):
    from app.javiera_workbook_models import JavieraWorkbookHead, JavieraWorkbook
    from app.models import User
    from app.javiera_workbook_api import active_workbook
    from sqlalchemy import select

    client, sessions, headers, imported = prepare(env, monkeypatch, tmp_path)
    with sessions.begin() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        head = db.get(JavieraWorkbookHead, user.org_id)
        head.publications = {}
        head.published_id = None
        db.flush()
        found = active_workbook(db, user.org_id, published=True, code="irl")
        assert found.id == imported["id"]

    response = client.get("/api/v1/javiera/workbook", headers=headers)
    assert response.status_code == 200
    assert response.json()["publications"]["irl"] == imported["id"]
    assert response.json()["publications"]["pts"] == imported["id"]
    with sessions() as db:
        user = db.scalar(select(User).where(User.email == "a@example.cl"))
        head = db.get(JavieraWorkbookHead, user.org_id)
        assert head.publications == {}
        assert head.published_id is None
    # A future save registers the available sources durably, without approval.
