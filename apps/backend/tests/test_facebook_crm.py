"""Isolated tests: fake Meta webhook/Messenger, no real private messages or tokens."""
import hashlib
import hmac
import json

from sqlalchemy import select

from app.config import settings
from app.facebook_crm_models import FacebookChatMessage, FacebookLead, FacebookTradeGuide
from app.facebook_chat_worker import process_chat_next
from app.models import User
from test_network import network


def enable_messaging(n, monkeypatch):
    with n["Session"]() as db:
        org_id = db.scalar(select(User.org_id).where(User.email == "admin@network.example.cl"))
    monkeypatch.setenv("FACEBOOK_MESSAGING_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_ORG_ID", org_id)
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "1489275590928529")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "synthetic-test-only-meta-secret")
    monkeypatch.setenv("FACEBOOK_WEBHOOK_VERIFY_TOKEN", "synthetic-verify-token")
    monkeypatch.setenv("FACEBOOK_PAGE_TOKEN", "synthetic-page-token")
    settings.cache_clear()
    return org_id


def incoming(n, text="soy maestro gasfiter", mid="mid-1", audio=False):
    message = {"mid": mid}
    if audio:
        message["attachments"] = [{"type": "audio", "payload": {
            "url": "https://example.test/never-fetch-me"}}]
    else:
        message["text"] = text
    payload = {"object": "page", "entry": [{"id": "1489275590928529",
        "messaging": [{"sender": {"id": "123456789012345"}, "message": message}]}]}
    data = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(b"synthetic-test-only-meta-secret", data, hashlib.sha256).hexdigest()
    return n["admin"].post("/api/v1/network/facebook/webhook", content=data,
                           headers={"X-Hub-Signature-256": signature,
                                    "Content-Type": "application/json"})


def test_webhook_requires_signed_meta_event_and_deduplicates(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    uri = "/api/v1/network/facebook/webhook"
    challenge = n["admin"].get(uri + "?hub.mode=subscribe&hub.verify_token=synthetic-verify-token&hub.challenge=TEST_OK")
    assert challenge.status_code == 200
    assert challenge.text == "TEST_OK"
    invalid = n["admin"].post(uri, content=b'{"object":"page"}')
    assert invalid.status_code == 403
    assert incoming(n).status_code == 200
    assert incoming(n).status_code == 200
    result = n["admin"].get("/api/v1/network/facebook/center")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["counts"]["contacts"] == 1
    assert data["counts"]["unread"] == 1
    lead_id = data["leads"][0]["id"]
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id)
    assert len(detail.json()["messages"]) == 1
    assert detail.json()["lead"]["ai_consent"] is False
    assert n["send"](n["a"], "/facebook/center", method="GET").status_code == 403
    assert n["send"](n["a"], "/facebook/leads/" + lead_id + "/reply",
                     {"message": "Hola maestro"}).status_code == 403
    assert incoming(n, mid="mid-audio", audio=True).status_code == 200
    messages = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()["messages"]
    assert len(messages) == 2
    assert "voz" in messages[-1]["body"]
    assert "example.test" not in str(messages)  # nunca almacenar URL externa del adjunto


def test_trade_guide_explains_documents_without_requiring_formality(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n).status_code == 200
    leads = n["admin"].get("/api/v1/network/facebook/center").json()["leads"]
    lead_id = leads[0]["id"]
    guide = {"trade": "Gasfitería", "aliases": ["gasfiter", "maestro sanitario"],
             "explanation": "Repara tuberías y desagües.",
             "document_guidance": ["Mutualidad: protección ante accidentes en obra, confirmar según contrato."],
             "approved": True}
    assert n["send"](n["a"], "/facebook/guides/gasfiteria", guide, "PUT").status_code == 403
    added = n["send"](n["admin"], "/facebook/guides/gasfiteria", guide, "PUT")
    assert added.status_code == 200, added.text
    assert n["admin"].get("/api/v1/network/facebook/guides").json()[0]["trade"] == "Gasfitería"
    update = n["send"](n["admin"], "/facebook/leads/" + lead_id,
        {"specialty": "gasfiter", "workers": 1}, "PATCH")
    assert update.status_code == 200
    assert update.json()["status"] == "new"  # PATCH no borra otros campos
    assert update.json()["ai_consent"] is False

    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-key-never-used")
    settings.cache_clear()
    def should_not_run(*args, **kwargs):
        raise AssertionError("No enviar conversación personal al proveedor sin consentimiento")
    monkeypatch.setattr("app.facebook_crm.generate_text", should_not_run)
    draft = n["send"](n["admin"], "/facebook/leads/" + lead_id + "/suggest")
    assert draft.status_code == 200, draft.text
    assert draft.json()["source"] == "template"
    assert "¿" in draft.json()["draft"]

    def fake_ai(instructions, supplied, max_chars):
        assert "Repara tuberías y desagües" in supplied
        assert "Mutualidad" in supplied
        assert "una sola pregunta" in instructions.lower() or "UNA sola pregunta" in instructions
        return "Hola maestro, soy el asistente virtual. ¿Cuándo puedes empezar?"
    monkeypatch.setattr("app.facebook_crm.generate_text", fake_ai)
    consent = n["send"](n["admin"], "/facebook/leads/" + lead_id,
        {"ai_consent": True}, "PATCH")
    assert consent.status_code == 200
    reply = n["send"](n["admin"], "/facebook/leads/" + lead_id + "/suggest")
    assert reply.status_code == 200
    assert reply.json()["source"] == "ai"
    assert "¿Cuándo" in reply.json()["draft"]


def test_reply_worker_without_actual_message_delivery(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n).status_code == 200
    lead_id = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]["id"]
    reply = n["send"](n["admin"], "/facebook/leads/" + lead_id + "/reply",
                      {"message": "Hola, ¿qué oficio haces?"})
    assert reply.status_code == 202, reply.text
    calls = []
    def fake_send(page_id, psid, message, token):
        calls.append((page_id, psid, message, token))
        return "mid-real-synthetic-1"
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", fake_send)
    assert process_chat_next(n["Session"]) is True
    assert process_chat_next(n["Session"]) is False
    assert len(calls) == 1
    assert calls[0][3] == "synthetic-page-token"
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()
    assert detail["messages"][-1]["state"] == "sent"
    assert n["admin"].get("/api/v1/network/facebook/center").json()["counts"]["contacts"] == 1
