"""Synthetic contract tests for admin multi-provider AI; no real network or secrets."""
import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import ai_gateway
from app.ai_gateway import orchestration_available, orchestrated_text
from app.ai_models import AIConnection, AIOrchestration, AIUsage
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import Organization, User
from app.network_models import NetworkMember
from app.security import hash_password

ROOT = "/api/v1/admin/ai"
PASSWORD = "ai-test-password-2026"


@pytest.fixture
def ai_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_SECRET", "synthetic-galant-ai-tests-" * 5)
    monkeypatch.setenv("SECURE_COOKIES", "false")
    monkeypatch.setenv("AI_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    settings.cache_clear()
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "ai.sqlite"),
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as db:
        org = Organization(name="Prueba de IA")
        another = Organization(name="Organización ajena")
        db.add_all([org, another])
        db.flush()
        for name, role, organization in [
            ("admin", "admin", org), ("resident", "resident", org),
            ("outside", "admin", another),
        ]:
            user = User(org_id=organization.id, email=name + "@example.cl",
                        password_hash=hash_password(PASSWORD), role=role)
            db.add(user)
            db.flush()
            db.add(NetworkMember(user_id=user.id, name="Persona " + name))
        org_id = org.id

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield {"client": client, "sessions": sessions, "org_id": org_id}
    finally:
        app.dependency_overrides.clear()
        settings.cache_clear()
        engine.dispose()


def signin(client, account="admin"):
    response = client.post("/api/v1/auth/login", json={
        "email": account + "@example.cl", "password": PASSWORD,
    })
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.cookies["galant_post_csrf"]}


def add(client, headers, name="NVIDIA Principal", provider="nvidia",
        model="deepseek-ai/deepseek-v4.1-flash", key="nvapi-example-secret"):
    response = client.post(ROOT + "/connections", headers=headers, json={
        "name": name, "provider": provider, "model": model,
        "api_key": key, "enabled": True,
        "price_input_per_million": 0.12, "price_output_per_million": 0.30,
    })
    assert response.status_code == 201, response.text
    return response.json()


class FakeResponse:
    def __init__(self, result):
        self.payload = json.dumps(result).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return self.payload


def test_admin_access_encryption_and_disconnect(ai_env):
    client, sessions = ai_env["client"], ai_env["sessions"]
    assert client.get(ROOT + "/bootstrap").status_code == 401
    resident = signin(client, "resident")
    assert client.get(ROOT + "/bootstrap").status_code == 403
    assert client.post(ROOT + "/connections", headers=resident, json={}).status_code == 403

    headers = signin(client)
    listing = client.get(ROOT + "/bootstrap").json()
    assert listing["server_ready"] is True
    assert {"messaging_enabled", "ai_enabled", "auto_reply_enabled", "page_configured"} <= listing["messenger_ready"].keys()
    assert {"gemini", "groq", "nvidia"}.issubset({p["id"] for p in listing["providers"]})
    record = add(client, headers)
    assert record["has_key"] is True and "api_key" not in record
    assert "encrypted_key" not in client.get(ROOT + "/bootstrap").text
    with sessions() as db:
        conn = db.get(AIConnection, record["id"])
        assert conn.encrypted_key != "nvapi-example-secret"
        assert "nvapi-example-secret" not in conn.encrypted_key
        assert ai_gateway.decrypt_key(conn.encrypted_key) == "nvapi-example-secret"
    no_secret = client.patch(ROOT + "/connections/" + record["id"], headers=headers,
                             json={"model": "deepseek-ai/deepseek-v4.1-flash"})
    assert no_secret.status_code == 200
    assert client.post(ROOT + "/connections/" + record["id"] + "/disconnect",
                       headers=headers).json()["has_key"] is False
    with sessions() as db:
        assert db.get(AIConnection, record["id"]).encrypted_key is None


def test_connection_probe_measures_reported_tokens_and_policy(ai_env, monkeypatch):
    client, sessions = ai_env["client"], ai_env["sessions"]
    headers = signin(client)
    record = add(client, headers)
    calls = []

    def fake_open(request, timeout):
        calls.append({"url": request.full_url, "headers": dict(request.header_items()),
                      "body": json.loads(request.data)})
        return FakeResponse({"choices": [{"message": {"content": "OK, Galancito."}}],
                             "usage": {"prompt_tokens": 24, "completion_tokens": 7}})

    monkeypatch.setattr(ai_gateway, "urlopen", fake_open)
    probe = client.post(ROOT + "/connections/" + record["id"] + "/test", headers=headers)
    assert probe.status_code == 200, probe.text
    assert probe.json()["ok"] is True
    assert probe.json()["connection"]["status"] == "verified"
    assert calls[0]["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer nvapi-example-secret"
    assert calls[0]["body"]["model"] == "deepseek-ai/deepseek-v4.1-flash"

    policy = client.put(ROOT + "/policy", headers=headers, json={
        "enabled": True, "fallback_enabled": False, "monthly_token_limit": 1000,
        "task_routes": {"red_obras": record["id"]},
    })
    assert policy.status_code == 200, policy.text
    with sessions.begin() as db:
        assert orchestration_available(db, ai_env["org_id"], "red_obras")
        text = orchestrated_text(db, ai_env["org_id"], task="red_obras",
                                 instructions="Asesoría", prompt="¿Cómo publico una necesidad?")
        assert text == "OK, Galancito."
    usage = client.get(ROOT + "/usage?days=30").json()
    assert usage["total_calls"] == 2
    assert usage["total_tokens"] == 62
    assert usage["unpriced_calls"] == 0
    assert usage["estimated_cost_usd"] > 0
    assert not client.get(ROOT + "/bootstrap").json()["connections"][0].get("api_key")
    with sessions() as db:
        assert db.scalar(select(AIUsage).where(AIUsage.task == "red_obras")).input_tokens == 24


def test_gemini_usage_and_error_masking(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    record = add(client, headers, name="Gemini Estudio", provider="gemini",
                 model="gemini-2.5-flash", key="ai-google-secret")
    def fake_open(request, timeout):
        assert request.full_url.endswith("gemini-2.5-flash:generateContent")
        assert request.get_header("X-goog-api-key") == "ai-google-secret"
        return FakeResponse({
            "candidates": [{"content": {"parts": [{"text": "OK"}]}}],
            "usageMetadata": {"promptTokenCount": 19, "candidatesTokenCount": 3},
        })
    monkeypatch.setattr(ai_gateway, "urlopen", fake_open)
    assert client.post(ROOT + "/connections/" + record["id"] + "/test",
                       headers=headers).json()["ok"] is True
    assert client.get(ROOT + "/usage").json()["total_tokens"] == 22

    def unavailable(*_args, **_kwargs):
        from urllib.error import HTTPError
        raise HTTPError("https://example.invalid/private?key=secret", 401, "raw-private-body", None, None)
    monkeypatch.setattr(ai_gateway, "urlopen", unavailable)
    failed = client.post(ROOT + "/connections/" + record["id"] + "/test", headers=headers)
    assert failed.status_code == 200
    assert failed.json()["ok"] is False
    assert "HTTP 401" in failed.json()["message"]
    assert "private" not in failed.text and "secret" not in failed.text
    assert client.get(ROOT + "/usage").json()["total_calls"] == 2


def test_cross_organization_isolation_and_no_unchecked_routing(ai_env):
    client, sessions = ai_env["client"], ai_env["sessions"]
    headers = signin(client)
    record = add(client, headers)
    with sessions() as db:
        assert not orchestration_available(db, ai_env["org_id"], "red_obras")
    outsider = signin(client, "outside")
    assert client.get(ROOT + "/bootstrap").json()["connections"] == []
    assert client.patch(ROOT + "/connections/" + record["id"], headers=outsider,
                        json={"enabled": False}).status_code == 404
    assert client.put(ROOT + "/policy", headers=outsider, json={
        "enabled": True, "task_routes": {"red_obras": record["id"]},
    }).status_code == 422


def test_no_encryption_key_refuses_secret_storage(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    monkeypatch.delenv("AI_CREDENTIAL_ENCRYPTION_KEY")
    response = client.post(ROOT + "/connections", headers=headers, json={
        "name": "Sin clave", "provider": "groq", "model": "example/model",
        "api_key": "private-key",
    })
    assert response.status_code == 503
    assert "private-key" not in response.text


def test_routing_requires_real_successful_verification(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    row = add(client, headers, name="Sin verificar", provider="groq",
              model="llama-3.3-70b-versatile", key="gsk-dummy")
    policy = {"enabled": True, "fallback_enabled": False,
              "monthly_token_limit": 2000, "task_routes": {"red_obras": row["id"]}}
    denied = client.put(ROOT + "/policy", headers=headers, json=policy)
    assert denied.status_code == 422

    monkeypatch.setattr(ai_gateway, "urlopen", lambda *_args, **_kwargs:
                        FakeResponse({"choices": [{"message": {"content": "OK"}}],
                                      "usage": {"prompt_tokens": 5, "completion_tokens": 3}}))
    assert client.post(ROOT + "/connections/" + row["id"] + "/test",
                       headers=headers).json()["ok"] is True
    assert client.put(ROOT + "/policy", headers=headers, json=policy).status_code == 200
    paused = client.patch(ROOT + "/connections/" + row["id"], headers=headers,
                          json={"enabled": False})
    assert paused.status_code == 200
    with ai_env["sessions"]() as db:
        assert not orchestration_available(db, ai_env["org_id"], "red_obras")
        assert orchestrated_text(db, ai_env["org_id"], task="red_obras",
                                 instructions="Prueba", prompt="No enviar") is None
    assert client.put(ROOT + "/policy", headers=headers, json=policy).status_code == 422


def test_disconnect_clears_stale_routing_without_losing_usage(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    row = add(client, headers, name="Modelo temporal")
    monkeypatch.setattr(ai_gateway, "urlopen", lambda *_args, **_kwargs:
                        FakeResponse({"choices": [{"message": {"content": "OK"}}],
                                      "usage": {"prompt_tokens": 11, "completion_tokens": 2}}))
    assert client.post(ROOT + "/connections/" + row["id"] + "/test",
                       headers=headers).json()["ok"] is True
    policy = {"enabled": True, "fallback_enabled": False,
              "monthly_token_limit": 0, "task_routes": {"red_obras": row["id"]}}
    assert client.put(ROOT + "/policy", headers=headers, json=policy).status_code == 200
    removed = client.post(ROOT + "/connections/" + row["id"] + "/disconnect",
                          headers=headers)
    assert removed.status_code == 200 and not removed.json()["has_key"]
    after = client.get(ROOT + "/bootstrap").json()
    assert after["policy"]["enabled"] is False
    assert after["policy"]["task_routes"] == {}
    assert client.get(ROOT + "/usage").json()["total_tokens"] == 13
    with ai_env["sessions"]() as db:
        assert not orchestration_available(db, ai_env["org_id"], "red_obras")


def test_invalid_encryption_key_is_not_reported_ready(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    monkeypatch.setenv("AI_CREDENTIAL_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    assert client.get(ROOT + "/bootstrap").json()["server_ready"] is False
    result = client.post(ROOT + "/connections", headers=headers, json={
        "name": "Groq inseguro", "provider": "groq",
        "model": "llama-3.3-70b-versatile", "api_key": "gsk-hidden",
    })
    assert result.status_code == 503
    assert "gsk-hidden" not in result.text


def test_duplicate_provider_name_returns_409_and_keeps_first_key(ai_env):
    client, sessions = ai_env["client"], ai_env["sessions"]
    headers = signin(client)
    original = add(client, headers, name="Misma conexión")
    duplicate = client.post(ROOT + "/connections", headers=headers, json={
        "name": "Misma conexión", "provider": "groq", "model": "llama-3.3-70b-versatile",
        "api_key": "gsk-private-second", "enabled": True,
    })
    assert duplicate.status_code == 409, duplicate.text
    assert "gsk-private-second" not in duplicate.text
    with sessions() as db:
        names = list(db.scalars(select(AIConnection).where(AIConnection.org_id == ai_env["org_id"])))
        assert len(names) == 1 and names[0].id == original["id"]
        assert ai_gateway.decrypt_key(names[0].encrypted_key) == "nvapi-example-secret"


def test_provider_invalid_json_shape_returns_safe_error(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    record = add(client, headers)
    monkeypatch.setattr(ai_gateway, "urlopen", lambda *_args, **_kwargs:
                        FakeResponse({"choices": "private-malformed", "usage": {"prompt_tokens": 12}}))
    result = client.post(ROOT + "/connections/" + record["id"] + "/test", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["ok"] is False
    assert "formato inválido" in result.json()["message"]
    assert "private-malformed" not in result.text
    stats = client.get(ROOT + "/usage").json()
    assert stats["total_calls"] == 1
    assert stats["groups"][0]["status"] == "error"


def test_independent_review_requires_distinct_verified_model(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    primary = add(client, headers, name="Equipo principal")
    reviewer = add(client, headers, name="Segundo modelo", provider="groq",
                   model="llama-3.3-70b-versatile", key="gsk-test-second")
    seen = []
    def fake_open(request, timeout):
        payload = json.loads(request.data)
        seen.append({"model": payload["model"], "messages": payload["messages"], "timeout": timeout})
        if payload["model"] == "llama-3.3-70b-versatile":
            return FakeResponse({"choices": [{"message": {"content": '{"valid": true}'}}],
                                 "usage": {"prompt_tokens": 9, "completion_tokens": 5}})
        return FakeResponse({"choices": [{"message": {"content": "Se requiere validación humana."}}],
                             "usage": {"prompt_tokens": 13, "completion_tokens": 8}})
    monkeypatch.setattr(ai_gateway, "urlopen", fake_open)
    for item in (primary, reviewer):
        assert client.post(ROOT + "/connections/" + item["id"] + "/test",
                           headers=headers).json()["ok"] is True
    policy = {"enabled": True, "review_enabled": True, "fallback_enabled": False,
              "monthly_token_limit": 12000,
              "task_routes": {"red_obras": primary["id"], "review": primary["id"]}}
    assert client.put(ROOT + "/policy", headers=headers, json=policy).status_code == 422
    policy["task_routes"]["review"] = reviewer["id"]
    saved = client.put(ROOT + "/policy", headers=headers, json=policy)
    assert saved.status_code == 200, saved.text
    assert saved.json()["review_enabled"] is True

    before = len(seen)
    with ai_env["sessions"].begin() as db:
        assert orchestration_available(db, ai_env["org_id"], "red_obras")
        result = orchestrated_text(db, ai_env["org_id"], task="red_obras",
                                   instructions="Asesora solo con evidencia",
                                   prompt="Contexto sintético publicado",
                                   max_output_tokens=140)
        assert result == "Se requiere validación humana."
    calls = seen[before:]
    assert len(calls) == 2
    assert calls[0]["model"] == "deepseek-ai/deepseek-v4.1-flash"
    assert calls[1]["model"] == "llama-3.3-70b-versatile"
    assert "respuesta_propuesta" in calls[1]["messages"][1]["content"]
    assert calls[1]["timeout"] <= 2.7
    usage = client.get(ROOT + "/usage").json()
    assert any(row["task"] == "review" and row["calls"] == 1 for row in usage["groups"])
    assert usage["unpriced_calls"] == 0


def test_review_rejects_invented_response_without_training(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    primary = add(client, headers, name="Redacción")
    reviewer = add(client, headers, name="Control", provider="groq",
                   model="llama-3.3-70b-versatile", key="gsk-fake-review")
    def fake_open(request, timeout):
        model = json.loads(request.data)["model"]
        output = '{"valid": false}' if "llama" in model else "Te adjudicamos la obra."
        return FakeResponse({"choices": [{"message": {"content": output}}],
                             "usage": {"prompt_tokens": 10, "completion_tokens": 3}})
    monkeypatch.setattr(ai_gateway, "urlopen", fake_open)
    for conn in (primary, reviewer):
        assert client.post(ROOT + "/connections/" + conn["id"] + "/test",
                           headers=headers).json()["ok"]
    policy = {"enabled": True, "review_enabled": True, "fallback_enabled": False,
              "monthly_token_limit": 5000,
              "task_routes": {"red_obras": primary["id"], "review": reviewer["id"]}}
    assert client.put(ROOT + "/policy", headers=headers, json=policy).status_code == 200
    with ai_env["sessions"].begin() as db:
        assert orchestrated_text(db, ai_env["org_id"], task="red_obras",
                                 instructions="Revisar", prompt="Pregunta", max_output_tokens=100) is None
    bootstrap = client.get(ROOT + "/bootstrap").json()
    assert bootstrap["learning"]["approved"] == 0
    assert bootstrap["learning"]["pending"] == 0


def test_messenger_tries_another_configured_ai_after_reviewer_rejects(ai_env, monkeypatch):
    """Only a consented team route uses other approved providers."""
    ids = []
    with ai_env["sessions"].begin() as db:
        admin_id = db.scalar(select(User.id).where(
            User.org_id == ai_env["org_id"], User.role == "admin"))
        for name, provider, model in (
            ("Principal", "openai", "gpt-4o-mini"),
            ("Revisor", "groq", "llama-3.3-70b-versatile"),
            ("Alternativa", "mistral", "mistral-small-latest"),
        ):
            conn = AIConnection(org_id=ai_env["org_id"], name=name,
                                provider=provider, model=model,
                                encrypted_key="synthetic-not-decrypted", enabled=True,
                                last_status="verified", updated_by=admin_id)
            db.add(conn)
            db.flush()
            ids.append(conn.id)
        db.add(AIOrchestration(org_id=ai_env["org_id"], enabled=True,
                               fallback_enabled=True, review_enabled=True,
                               monthly_token_limit=0,
                               task_routes={"messenger": ids[0], "review": ids[1]}))
    calls = []
    def fake_run(db, conn, **kwargs):
        calls.append(conn.id)
        if conn.id == ids[0]:
            return "Respuesta sin respaldo"
        if conn.id == ids[2]:
            return "La disponibilidad debe confirmarla administración."
        proposed = json.loads(kwargs["prompt"])["respuesta_propuesta"]
        return json.dumps({"valid": proposed.startswith("La disponibilidad")})
    monkeypatch.setattr(ai_gateway, "run_connection", fake_run)
    with ai_env["sessions"].begin() as db:
        answer = orchestrated_text(db, ai_env["org_id"], task="messenger",
                                   instructions="Responder con evidencia",
                                   prompt="Consulta sintética", max_output_tokens=120)
    assert answer == "La disponibilidad debe confirmarla administración."
    assert calls == [ids[0], ids[1], ids[2], ids[1]]
    with ai_env["sessions"].begin() as db:
        db.get(AIConnection, ids[0]).last_status = "error"
    calls.clear()
    with ai_env["sessions"].begin() as db:
        assert orchestration_available(db, ai_env["org_id"], "messenger")
        answer = orchestrated_text(db, ai_env["org_id"], task="messenger",
                                   instructions="Responder con evidencia",
                                   prompt="Otra consulta sintética", max_output_tokens=120)
    assert answer == "La disponibilidad debe confirmarla administración."
    assert calls == [ids[2], ids[1]]


def test_preflight_token_cap_prevents_unaffordable_external_call(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    primary = add(client, headers, name="Modelo de presupuesto")
    calls = []
    def fake_open(request, timeout):
        calls.append(request)
        return FakeResponse({"choices": [{"message": {"content": "OK"}}],
                             "usage": {"prompt_tokens": 6, "completion_tokens": 3}})
    monkeypatch.setattr(ai_gateway, "urlopen", fake_open)
    assert client.post(ROOT + "/connections/" + primary["id"] + "/test",
                       headers=headers).json()["ok"]
    policy = {"enabled": True, "review_enabled": False, "fallback_enabled": False,
              "monthly_token_limit": 20, "task_routes": {"red_obras": primary["id"]}}
    assert client.put(ROOT + "/policy", headers=headers, json=policy).status_code == 200
    with ai_env["sessions"].begin() as db:
        assert orchestrated_text(db, ai_env["org_id"], task="red_obras",
                                 instructions="No inventar", prompt="Consulta de prueba",
                                 max_output_tokens=100) is None
    assert len(calls) == 1  # Only the administrator's explicit connection test.


def test_phone_and_api_tokens_are_private_before_external_processing():
    from app.galancito_triage import private_data
    for value in ("Llámame al +56 9 8765 4321", "Mi teléfono es 9 8765 4321",
                  "usa nvapi-abcdefghijklmnop", "token gsk_1234567890123456"):
        assert private_data(value)
    assert not private_data("Busco carpinteros para mañana en Coronel")
    from app.ai_review import accepted_review
    assert accepted_review('{"valid": true}')
    assert not accepted_review('{"valid": false}')
    assert not accepted_review("Una IA dice que sí")
    assert not accepted_review('{"valid": true, "instructions": "publicar"}')


def test_review_migration_is_additive_and_idempotent_for_existing_database(tmp_path):
    from sqlalchemy import inspect, text
    from app.migrations import v20_8_1_ai_collaboration
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "legacy-review.sqlite"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ai_orchestration (org_id VARCHAR(36) PRIMARY KEY, "
                                "enabled BOOLEAN NOT NULL DEFAULT FALSE, "
                                "fallback_enabled BOOLEAN NOT NULL DEFAULT FALSE, "
                                "monthly_token_limit INTEGER NOT NULL DEFAULT 0, "
                                "task_routes JSON, updated_by VARCHAR(36), updated_at DATETIME)"))
        connection.execute(text("INSERT INTO ai_orchestration "
                                "(org_id, enabled, fallback_enabled, monthly_token_limit) "
                                "VALUES ('legacy-org', TRUE, FALSE, 2500)"))
        v20_8_1_ai_collaboration.upgrade(connection)
        v20_8_1_ai_collaboration.upgrade(connection)
        cols = {c["name"] for c in inspect(connection).get_columns("ai_orchestration")}
        assert "review_enabled" in cols
        saved = connection.execute(text("SELECT monthly_token_limit, review_enabled "
                                        "FROM ai_orchestration WHERE org_id='legacy-org'")).one()
        assert saved[0] == 2500
        assert saved[1] in (False, 0)
    engine.dispose()


def test_selected_team_quota_does_not_fall_back_to_paid_legacy_provider(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    conn = add(client, headers, name="Proveedor con límite")
    calls = []
    def fake_open(request, timeout):
        calls.append(request)
        return FakeResponse({"choices": [{"message": {"content": "OK"}}],
                             "usage": {"prompt_tokens": 8, "completion_tokens": 5}})
    monkeypatch.setattr(ai_gateway, "urlopen", fake_open)
    assert client.post(ROOT + "/connections/" + conn["id"] + "/test",
                       headers=headers).json()["ok"] is True
    assert client.put(ROOT + "/policy", headers=headers, json={
        "enabled": True, "fallback_enabled": True, "review_enabled": False,
        "monthly_token_limit": 1, "task_routes": {"red_obras": conn["id"]},
    }).status_code == 200
    monkeypatch.setenv("GALANCITO_AI_ENABLED", "true")
    monkeypatch.setenv("GALANCITO_AI_PROVIDER", "openai")
    monkeypatch.setenv("GALANCITO_AI_API_KEY", "legacy-not-for-use")
    settings.cache_clear()
    status = client.get("/api/v1/network/galancito/status")
    assert status.status_code == 200, status.text
    assert status.json()["external_ai_available"] is False
    answer = client.post("/api/v1/network/galancito/chat",
                         headers=headers,
                         json={"message": "Explica cómo resolver una coordinación compleja entre obras",
                               "allow_external_ai": True})
    assert answer.status_code == 200, answer.text
    assert answer.json()["source"] in ("local", "fallback")
    assert len(calls) == 1  # Never contacted either paid provider after the quota.


def test_private_primary_output_never_reaches_secondary_provider(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    primary = add(client, headers, name="Modelo confidencial")
    reviewer = add(client, headers, name="Revisor confidencial", provider="groq",
                   model="llama-3.3-70b-versatile", key="gsk-fake-second")
    phase = {"test": True}
    reached = []
    def fake_open(request, timeout):
        model = json.loads(request.data)["model"]
        reached.append(model)
        if phase["test"]:
            answer = "OK"
        elif model == primary["model"]:
            answer = "Secreto inesperado nvapi-1234567890abcdef"
        else:
            raise AssertionError("Never send private output to review model")
        return FakeResponse({"choices": [{"message": {"content": answer}}],
                             "usage": {"prompt_tokens": 9, "completion_tokens": 4}})
    monkeypatch.setattr(ai_gateway, "urlopen", fake_open)
    for connection in (primary, reviewer):
        assert client.post(ROOT + "/connections/" + connection["id"] + "/test",
                           headers=headers).json()["ok"]
    assert client.put(ROOT + "/policy", headers=headers, json={
        "enabled": True, "fallback_enabled": False, "review_enabled": True,
        "monthly_token_limit": 10000,
        "task_routes": {"red_obras": primary["id"], "review": reviewer["id"]},
    }).status_code == 200
    phase["test"] = False
    before = len(reached)
    with ai_env["sessions"].begin() as db:
        result = orchestrated_text(db, ai_env["org_id"], task="red_obras",
                                   instructions="Asesoría", prompt="Pregunta pública",
                                   max_output_tokens=100)
        assert result is None
    assert reached[before:] == [primary["model"]]


def test_reviewer_must_use_a_different_underlying_model(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    first = add(client, headers, name="DeepSeek A")
    duplicate = add(client, headers, name="DeepSeek B", key="nvapi-synthetic-another")
    monkeypatch.setattr(ai_gateway, "urlopen", lambda *_args, **_kwargs:
                        FakeResponse({"choices": [{"message": {"content": "OK"}}],
                                      "usage": {"prompt_tokens": 7, "completion_tokens": 2}}))
    for item in (first, duplicate):
        assert client.post(ROOT + "/connections/" + item["id"] + "/test",
                           headers=headers).json()["ok"]
    response = client.put(ROOT + "/policy", headers=headers, json={
        "enabled": True, "review_enabled": True,
        "task_routes": {"red_obras": first["id"], "review": duplicate["id"]},
    })
    assert response.status_code == 422
    assert "modelo diferente" in response.text


def test_ai_gateway_refuses_redirects_to_another_host():
    from urllib.request import Request
    handler = ai_gateway._NoExternalRedirects()
    target = handler.redirect_request(
        Request("https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": "Bearer secret-synthetic"}),
        None, 307, "Temporary Redirect", {},
        "https://attacker.example.invalid/collect",
    )
    assert target is None



def test_gemini_404_recovers_using_list_and_actual_generate(ai_env, monkeypatch):
    """A list entry is not proof; the new model must really generate text."""
    from urllib.error import HTTPError
    from app import ai_model_recovery
    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="Google Gemini · gemini-2.5-flash",
                provider="gemini", model="gemini-2.5-flash", key="AIza-synthetic-not-real")
    calls = []

    def fake_open(request, timeout):
        calls.append((request.get_method(), request.full_url, request.get_header("X-goog-api-key")))
        assert "AIza-synthetic-not-real" not in request.full_url
        if request.get_method() == "GET":
            return FakeResponse({"models": [
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            ]})
        if "gemini-2.5-flash:generateContent" in request.full_url:
            raise HTTPError(request.full_url, 404, "Cannot access restricted old model", None, None)
        if "gemini-3.8-flash:generateContent" in request.full_url:
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": "OK"}]}}],
                                 "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 5}})
        raise AssertionError("Unexpected API path")

    monkeypatch.setattr(ai_gateway, "urlopen", fake_open)
    previous = client.post(ROOT + "/connections/" + saved["id"] + "/test", headers=headers)
    assert previous.json()["ok"] is False
    assert "(HTTP 404)" in previous.json()["message"]

    recovered = client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=headers)
    assert recovered.status_code == 200, recovered.text
    result = recovered.json()
    assert result["ok"] is True
    assert result["model"] == "gemini-3.8-flash"
    assert result["attempts"] == 1
    assert result["connection"]["enabled"] is True
    assert result["connection"]["status"] == "verified"
    assert result["connection"]["name"] == "Google Gemini · gemini-3.8-flash"
    assert "api_key" not in recovered.text and "AIza-synthetic-not-real" not in recovered.text
    assert calls[0][2] == "AIza-synthetic-not-real"
    with ai_env["sessions"]() as db:
        record = db.get(AIConnection, saved["id"])
        assert ai_gateway.decrypt_key(record.encrypted_key) == "AIza-synthetic-not-real"
        assert record.model == "gemini-3.8-flash"
    report = client.get(ROOT + "/usage").json()
    assert report["total_calls"] == 2  # 404 and successful candidate
    assert report["total_tokens"] == 16


def test_gemini_catalog_may_list_inaccessible_model_then_try_next(ai_env, monkeypatch):
    """A listed 3.8 that returns 404 must not be reported as verified."""
    from urllib.error import HTTPError
    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="Primario Gemini",
                provider="gemini", model="gemini-2.5-flash")
    paths = []

    def fake_open(request, timeout):
        paths.append(request.full_url)
        if request.get_method() == "GET":
            return FakeResponse({"models": [
                {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-pro", "supportedGenerationMethods": ["generateContent"]},
            ]})
        if "gemini-3.8-flash:" in request.full_url:
            raise HTTPError(request.full_url, 404, "restricted", None, None)
        if "gemini-3.5-flash-lite:" in request.full_url:
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": "OK Lite"}]}}],
                                 "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1}})
        raise AssertionError("Unexpected model probe")

    monkeypatch.setattr(ai_gateway, "urlopen", fake_open)
    r = client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=headers)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["model"] == "gemini-3.5-flash-lite"
    assert r.json()["attempts"] == 2
    assert sum("generateContent" in p for p in paths) == 2
    assert all("gemini-pro" not in p for p in paths)
    usage = client.get(ROOT + "/usage").json()
    assert usage["total_calls"] == 2
    assert usage["total_tokens"] == 4


def test_gemini_catalog_failure_does_not_erase_key_or_model(ai_env, monkeypatch):
    """Invalid credentials stop recovery without altering existing encrypted key."""
    from urllib.error import HTTPError
    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="Recuperación fallida",
                provider="gemini", model="gemini-2.5-flash", key="AIza-example-private")
    def invalid(request, timeout):
        raise HTTPError(request.full_url, 401, "secret remote details", None, None)
    monkeypatch.setattr(ai_gateway, "urlopen", invalid)
    result = client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=headers)
    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["attempts"] == 0
    assert "AIza-example-private" not in result.text
    with ai_env["sessions"]() as db:
        record = db.get(AIConnection, saved["id"])
        assert record.model == "gemini-2.5-flash"
        assert record.encrypted_key
    assert client.get(ROOT + "/usage").json()["total_calls"] == 0


def test_recovery_is_admin_only_and_org_scoped(ai_env):
    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="Conexión protegida", provider="gemini",
                model="gemini-2.5-flash")
    assert client.post(ROOT + "/connections/" + saved["id"] + "/recover").status_code in (401, 403)
    signin(client, "resident")
    assert client.post(ROOT + "/connections/" + saved["id"] + "/recover").status_code == 403
    outsider = signin(client, "outside")
    assert client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=outsider).status_code == 404


def test_recovery_non_gemini_refused(ai_env):
    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="Proveedor no recuperable", provider="openai",
                model="gpt-4.1-mini")
    result = client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=headers)
    assert result.status_code == 422


def test_gemini_probes_are_bounded(ai_env, monkeypatch):
    from urllib.error import HTTPError
    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="Gemini sin acceso",
                provider="gemini", model="gemini-2.5-flash")
    hits = []
    def no_access(request, timeout):
        if request.get_method() == "GET":
            return FakeResponse({"models": [
                {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.7-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            ]})
        hits.append(request.full_url)
        raise HTTPError(request.full_url, 404, "model unavailable", None, None)
    monkeypatch.setattr(ai_gateway, "urlopen", no_access)
    response = client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=headers)
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["attempts"] == 4
    assert len(hits) == 4
    with ai_env["sessions"]() as db:
        conn = db.get(AIConnection, saved["id"])
        assert conn.model == "gemini-2.5-flash" and not conn.enabled
    assert client.get(ROOT + "/usage").json()["total_calls"] == 4


def test_gemini_503_reports_provider_outage_without_claiming_model_failure(ai_env, monkeypatch):
    from urllib.error import HTTPError

    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="Gemini temporal", provider="gemini",
                model="gemini-2.5-flash")
    probes = []

    def unavailable(request, timeout):
        if request.get_method() == "GET":
            return FakeResponse({"models": [
                {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            ]})
        probes.append(request.full_url)
        raise HTTPError(request.full_url, 503, "private provider details", None, None)

    monkeypatch.setattr(ai_gateway, "urlopen", unavailable)
    result = client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=headers)
    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["attempts"] == 1
    assert "temporalmente no disponible" in result.json()["message"]
    assert "No se encontró un modelo" not in result.text
    assert "private provider details" not in result.text
    assert len(probes) == 1


def test_gemini_recovery_checks_later_listed_models(ai_env, monkeypatch):
    from urllib.error import HTTPError

    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="Gemini catálogo", provider="gemini",
                model="gemini-2.5-flash")

    def later_model(request, timeout):
        if request.get_method() == "GET":
            return FakeResponse({"models": [
                {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.7-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            ]})
        if "gemini-2.5-flash:" in request.full_url:
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})
        raise HTTPError(request.full_url, 404, "unavailable", None, None)

    monkeypatch.setattr(ai_gateway, "urlopen", later_model)
    result = client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=headers)
    assert result.status_code == 200
    assert result.json()["ok"] is True
    assert result.json()["model"] == "gemini-2.5-flash"
    assert result.json()["attempts"] == 4



def test_global_nvidia_lightning_is_linked_to_every_organization(ai_env):
    """One encrypted key links all user orgs and never joins their business data."""
    from app.ai_global_lightning import GLOBAL_ID, MODEL, sync_all, sync_org
    from app.ai_models import AIGlobalCredential, AIOrchestration
    from app.models import Organization, User
    _, sessions = ai_env["client"], ai_env["sessions"]
    encrypted = ai_gateway.encrypt_key("nvapi-test-shared-key")
    with sessions.begin() as db:
        db.add(AIGlobalCredential(
            id=GLOBAL_ID, provider="nvidia", model=MODEL,
            encrypted_key=encrypted, enabled=True, verified_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        ))
        db.flush()
        linked, total = sync_all(db, force=True)
        assert (linked, total) == (2, 2)
    with sessions() as db:
        orgs = list(db.scalars(select(Organization.id)))
        assert len(orgs) == 2
        connections = list(db.scalars(select(AIConnection).where(
            AIConnection.model == MODEL
        )))
        assert len(connections) == 2
        assert len({c.id for c in connections}) == 2
        assert all(ai_gateway.decrypt_key(c.encrypted_key) == "nvapi-test-shared-key"
                   for c in connections)
        for org_id in orgs:
            policy = db.get(AIOrchestration, org_id)
            conn = next(c for c in connections if c.org_id == org_id)
            assert policy.enabled
            assert policy.task_routes.get("red_obras") == conn.id
            assert not policy.task_routes.get("messenger")
            assert policy.monthly_token_limit == 100000

    # A user joining a new org later inherits the provider, with no second key.
    with sessions.begin() as db:
        new_org = Organization(name="Obra nueva")
        db.add(new_org)
        db.flush()
        db.add(User(org_id=new_org.id, email="later@example.cl",
                    role="resident", enabled=True, password_hash="test-only"))
        db.flush()
        assert sync_org(db, new_org.id)
        assert not sync_org(db, new_org.id)
    with sessions() as db:
        conn = db.scalar(select(AIConnection).where(
            AIConnection.org_id == new_org.id, AIConnection.model == MODEL
        ))
        assert conn and conn.enabled
        assert ai_gateway.decrypt_key(conn.encrypted_key) == "nvapi-test-shared-key"


def test_global_nvidia_only_activates_after_verified_credential(ai_env):
    from app.ai_global_lightning import GLOBAL_ID, MODEL, sync_all
    from app.ai_models import AIGlobalCredential
    with ai_env["sessions"].begin() as db:
        db.add(AIGlobalCredential(id=GLOBAL_ID, provider="nvidia",
                                  model=MODEL, enabled=False,
                                  encrypted_key=ai_gateway.encrypt_key("nvapi-demo")))
        db.flush()
        assert sync_all(db, force=True) == (0, 2)


def test_nvidia_lightning_disables_reasoning_for_quick_replies(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    record = add(client, headers, name="Lightning rápido",
                 model="nvidia/nemotron-3.5-lightning-30b-a3b")
    def fake_open(request, timeout):
        body = json.loads(request.data)
        assert body["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["temperature"] == 1.0
        return FakeResponse({"choices": [{"message": {"content": "OK"}}],
                             "usage": {"prompt_tokens": 6, "completion_tokens": 1}})
    monkeypatch.setattr(ai_gateway, "urlopen", fake_open)
    result = client.post(ROOT + "/connections/" + record["id"] + "/test", headers=headers)
    assert result.status_code == 200 and result.json()["ok"] is True


def test_nvidia_recovery_never_substitutes_nemotron_for_deepseek(ai_env, monkeypatch):
    """A DeepSeek connection must not pass a test using another model."""
    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="NVIDIA DeepSeek")
    requests = []

    def nvidia_response(request, timeout):
        requests.append(request)
        assert request.get_header("Authorization") == "Bearer nvapi-example-secret"
        assert request.get_method() == "GET"
        return FakeResponse({"data": [
            {"id": "nvidia/nemotron-3.5-bolt-e4b"},
            {"id": "nvidia/nemotron-3.5-embed-1b"},
        ]})

    monkeypatch.setattr(ai_gateway, "urlopen", nvidia_response)
    result = client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=headers)
    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["attempts"] == 0
    assert "DeepSeek" in result.json()["message"]
    assert len(requests) == 1
    with ai_env["sessions"]() as db:
        record = db.get(AIConnection, saved["id"])
        assert record.model == "deepseek-ai/deepseek-v4.1-flash"
        assert not record.enabled
    assert "nvapi-example-secret" not in result.text


def test_nvidia_deepseek_recovery_and_sampling_use_real_model(ai_env, monkeypatch):
    """Recovery verifies an actual current DeepSeek model with a chat probe."""
    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="NVIDIA DeepSeek V4",
                model="deepseek-ai/deepseek-v4-flash")
    calls = []

    def nvidia_response(request, timeout):
        calls.append(request)
        assert request.get_header("Authorization") == "Bearer nvapi-example-secret"
        if request.get_method() == "GET":
            return FakeResponse({"data": [
                {"id": "deepseek-ai/deepseek-v4-flash"},
                {"id": "nvidia/nemotron-3.5-bolt-e4b"},
            ]})
        body = json.loads(request.data)
        assert body["model"] == "deepseek-ai/deepseek-v4-flash"
        assert body["temperature"] == 1.0
        assert body["top_p"] == 0.95
        assert body["reasoning_effort"] == "none"
        assert body["max_tokens"] == 512
        return FakeResponse({"choices": [{"message": {"content": "OK"}}],
                             "usage": {"prompt_tokens": 8, "completion_tokens": 2}})

    monkeypatch.setattr(ai_gateway, "urlopen", nvidia_response)
    result = client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=headers)
    assert result.status_code == 200
    assert result.json()["ok"] is True
    assert result.json()["model"] == "deepseek-ai/deepseek-v4-flash"
    assert result.json()["connection"]["enabled"] is True
    assert result.json()["connection"]["status"] == "verified"
    assert len(calls) == 2
    assert client.get(ROOT + "/usage").json()["total_tokens"] == 10
    assert "nvapi-example-secret" not in result.text


def test_nvidia_410_retired_model_can_recover_without_changing_key(ai_env, monkeypatch):
    """A retired V4.1 model gets a safe error, then a verified V4 replacement."""
    from urllib.error import HTTPError
    client = ai_env["client"]
    headers = signin(client)
    saved = add(client, headers, name="Modelo retirado")
    seen = []

    def nvidia_response(req, timeout):
        if req.get_method() == "GET":
            return FakeResponse({"data": [
                {"id": "deepseek-ai/deepseek-v4-flash"},
                {"id": "nvidia/nemotron-3.5-bolt-e4b"},
            ]})
        body = json.loads(req.data)
        seen.append(body["model"])
        if body["model"] == "deepseek-ai/deepseek-v4.1-flash":
            raise HTTPError(req.full_url, 410, "retired model private body", None, None)
        assert body["model"] == "deepseek-ai/deepseek-v4-flash"
        return FakeResponse({"choices": [{"message": {"content": "OK"}}],
                             "usage": {"prompt_tokens": 5, "completion_tokens": 2}})

    monkeypatch.setattr(ai_gateway, "urlopen", nvidia_response)
    first = client.post(ROOT + "/connections/" + saved["id"] + "/test", headers=headers)
    assert first.status_code == 200
    assert first.json()["ok"] is False
    assert "HTTP 410" in first.json()["message"]
    assert "private body" not in first.text
    fixed = client.post(ROOT + "/connections/" + saved["id"] + "/recover", headers=headers)
    assert fixed.status_code == 200
    assert fixed.json()["ok"] is True
    assert fixed.json()["model"] == "deepseek-ai/deepseek-v4-flash"
    assert fixed.json()["connection"]["status"] == "verified"
    assert fixed.json()["connection"]["enabled"] is True
    assert seen == ["deepseek-ai/deepseek-v4.1-flash", "deepseek-ai/deepseek-v4-flash"]
    with ai_env["sessions"]() as db:
        from app.ai_gateway import decrypt_key
        assert decrypt_key(db.get(AIConnection, saved["id"]).encrypted_key) == "nvapi-example-secret"

def test_groq_recovers_from_active_models_using_saved_key(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    item = add(client, headers, name="Groq recuperación", provider="groq",
               model="llama-3.3-70b-versatile", key="gsk-synthetic-only")
    seen = []
    def fake(req, timeout):
        seen.append((req.get_method(), req.full_url, req.get_header("Authorization")))
        if req.get_method() == "GET":
            return FakeResponse({"data": [
                {"id": "whisper-large-v3", "active": True},
                {"id": "llama-3.3-70b-versatile", "active": False},
                {"id": "llama-3.1-8b-instant", "active": True}]})
        assert json.loads(req.data)["model"] == "llama-3.1-8b-instant"
        return FakeResponse({"choices": [{"message": {"content": "OK"}}],
                             "usage": {"prompt_tokens": 10, "completion_tokens": 4}})
    monkeypatch.setattr(ai_gateway, "urlopen", fake)
    result = client.post(ROOT + "/connections/" + item["id"] + "/recover", headers=headers)
    assert result.status_code == 200 and result.json()["ok"] is True, result.text
    assert result.json()["model"] == "llama-3.1-8b-instant"
    assert result.json()["connection"]["enabled"] is True
    assert result.json()["connection"]["status"] == "verified"
    assert len(seen) == 2
    assert all(x[2] == "Bearer gsk-synthetic-only" for x in seen)
    assert "gsk-synthetic-only" not in result.text
    assert client.get(ROOT + "/usage").json()["total_tokens"] == 14


def test_zai_standard_endpoint_and_thinking(ai_env, monkeypatch):
    client = ai_env["client"]
    headers = signin(client)
    item = add(client, headers, name="Z.ai estándar",
               provider="zai", model="glm-4.7", key="zai-test-only")
    calls = []
    def fake(req, timeout):
        calls.append((req.full_url, req.get_header("Authorization"), json.loads(req.data)))
        return FakeResponse({"choices": [{"message": {"content": "OK"}}],
                             "usage": {"prompt_tokens": 13, "completion_tokens": 6}})
    monkeypatch.setattr(ai_gateway, "urlopen", fake)
    result = client.post(ROOT + "/connections/" + item["id"] + "/test", headers=headers)
    assert result.status_code == 200 and result.json()["ok"] is True, result.text
    assert len(calls) == 1
    url, auth, body = calls[0]
    assert url == "https://api.z.ai/api/paas/v4/chat/completions" and auth == "Bearer zai-test-only"
    assert body["thinking"] == {"type": "disabled"} and body["model"] == "glm-4.7"
    assert "zai-test-only" not in result.text


def test_zai_standard_recovery_never_uses_coding_plan(ai_env, monkeypatch):
    from urllib.error import HTTPError
    client = ai_env["client"]
    headers = signin(client)
    item = add(client, headers, name="Z.ai estándar", provider="zai", model="glm-4.7")
    urls = []
    def fake(req, timeout):
        urls.append(req.full_url)
        payload = json.loads(req.data)
        if payload["model"] == "glm-4.7":
            raise HTTPError(req.full_url, 404, "not permitted", None, None)
        assert payload["model"] == "glm-5.3-flash"
        assert "thinking" not in payload and payload["temperature"] == 1.0
        return FakeResponse({"choices": [{"message": {"content": "OK"}}],
                             "usage": {"prompt_tokens": 30, "completion_tokens": 100}})
    monkeypatch.setattr(ai_gateway, "urlopen", fake)
    r = client.post(ROOT + "/connections/" + item["id"] + "/recover", headers=headers)
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert r.json()["model"] == "glm-5.3-flash" and r.json()["attempts"] == 2
    assert len(urls) == 2
    assert all(url == "https://api.z.ai/api/paas/v4/chat/completions" for url in urls)


def test_groq_and_zai_auth_errors_do_not_retry_or_expose_secrets(ai_env, monkeypatch):
    from urllib.error import HTTPError
    client = ai_env["client"]
    headers = signin(client)
    groq = add(client, headers, name="Groq bad key", provider="groq",
               model="llama-3.1-8b-instant")
    zai = add(client, headers, name="Zai bad key", provider="zai",
              model="glm-4.7")
    seen = []
    def fake(req, timeout):
        seen.append(req.full_url)
        raise HTTPError(req.full_url, 401, "raw-secret-payload", None, None)
    monkeypatch.setattr(ai_gateway, "urlopen", fake)
    for obj in (groq, zai):
        r = client.post(ROOT + "/connections/" + obj["id"] + "/recover", headers=headers)
        assert r.status_code == 200 and r.json()["ok"] is False
        assert "raw-secret-payload" not in r.text
    assert len(seen) == 2


def test_recovery_providers_are_org_scoped(ai_env):
    client = ai_env["client"]
    headers = signin(client)
    for provider, model in (("groq", "llama-3.1-8b-instant"), ("zai", "glm-4.7")):
        row = add(client, headers, name="Scoped " + provider, provider=provider, model=model)
        outsider = signin(client, "outside")
        assert client.post(ROOT + "/connections/" + row["id"] + "/recover", headers=outsider).status_code == 404
        headers = signin(client)


def test_zai_coding_plan_not_supported_for_multiuser_application(ai_env):
    client = ai_env["client"]
    headers = signin(client)
    response = client.post(ROOT + "/connections", headers=headers, json={
        "name": "Coding Plan inappropriate for Red de Obras",
        "provider": "zai_coding", "model": "glm-5.3-flash",
        "api_key": "fake-nonproduction-only",
    })
    assert response.status_code == 422
    assert "fake-nonproduction-only" not in response.text
