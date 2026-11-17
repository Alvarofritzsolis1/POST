"""Qwen3 1.7B on the PRIVATE Ollama Docker network.

Only two allowed callers: Facebook Messenger replies and Red de Obras advising.
Never accepts an arbitrary model, host, URL, or general GALANT business action.
No paid API, no Internet endpoint, no stored prompts and no tool execution.
"""
from __future__ import annotations

import json
import re
import os
import time
from pathlib import Path
from contextvars import ContextVar
from threading import BoundedSemaphore
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .config import settings

MODEL = "qwen3:1.7b"
INTERNAL_URL = "http://galancito-ollama:11434/api/chat"
MAX_CONTEXT_CHARS = 3000
MAX_INSTRUCTIONS_CHARS = 3300


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("Ollama no debe redirigir consultas")


_opener = build_opener(NoRedirect)
_slot = BoundedSemaphore(1)
last_timings: ContextVar[dict] = ContextVar("galancito_timings", default={})


def available_memory_mb() -> int | None:
    """Host pressure signal. Ollama has a separate hard container limit."""
    try:
        values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        available = int(values["MemAvailable"].split()[0]) // 1024
        # The caller's cgroup is *not* the Ollama cgroup. Only use it as an
        # additional pressure signal, never as the model's RAM measurement.
        return available
    except (OSError, ValueError, KeyError):
        return None


def model_status() -> dict:
    try:
        with _opener.open(Request(INTERNAL_URL.replace("/api/chat", "/api/ps")), timeout=1) as response:
            result = json.loads(response.read(16384))
        models = result.get("models", [])
        active = next((m for m in models if m.get("name") == MODEL), None)
        return {"state": "available", "loaded": bool(active),
                "model_ram_bytes": active.get("size") if active else 0}
    except (OSError, ValueError, AttributeError, TypeError):
        return {"state": "unavailable", "model_ram_bytes": None}


def generate_local_text(instructions: str, data: str,
                        max_chars: int = 550) -> str:
    """Synchronous bounded chat with a single small model, no external APIs."""
    last_timings.set({})
    if not 1 <= max_chars <= 1200:
        raise ValueError("Longitud de respuesta de Galancito inválida")
    cfg = settings()
    memory = available_memory_mb()
    pressured = memory is not None and memory < cfg.galancito_memory_reserve_mb
    if pressured:
        # An empty chat with keep_alive=0 unloads an existing model, without
        # asking Ollama to generate or preload it under memory pressure.
        try:
            unload = Request(INTERNAL_URL, data=json.dumps({"model": MODEL, "keep_alive": 0}).encode(),
                             headers={"Content-Type": "application/json"}, method="POST")
            with _opener.open(unload, timeout=1):
                pass
        except (OSError, ValueError):
            pass
        raise RuntimeError("Galancito priorizó la memoria de GALANT")
    if not _slot.acquire(blocking=False):
        last_timings.set({"queue_ms": 0, "busy": True})
        raise RuntimeError("Galancito está ocupado")
    try:
        return _generate(instructions, data, max_chars, cfg)
    finally:
        _slot.release()


def _generate(instructions, data, max_chars, cfg):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": instructions[:MAX_INSTRUCTIONS_CHARS]},
            {"role": "user", "content": data[:MAX_CONTEXT_CHARS]},
        ],
        "stream": False,
        "think": False,  # nunca incluir razonamiento interno en respuestas
        "keep_alive": cfg.galancito_keep_alive,
        "options": {
            "num_ctx": cfg.galancito_num_ctx,
            "num_predict": cfg.galancito_num_predict,
            "num_thread": min(cfg.galancito_num_thread, os.cpu_count() or 1),
            "temperature": 0.2,
        },
    }
    request = Request(
        INTERNAL_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with _opener.open(request, timeout=min(cfg.galancito_timeout_seconds, 8)) as response:
            result = json.loads(response.read(100000).decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        # No incluir mensajes de trabajadores, secretos o direcciones internas en logs.
        raise RuntimeError("Galancito local no disponible") from None
    if not isinstance(result, dict):
        raise RuntimeError("Galancito local devolvió datos inválidos")
    def ms(name):
        value = result.get(name, 0)
        return max(0, value / 1_000_000) if isinstance(value, (float, int)) else 0
    # Ollama's durations are nanoseconds; transport is a residual, not a claim
    # of independently measured server queue time.
    elapsed = (time.perf_counter() - started) * 1000
    last_timings.set({"load_ms": ms("load_duration"), "prompt_ms": ms("prompt_eval_duration"),
                      "generation_ms": ms("eval_duration"), "ollama_total_ms": ms("total_duration"),
                      "transport_ms": max(0, elapsed - ms("total_duration")), "queue_ms": 0,
                      "eval_count": result.get("eval_count", 0)})
    msg = result.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, str):
        raise RuntimeError("Galancito local no devolvió una respuesta")
    # La salida de modelos de razonamiento no se entrega al usuario.
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
    if "<think>" in content.lower() or "</think>" in content.lower():
        raise RuntimeError("Galancito local devolvió razonamiento no público")
    clean = content.strip()
    if not clean:
        raise RuntimeError("Galancito local no devolvió contenido útil")
    return clean[:max_chars]
