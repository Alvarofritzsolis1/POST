"""Isolated tests: fake Meta webhook/Messenger, no real private messages or tokens."""
import hashlib
import hmac
import json
import pytest

from sqlalchemy import select

from app.config import settings
from app.facebook_crm_models import FacebookChatMessage, FacebookLead, FacebookTradeGuide
from app.facebook_chat_worker import process_chat_next
from app.models import User
from test_network import network


@pytest.fixture(autouse=True)
def no_real_meta_sender_actions(monkeypatch):
    """Synthetic CI must never mark a real person's Messenger thread seen."""
    monkeypatch.setattr("app.facebook_chat_worker.graph_sender_action",
                        lambda page_id, psid, action, token: None)


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
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-key-never-used")
    settings.cache_clear()
    assert incoming(n, text="¿Cuáles son los requisitos para postular?").status_code == 200
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
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
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
    monkeypatch.setenv("FACEBOOK_AI_AUTO_REPLY_ENABLED", "false")
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-key")
    settings.cache_clear()
    readiness = n["admin"].get("/api/v1/network/facebook/center").json()
    assert readiness["auto_reply_enabled"] is True
    assert readiness["auto_reply"]["configured"] is True
    assert incoming(n, text="¿Cuáles son los requisitos para postular?", mid="first").status_code == 200
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
    assert "¿Qué oficio haces?" in calls[-1]
    assert "asistente virtual" not in calls[-1].lower()
    assert n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]["ai_consent_state"] == "accepted"
    # A manual answer takes this turn, but the next incoming turn is automatic.
    reply = n["send"](n["admin"], "/facebook/leads/" + lead["id"] + "/reply",
                      {"message": "Te atiendo yo desde ahora."})
    assert reply.status_code == 202
    status = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["lead"]
    assert status["ai_paused"] is False
    assert incoming(n, text="tengo dos ayudantes", mid="later").status_code == 200
    messages = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["messages"]
    assert any(msg["state"] == "ai_pending" for msg in messages)


def test_manual_trade_question_continues_automatically_and_can_be_paused(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-key")
    settings.cache_clear()
    assert incoming(n, text="hola", mid="trade-hello").status_code == 200
    lead_id = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]["id"]
    sent = n["send"](n["admin"], "/facebook/leads/" + lead_id + "/reply",
                     {"message": "Hola, gracias por escribirnos. ¿En qué oficio te especializas?"})
    assert sent.status_code == 202
    sends = []
    def send_once(page, psid, body, token):
        sends.append(body)
        return "mid-manual-" + str(len(sends))
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", send_once)
    assert process_chat_next(n["Session"])
    assert incoming(n, text="SOY GASFITER", mid="trade-answer").status_code == 200
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()
    assert detail["lead"]["specialty"] == "Gasfitería"
    assert detail["lead"]["ai_paused"] is False
    queued = detail["messages"][-1]
    assert queued["state"] == "pending" and queued["automated"] is True
    assert "gasfitería" in queued["body"].lower()
    assert "cuenta" in queued["body"].lower()
    assert process_chat_next(n["Session"])
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()
    assert detail["messages"][-1]["state"] == "sent"
    paused = n["send"](n["admin"], "/facebook/leads/" + lead_id,
                       {"ai_paused": True}, "PATCH")
    assert paused.status_code == 200 and paused.json()["ai_paused"] is True
    assert incoming(n, text="trabajo por mi cuenta", mid="trade-paused").status_code == 200
    assert n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()["messages"][-1]["direction"] == "inbound"
    resumed = n["send"](n["admin"], "/facebook/leads/" + lead_id,
                        {"ai_paused": False}, "PATCH")
    assert resumed.status_code == 200 and resumed.json()["ai_paused"] is False
    assert incoming(n, text="trabajo solo", mid="trade-resumed").status_code == 200
    assert n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()["messages"][-1]["automated"] is True


def test_new_inbound_replaces_unsent_automatic_question(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    settings.cache_clear()
    assert incoming(n, text="hola", mid="replacement-1").status_code == 200
    lead_id = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]["id"]
    first = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()["messages"][-1]
    assert first["state"] == "pending"
    assert incoming(n, text="soy gasfiter", mid="replacement-2").status_code == 200
    messages = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()["messages"]
    assert next(msg for msg in messages if msg["id"] == first["id"])["state"] == "cancelled"
    assert messages[-1]["state"] == "pending" and "gasfitería" in messages[-1]["body"].lower()


def test_explicit_human_request_notifies_administration(network, monkeypatch):
    from app.network_models import NetworkNotification

    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    settings.cache_clear()
    assert incoming(n, text="Quiero hablar con una persona", mid="human-request-1").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["needs_support"] is True
    assert "humana" in lead["support_reason"].lower()
    with n["Session"]() as db:
        alerts = db.scalars(select(NetworkNotification).where(
            NetworkNotification.resource_id == lead["id"])).all()
    assert alerts and all(alert.resource_type == "facebook" for alert in alerts)
    assert n["send"](n["admin"], "/facebook/leads/" + lead["id"],
                     {"needs_support": False}, "PATCH").status_code == 200
    assert incoming(n, text="Quiero hablar con una persona", mid="human-request-2").status_code == 200
    with n["Session"]() as db:
        repeated = db.scalars(select(NetworkNotification).where(
            NetworkNotification.resource_id == lead["id"])).all()
    assert len(repeated) == 2 * len(alerts)


def test_model_failure_notifies_human_instead_of_sending_generic_answer(network, monkeypatch):
    from app.network_models import NetworkNotification

    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-key")
    settings.cache_clear()
    assert incoming(n, text="hola", mid="complex-hello").status_code == 200
    lead_id = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]["id"]
    with n["Session"].begin() as db:
        lead = db.get(FacebookLead, lead_id)
        lead.ai_consent = True
        lead.ai_consent_state = "accepted"
        for pending in db.scalars(select(FacebookChatMessage).where(
                FacebookChatMessage.lead_id == lead_id,
                FacebookChatMessage.direction == "outbound")):
            pending.state = "cancelled"
    assert incoming(n, text="¿Cuánto pagan en una obra?", mid="complex-question").status_code == 200
    monkeypatch.setattr("app.facebook_chat_worker.generate_text",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("model unavailable")))
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda page, psid, body, token: sent.append(body) or "mid-complex-fallback")
    assert process_chat_next(n["Session"])
    assert len(sent) == 1 and "pendiente de revisión humana" in sent[0]
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()
    assert detail["lead"]["needs_support"] is True
    with n["Session"]() as db:
        assert db.scalar(select(NetworkNotification.id).where(
            NetworkNotification.resource_id == lead_id))


def test_automatic_reply_limit_alerts_instead_of_failing_silently(network, monkeypatch):
    from app.network_models import NetworkNotification

    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    settings.cache_clear()
    assert incoming(n, text="hola", mid="limit-hello").status_code == 200
    lead_id = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]["id"]
    with n["Session"].begin() as db:
        lead = db.get(FacebookLead, lead_id)
        for i in range(29):
            db.add(FacebookChatMessage(org_id=lead.org_id, lead_id=lead.id,
                                       page_id=lead.page_id, direction="outbound",
                                       state="sent", body="Respuesta sintética " + str(i)))
    assert incoming(n, text="SOY GASFITER", mid="limit-trade").status_code == 200
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()
    assert detail["lead"]["needs_support"] is True
    assert "Límite" in detail["lead"]["support_reason"]
    assert detail["messages"][-1]["direction"] == "inbound"
    with n["Session"]() as db:
        assert db.scalar(select(NetworkNotification.id).where(
            NetworkNotification.resource_id == lead_id))


def test_galancito_respects_refusal_without_external_ai(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
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


def test_verified_ai_team_answers_messenger_only_after_new_consent(network, monkeypatch):
    from cryptography.fernet import Fernet
    from app import ai_gateway
    from app.ai_models import AIConnection, AIOrchestration, AIUsage

    n = network
    org_id = enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("AI_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    settings.cache_clear()
    with n["Session"].begin() as db:
        admin_id = db.scalar(select(User.id).where(User.email == "admin@network.example.cl"))
        connection = AIConnection(
            org_id=org_id, updated_by=admin_id, name="Modelo de Messenger",
            provider="groq", model="llama-3.1-8b-instant",
            encrypted_key=ai_gateway.encrypt_key("synthetic-groq-key"),
            enabled=True, last_status="verified",
        )
        db.add(connection)
        db.flush()
        db.add(AIOrchestration(
            org_id=org_id, enabled=True, updated_by=admin_id,
            task_routes={"red_obras": connection.id, "messenger": connection.id},
        ))

    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, *_args):
            return json.dumps({
                "choices": [{"message": {"content": "¿En qué comuna puedes trabajar?"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            }).encode()

    def generate(request, timeout):
        calls.append(request)
        assert request.get_header("Authorization") == "Bearer synthetic-groq-key"
        return Response()

    sent = []
    monkeypatch.setattr(ai_gateway, "urlopen", generate)
    def send(page, psid, body, token):
        sent.append(body)
        return "sent-" + str(len(sent))

    monkeypatch.setattr("app.facebook_chat_worker.graph_send", send)
    monkeypatch.setattr("app.facebook_chat_worker.quick_reply", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.facebook_chat_worker.exact_answer", lambda *_args, **_kwargs: None)

    assert incoming(n, text="Necesito orientación para preparar una oferta", mid="team-1").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["ai_consent_state"] == "requested_team"
    assert process_chat_next(n["Session"]) is True
    assert "proveedores de IA externos" in sent[0]
    assert calls == []
    assert incoming(n, text="sí", mid="team-consent").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["ai_consent_state"] == "accepted_team"
    assert process_chat_next(n["Session"]) is True
    assert len(calls) == 1
    assert "comuna" in sent[-1]
    with n["Session"]() as db:
        assert db.scalar(select(AIUsage).where(AIUsage.task == "messenger")).total_tokens == 19


def test_messenger_reasks_when_legacy_consent_precedes_team_assignment(network, monkeypatch):
    from cryptography.fernet import Fernet
    from app import ai_gateway
    from app.ai_models import AIConnection, AIOrchestration

    n = network
    org_id = enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-openai-key")
    monkeypatch.setenv("AI_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    settings.cache_clear()
    assert incoming(n, text="¿Cuáles son los requisitos para postular?", mid="old-1").status_code == 200
    assert incoming(n, text="sí", mid="old-consent").status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["ai_consent_state"] == "accepted"

    with n["Session"].begin() as db:
        admin_id = db.scalar(select(User.id).where(User.email == "admin@network.example.cl"))
        connection = AIConnection(
            org_id=org_id, updated_by=admin_id, name="Modelo nuevo",
            provider="gemini", model="gemini-2.5-flash",
            encrypted_key=ai_gateway.encrypt_key("synthetic-gemini-key"),
            enabled=True, last_status="verified",
        )
        db.add(connection)
        db.flush()
        db.add(AIOrchestration(
            org_id=org_id, enabled=True, updated_by=admin_id,
            task_routes={"red_obras": connection.id, "messenger": connection.id},
        ))

    assert incoming(n, text="¿Qué necesito para ofrecer servicios?", mid="new-2").status_code == 200
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()
    assert detail["lead"]["ai_consent_state"] == "requested_team"
    assert detail["lead"]["ai_consent"] is False
    assert any("proveedores de IA externos" in message["body"] for message in detail["messages"])
    assert not any(message["state"] == "ai_pending" for message in detail["messages"])


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


def test_lead_insights_proposes_name_without_editing_and_ranks_needs(network, monkeypatch):
    from datetime import timedelta
    from uuid import uuid4
    from app.network_models import NetworkRequirement
    from app.network_service import today

    n = network
    enable_messaging(n, monkeypatch)
    response = incoming(n, "Hola, me llamo Juan Pérez, soy gasfiter. Tengo 3 trabajadores",
                        mid="juan-profile-1")
    assert response.status_code == 200
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    with n["Session"].begin() as db:
        org_id = db.get(FacebookLead, lead["id"]).org_id
        requirement = NetworkRequirement(
            org_id=org_id, site_id=n["sites"][0], created_by=n["a_user"]["id"],
            specialty="Gasfitería", specialty_key="gasfiteria",
            title="Instalaciones sanitarias", description="Redes de agua",
            workers=2, priority="normal", state="published",
            start_date=today()+timedelta(days=5),
            end_date=today()+timedelta(days=20),
            deadline=today()+timedelta(days=4),
            client_key=uuid4().hex,
        )
        db.add(requirement)
        db.flush()
        target_id = requirement.id
    insights = n["admin"].get("/api/v1/network/facebook/leads/"+lead["id"]+"/insights")
    assert insights.status_code == 200, insights.text
    payload = insights.json()
    assert payload["changes_applied"] is False
    assert payload["review_required"] is True
    assert payload["matches"][0]["id"] == target_id
    assert payload["matches"][0]["site"] == "Brisas de Junquillar"
    assert payload["matches"][0]["review_required"]
    assert any(item["field"] == "name" and item["value"] == "Juan Pérez"
               for item in payload["suggestions"])
    unchanged = n["admin"].get("/api/v1/network/facebook/leads/"+lead["id"]).json()
    assert unchanged["lead"]["name"] == "Interesado de Facebook"
    assert unchanged["lead"]["requirement_id"] is None
    assert n["send"](n["a"], "/facebook/leads/"+lead["id"]+"/insights",
                     method="GET").status_code == 403
    confirmed = n["send"](n["admin"], "/facebook/leads/"+lead["id"],
                          {"name": "Juan Pérez", "requirement_id": target_id}, "PATCH")
    assert confirmed.status_code == 200
    assert confirmed.json()["name"] == "Juan Pérez"
    assert confirmed.json()["requirement_id"] == target_id


def test_profile_links_only_one_compatible_active_requirement(network, monkeypatch):
    from datetime import timedelta
    from uuid import uuid4
    from app.network_models import NetworkRequirement
    from app.network_service import today

    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="soy gasfiter", mid="link-hello").status_code == 200
    lead_id = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]["id"]
    with n["Session"].begin() as db:
        org_id = db.get(FacebookLead, lead_id).org_id
        reqs = []
        for index in range(2):
            req = NetworkRequirement(
                org_id=org_id, site_id=n["sites"][index], created_by=n["a_user"]["id"],
                specialty="Gasfitería", specialty_key="gasfiteria",
                title="Gasfitería obra " + str(index), workers=2,
                start_date=today() + timedelta(days=8),
                end_date=today() + timedelta(days=18),
                deadline=today() + timedelta(days=6),
                client_key=uuid4().hex, state="published")
            db.add(req)
            reqs.append(req)
        db.flush()
        target_id = reqs[0].id
        other_id = reqs[1].id
    ready = {"interest_type": "service_offer", "specialty": "Gasfitería",
             "workers": 3, "availability": (today() + timedelta(days=2)).isoformat()}
    ambiguous = n["send"](n["admin"], "/facebook/leads/" + lead_id, ready, "PATCH")
    assert ambiguous.status_code == 200 and ambiguous.json()["requirement_id"] is None
    with n["Session"].begin() as db:
        db.get(NetworkRequirement, other_id).state = "draft"
    unique = n["send"](n["admin"], "/facebook/leads/" + lead_id,
                       {"work_area": "Coronel"}, "PATCH")
    assert unique.status_code == 200 and unique.json()["requirement_id"] == target_id


def test_messenger_profile_name_is_optional_and_does_not_override_manual_name(network, monkeypatch):
    from app import facebook_chat_worker as worker
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, "Hola", mid="profile-1").status_code == 200
    lead_id = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]["id"]
    called = []
    def resolved(psid, token):
        called.append((psid, token))
        return "María Fernández"
    monkeypatch.setattr(worker, "messenger_profile_name", resolved)
    worker._profile_attempted.clear()
    monkeypatch.setattr(worker, "_profile_auth_denied", False)
    assert worker.process_profile_next(n["Session"]) is True
    assert worker.process_profile_next(n["Session"]) is False
    assert len(called) == 1
    assert called[0][1] == "synthetic-page-token"
    got = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()["lead"]
    assert got["name"] == "María Fernández"
    assert n["send"](n["admin"], "/facebook/leads/"+lead_id,
                     {"name": "María Fernanda"}, "PATCH").status_code == 200
    worker._profile_attempted.clear()
    assert worker.process_profile_next(n["Session"]) is False
    again = n["admin"].get("/api/v1/network/facebook/leads/" + lead_id).json()["lead"]
    assert again["name"] == "María Fernanda"


def test_local_name_extractor_rejects_ambiguous_job_titles():
    from types import SimpleNamespace
    from app.facebook_lead_insights import name_from_conversation
    name = lambda body: name_from_conversation([SimpleNamespace(direction="inbound", body=body)])
    assert name("Soy Juan Pérez y trabajo en obra")["value"] == "Juan Pérez"
    assert name("Me llamo Carlos")["value"] == "Carlos"
    assert name("soy maestro carpintero") is None
    assert name("hola necesito trabajo") is None


def test_recover_external_message_missing_from_webhook(network, monkeypatch):
    """Old messages become inbox leads without reopening a stale conversation."""
    from app.network_facebook import process_manual_next
    from app import facebook_inbox_sync as recovery

    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    settings.cache_clear()
    requests = []

    def fake_meta(token, resource, edge, fields, limit):
        requests.append(edge)
        assert token == "synthetic-page-token"
        if edge == "conversations":
            return {"data": [{"id": "t_synthetic_external_001"}]}
        return {"data": [
            {"id": "m_test_external_001", "message": "Hola, soy carpintero",
             "from": {"id": "987654321098765"},
             "created_time": "2020-11-18T13:50:00+0000"},
            {"id": "m_test_echo_002", "message": "Respuesta de la página",
             "from": {"id": "1489275590928529"},
             "created_time": "2020-11-18T13:51:00+0000"},
        ]}

    monkeypatch.setattr(recovery, "_graph_get", fake_meta)
    assert n["send"](n["a"], "/facebook/inbox/sync").status_code == 403
    queued = n["send"](n["admin"], "/facebook/inbox/sync")
    assert queued.status_code == 202 and queued.json()["queued"]
    assert process_manual_next(n["Session"])
    center = n["admin"].get("/api/v1/network/facebook/center").json()
    assert center["inbox_sync"]["state"] == "synced"
    assert "1 mensajes" in center["inbox_sync"]["summary"]
    assert center["counts"]["contacts"] == 1
    detail = n["admin"].get(
        "/api/v1/network/facebook/leads/" + center["leads"][0]["id"]).json()
    assert [x["body"] for x in detail["messages"]] == ["Hola, soy carpintero"]
    assert detail["messages"][0]["direction"] == "inbound"
    assert requests == ["conversations", "messages"]
    # Within the rate limit, a repeated click never schedules duplicate work.
    repeated = n["send"](n["admin"], "/facebook/inbox/sync")
    assert repeated.status_code == 202 and not repeated.json()["queued"]


def test_recovery_queues_fresh_unanswered_trade_once(network, monkeypatch):
    from datetime import timezone, datetime
    from app import facebook_inbox_sync as recovery

    n = network
    org_id = enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_AUTO_REPLY_ENABLED", "false")
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    settings.cache_clear()
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(recovery, "_graph_get", lambda token, resource, edge, fields, limit:
        {"data": [{"id": "t_fresh_gasfiter_01"}]} if edge == "conversations" else
        {"data": [{"id": "m_fresh_gasfiter_01", "message": "SOY GASFITER",
                   "from": {"id": "987654321098765"}, "created_time": now}]})
    first = recovery.sync_page_inbox(page_id="1489275590928529",
                                     page_token="synthetic-page-token",
                                     org_id=org_id, session_factory=n["Session"])
    assert first["messages_imported"] == 1 and first["replies_queued"] == 1
    second = recovery.sync_page_inbox(page_id="1489275590928529",
                                      page_token="synthetic-page-token",
                                      org_id=org_id, session_factory=n["Session"])
    assert second["messages_imported"] == 0 and second["replies_queued"] == 0
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    assert lead["specialty"] == "Gasfitería"
    messages = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["messages"]
    assert len(messages) == 2 and messages[-1]["automated"]


def test_recovery_does_not_answer_after_meta_page_reply(network, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app import facebook_inbox_sync as recovery

    n = network
    org_id = enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    settings.cache_clear()
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(recovery, "_graph_get", lambda token, resource, edge, fields, limit:
        {"data": [{"id": "t_already_answered_01"}]} if edge == "conversations" else
        {"data": [
            {"id": "m_answered_in_01", "message": "SOY GASFITER",
             "from": {"id": "987654321098765"},
             "created_time": (now - timedelta(minutes=2)).isoformat()},
            {"id": "m_answered_out_01", "message": "Gracias por responder",
             "from": {"id": "1489275590928529"},
             "created_time": (now - timedelta(minutes=1)).isoformat()},
        ]})
    result = recovery.sync_page_inbox(page_id="1489275590928529",
                                      page_token="synthetic-page-token",
                                      org_id=org_id, session_factory=n["Session"])
    assert result["messages_imported"] == 1 and result["replies_queued"] == 0


def test_recovery_deduplicates_webhook_messages(network, monkeypatch):
    from app import facebook_inbox_sync as recovery

    n = network
    org_id = enable_messaging(n, monkeypatch)
    assert incoming(n, text="Mensaje existente", mid="m_same_remote_1").status_code == 200
    monkeypatch.setattr(recovery, "_graph_get", lambda token, resource, edge, fields, limit:
        {"data": [{"id": "t_synthetic_external_001"}]} if edge == "conversations" else
        {"data": [{"id": "m_same_remote_1", "message": "Mensaje existente",
                   "from": {"id": "123456789012345"},
                   "created_time": "2026-11-18T13:50:00+0000"}]})
    first = recovery.sync_page_inbox(
        page_id="1489275590928529", page_token="synthetic-page-token",
        org_id=org_id, session_factory=n["Session"])
    assert first["messages_imported"] == 0
    assert first["new_contacts"] == 0
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()
    assert len(detail["messages"]) == 1


def test_recovery_meta_190_is_sanitized_and_visible(network, monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    from app import facebook_inbox_sync as recovery
    from app.network_facebook import process_manual_next

    n = network
    enable_messaging(n, monkeypatch)
    secret = "NOT-TO-BE-STORED-SECRET"
    def deny(token, resource, edge, fields, limit):
        raise HTTPError("https://graph.facebook.com/?access_token=" + secret,
                        401, "Unauthorized", {},
                        BytesIO(json.dumps({"error": {"code": 190,
                            "message": "token " + secret}}).encode()))
    monkeypatch.setattr(recovery, "_graph_get", deny)
    assert n["send"](n["admin"], "/facebook/inbox/sync").status_code == 202
    assert process_manual_next(n["Session"])
    result = n["admin"].get("/api/v1/network/facebook/center").json()["inbox_sync"]
    assert result["state"] == "failed"
    assert "190" in result["error"]
    assert secret not in str(result)


def test_automatic_messenger_recovery_does_not_need_manual_click(network, monkeypatch):
    """Worker polls the Page API automatically, but not repeatedly on Meta failures."""
    from app import facebook_inbox_sync as recovery
    n = network
    org_id = enable_messaging(n, monkeypatch)
    observed = []

    class StopAfterFirstCycle:
        def __init__(self):
            self.waits = []

        def wait(self, seconds):
            self.waits.append(seconds)
            return len(self.waits) == 2

        def is_set(self):
            return False

    def fake_sync(**kwargs):
        observed.append(kwargs)
        return {"messages_imported": 1}

    monkeypatch.setattr(recovery, "sync_page_inbox", fake_sync)
    signal = StopAfterFirstCycle()
    recovery.periodic_recovery(signal)
    assert signal.waits == [5, 30]
    assert len(observed) == 1
    assert observed[0]["org_id"] == org_id
    assert observed[0]["conversation_limit"] == 10
    assert observed[0]["message_limit"] == 15


def test_automatic_messenger_recovery_backs_off_on_unauthorized(network, monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    from app import facebook_inbox_sync as recovery
    enable_messaging(network, monkeypatch)

    class StopAfterFirstCycle:
        def __init__(self):
            self.waits = []

        def wait(self, seconds):
            self.waits.append(seconds)
            return len(self.waits) == 2

        def is_set(self):
            return False

    def deny(**kwargs):
        raise HTTPError("https://graph.facebook.com/v27.0/123",
                        401, "Unauthorized", {}, BytesIO(b"{}"))

    monkeypatch.setattr(recovery, "sync_page_inbox", deny)
    signal = StopAfterFirstCycle()
    recovery.periodic_recovery(signal)
    assert signal.waits == [5, 300]


def test_inbox_preview_disambiguates_multiple_unknown_contacts(network, monkeypatch):
    """Contact cards should show the latest text rather than duplicate Nuevo labels."""
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="Hola, soy maestro", mid="preview-a-1").status_code == 200
    overview = n["admin"].get("/api/v1/network/facebook/center").json()
    assert overview["leads"][0]["last_message"] == {
        "text": "Hola, soy maestro", "direction": "inbound"}
    assert "psid" not in overview["leads"][0]  # Keep identifiers out of the UI.



def test_messenger_automatic_reply_readiness_explains_missing_configuration(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "false")
    settings.cache_clear()
    result = n["admin"].get("/api/v1/network/facebook/center")
    assert result.status_code == 200, result.text
    assert result.json()["auto_reply_enabled"] is False
    auto = result.json()["auto_reply"]
    assert auto["configured"] is False
    assert any("Asistente de Facebook deshabilitado" in item for item in auto["missing"])
    assert "token" not in str(auto).lower()
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    settings.cache_clear()
    response = n["admin"].get("/api/v1/network/facebook/center")
    assert response.status_code == 200, response.text
    assert response.json()["auto_reply_enabled"] is True
    # Local replies do not depend on a verified external model.
    assert response.json()["auto_reply"]["configured"] is True
    assert response.json()["ai_provider"] == "disabled"


def test_facebook_name_fills_on_arrival_and_history_reconciles(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    assert incoming(n, text="hola soy carpintero", mid="name-first").status_code == 200
    current = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    with n["Session"].begin() as db:
        lead = db.get(FacebookLead, current["id"])
        db.add(FacebookChatMessage(
            org_id=lead.org_id, lead_id=lead.id, page_id=lead.page_id,
            direction="outbound", state="sent", body="¿Cuál es tu nombre?",
        ))
    assert incoming(n, text="ALVARO", mid="name-declared").status_code == 200
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + current["id"]).json()
    assert detail["lead"]["name"] == "ALVARO"
    assert "ALVARO" in detail["lead"]["profile"]["summary"]
    assert n["send"](n["admin"], "/facebook/leads/" + current["id"],
                     {"name": ""}, "PATCH").status_code == 200
    restored = n["send"](n["admin"], "/facebook/leads/" + current["id"] + "/refresh-profile")
    assert restored.status_code == 200, restored.text
    assert restored.json()["name"] == "ALVARO"
    assert n["send"](n["a"], "/facebook/leads/" + current["id"] + "/refresh-profile").status_code == 403


def test_messenger_reports_real_drafting_and_sending_stages(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "fake-synthetic-key")
    settings.cache_clear()
    assert incoming(n, text="¿Cuáles son los requisitos para postular?", mid="staged-1").status_code == 200
    calls = []
    def mock_send(page_id, psid, body, token):
        with n["Session"]() as db:
            state = db.scalar(select(FacebookChatMessage.state).where(
                FacebookChatMessage.direction == "outbound",
            ).order_by(FacebookChatMessage.created_at.desc()).limit(1))
            calls.append(("meta", state))
        return "mid-state-" + str(len(calls))
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", mock_send)
    assert process_chat_next(n["Session"])
    assert incoming(n, text="Sí", mid="staged-2").status_code == 200
    def fake_generation(instructions, prompt, max_chars):
        with n["Session"]() as db:
            state = db.scalar(select(FacebookChatMessage.state).where(
                FacebookChatMessage.direction == "outbound",
            ).order_by(FacebookChatMessage.created_at.desc()).limit(1))
            calls.append(("model", state))
        return "Puedes contarme tu experiencia. ¿En qué comuna trabajas?"
    monkeypatch.setattr("app.facebook_chat_worker.generate_text", fake_generation)
    assert process_chat_next(n["Session"])
    assert ("model", "drafting") in calls
    assert ("meta", "sending") in calls
    detail = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    messages = n["admin"].get("/api/v1/network/facebook/leads/" + detail["id"]).json()["messages"]
    assert messages[-1]["state"] == "sent"
    assert messages[-1]["updated_at"]


def test_messenger_typing_dots_match_meta_sender_actions(network, monkeypatch):
    """Real processing triggers seen -> typing -> off; no fake idle animation."""
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-test-key")
    settings.cache_clear()
    actions = []
    monkeypatch.setattr(
        "app.facebook_chat_worker.graph_sender_action",
        lambda page_id, psid, action, token: actions.append(action))
    monkeypatch.setattr(
        "app.facebook_chat_worker.graph_send",
        lambda page_id, psid, body, token: "mid-synthetic-typing")
    assert incoming(n, text="Hola, quiero ofrecer carpintería", mid="typing-1").status_code == 200
    # Simple intake can be answered locally before any model authorization.
    assert process_chat_next(n["Session"]) is True
    assert actions == ["mark_seen", "typing_on", "typing_off"]
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    detail = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()
    assert detail["messages"][-1]["state"] == "sent"
    assert detail["lead"]["ai_consent"] is False
