"""Pruebas de seguridad, idempotencia y publicación sin contacto real con Meta."""
from urllib.error import URLError

from app.config import settings
from app.network_facebook import process_next
from app.network_models import NetworkFacebookPost
from app.network_service import today

from test_network import network, request_body  # reutilizar fixture pública Red de Obras


def _enable(monkeypatch):
    monkeypatch.setenv("FACEBOOK_AUTOPUBLISH_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "1489275590928529")
    monkeypatch.setenv("FACEBOOK_PAGE_TOKEN", "token_sintetico_no_real")
    settings.cache_clear()


def test_facebook_publishes_once_updates_and_deletes(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    body = request_body(n, items=2)
    created = n["send"](n["a"], "/requirements", body)
    assert created.status_code == 201, created.text
    req = created.json()
    assert req["facebook"]["state"] == "pending"
    calls = []

    def graph(method, path, token, message=None):
        calls.append((method, path, message))
        assert token == "token_sintetico_no_real"
        assert "Observación privada de la obra" not in (message or "")
        assert "Carpintería" in (message or "") or method == "DELETE"
        return {"id": "1489275590928529_99887766"} if path.endswith("/feed") else {"success": True}

    monkeypatch.setattr("app.network_facebook.graph_request", graph)
    assert process_next(n["Session"]) is True
    assert process_next(n["Session"]) is False
    assert len(calls) == 1
    current = n["a"].get("/api/v1/network/requirements/" + req["id"]).json()
    assert current["facebook"]["state"] == "published"
    assert current["facebook"]["post_url"]
    assert n["send"](n["admin"], "/requirements/" + req["id"] + "/facebook/sync").status_code == 200
    assert process_next(n["Session"]) is True  # actualización del mismo post
    assert calls[-1][:2] == ("POST", "/1489275590928529_99887766")

    edit = request_body(n, items=2)
    edit.update({"version": current["version"], "reason": "Cambio de fecha",
                 "title": "Carpinteros para terminaciones, segunda etapa"})
    updated = n["send"](n["a"], "/requirements/" + req["id"], edit, "PUT")
    assert updated.status_code == 200, updated.text
    assert process_next(n["Session"]) is True
    assert len(calls) == 3  # no nueva publicación para cambios
    assert calls[-1][1] == "/1489275590928529_99887766"
    assert "segunda etapa" in calls[-1][2]

    cancel = request_body(n, items=2)
    cancel.update({"state": "cancelled", "version": updated.json()["version"],
                   "reason": "Partida cancelada"})
    response = n["send"](n["a"], "/requirements/" + req["id"], cancel, "PUT")
    assert response.status_code == 200, response.text
    assert process_next(n["Session"]) is True
    assert calls[-1][:2] == ("DELETE", "/1489275590928529_99887766")
    assert n["a"].get("/api/v1/network/requirements/" + req["id"]).json()["facebook"]["state"] == "deleted"


def test_facebook_ambiguous_response_requires_manual_review(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    body = request_body(n)
    created = n["send"](n["a"], "/requirements", body)
    assert created.status_code == 201
    req_id = created.json()["id"]

    def lost_response(*_args, **_kwargs):
        raise URLError("Simulación de respuesta perdida")

    monkeypatch.setattr("app.network_facebook.graph_request", lost_response)
    assert process_next(n["Session"])
    assert not process_next(n["Session"])
    state = n["a"].get("/api/v1/network/requirements/" + req_id).json()["facebook"]
    assert state["state"] == "uncertain"
    # Impide reintentar una petición que pudo haberse procesado.
    assert n["send"](n["admin"], "/requirements/" + req_id + "/facebook/sync").status_code == 409
    # Un residente tampoco puede forzar la publicación.
    assert n["send"](n["a"], "/requirements/" + req_id + "/facebook/sync").status_code == 403


def test_facebook_off_by_default(network):
    n = network
    assert settings().facebook_autopublish_enabled is False
    req = n["send"](n["a"], "/requirements", request_body(n))
    assert req.status_code == 201
    assert req.json()["facebook"]["state"] == "disabled"
    with n["Session"]() as db:
        assert db.query(NetworkFacebookPost).count() == 0
