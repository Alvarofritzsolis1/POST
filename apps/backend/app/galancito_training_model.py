"""Prepare the fixed local model on demand while the worker stays responsive."""
import json
import logging
from threading import Thread
from time import monotonic
from urllib.error import HTTPError
from urllib.request import Request

from .galancito_local import MODEL, TRAINING_OLLAMA, _opener

logger = logging.getLogger(__name__)


def _request(path, data):
    return Request(TRAINING_OLLAMA + path, data=json.dumps(data).encode(),
                   headers={"Content-Type": "application/json"})


def model_installed():
    try:
        with _opener.open(_request("/api/show", {"model": MODEL}), timeout=2):
            return True
    except HTTPError as error:
        if error.code == 404:
            return False
        raise


def pull_model():
    deadline = monotonic() + 45 * 60
    with _opener.open(_request("/api/pull", {"model": MODEL, "stream": True}), timeout=90) as response:
        while monotonic() < deadline:
            line = response.readline(8192)
            if not line:
                break
            status = json.loads(line)
            if not isinstance(status, dict) or status.get("error"):
                break
            if status.get("status") == "success":
                return
    raise RuntimeError("No se pudo completar la descarga de Qwen")


class TrainingModel:
    def __init__(self):
        self.download = None
        self.retry_at = 0
        self.ready_until = 0
        self.problem = None

    def _pull(self):
        try:
            pull_model()
        except (OSError, ValueError, RuntimeError):
            self.problem = "No se pudo descargar Qwen. GALANT volverá a intentarlo."
            self.retry_at = monotonic() + 120
            logger.warning("Descarga del modelo de entrenamiento pendiente de reintento")
        else:
            self.ready_until = monotonic() + 60

    def waiting_reason(self, disk_free_mb):
        if self.download is not None and self.download.is_alive():
            return "Descargando Qwen por primera vez. La ronda seguirá automáticamente."
        now = monotonic()
        if self.ready_until > now:
            return None
        if self.retry_at > now:
            return self.problem
        try:
            if model_installed():
                self.ready_until = now + 60
                return None
        except OSError:
            return "En espera de Ollama, el servicio de IA local"
        if disk_free_mb < 2048:
            return "Qwen necesita al menos 2 GB libres para terminar de descargarse"
        self.download = Thread(target=self._pull, name="training-model-download", daemon=True)
        self.download.start()
        return "Preparando Qwen para la primera ronda"
