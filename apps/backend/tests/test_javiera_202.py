"""GALANT 20.2: one-time registration of previously approved Excel, without bypassing data checks."""
from app.javiera_excel import DOC_SHEETS
from test_control_api import env, login
from test_javiera_workbook import prepare
from test_javiera_all_roles_contract import all_roles_master
import test_javiera_workbook as workbook_test_data


def test_existing_approved_master_activation_is_once_only_and_audited(env, monkeypatch, tmp_path):
    # Previously approved fixture has complete IRL + PTS for all 25 roles.
    monkeypatch.setattr(workbook_test_data, "master", lambda: all_roles_master.__wrapped__())
    client, sessions, headers, imported = prepare(env, monkeypatch, tmp_path)
    path = "/api/v1/javiera/workbook/" + imported["id"]
    request = {
        "expected_revision": imported["revision"],
        "confirmation": "PLANTILLAS_PREVIAMENTE_APROBADAS",
    }
    assert client.get("/api/v1/javiera/workbook").json()["publications"] == {}
    bad = client.post(path + "/activate-approved-master", headers=headers,
                      json={**request, "confirmation": "SI"})
    assert bad.status_code == 422
    result = client.post(path + "/activate-approved-master", headers=headers, json=request)
    assert result.status_code == 200, result.text
    assert set(result.json()["codes"]) == set(DOC_SHEETS)
    state = client.get("/api/v1/javiera/workbook").json()
    assert state["publications"] == {code: imported["id"] for code in DOC_SHEETS}
    assert result.json()["workbook_sha256"] == imported["sha256"]
    # No se inventa una segunda acta de aprobación ni se puede repetir la operación.
    assert client.post(path + "/activate-approved-master", headers=headers, json=request).status_code == 409
    newer = client.post(path + "/edit", headers=headers, json={
        "expected_revision": imported["revision"], "sheet": "Contrato Imprimible",
        "reason": "Corregir texto sintético de prueba",
        "edits": [{"cell": "A1", "value": "DOCUMENTO ACTUALIZADO"}],
    })
    assert newer.status_code == 200, newer.text
    # Las nuevas revisiones NO reciben aprobación automática.
    after = client.get("/api/v1/javiera/workbook").json()
    assert after["current"]["id"] == newer.json()["id"]
    assert after["publications"]["labor_contract"] == imported["id"]


def test_approved_master_activation_respects_permissions(env, monkeypatch, tmp_path):
    client, _, headers, imported = prepare(env, monkeypatch, tmp_path)
    path = "/api/v1/javiera/workbook/" + imported["id"] + "/activate-approved-master"
    login(client, "c@example.cl")
    response = client.post(path, json={
        "expected_revision": imported["revision"],
        "confirmation": "PLANTILLAS_PREVIAMENTE_APROBADAS",
    })
    assert response.status_code == 403



def test_unfinished_original_cannot_be_activated_by_checkbox(env, monkeypatch, tmp_path):
    client, sessions, headers, imported = prepare(env, monkeypatch, tmp_path)
    response = client.post(
        "/api/v1/javiera/workbook/" + imported["id"] + "/activate-approved-master",
        headers=headers,
        json={"expected_revision": imported["revision"],
              "confirmation": "PLANTILLAS_PREVIAMENTE_APROBADAS"},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["blocking_count"] > 0
    assert detail["issues"]
    assert client.get("/api/v1/javiera/workbook").json()["publications"] == {}
