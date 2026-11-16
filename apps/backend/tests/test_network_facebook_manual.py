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
