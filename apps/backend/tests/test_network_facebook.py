"""Pruebas de seguridad, idempotencia y publicación sin contacto real con Meta."""
import base64
from io import BytesIO

from PIL import Image
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



def _visual(body):
    """JPG sintético verificado; sin contenido privado ni acceso real a Meta."""
    image = Image.new("RGB", (1080, 1350), "#0f4048")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    body["publish_to_facebook"] = True
    body["public_location"] = "San Pedro de la Paz, Biobío"
    body["poster_data"] = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    return body


def test_social_art_requires_explicit_area_and_jpg(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    body = request_body(n)
    body["publish_to_facebook"] = True
    missing_location = n["send"](n["a"], "/requirements", body)
    assert missing_location.status_code == 422
    assert "sector aproximado" in missing_location.text

    body["public_location"] = "San Pedro de la Paz, Biobío"
    missing_photo = n["send"](n["a"], "/requirements", body)
    assert missing_photo.status_code == 422
    assert "fotografía" in missing_photo.text

    body = _visual(body)
    body["public_location"] = "Brisas de Junquillar"
    internal_name = n["send"](n["a"], "/requirements", body)
    assert internal_name.status_code == 422
    assert "nombre de la obra" in internal_name.text

    body["public_location"] = "San Pedro de la Paz, Biobío"
    created = n["send"](n["a"], "/requirements", body)
    assert created.status_code == 201, created.text
    public_art = n["a"].get("/api/v1/network/requirements/" + created.json()["id"] + "/poster")
    assert public_art.status_code == 200
    assert public_art.headers["content-type"].startswith("image/jpeg")
    assert n["b"].get("/api/v1/network/requirements/" + created.json()["id"] + "/poster").status_code == 403
    catalog = n["send"](n["a"], "/catalog", method="GET").json()
    site = next(s for s in catalog["sites"] if s["id"] == body["site_id"])
    assert site["public_location"] == "San Pedro de la Paz, Biobío"


def test_facebook_publishes_once_updates_and_deletes(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    body = _visual(request_body(n, items=2))
    created = n["send"](n["a"], "/requirements", body)
    assert created.status_code == 201, created.text
    req = created.json()
    assert req["facebook"]["state"] == "pending"
    assert req["poster_available"] is True
    calls = []

    def photo(page_id, token, message, poster_path, org_id):
        calls.append(("PHOTO", page_id, message))
        assert token == "token_sintetico_no_real"
        assert "Observación privada de la obra" not in message
        assert req["site"] not in message
        assert "San Pedro de la Paz" in message
        return {"post_id": "1489275590928529_99887766"}

    def graph(method, path, token, message=None):
        calls.append((method, path, message))
        return {"success": True}

    monkeypatch.setattr("app.network_facebook.graph_photo_post", photo)
    monkeypatch.setattr("app.network_facebook.graph_request", graph)
    assert process_next(n["Session"]) is True
    assert process_next(n["Session"]) is False
    assert len(calls) == 1
    current = n["a"].get("/api/v1/network/requirements/" + req["id"]).json()
    assert current["facebook"]["state"] == "published"
    assert current["facebook"]["post_url"]
    # No auto-republicación de una foto; requiere revisión y nuevo consentimiento.
    assert n["send"](n["admin"], "/requirements/" + req["id"] + "/facebook/sync").status_code == 200
    assert process_next(n["Session"]) is True
    assert len(calls) == 1
    check = n["a"].get("/api/v1/network/requirements/" + req["id"]).json()
    assert check["facebook"]["state"] == "failed"

    edit = request_body(n, items=2)
    edit.update({"publish_to_facebook": True,
                 "public_location": "San Pedro de la Paz, Biobío",
                 "version": current["version"], "reason": "Cambio de fecha",
                 "title": "Carpinteros para terminaciones, segunda etapa"})
    updated = n["send"](n["a"], "/requirements/" + req["id"], edit, "PUT")
    assert updated.status_code == 200, updated.text
    assert process_next(n["Session"]) is True
    assert len(calls) == 1

    cancel = request_body(n, items=2)
    cancel.update({"publish_to_facebook": True,
                   "state": "cancelled", "version": updated.json()["version"],
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
    _visual(body)
    created = n["send"](n["a"], "/requirements", body)
    assert created.status_code == 201
    req_id = created.json()["id"]

    def lost_response(*_args, **_kwargs):
        raise URLError("Simulación de respuesta perdida")

    monkeypatch.setattr("app.network_facebook.graph_photo_post", lost_response)
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
    created = n["send"](n["a"], "/requirements", _visual(request_body(n)))
    assert created.status_code == 201, created.text
    req_id = created.json()["id"]
    calls = []
    monkeypatch.setattr("app.network_facebook.graph_photo_post", lambda *args: calls.append("PHOTO") or {"post_id": "1489275590928529_445566"})
    monkeypatch.setattr("app.network_facebook.graph_request", lambda method, path, token, message=None: calls.append((method, path)) or {"success": True})
    assert process_next(n["Session"])
    current = n["a"].get("/api/v1/network/requirements/" + req_id).json()
    edit = request_body(n)
    edit.update({"publish_to_facebook": False, "version": current["version"],
                 "reason": "Desactivar difusión externa"})
    updated = n["send"](n["a"], "/requirements/" + req_id, edit, "PUT")
    assert updated.status_code == 200, updated.text
    assert process_next(n["Session"])
    assert calls == ["PHOTO", ("DELETE", "/1489275590928529_445566")]


def test_galancito_local_writes_only_hook_for_selected_automatic_ad(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "ollama")
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_AD_ENABLED", "true")
    settings.cache_clear()
    made = n["send"](n["a"], "/requirements", _visual(request_body(n)))
    assert made.status_code == 201, made.text
    calls = []
    monkeypatch.setattr("app.network_facebook.graph_photo_post",
                        lambda page, token, msg, path, org: calls.append(msg) or {"post_id": "1489275590928529_909090"})
    assert process_next(n["Session"]) is True
    assert len(calls) == 1
    assert "Dotación estimada:" in calls[0]
    assert "Inicio estimado:" in calls[0]
    assert "Convocatoria sujeta a evaluación" in calls[0]
    assert "San Pedro de la Paz" in calls[0]
    settings.cache_clear()


def test_galancito_local_auto_ad_falls_back_without_hallucinations(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "ollama")
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_AD_ENABLED", "true")
    settings.cache_clear()
    assert n["send"](n["a"], "/requirements", _visual(request_body(n))).status_code == 201
    content = []
    monkeypatch.setattr("app.network_facebook.graph_photo_post",
                        lambda page, token, msg, path, org: content.append(msg) or {"post_id": "1489275590928529_737373"})
    assert process_next(n["Session"]) is True
    assert content[0].startswith("Buscamos empresas contratistas de ")
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
    created = n["send"](n["a"], "/requirements", _visual(request_body(n)))
    assert created.status_code == 201, created.text
    req_id = created.json()["id"]
    monkeypatch.setattr("app.network_facebook.graph_photo_post",
                        lambda *args: {"post_id": "1489275590928529_321987"})
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
    created = n["send"](n["a"], "/requirements", _visual(request_body(n)))
    assert created.status_code == 201

    def denied(*args, **kwargs):
        raise HTTPError("https://graph.facebook.com/ignored", 400, "Bad Request",
                        {}, BytesIO(b'{"error":{"code":200,"message":"private"}}'))

    monkeypatch.setattr("app.network_facebook.graph_photo_post", denied)
    assert process_next(n["Session"])
    requirement = n["send"](n["admin"], "/requirements/" + created.json()["id"], method="GET")
    assert requirement.status_code == 200
    status = requirement.json()["facebook"]
    assert status["state"] == "failed"
    assert "pages_manage_posts" in status["error"]
    assert "private" not in status["error"]
