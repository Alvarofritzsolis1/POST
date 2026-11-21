from io import BytesIO
import json
from threading import Event
from urllib.error import HTTPError

from app import galancito_training_model as model


def test_first_round_downloads_once_and_waits_for_installed_model(monkeypatch):
    started = Event()
    complete = Event()

    def download(request, timeout):
        assert json.loads(request.data)["model"] == model.MODEL
        if request.full_url.endswith("/api/show"):
            raise HTTPError(request.full_url, 404, "", {}, None)
        assert request.full_url == model.TRAINING_OLLAMA + "/api/pull"
        started.set()
        assert complete.wait(3)
        return BytesIO(b'{"status":"pulling manifest"}\n{"status":"success"}\n')

    monkeypatch.setattr(model._opener, "open", download)
    setup = model.TrainingModel()
    assert "2 GB" in setup.waiting_reason(1024)
    assert setup.download is None
    assert "Preparando Qwen" in setup.waiting_reason(4500)
    assert started.wait(2)
    first = setup.download
    try:
        assert "Descargando Qwen" in setup.waiting_reason(4500)
        assert setup.download is first
    finally:
        complete.set()
        first.join(3)
    assert setup.waiting_reason(4500) is None


def test_registry_failure_is_retried_with_a_delay(monkeypatch):
    def download_failure(*_):
        raise OSError("service offline")

    monkeypatch.setattr(model, "model_installed", lambda *_: False)
    monkeypatch.setattr(model, "pull_model", download_failure)
    setup = model.TrainingModel()
    setup.waiting_reason(4500)
    setup.download.join(3)
    assert "volverá a intentarlo" in setup.waiting_reason(4500)


def test_qwen35_training_uses_existing_private_live_engine(monkeypatch):
    """Advanced model is read from main Ollama and must never auto-pull a second 4B."""
    import io
    checked = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    def fake_open(request, timeout):
        checked.append((request.full_url, json.loads(request.data)))
        return Response()
    monkeypatch.setattr(model._opener, "open", fake_open)
    setup = model.TrainingModel()
    assert setup.waiting_reason(100, model.ADVANCED_MODEL) is None
    assert checked[0][0] == model.INTERNAL_URL.replace("/api/chat", "/api/show")
    assert checked[0][1]["model"] == model.ADVANCED_MODEL
    assert setup.download is None


def test_qwen35_training_does_not_pull_when_missing(monkeypatch):
    from urllib.error import HTTPError
    def not_found(request, timeout):
        raise HTTPError(request.full_url, 404, "", {}, None)
    monkeypatch.setattr(model._opener, "open", not_found)
    setup = model.TrainingModel()
    reason = setup.waiting_reason(7000, model.ADVANCED_MODEL)
    assert "no está descargado" in reason
    assert setup.download is None
