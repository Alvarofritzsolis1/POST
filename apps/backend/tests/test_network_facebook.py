"""Pruebas de seguridad, idempotencia y publicación sin contacto real con Meta."""
from io import BytesIO
from urllib.error import HTTPError, URLError

from app.config import settings
from app.network_facebook import meta_http_error, process_next
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
    body["publish_to_facebook"] = True
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
    edit["publish_to_facebook"] = True
    edit.update({"version": current["version"], "reason": "Cambio de fecha",
                 "title": "Carpinteros para terminaciones, segunda etapa"})
    updated = n["send"](n["a"], "/requirements/" + req["id"], edit, "PUT")
    assert updated.status_code == 200, updated.text
    assert process_next(n["Session"]) is True
    assert len(calls) == 3  # no nueva publicación para cambios
    assert calls[-1][1] == "/1489275590928529_99887766"
    assert "segunda etapa" in calls[-1][2]

    cancel = request_body(n, items=2)
    cancel["publish_to_facebook"] = True
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
    body["publish_to_facebook"] = True
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


def test_facebook_opt_out_never_creates_external_job(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    body = request_body(n)
    # Omitido por API = no consentimiento; la casilla del formulario nuevo sí envía True.
    created = n["send"](n["a"], "/requirements", body)
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["publish_to_facebook"] is False
    assert data["facebook"]["state"] == "not_selected"
    with n["Session"]() as db:
        assert db.query(NetworkFacebookPost).count() == 0
    assert process_next(n["Session"]) is False


def test_facebook_can_be_disabled_on_an_existing_post(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    body = request_body(n)
    body["publish_to_facebook"] = True
    created = n["send"](n["a"], "/requirements", body)
    assert created.status_code == 201, created.text
    req_id = created.json()["id"]
    calls = []

    def graph(method, path, token, message=None):
        calls.append((method, path))
        return {"id": "1489275590928529_445566"} if path.endswith("/feed") else {"success": True}

    monkeypatch.setattr("app.network_facebook.graph_request", graph)
    assert process_next(n["Session"])
    current = n["a"].get("/api/v1/network/requirements/" + req_id).json()
    edit = request_body(n)
    edit.update({
        "publish_to_facebook": False,
        "version": current["version"],
        "reason": "Desactivar difusión externa",
    })
    updated = n["send"](n["a"], "/requirements/" + req_id, edit, "PUT")
    assert updated.status_code == 200, updated.text
    assert process_next(n["Session"])
    assert calls == [
        ("POST", "/1489275590928529/feed"),
        ("DELETE", "/1489275590928529_445566"),
    ]


def test_galancito_local_writes_only_hook_for_selected_automatic_ad(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "ollama")
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_AD_ENABLED", "true")
    settings.cache_clear()
    body = request_body(n)
    body["publish_to_facebook"] = True
    made = n["send"](n["a"], "/requirements", body)
    assert made.status_code == 201, made.text
    calls, generated = [], []
    monkeypatch.setattr("app.facebook_ai.generate_ad_opening",
                        lambda title, trade: generated.append((title, trade)) or
                        "Buscamos especialistas en " + trade)
    def send(method, path, token, message=None):
        calls.append(message or "")
        return {"id": "1489275590928529_909090"} if method == "POST" and path.endswith("/feed") else {"success": True}
    monkeypatch.setattr("app.network_facebook.graph_request", send)
    assert process_next(n["Session"]) is True
    assert len(generated) == 1 and len(calls) == 1
    assert calls[0].startswith("Buscamos especialistas en")
    assert "Dotación estimada:" in calls[0]
    assert "Inicio estimado:" in calls[0]
    assert "Convocatoria sujeta a evaluación" in calls[0]
    settings.cache_clear()


def test_galancito_local_auto_ad_falls_back_without_hallucinations(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "ollama")
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_AD_ENABLED", "true")
    settings.cache_clear()
    body = request_body(n)
    body["publish_to_facebook"] = True
    assert n["send"](n["a"], "/requirements", body).status_code == 201
    monkeypatch.setattr("app.facebook_ai.generate_ad_opening",
                        lambda *_: "Carpintería con sueldo garantizado $2000000")
    content = []
    monkeypatch.setattr("app.network_facebook.graph_request",
                        lambda method, path, token, msg=None:
                        content.append(msg or "") or {"id": "1489275590928529_737373"})
    assert process_next(n["Session"]) is True
    assert content[0].startswith("CONVOCATORIA PARA EMPRESAS CONTRATISTAS")
    assert "$2000000" not in content[0]
    settings.cache_clear()


def test_meta_400_shows_safe_permission_diagnostic_without_leaking_tokens():
    body = (b'{"error":{"code":200,"error_subcode":123,'
            b'"message":"access_token=private_secret_should_never_appear",'
            b'"fbtrace_id":"Trace_abcd123"}}')
    exc = HTTPError("https://graph.facebook.com/ignored", 400, "Bad Request",
                    {}, BytesIO(body))
    message = meta_http_error(exc)
    assert "HTTP 400" in message
    assert "código Meta 200" in message
    assert "pages_manage_posts" in message
    assert "Trace_abcd123" in message
    assert "private_secret_should_never_appear" not in message


def test_meta_token_expired_has_specific_recovery_hint():
    exc = HTTPError("https://graph.facebook.com/ignored", 400, "Bad Request",
                    {}, BytesIO(b'{"error":{"code":190,"message":"secret"}}'))
    message = meta_http_error(exc)
    assert "Token inválido o vencido" in message
    assert "secret" not in message


def test_facebook_center_shows_confirmed_publications_not_false_not_queued(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    body = request_body(n)
    body["publish_to_facebook"] = True
    created = n["send"](n["a"], "/requirements", body)
    assert created.status_code == 201
    req_id = created.json()["id"]

    def graph(method, path, token, message=None):
        return {"id": "1489275590928529_321987"} if method == "POST" else {"success": True}

    monkeypatch.setattr("app.network_facebook.graph_request", graph)
    assert process_next(n["Session"])
    result = n["send"](n["admin"], "/facebook/center", method="GET")
    assert result.status_code == 200, result.text
    payload = result.json()
    published = [r for r in payload["publications"] if r["requirement_id"] == req_id]
    assert len(published) == 1
    assert published[0]["state"] == "published"
    assert published[0]["post_url"] == "https://www.facebook.com/1489275590928529_321987"
    assert payload["counts"]["published_ads"] >= 1
    assert not [r for r in payload["pending_ads"] if r["requirement_id"] == req_id]
    assert n["send"](n["a"], "/facebook/center", method="GET").status_code == 403


def test_meta_400_in_worker_sets_actionable_failed_status(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    body = request_body(n)
    body["publish_to_facebook"] = True
    created = n["send"](n["a"], "/requirements", body)
    assert created.status_code == 201

    def denied(*args, **kwargs):
        raise HTTPError("https://graph.facebook.com/ignored", 400, "Bad Request",
                        {}, BytesIO(b'{"error":{"code":200,"message":"private"}}'))

    monkeypatch.setattr("app.network_facebook.graph_request", denied)
    assert process_next(n["Session"])
    requirement = n["send"](n["admin"], "/requirements/" + created.json()["id"], method="GET")
    assert requirement.status_code == 200
    status = requirement.json()["facebook"]
    assert status["state"] == "failed"
    assert "pages_manage_posts" in status["error"]
    assert "private" not in status["error"]
