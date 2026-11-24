"""MAX POWER must never route its 2B inference to production Ollama."""
from types import SimpleNamespace
import pytest
from app import galancito_local as local
from app import galancito_training_model as training
from app import max_power_messenger as messenger


def test_model_download_and_status_use_isolated_ollama(monkeypatch):
    monkeypatch.setattr(training, "MAX_POWER_ISOLATED", True)
    url = training._request("/api/show", {"model": training.MODEL})
    assert url.full_url.startswith("http://galancito-training-ollama:11434/")
    assert "galancito-ollama:11434" not in url.full_url.replace("galancito-training-ollama", "")


def test_training_inference_routes_2b_to_isolated_service(monkeypatch):
    monkeypatch.setattr(local, "MAX_POWER_ISOLATED", True)
    captured = {}
    def fake_generate(instructions, data, max_chars, cfg, **kwargs):
        captured.update(kwargs)
        return "Ensayo local"
    monkeypatch.setattr(local, "_generate", fake_generate)
    cfg = SimpleNamespace(galancito_local_model=training.MODEL)
    answer = local.generate_training_text("Eres Galancito", "Hola", 41, cfg)
    assert answer == "Ensayo local"
    assert captured["url"] == local.TRAINING_OLLAMA + "/api/chat"
    assert captured["allow_training"] is True


def test_messenger_experiments_fail_closed_without_isolation(monkeypatch):
    monkeypatch.setattr(messenger, "MAX_POWER_ISOLATED", False)
    with pytest.raises(RuntimeError, match="no ejecuta ensayos"):
        messenger._answer("instructions", "context", 3, "nonexistent-org")



def test_max_power_timeout_tracks_token_budget_without_extending_messenger(monkeypatch):
    from app.galancito_trainer import practice_threads
    monkeypatch.setattr(local, "MAX_POWER_ISOLATED", True)
    monkeypatch.setenv("GALANT_TRAINING_OLLAMA_THREADS", "2")
    snapshot = {"worker_cores": 0.35}
    assert practice_threads(snapshot) == 1
    assert practice_threads(snapshot, isolated=True) == 2
    assert local.training_timeout_seconds(320, thinking=True) > 120
    assert local.training_timeout_seconds(320, thinking=True) <= 360
    assert local.training_timeout_seconds(128) < local.training_timeout_seconds(320, thinking=True)

    observed = {}
    def fail_after_timeout(req, timeout):
        observed["timeout"] = timeout
        observed["request"] = req
        raise TimeoutError("internal socket details must not escape")
    monkeypatch.setattr(local._opener, "open", fail_after_timeout)
    cfg = SimpleNamespace(galancito_num_ctx=2048, galancito_num_predict=320,
                          galancito_num_thread=2, galancito_keep_alive="2m",
                          galancito_local_model="qwen3.5:2b-q4_K_M")
    with pytest.raises(RuntimeError, match="Tiempo de espera agotado en Ollama de práctica") as err:
        local.generate_training_text("Cálculo", "Datos reales", 42, cfg, thinking=True)
    assert "internal socket details" not in str(err.value)
    assert observed["timeout"] == local.training_timeout_seconds(320, thinking=True)
    assert observed["request"].full_url == local.TRAINING_OLLAMA + "/api/chat"


def test_isolated_ollama_cpu_is_capped_without_changing_production():
    from pathlib import Path
    compose = (Path(__file__).resolve().parents[3] / "docker-compose.preview.yml").read_text()
    isolated = compose.split("  galancito-training-ollama:\n", 1)[1].split("\n  frontend:", 1)[0]
    controller = compose.split("  max-power-controller:\n", 1)[1].split("\n  galancito-training-ollama:", 1)[0]
    production = compose.split("  galancito-ollama:\n", 1)[1].split("\n  galancito-trainer:", 1)[0]
    assert "GALANT_TRAINING_OLLAMA_CPUS" in isolated
    assert "GALANT_TRAINING_OLLAMA_THREADS" in controller
    assert "GALANCITO_OLLAMA_CPUS" in production
    assert "ports:" not in isolated
