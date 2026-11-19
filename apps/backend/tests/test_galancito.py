"""GALANCITO is read-only, tenant-scoped and private without explicit user opt-in."""
from app.config import settings
from test_network import network, request_body


def test_galancito_is_available_without_external_ai(network, monkeypatch):
    n = network
    monkeypatch.setenv("GALANCITO_AI_ENABLED", "false")
    settings.cache_clear()
    status = n["admin"].get("/api/v1/network/galancito/status")
    assert status.status_code == 200, status.text
    assert status.json()["name"] == "Galancito"
    assert status.json()["external_ai_available"] is False
    response = n["send"](n["admin"], "/galancito/chat",
        {"message": "hola", "area": "red_obras", "allow_external_ai": False})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source"] == "local" and data["read_only"] is True
    assert "Red de Obras" in data["answer"]
    assert "asistente virtual" not in data["answer"].lower()
    # Galancito no se puede invocar para módulos ajenos a Red de Obras.
    denied = n["send"](n["admin"], "/galancito/chat",
        {"message": "hola", "area": "galant"})
    assert denied.status_code == 422
    docs = n["send"](n["a"], "/galancito/chat",
        {"message": "qué papeles para entrar a obra", "area": "red_obras"})
    assert docs.status_code == 200, docs.text
    assert "sociedad" not in docs.json()["answer"].lower() or "empresa" in docs.json()["answer"].lower()
    assert "¿" in docs.json()["answer"]


def test_galancito_restricts_external_ai_to_explicit_consent(network, monkeypatch):
    n = network
    monkeypatch.setenv("GALANCITO_AI_ENABLED", "true")
    monkeypatch.setenv("GALANCITO_AI_API_KEY", "synthetic-do-not-send")
    settings.cache_clear()
    calls = []
    def mocked(instructions, context, limit):
        calls.append(context)
        assert "Galancito" in instructions
        assert "Necesidades publicadas (títulos): []" in context
        return "Soy Galancito. ¿En qué puedo ayudarte?"
    monkeypatch.setattr("app.galancito_api.generate_internal_text", mocked)
    local = n["send"](n["admin"], "/galancito/chat",
        {"message": "hola", "allow_external_ai": False})
    assert local.status_code == 200 and not calls
    external = n["send"](n["admin"], "/galancito/chat",
        {"message": "Explica cómo organizar una coordinación de servicios", "allow_external_ai": True})
    assert external.status_code == 200
    assert external.json()["source"] == "ai" and len(calls) == 1
    private = n["send"](n["admin"], "/galancito/chat",
        {"message": "mi RUT es 12.345.678-5", "allow_external_ai": True})
    assert private.status_code == 200 and private.json()["source"] == "local"
    assert len(calls) == 1
    assert private.json()["notice"]


def test_galancito_only_shows_published_titles_in_its_organization(network):
    n = network
    draft = request_body(n)
    draft["title"] = "Borrador privado Junto a Los Pinos"
    draft["state"] = "draft"
    assert n["send"](n["a"], "/requirements", draft).status_code == 201
    response = n["send"](n["a"], "/galancito/chat",
        {"message": "Necesito conocer las obras actuales", "area": "red_obras"})
    assert response.status_code == 200, response.text
    assert "Borrador privado Junto a Los Pinos" not in response.json()["answer"]
    assert response.json()["read_only"] is True
