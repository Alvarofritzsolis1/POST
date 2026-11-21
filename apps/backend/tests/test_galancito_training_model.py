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
    def download_failure():
        raise OSError("service offline")

    monkeypatch.setattr(model, "model_installed", lambda: False)
    monkeypatch.setattr(model, "pull_model", download_failure)
    setup = model.TrainingModel()
    setup.waiting_reason(4500)
    setup.download.join(3)
    assert "volverá a intentarlo" in setup.waiting_reason(4500)
