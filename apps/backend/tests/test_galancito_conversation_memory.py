"""Messenger regressions: one burst, ordered memory and provider consent."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys
import pytest

from sqlalchemy import create_engine, inspect, text

from app.config import settings
from app.facebook_chat_worker import process_chat_next
from app.migrations.v20_9_1_galancito_memory import upgrade
from test_facebook_crm import LEGACY_LOCAL_NOTICE, enable_messaging, incoming, seed_historical_permission
from test_network import network


def _signed(n, events):
    data = json.dumps({"object": "page", "entry": [
        {"id": "1489275590928529", "messaging": [
            {"sender": {"id": "123456789012345"}, "timestamp": int(at.timestamp() * 1000),
             "message": {"mid": mid, "text": body}} for at, mid, body in events
        ]},
    ]}).encode()
    signature = hmac.new(b"synthetic-test-only-meta-secret", data, hashlib.sha256).hexdigest()
    return n["admin"].post("/api/v1/network/facebook/webhook", content=data,
                           headers={"X-Hub-Signature-256": "sha256=" + signature})


def _detail(n):
    lead = n["admin"].get("/api/v1/network/facebook/center").json()["leads"][0]
    return n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()


def test_one_reply_for_burst_and_late_message_cannot_restore_a_corrected_fact(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "")
    settings.cache_clear()
    sending = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda page, psid, body, token: sending.append(body) or "sent-burst")
    now = datetime.now(timezone.utc)
    burst = [
        (now - timedelta(seconds=4), "burst-3", "Corrijo, puedo comenzar el 15/01/2027"),
        (now - timedelta(seconds=8), "burst-1", "Me llamo Elena. Soy carpintera"),
        (now - timedelta(seconds=6), "burst-2", "También hago pintura y trabajo en Coronel y Lota"),
    ]
    assert _signed(n, burst).status_code == 200
    assert _signed(n, burst).status_code == 200
    assert _signed(n, [(now - timedelta(seconds=7), "burst-late",
                        "Puedo comenzar el 03/01/2027")]).status_code == 200
    assert process_chat_next(n["Session"])
    assert not process_chat_next(n["Session"])
    assert len(sending) == 1 and sending[0].count("?") <= 1
    detail = _detail(n)
    lead = detail["lead"]
    assert lead["name"] == "Elena"
    assert set(lead["trades"]) == {"Carpintería", "Pintura"}
    assert set(lead["work_communes"]) == {"Coronel", "Lota"}
    assert lead["availability"] == "2027-01-15"
    assert lead["profile"]["sources"]["availability"]["message_id"] == "burst-3"
    assert len([m for m in detail["messages"] if m["direction"] == "inbound"]) == 4


def test_affirmation_before_delivery_and_provider_switch_do_not_grant_permission(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "ollama")
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    settings.cache_clear()
    assert incoming(n, "¿Cuáles son los requisitos para postular?", mid="privacy-1").status_code == 200
    assert incoming(n, "sí", mid="privacy-2").status_code == 200
    assert not _detail(n)["lead"]["ai_consent"]
    seed_historical_permission(n)
    assert incoming(n, "sí", mid="privacy-3").status_code == 200
    assert _detail(n)["lead"]["ai_consent"]
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "openai")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic-only")
    settings.cache_clear()
    assert incoming(n, "¿Qué requisitos necesito para postular?", mid="privacy-4").status_code == 200
    detail = _detail(n)
    from sqlalchemy import select
    from app.facebook_crm_models import FacebookLead
    from app.facebook_ai import messenger_contact_ai_source
    with n["Session"]() as db:
        assert messenger_contact_ai_source(db, db.scalar(select(FacebookLead))) != "openai"
    assert not any("OpenAI" in message["body"] for message in detail["messages"]
                   if message["body"] != LEGACY_LOCAL_NOTICE)
    assert not any(message["state"] == "ai_pending" for message in detail["messages"])


def test_migration_is_idempotent_and_preserves_legacy_rows():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE facebook_leads (id TEXT PRIMARY KEY, specialty TEXT)"))
        connection.execute(text("CREATE TABLE facebook_chat_messages (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO facebook_leads VALUES ('lead-1', 'Pintura')"))
        upgrade(connection)
        upgrade(connection)
        assert connection.execute(text("SELECT specialty, work_communes, profile_sources "
                                       "FROM facebook_leads")).one() == ("Pintura", "[]", "{}")
        assert "consent_decision" in {c["name"] for c in inspect(connection).get_columns("facebook_chat_messages")}


def test_40_conversations_use_the_signed_webhook_and_durable_worker(tmp_path):
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/evaluate_galancito_conversations.py"),
         "--output", str(tmp_path / "conversations.json")],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    report_path = tmp_path / "conversations.json"
    assert result.returncode == 0, result.stdout + result.stderr + (
        report_path.read_text() if report_path.exists() else "")
    report = json.loads(report_path.read_text())
    assert report["passed"] == report["conversations"] == 40


def test_unanswered_question_survives_a_detail_before_consent(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "false")
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "ollama")
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "")
    settings.cache_clear()
    assert incoming(n, "¿Cuáles son los requisitos para postular?", mid="focus-1").status_code == 200
    assert incoming(n, "Hago pintura y trabajo en Coronel", mid="focus-2").status_code == 200
    detail = _detail(n)
    assert detail["lead"]["trades"] == ["Pintura"]
    assert not any("autorizas" in message["body"].casefold() for message in detail["messages"])
    seed_historical_permission(n)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    settings.cache_clear()
    assert incoming(n, "sí", mid="focus-3").status_code == 200
    sent = []
    def generate(_instructions, prompt, _limit):
        assert "Consulta actual: ¿Cuáles son los requisitos para postular?" in prompt
        assert "Coronel" in prompt
        return "Los requisitos dependen de la obra. El equipo puede orientarte."
    monkeypatch.setattr("app.facebook_chat_worker.generate_text", generate)
    monkeypatch.setattr("app.facebook_chat_worker.graph_sender_action", lambda *_: None)
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", lambda *args: sent.append(args[2]) or "focus-sent")
    assert process_chat_next(n["Session"])
    assert sent == ["Los requisitos dependen de la obra. El equipo puede orientarte."]


def test_second_fragment_can_answer_a_still_pending_question(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "")
    settings.cache_clear()
    assert incoming(n, "Busco pega de carpintero", mid="fragment-first").status_code == 200
    lead_id = _detail(n)["lead"]["id"]
    manual = n["send"](n["admin"], "/facebook/leads/" + lead_id + "/reply",
                       {"message": "¿En qué comuna puedes trabajar?"})
    assert manual.status_code == 202
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", lambda *_args: "fragment-manual")
    assert process_chat_next(n["Session"])
    assert incoming(n, "También hago electricidad", mid="fragment-trade").status_code == 200
    assert incoming(n, "Penco", mid="fragment-commune").status_code == 200
    detail = _detail(n)
    assert detail["lead"]["work_communes"] == ["Penco"]
    assert set(detail["lead"]["trades"]) == {"Carpintería", "Electricidad"}
    assert detail["lead"]["profile"]["sources"]["work_communes"]["message_id"] == "fragment-commune"


@pytest.mark.parametrize("path", ["webhook", "recovery", "queued_notice"])
def test_project_question_before_sharing_phone_gets_a_project_reply(network, monkeypatch, path):
    from sqlalchemy import select
    from app import facebook_inbox_sync
    from app.facebook_crm_models import FacebookChatMessage
    from app.network_models import NetworkFacebookPost
    from test_network import requirement

    n = network
    org_id = enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "ollama")
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    settings.cache_clear()
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda _page, _psid, body, _token: sent.append(body) or f"project-reply-{len(sent)}")
    monkeypatch.setattr("app.facebook_chat_worker.generate_text",
                        lambda *_args, **_kwargs: pytest.fail("La consulta se resuelve con datos del aviso"))
    message = ("Trabajo con un contratista. Me dice el proyecto para así darle la inf y num de tlf "
               "por donde nos podamos comunicar con usted.")
    if path == "recovery":
        monkeypatch.setattr(facebook_inbox_sync, "_graph_get", lambda _token, _resource, edge, _fields, _limit:
            {"data": [{"id": "project-thread"}]} if edge == "conversations" else
            {"data": [{"id": "project-before-contact", "message": message,
                       "from": {"id": "123456789012345"}, "created_time": datetime.now(timezone.utc).isoformat()}]})
        recovered = facebook_inbox_sync.sync_page_inbox(page_id=settings().facebook_page_id,
            page_token="synthetic", org_id=org_id, session_factory=n["Session"])
        assert recovered["replies_queued"] == 1
    else:
        assert incoming(n, message, mid="project-before-contact").status_code == 200
    if path == "queued_notice":
        with n["Session"].begin() as db:
            db.scalar(select(FacebookChatMessage).where(FacebookChatMessage.state == "pending")).state = "cancelled"
        seed_historical_permission(n, state="pending")
    assert process_chat_next(n["Session"])
    assert sent == ["Claro. ¿Recuerdas el nombre de la obra, el trabajo o la comuna del aviso?"]
    lead = _detail(n)["lead"]
    assert not lead["ai_consent"]
    assert not lead["contact_phone"]
    assert not lead["phone_requested_at"]
    assert not lead["needs_support"]

    req = requirement(n)
    with n["Session"].begin() as db:
        db.add(NetworkFacebookPost(org_id=org_id, requirement_id=req["id"],
            page_id=settings().facebook_page_id, state="published", post_id="1489275590928529_123456"))
    assert incoming(n, "Brisas de Junquillar", mid="identified-project").status_code == 200
    assert process_chat_next(n["Session"])
    assert sent[-1] == ("La obra indicada es Brisas de Junquillar. "
                        "Te dejo el aviso: https://www.facebook.com/1489275590928529_123456")


def test_location_question_asks_for_notice_before_any_provider_and_uses_public_data(network, monkeypatch):
    from app.facebook_worksite_reply import ASK_WORKSITE
    from app.galancito_knowledge import search_value
    from app.galancito_knowledge_models import Knowledge
    from app.network_models import NetworkFacebookPost
    from test_network import requirement

    n = network
    org_id = enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic")
    settings.cache_clear()
    req = requirement(n)
    pending = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda _page, _psid, body, _token: pending.append(body) or f"m-location-{len(pending)}")
    monkeypatch.setattr("app.facebook_chat_worker.generate_text",
                        lambda *_args: pytest.fail("No debe llamar a IA para contestar ubicación."))

    assert incoming(n, "donde queda ubicada la obra", mid="location-question").status_code == 200
    assert process_chat_next(n["Session"])
    assert pending == [ASK_WORKSITE]
    assert _detail(n)["lead"]["ai_consent_state"] == "not_requested"
    with n["Session"].begin() as db:
        db.add(NetworkFacebookPost(org_id=org_id, requirement_id=req["id"],
                                   page_id="1489275590928529", state="published",
                                   post_id="1489275590928529_123456"))
    assert incoming(n, "Brisas de Junquillar", mid="location-name").status_code == 200
    assert process_chat_next(n["Session"])
    assert "No tengo la dirección confirmada" in pending[-1]
    assert "1489275590928529_123456" in pending[-1]
    assert "Observación privada" not in pending[-1]

    title = "Ubicación del aviso"
    phrase = "Dónde queda la obra Brisas de Junquillar"
    answer = "La obra Brisas de Junquillar está en la comuna de Coronel."
    with n["Session"].begin() as db:
        db.add(Knowledge(org_id=org_id, updated_by=n["a_user"]["id"], title=title,
                         kind="faq", scope="messenger", content=answer, phrases=[phrase],
                         status="approved", search_text=search_value(title, answer, [phrase])))
    assert incoming(n, "en q comuna queda la obra Brisas de Junquillar", mid="location-approved").status_code == 200
    assert process_chat_next(n["Session"])
    assert pending[-1] == answer
    assert not process_chat_next(n["Session"])


def test_consent_confusion_and_relative_date_resume_the_conversation(network, monkeypatch):
    from sqlalchemy import select
    from app.facebook_crm_models import FacebookLead
    from app.galancito_escalation import flag_for_human
    from app.galancito_memory import CHILE
    from app.models import utcnow

    n = network
    enable_messaging(n, monkeypatch)
    monkeypatch.setenv("FACEBOOK_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_API_KEY", "synthetic")
    settings.cache_clear()
    # Historical notice already delivered by the previous release.
    monkeypatch.setattr("app.facebook_ai.messenger_ai_source", lambda *_: "team")
    sent = []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda _page, _psid, body, _token: sent.append(body) or f"m-dates-{len(sent)}")

    assert incoming(n, "Hola", mid="date-intro").status_code == 200
    assert process_chat_next(n["Session"])
    assert "autorizas" not in sent[-1].lower()
    seed_historical_permission(n, provider="team")
    assert incoming(n, "no entiendo", mid="date-confusion").status_code == 200
    assert process_chat_next(n["Session"])
    assert sent[-1] == "Podemos seguir por acá. Cuéntame qué necesitas y vemos cómo ayudarte."
    lead = _detail(n)["lead"]
    assert not lead["needs_support"] and not lead["ai_consent"]

    # A contact already flagged by the prior version can still give a date.
    with n["Session"].begin() as db:
        row = db.scalar(select(FacebookLead).where(FacebookLead.id == lead["id"]))
        flag_for_human(db, row, "La persona expresó dificultades con la explicación o el trámite")
    manual = n["send"](n["admin"], f"/facebook/leads/{lead['id']}/reply",
                       {"message": "Necesito gasfiter para 2 semanas mas"})
    assert manual.status_code == 202
    assert process_chat_next(n["Session"])
    day = utcnow().astimezone(CHILE).date()
    assert incoming(n, "vale", mid="date-ack").status_code == 200
    assert not process_chat_next(n["Session"])
    # Human takeover must stay active until the administrator explicitly
    # resumes automation. The prior test incorrectly expected the bot to
    # answer while the person was still assigned to a human.
    assert _detail(n)["lead"]["ai_paused"] is True
    resumed = n["send"](
        n["admin"], f"/facebook/leads/{lead['id']}",
        {"needs_support": False, "ai_paused": False}, method="PATCH")
    assert resumed.status_code == 200
    assert incoming(n, "pero yo puedo en 1 semana mas", mid="date-answer").status_code == 200
    assert process_chat_next(n["Session"])
    early, requested = day + timedelta(days=7), day + timedelta(days=14)
    assert f"{early:%d/%m}" in sent[-1] and f"{requested:%d/%m}" in sent[-1]
    assert sent[-1].endswith("¿También puedes ese día?")
    updated = _detail(n)["lead"]
    assert updated["availability"] == str(early)
    assert not updated["ai_consent"] and not updated["needs_support"]
    assert not updated["trades"]
    assert incoming(n, "sí", mid="date-confirmed").status_code == 200
    assert process_chat_next(n["Session"])
    confirmed = _detail(n)["lead"]
    assert confirmed["availability"] == str(requested)
    assert not confirmed["ai_consent"]
    assert f"puedes el {requested:%d/%m}" in sent[-1]
