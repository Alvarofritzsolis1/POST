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
    # Galancito solicita permiso por Messenger; un administrador no puede inventarlo.
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_AUTO_REPLY_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-key-never-used")
    settings.cache_clear()
    assert incoming(n).status_code == 200
    leads = n["admin"].get("/api/v1/network/facebook/center").json()["leads"]
    lead_id = leads[0]["id"]
    assert leads[0]["ai_consent_state"] == "requested"
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
    forged = n["send"](n["admin"], "/facebook/leads/" + lead_id,
        {"ai_consent": True}, "PATCH")
    assert forged.status_code == 422
    consent = incoming(n, text="sí", mid="mid-authorized")
    assert consent.status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()["lead"]
    assert lead["ai_consent"] is True and lead["ai_consent_state"] == "accepted"
    # Simple intake stays deterministic; a nuanced explanation uses the
    # approved trade guide after the contact has explicitly consented.
    assert incoming(n, text="Explica cómo orientar este oficio sin aplicar requisitos de otro", mid="nuanced").status_code == 200
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


def test_explicit_document_help_creates_persistent_alert_and_gentle_reply(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_AUTO_REPLY_ENABLED", "true")
    settings.cache_clear()
    assert incoming(n, text="no entiendo lo del f30, no se como sacar los papeles").status_code == 200
    center = n["admin"].get("/api/v1/network/facebook/center")
    assert center.status_code == 200, center.text
    lead = center.json()["leads"][0]
    assert lead["needs_support"] is True
    assert "trámite" in lead["support_reason"] or "dificultades" in lead["support_reason"]
    assert center.json()["counts"]["support"] == 1
    notifications = n["admin"].get("/api/v1/network/notifications")
    assert notifications.status_code == 200
    support_alerts = [row for row in notifications.json()["rows"]
                      if row["resource_type"] == "facebook"]
    assert len(support_alerts) == 1
    assert support_alerts[0]["resource_id"] == lead["id"]
    # Los reintentos de Meta no pueden crear más notificaciones.
    assert incoming(n, text="no entiendo lo del f30", mid="mid-1").status_code == 200
    notifications = n["admin"].get("/api/v1/network/notifications").json()["rows"]
    assert len([row for row in notifications if row["resource_type"] == "facebook"]) == 1
    inbox = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()
    messages = inbox["messages"]
    assert messages[0]["direction"] == "inbound"
    assert messages[-1]["direction"] == "outbound"
    assert messages[-1]["state"] == "pending"
    assert messages[-1]["body"].count("?") <= 1
    assert "F-30" not in messages[-1]["body"]
    assert n["send"](n["a"], "/facebook/leads/" + lead["id"] + "/onboarding",
                     method="GET").status_code == 403
    draft = n["send"](n["admin"], "/facebook/leads/" + lead["id"] + "/suggest")
    assert draft.status_code == 200
    assert draft.json()["source"] == "help_first"
    assert draft.json()["alert_admin"] is True
    guide = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"] + "/onboarding")
    assert guide.status_code == 200
    assert guide.json()["human_followup"] is True
    assert guide.json()["ask_for_files_now"] is False

    edited = n["send"](n["admin"], "/facebook/leads/" + lead["id"],
        {"entity_type": "individual", "has_employees": False}, "PATCH")
    assert edited.status_code == 200, edited.text
    guide = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"] + "/onboarding").json()
    assert not any("Constitución" in s for s in guide["required_for_review"])
    assert not any("Contratos de trabajo" in s for s in guide["required_for_review"])
    # Only the admin may remove the alert once human assistance is provided.
    cleared = n["send"](n["admin"], "/facebook/leads/" + lead["id"],
        {"needs_support": False}, "PATCH")
    assert cleared.status_code == 200
    assert cleared.json()["needs_support"] is False
    assert cleared.json()["support_reason"] == ""


def test_bad_spelling_alone_does_not_trigger_support_alert(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="ola soy gasfite tengo do ayudantes").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["needs_support"] is False


def test_galancito_conversation_auto_reply_only_after_messenger_consent(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_AUTO_REPLY_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-key")
    settings.cache_clear()
    assert incoming(n, text="hola necesito trabajos", mid="first").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["ai_consent"] is False and lead["ai_consent_state"] == "requested"
    pending = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["messages"]
    assert len(pending) == 2
    assert "Galancito" in pending[-1]["body"] and "autorizas" in pending[-1]["body"]
    calls, ai_calls = [], []

    def send_mock(page_id, psid, msg, token):
        calls.append(msg)
        return "mid-synthetic-" + str(len(calls))
    def generate_mock(instructions, context, maximum):
        ai_calls.append(context)
        assert "Galancito" in instructions
        return "¡Hola! ¿Qué oficio haces?"
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", send_mock)
    monkeypatch.setattr("app.facebook_chat_worker.generate_text", generate_mock)
    assert process_chat_next(n["Session"]) is True
    assert len(calls) == 1 and not ai_calls
    assert incoming(n, text="Sí", mid="consent-yes").status_code == 200
    assert process_chat_next(n["Session"]) is True
    assert len(calls) == 2 and len(ai_calls) == 1
    assert calls[-1].startswith("Soy Galancito")
    assert n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]["ai_consent_state"] == "accepted"
    # Cuando responde una persona, el asistente deja de competir por la conversación.
    reply = n["send"](n["admin"], "/facebook/leads/" + lead["id"] + "/reply",
                      {"message": "Te atiendo yo desde ahora."})
    assert reply.status_code == 202
    status = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["lead"]
    assert status["ai_paused"] is True
    assert incoming(n, text="tengo dos ayudantes", mid="later").status_code == 200
    messages = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["messages"]
    assert not any(msg["state"] == "ai_pending" for msg in messages)


def test_galancito_respects_refusal_without_external_ai(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_AUTO_REPLY_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-key")
    settings.cache_clear()
    assert incoming(n, text="Hola, soy maestro", mid="intro").status_code == 200
    assert incoming(n, text="no", mid="declined").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["ai_consent_state"] == "declined" and lead["ai_consent"] is False
    assert lead["needs_support"] is True
    msgs = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["messages"]
    assert not any(m["state"] == "ai_pending" for m in msgs)
    assert any("una persona" in m["body"].lower() for m in msgs if m["direction"] == "outbound")


def test_galancito_opt_in_parser_is_deliberately_narrow():
    from app.galancito_flow import consent_decision, galancito_prefix
    assert consent_decision("sí") is True
    assert consent_decision("autorizo") is True
    assert consent_decision("NO") is False
    assert consent_decision("prefiero persona") is False
    assert consent_decision("si puedo trabajar mañana") is None
    assert "Galancito" in galancito_prefix("¿Qué oficio haces?")
    from app.galancito_flow import safe_ai_reply
    from app.galancito_flow import wants_human
    assert wants_human("prefiero persona") is True
    assert wants_human("no quiero IA") is True
    assert wants_human("no estoy seguro") is False
    assert "Galancito" in safe_ai_reply("¡Hola! ¿Qué oficio haces?")
    assert "documento de identidad" not in safe_ai_reply("envía tu documento de identidad")
    assert "contratamos" not in safe_ai_reply("Ya estas contratado")
    assert safe_ai_reply("¿Qué haces? ¿Cuándo puedes?").count("?") <= 1


def test_galancito_revocation_halts_ai_after_prior_consent(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_AUTO_REPLY_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-key")
    settings.cache_clear()
    assert incoming(n, text="hola", mid="intro").status_code == 200
    assert incoming(n, text="sí", mid="accept").status_code == 200
    assert incoming(n, text="no quiero IA", mid="withdraw").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["ai_consent_state"] == "declined"
    assert lead["ai_consent"] is False
    assert lead["needs_support"] is True
    messages = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["messages"]
    assert not any(m["state"] == "ai_pending" for m in messages)


def test_messenger_meta_rejection_preserves_codes_not_private_fields(network, monkeypatch):
    """Meta 401 ya no se reduce a HTTP 401; conserva solo información segura."""
    from io import BytesIO
    from urllib.error import HTTPError
    from app.facebook_chat_worker import meta_messenger_error

    secret = "SUPER-PRIVATE-TOKEN-MUST-NEVER-BE-SAVED"
    payload = {"error": {
        "code": 200, "error_subcode": 2018001,
        "fbtrace_id": "Aa_bb-0123",
        "message": "Denied: token=" + secret + " sender=123456789012345",
        "error_user_msg": "Private message with " + secret,
    }}
    exc = HTTPError("https://graph.facebook.com/v27.0/secret?access_token=" + secret,
                    401, "Unauthorized", {},
                    BytesIO(json.dumps(payload).encode("utf-8")))
    formatted = meta_messenger_error(exc)
    assert "HTTP 401" in formatted
    assert "código Meta 200" in formatted
    assert "subcódigo 2018001" in formatted
    assert "Aa_bb-0123" in formatted
    assert "pages_messaging" in formatted
    assert secret not in formatted and "sender=123" not in formatted
    assert "graph.facebook.com" not in formatted
    assert "Private message" not in formatted

    unknown = HTTPError("https://example.invalid/private", 401,
                        "Unauthorized", {}, BytesIO(b"not json"))
    safe = meta_messenger_error(unknown)
    assert "HTTP 401" in safe and "autorización" in safe.lower()
    assert "example.invalid" not in safe


def test_messenger_failed_delivery_is_visible_without_replaying(network, monkeypatch):
    """La IA puede estar activa pero el último mensaje no está entregado."""
    from io import BytesIO
    from urllib.error import HTTPError

    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="Hola", mid="messenger-error-1").status_code == 200
    lead_id = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]["id"]
    reply = n["send"](n["admin"], "/facebook/leads/" + lead_id + "/reply",
                      {"message": "Hola, ¿en qué puedo ayudarte?"})
    assert reply.status_code == 202
    calls = []

    def deny(*args):
        calls.append(1)
        raise HTTPError("https://graph.facebook.com/v27.0/messages", 401, "Denied", {},
                        BytesIO(json.dumps({"error": {"code": 200, "error_subcode": 2018001}}).encode()))

    monkeypatch.setattr("app.facebook_chat_worker.graph_send", deny)
    assert process_chat_next(n["Session"])
    assert not process_chat_next(n["Session"])
    assert len(calls) == 1
    overview = n["admin"].get("/api/v1/network/facebook/center").json()
    assert overview["messenger_delivery"]["state"] == "failed"
    assert "código Meta 200" in overview["messenger_delivery"]["error"]
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()
    failed = detail["messages"][-1]
    assert failed["state"] == "failed"
    assert "subcódigo 2018001" in failed["error"]

    # Un mensaje nuevo y confirmado limpia el estado global sin borrar el error histórico.
    reply = n["send"](n["admin"], "/facebook/leads/" + lead_id + "/reply",
                      {"message": "Nueva respuesta manual de prueba"})
    assert reply.status_code == 202
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda page, psid, msg, token: "mid-synthetic-recovered")
    assert process_chat_next(n["Session"])
    recovered = n["admin"].get("/api/v1/network/facebook/center").json()
    assert recovered["messenger_delivery"]["state"] == "sent"
    assert recovered["messenger_delivery"]["error"] is None
