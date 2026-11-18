"""Synthetic contract tests for admin multi-provider AI; no real network or secrets."""
import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import ai_gateway
from app.ai_gateway import orchestration_available, orchestrated_text
from app.ai_models import AIConnection, AIUsage
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
