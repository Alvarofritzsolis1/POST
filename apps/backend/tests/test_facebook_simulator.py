"""Interactive simulation must use the Messenger flow without touching its live stores."""
from sqlalchemy import func, select

from app.config import settings
from app.facebook_crm_models import FacebookChatMessage, FacebookLead
from app.galancito_knowledge_models import AssistantRun
from test_ai_control_center import ai_env, signin

BASE = "/api/v1/admin/ai/messenger-simulator"


def test_simulator_is_admin_scoped_and_retains_only_its_test_profile(ai_env, monkeypatch):
    client = ai_env["client"]
    admin = signin(client)
    def unexpected(*args, **kwargs):
        raise AssertionError("A simulation must never contact Meta")
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", unexpected)
    monkeypatch.setattr("app.facebook_chat_worker.graph_sender_action", unexpected)

    def send(message, state=None):
        response = client.post(BASE + "/turn", headers=admin, json={"message": message, "state": state})
        assert response.status_code == 200, response.text
        return response.json()

    first = send("Vi una postulacion de trabajo")
    assert first["reply"].startswith("¿Qué aviso viste?")
    assert first["source"] == "local" and first["intent"] == "apply"
    assert first["checks"]["safe"] and not first["profile"]["specialty"]

    # Start a separate conversation and exercise real memory/normalization.
    declared = send("Soy carpintero y trabajo en Coronel. Puedo ir con dos maestros.")
    assert declared["profile"]["specialty"] == "Carpintería"
    assert declared["profile"]["workers"] == 3
    correction = send("Corrijo: puedo ir con cuatro maestros.", declared["state"])
    assert correction["profile"]["specialty"] == "Carpintería"
    assert correction["profile"]["workers"] == 5
    assert correction["field_states"]["workers"] == "corregido"
    assert "workers" in correction["changed_fields"]

    with ai_env["sessions"]() as db:
        for model in (FacebookLead, FacebookChatMessage, AssistantRun):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    other = signin(client, "outside")
    assert client.post(BASE + "/turn", headers=other, json={
        "message": "hola", "state": correction["state"],
    }).status_code == 403
    resident = signin(client, "resident")
    assert client.get(BASE, headers=resident).status_code == 403


def test_simulator_local_mode_checks_consent_and_never_calls_external_services(ai_env, monkeypatch):
    client = ai_env["client"]
    admin = signin(client)
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("FACEBOOK_AI_PROVIDER", "openai")
    settings.cache_clear()
    calls = []
    def local(instructions, context, limit):
        calls.append(context)
        return "Los requisitos los confirma el equipo de cada obra."
    def unexpected(*args, **kwargs):
        raise AssertionError("Only the configured local model can receive a test message")
    monkeypatch.setattr("app.facebook_chat_worker.generate_local_text", local)
    monkeypatch.setattr("app.facebook_chat_worker.generate_text", unexpected)
    monkeypatch.setattr("app.facebook_chat_worker.orchestrated_text", unexpected)
    monkeypatch.setattr("app.facebook_chat_worker.graph_send", unexpected)
    first = client.post(BASE + "/turn", headers=admin, json={
        "mode": "local", "message": "¿Cuáles son los requisitos para postular?",
    })
    assert first.status_code == 200, first.text
    assert first.json()["source"] == "consent" and not calls
    assert "IA local" in first.json()["reply"]
    second = client.post(BASE + "/turn", headers=admin, json={
        "mode": "local", "message": "Sí, autorizo", "state": first.json()["state"],
    })
    assert second.status_code == 200, second.text
    assert second.json()["source"] == "ai"
    assert calls and "requisitos para postular" in calls[0]
