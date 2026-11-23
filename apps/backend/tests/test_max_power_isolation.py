"""MAX POWER must never route its 4B inference to production Ollama."""
from types import SimpleNamespace
import pytest
from app import galancito_local as local
from app import galancito_training_model as training
from app import max_power_messenger as messenger


def test_model_download_and_status_use_isolated_ollama(monkeypatch):
    monkeypatch.setattr(training, "MAX_POWER_ISOLATED", True)
    url = training._request("/api/show", {"model": training.ADVANCED_MODEL},
                            training.ADVANCED_MODEL)
    assert url.full_url.startswith("http://galancito-training-ollama:11434/")
    assert "galancito-ollama:11434" not in url.full_url.replace("galancito-training-ollama", "")


def test_training_inference_routes_4b_to_isolated_service(monkeypatch):
    monkeypatch.setattr(local, "MAX_POWER_ISOLATED", True)
    captured = {}
    def fake_generate(instructions, data, max_chars, cfg, **kwargs):
        captured.update(kwargs)
        return "Ensayo local"
    monkeypatch.setattr(local, "_generate", fake_generate)
    cfg = SimpleNamespace(galancito_local_model=training.ADVANCED_MODEL)
    answer = local.generate_training_text("Eres Galancito", "Hola", 41, cfg)
    assert answer == "Ensayo local"
    assert captured["url"] == local.TRAINING_OLLAMA + "/api/chat"
    assert captured["allow_training"] is True


def test_messenger_experiments_fail_closed_without_isolation(monkeypatch):
    monkeypatch.setattr(messenger, "MAX_POWER_ISOLATED", False)
    with pytest.raises(RuntimeError, match="no ejecuta ensayos"):
        messenger._answer("instructions", "context", 3, "nonexistent-org")
