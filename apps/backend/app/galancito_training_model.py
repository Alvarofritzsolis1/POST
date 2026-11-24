"""Prepare the fixed local model on demand while the worker stays responsive."""
import json
import logging
from threading import Thread
from time import monotonic
from urllib.error import HTTPError
from urllib.request import Request

from .galancito_local import MODEL, MAX_POWER_ISOLATED, TRAINING_OLLAMA, _opener

logger = logging.getLogger(__name__)


def _request(path, data):
    return Request(TRAINING_OLLAMA + path, data=json.dumps(data).encode(),
                   headers={"Content-Type": "application/json"})


def model_installed(model_name=MODEL):
    try:
        with _opener.open(_request("/api/show", {"model": model_name}), timeout=2):
            return True
    except HTTPError as error:
        if error.code == 404:
            return False
        raise


def pull_model(model_name=MODEL):
    deadline = monotonic() + 45 * 60
    with _opener.open(_request("/api/pull", {"model": model_name, "stream": True}), timeout=90) as response:
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


def isolated_model_resident(model_name=MODEL):
    """Verify actual residency on the private Ollama; failure is a cold start."""
    if not MAX_POWER_ISOLATED:
        return False
    try:
        with _opener.open(Request(TRAINING_OLLAMA + "/api/ps"), timeout=1) as response:
            data = json.loads(response.read(65536))
        return any(isinstance(item, dict)
                   and str(item.get("name") or item.get("model") or "").casefold() == model_name.casefold()
                   and type(item.get("size")) is int and item["size"] > 0
                   for item in data.get("models", []))
    except (OSError, ValueError, AttributeError, TypeError):
        return False


class TrainingModel:
    def __init__(self):
        self.download = None
        self.retry_at = 0
        self.ready_until = 0
        self.problem = None
        self.active_model = MODEL
        self.ready_model = None

    def _pull(self):
        target = self.active_model
        try:
            pull_model(target)
        except (OSError, ValueError, RuntimeError):
            self.problem = "No se pudo descargar Qwen. GALANT volverá a intentarlo."
            self.retry_at = monotonic() + 120
            logger.warning("Descarga del modelo de entrenamiento pendiente de reintento")
        else:
            self.ready_model = target
            self.ready_until = monotonic() + 60

    def waiting_reason(self, disk_free_mb, model_name=MODEL):
        if model_name != MODEL:
            return "La versión histórica del modelo ya no está disponible para práctica"
        if self.download is not None and self.download.is_alive():
            return "Descargando Qwen3.5 2B para la práctica"
        now = monotonic()
        if self.ready_model == model_name and self.ready_until > now:
            return None
        if self.active_model == model_name and self.retry_at > now:
            return self.problem
        try:
            if model_installed(model_name):
                self.ready_model = model_name
                self.ready_until = now + 60
                return None
        except OSError:
            return "En espera del servicio privado de Ollama"
        required_disk_mb = 3072
        if disk_free_mb < required_disk_mb:
            minimum_gb = required_disk_mb // 1024
            return (
                f"No hay disco libre suficiente: se necesitan al menos {minimum_gb} GB "
                "para instalar el modelo de práctica aislado"
            )
        self.active_model = model_name
        self.problem, self.retry_at = None, 0
        self.download = Thread(target=self._pull, name="training-model-download", daemon=True)
        self.download.start()
        return "Preparando Qwen para la primera ronda"
