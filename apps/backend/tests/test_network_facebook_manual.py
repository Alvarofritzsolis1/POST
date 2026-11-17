"""Aceptación del módulo manual Facebook: no se llama a Meta en estas pruebas."""
from datetime import timedelta
from uuid import uuid4
from urllib.error import URLError

from app.config import settings
from app.network_facebook import process_manual_next
from app.network_service import today
from app.network_models import NetworkFacebookManual
from test_network import network


ROOT = "/facebook/tests"
PAGE_ID = "1489275590928529"


def _ad(n):
    start = today() + timedelta(days=9)
    return {
        "site_id": n["sites"][0],
        "title": "Empresas de carpintería para terminaciones",
        "specialty": "Carpintería",
        "city": "Coronel",
        "region": "Región del Biobío",
        "workers": 3,
        "start_date": str(start),
        "end_date": str(start + timedelta(days=20)),
        "deadline": str(start + timedelta(days=8)),
        "items": ["Instalación de puertas", "Terminaciones interiores"],
        "requirements": "Experiencia demostrable y documentación contractual vigente.",
        "contact_mode": "messenger",
        "contact_value": "",
    }


def _enable(monkeypatch):
    monkeypatch.setenv("FACEBOOK_MANUAL_TESTING_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AUTOPUBLISH_ENABLED", "false")
    monkeypatch.setenv("FACEBOOK_PAGE_ID", PAGE_ID)
    monkeypatch.setenv("FACEBOOK_PAGE_TOKEN", "prueba-local-sintetica-no-real")
    settings.cache_clear()


def test_preview_without_enabling_has_no_external_side_effects(network, monkeypatch):
    n = network
    data = _ad(n)
    answer = n["send"](n["admin"], ROOT + "/preview", data)
    assert answer.status_code == 200, answer.text
    preview = answer.json()
    assert "NO ES UNA CONVOCATORIA REAL" in preview["message"]
    assert "Coronel" in preview["message"]
    assert "Instalación de puertas" in preview["message"]
    assert "prueba-local-sintetica-no-real" not in str(preview)
    assert n["send"](n["a"], ROOT + "/preview", data).status_code == 403
    disabled = n["send"](n["admin"], ROOT + "/verify", {}).status_code
    assert disabled == 409
    disabled_post = n["send"](n["admin"], ROOT + "/publish", {
        "ad": data,
        "preview_hash": preview["preview_hash"],
        "confirmation": "PUBLICAR PRUEBA",
        "client_key": str(uuid4()),
    })
    assert disabled_post.status_code == 409
    with n["Session"]() as db:
        assert db.query(NetworkFacebookManual).count() == 0


def test_manual_verify_publish_and_remove(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    page = n["send"](n["admin"], ROOT + "/verify", {})
    assert page.status_code == 202, page.text
    requests = []

    def graph(method, path, token, message=None):
        requests.append((method, path, message))
        assert token == "prueba-local-sintetica-no-real"
        if method == "GET":
            return {"id": PAGE_ID, "name": "Portal Trabajo Contratistas De Construccion"}
        if method == "DELETE":
            return {"success": True}
        assert message.startswith("🧪 PUBLICACIÓN DE PRUEBA")
        assert "documentación contractual" in message
        return {"id": PAGE_ID + "_11223344"}

    monkeypatch.setattr("app.network_facebook.graph_request", graph)
    assert process_manual_next(n["Session"])
    assert requests[0][:2] == ("GET", "/" + PAGE_ID)
    assert not process_manual_next(n["Session"])
    status = n["admin"].get("/api/v1/network/facebook/tests").json()
    assert status["verified_page_name"] == "Portal Trabajo Contratistas De Construccion"
    assert status["manual_enabled"] is True and status["automatic_enabled"] is False

    ad = _ad(n)
    preview = n["send"](n["admin"], ROOT + "/preview", ad).json()
    key = str(uuid4())
    data = {"ad": ad, "preview_hash": preview["preview_hash"],
            "confirmation": "PUBLICAR PRUEBA", "client_key": key}
    sent = n["send"](n["admin"], ROOT + "/publish", data)
    assert sent.status_code == 202, sent.text
    assert sent.json()["state"] == "pending"
    dupe = n["send"](n["admin"], ROOT + "/publish", data)
    assert dupe.status_code == 202 and dupe.json()["id"] == sent.json()["id"]
    assert process_manual_next(n["Session"])
    assert not process_manual_next(n["Session"])
    assert len(requests) == 2
    history = n["admin"].get("/api/v1/network/facebook/tests").json()["history"]
    post = next(r for r in history if r["id"] == sent.json()["id"])
    assert post["state"] == "published"
    assert post["post_url"] == "https://www.facebook.com/" + PAGE_ID + "_11223344"

    bad = dict(data)
    bad["ad"] = {**ad, "title": "Otro anuncio distinto"}
    assert n["send"](n["admin"], ROOT + "/publish", bad).status_code == 409
    assert n["send"](n["a"], ROOT + "/publish", data).status_code == 403
    removing = n["send"](n["admin"], ROOT + "/" + post["id"] + "/remove", {
        "confirmation": "RETIRAR PRUEBA",
    })
    assert removing.status_code == 202
    assert process_manual_next(n["Session"])
    assert requests[-1][:2] == ("DELETE", "/" + PAGE_ID + "_11223344")
    status = n["admin"].get("/api/v1/network/facebook/tests").json()["history"]
    assert next(r for r in status if r["id"] == post["id"])["state"] == "deleted"


def test_network_outage_marks_uncertain_without_duplicate_retries(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    ad = _ad(n)
    preview = n["send"](n["admin"], ROOT + "/preview", ad).json()
    sent = n["send"](n["admin"], ROOT + "/publish", {
        "ad": ad, "preview_hash": preview["preview_hash"],
        "confirmation": "PUBLICAR PRUEBA", "client_key": str(uuid4()),
    })
    assert sent.status_code == 202
    calls = []

    def down(*args, **kwargs):
        calls.append(1)
        raise URLError("respuesta perdida")

    monkeypatch.setattr("app.network_facebook.graph_request", down)
    assert process_manual_next(n["Session"])
    assert not process_manual_next(n["Session"])
    assert len(calls) == 1
    history = n["admin"].get("/api/v1/network/facebook/tests").json()["history"]
    assert history[0]["state"] == "uncertain"
    assert n["send"](n["admin"], ROOT + "/" + sent.json()["id"] + "/remove", {
        "confirmation": "RETIRAR PRUEBA",
    }).status_code == 409


def test_validation_does_not_allow_false_contact_or_bad_dates(network):
    n = network
    ad = _ad(n)
    ad["contact_mode"] = "whatsapp"
    ad["contact_value"] = "abc"
    assert n["send"](n["admin"], ROOT + "/preview", ad).status_code == 422
    ad = _ad(n)
    ad["deadline"] = "2020-01-01"
    assert n["send"](n["admin"], ROOT + "/preview", ad).status_code == 422
    ad = _ad(n)
    ad["site_id"] = "nonexistent"
    assert n["send"](n["admin"], ROOT + "/preview", ad).status_code == 422


def test_automatic_channel_can_verify_without_enabling_manual_posts(network, monkeypatch):
    """Una verificación GET es segura y funciona sin permitir anuncios de prueba."""
    n = network
    _enable(monkeypatch)
    monkeypatch.setenv("FACEBOOK_MANUAL_TESTING_ENABLED", "false")
    monkeypatch.setenv("FACEBOOK_AUTOPUBLISH_ENABLED", "true")
    settings.cache_clear()
    calls = []

    def graph(method, path, token, message=None):
        calls.append((method, path))
        assert method == "GET" and message is None
        assert path == "/" + PAGE_ID
        return {"id": PAGE_ID, "name": "Página de pruebas sintética"}

    monkeypatch.setattr("app.network_facebook.graph_request", graph)
    queued = n["send"](n["admin"], ROOT + "/verify", {})
    assert queued.status_code == 202, queued.text
    assert queued.json()["state"] == "pending"
    assert n["send"](n["a"], ROOT + "/verify", {}).status_code == 403
    assert process_manual_next(n["Session"])
    assert not process_manual_next(n["Session"])
    assert calls == [("GET", "/" + PAGE_ID)]

    status = n["admin"].get("/api/v1/network/facebook/center").json()
    assert status["connection"]["state"] == "verified"
    assert status["connection"]["page_name"] == "Página de pruebas sintética"
    assert status["connection"]["checked_at"]
    assert "FACEBOOK_PAGE_TOKEN" not in str(status)
    tests = n["admin"].get("/api/v1/network/facebook/tests").json()
    assert tests["verification"]["state"] == "verified"
    assert tests["verified_page_name"] == "Página de pruebas sintética"
    assert not tests["manual_enabled"] and tests["automatic_enabled"]
    ad = _ad(n)
    preview = n["send"](n["admin"], ROOT + "/preview", ad).json()
    assert n["send"](n["admin"], ROOT + "/publish", {
        "ad": ad, "preview_hash": preview["preview_hash"],
        "confirmation": "PUBLICAR PRUEBA", "client_key": str(uuid4()),
    }).status_code == 409


def test_token_error_190_is_reported_and_can_be_reverified(network, monkeypatch):
    """El error 190 no se confunde con un token activo después de una verificación."""
    import io
    import json
    from urllib.error import HTTPError

    n = network
    _enable(monkeypatch)
    monkeypatch.setenv("FACEBOOK_MANUAL_TESTING_ENABLED", "false")
    monkeypatch.setenv("FACEBOOK_AUTOPUBLISH_ENABLED", "true")
    settings.cache_clear()

    def expired(method, path, token, message=None):
        raise HTTPError("https://graph.facebook.com/", 400, "Bad Request", {},
                        io.BytesIO(json.dumps({"error": {"code": 190, "error_subcode": 463}}).encode()))

    monkeypatch.setattr("app.network_facebook.graph_request", expired)
    assert n["send"](n["admin"], ROOT + "/verify", {}).status_code == 202
    assert process_manual_next(n["Session"])
    failed = n["admin"].get("/api/v1/network/facebook/center").json()["connection"]
    assert failed["state"] == "failed"
    assert "190" in failed["error"] and "463" in failed["error"]
    assert "token_sintetico" not in str(failed)

    monkeypatch.setattr("app.network_facebook.graph_request",
                        lambda method, path, token, message=None: {"id": PAGE_ID, "name": "Página recuperada"})
    assert n["send"](n["admin"], ROOT + "/verify", {}).status_code == 202
    assert process_manual_next(n["Session"])
    verified = n["admin"].get("/api/v1/network/facebook/center").json()["connection"]
    assert verified["state"] == "verified"
    assert verified["error"] is None
    assert verified["page_name"] == "Página recuperada"


def test_missing_worker_token_fails_verification_without_secrets(network, monkeypatch):
    n = network
    _enable(monkeypatch)
    monkeypatch.setenv("FACEBOOK_MANUAL_TESTING_ENABLED", "false")
    monkeypatch.setenv("FACEBOOK_AUTOPUBLISH_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_PAGE_TOKEN", "")
    settings.cache_clear()
    assert n["send"](n["admin"], ROOT + "/verify", {}).status_code == 202
    assert process_manual_next(n["Session"])
    data = n["admin"].get("/api/v1/network/facebook/center").json()["connection"]
    assert data["state"] == "failed"
    assert "FACEBOOK_PAGE_TOKEN" in data["error"]
    assert not process_manual_next(n["Session"])
