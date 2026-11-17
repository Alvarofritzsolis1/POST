"""Galancito offline: private small model, allowed scope and fallback."""
import json
from pathlib import Path
import pytest

from app.config import settings
from app.facebook_ai import AD_INSTRUCTIONS, REPLY_INSTRUCTIONS
from app.facebook_chat_worker import process_chat_next
from app import facebook_ai, galancito_local
from test_facebook_crm import enable_messaging, incoming
from test_network import network


def test_ollama_private_endpoint_bounded_and_no_thinking(monkeypatch):
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, length):
            return json.dumps({"message": {
                "content": "<think>internal thoughts</think>Hola, ¿Qué trabajo haces?"
            }}).encode()

    def open_mock(req, timeout):
        calls.append((req, timeout))
        return Response()

    monkeypatch.setattr(galancito_local._opener, "open", open_mock)
    assert galancito_local.generate_local_text("System", "hola") == "Hola, ¿Qué trabajo haces?"
    req, timeout = calls[0]
    assert req.full_url == "http://galancito-ollama:11434/api/chat"
    assert timeout <= 25
    payload = json.loads(req.data)
    assert payload["model"] == "qwen3:1.7b"
    assert payload["think"] is False and payload["stream"] is False
    assert payload["keep_alive"] == "2m"
    assert payload["options"]["num_ctx"] <= 2048
    assert payload["options"]["num_predict"] <= 140


def test_ollama_refuses_unclosed_private_reasoning(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, length): return b'{"message":{"content":"<think>secret"}}'
    monkeypatch.setattr(galancito_local._opener, "open", lambda *a, **kw: Response())
    with pytest.raises(RuntimeError):
        galancito_local.generate_local_text("System", "hola")
    with pytest.raises(ValueError):
        galancito_local.generate_local_text("System", "hola", max_chars=2000)


def test_local_provider_only_two_allowed_tasks(monkeypatch):
    for k, val in {
        "FACEBOOK_AI_PROVIDER": "ollama",
        "GALANCITO_AI_PROVIDER": "ollama",
        "GALANCITO_LOCAL_AI_ENABLED": "true",
        "FACEBOOK_AI_ENABLED": "true",
        "GALANCITO_AI_ENABLED": "true",
        "FACEBOOK_AI_API_KEY": "",
        "GALANCITO_AI_API_KEY": "",
    }.items(): monkeypatch.setenv(k, val)
    settings.cache_clear()
    calls = []
    monkeypatch.setattr(facebook_ai, "generate_local_text", lambda *args:
                        calls.append(args) or "Soy Galancito. ¿Qué trabajo haces?")
    monkeypatch.setattr(facebook_ai, "_generate", lambda *a: (_ for _ in ()).throw(
        AssertionError("El modelo local no debe llamar a OpenAI")))
    assert facebook_ai.facebook_reply_ai_available()
    assert facebook_ai.galancito_red_ai_available()
    assert facebook_ai.generate_text(REPLY_INSTRUCTIONS, "gasfiter")
    assert facebook_ai.generate_internal_text("Red de Obras", "consulta")
    assert facebook_ai.generate_text(AD_INSTRUCTIONS, "anuncio") is None
    assert len(calls) == 2
    settings.cache_clear()


def test_facebook_uses_local_ollama_after_explicit_consent(network, monkeypatch):
    n = network
    enable_messaging(n, monkeypatch)
    for k, v in {
        "FACEBOOK_AI_PROVIDER": "ollama",
        "GALANCITO_LOCAL_AI_ENABLED": "true",
        "FACEBOOK_AI_ENABLED": "true",
        "FACEBOOK_AI_AUTO_REPLY_ENABLED": "true",
        "FACEBOOK_AI_API_KEY": "",
    }.items(): monkeypatch.setenv(k, v)
    settings.cache_clear()
    assert incoming(n, text="ola soy gasfite", mid="local-1").status_code == 200
    center = n["admin"].get("/api/v1/network/facebook/center").json()
    lead = center["leads"][0]
    assert center["ai_provider"] == "ollama"
    assert lead["ai_consent_state"] == "requested"
    messages = n["admin"].get("/api/v1/network/facebook/leads/" + lead["id"]).json()["messages"]
    assert "IA local" in messages[-1]["body"]
    sent, generated = [], []
    monkeypatch.setattr("app.facebook_chat_worker.graph_send",
                        lambda p, u, text, token: sent.append(text) or "mid-local-" + str(len(sent)))
    monkeypatch.setattr(facebook_ai, "generate_local_text",
                        lambda inst, ctx, limit: generated.append(ctx) or "¿En qué comuna trabajas?")
    monkeypatch.setattr(facebook_ai, "_generate", lambda *a: (_ for _ in ()).throw(
        AssertionError("No paid API")))
    assert process_chat_next(n["Session"])
    assert len(sent) == 1 and not generated
    assert incoming(n, text="sí", mid="local-2").status_code == 200
    assert process_chat_next(n["Session"])
    # A recognized trade offer is answered without loading the LLM.
    assert not generated and len(sent) == 2
    assert "empleo" in sent[-1]
    assert "Galancito" in sent[-1]
    settings.cache_clear()


def test_red_de_obras_local_ai_without_external_api(network, monkeypatch):
    n = network
    for k,v in {"GALANCITO_AI_PROVIDER": "ollama", "GALANCITO_AI_ENABLED": "true",
                "GALANCITO_LOCAL_AI_ENABLED": "true", "GALANCITO_AI_API_KEY": ""}.items():
        monkeypatch.setenv(k, v)
    settings.cache_clear()
    calls = []
    monkeypatch.setattr("app.galancito_api.generate_internal_text",
                        lambda *args: calls.append(args) or "Soy Galancito. Revisa Red de Obras.")
    state = n["admin"].get("/api/v1/network/galancito/status").json()
    assert state["local_ai_available"] is True
    assert state["external_ai_available"] is False
    response = n["send"](n["admin"], "/galancito/chat",
        {"message": "Explica cómo organizar una coordinación de servicios", "area": "red_obras", "allow_external_ai": False})
    assert response.status_code == 200
    assert response.json()["source"] == "ai" and len(calls) == 1
    blocked = n["send"](n["admin"], "/galancito/chat",
        {"message": "ayúdame en trabajadores", "area": "galant"})
    assert blocked.status_code == 422
    settings.cache_clear()


def test_compose_optional_memory_cpu_and_no_published_port():
    file = Path(__file__).resolve().parents[3] / "docker-compose.preview.yml"
    text = file.read_text()
    section = text.split("  galancito-ollama:\n",1)[1].split("\n  frontend:",1)[0]
    for expected in ['profiles: [local-ai]', 'mem_limit: 3g', 'cpus: 1.5',
                     'OLLAMA_NUM_PARALLEL: "1"', 'OLLAMA_MAX_QUEUE: "2"',
                     'OLLAMA_KEEP_ALIVE: ${GALANCITO_KEEP_ALIVE:-2m}', 'galancito_models:/root/.ollama']:
        assert expected in section
    assert "ports:" not in section
