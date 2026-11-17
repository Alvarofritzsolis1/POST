"""Qwen3 1.7B on the PRIVATE Ollama Docker network.

Only two allowed callers: Facebook Messenger replies and Red de Obras advising.
Never accepts an arbitrary model, host, URL, or general GALANT business action.
No paid API, no Internet endpoint, no stored prompts and no tool execution.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MODEL = "qwen3:1.7b"
INTERNAL_URL = "http://galancito-ollama:11434/api/chat"
MAX_CONTEXT_CHARS = 3000
MAX_INSTRUCTIONS_CHARS = 3300


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("Ollama no debe redirigir consultas")


_opener = build_opener(NoRedirect)


def generate_local_text(instructions: str, data: str,
                        max_chars: int = 550) -> str:
    """Synchronous bounded chat with a single small model, no external APIs."""
    if not 1 <= max_chars <= 1200:
        raise ValueError("Longitud de respuesta de Galancito inválida")
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": instructions[:MAX_INSTRUCTIONS_CHARS]},
            {"role": "user", "content": data[:MAX_CONTEXT_CHARS]},
        ],
        "stream": False,
        "think": False,  # nunca incluir razonamiento interno en respuestas
        "keep_alive": "20s",
        "options": {
            "num_ctx": 2048,
            "num_predict": 140,
            "temperature": 0.3,
        },
    }
    request = Request(
        INTERNAL_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json"},
    )
    try:
        with _opener.open(request, timeout=24) as response:
            result = json.loads(response.read(100000).decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        # No incluir mensajes de trabajadores, secretos o direcciones internas en logs.
        raise RuntimeError("Galancito local no disponible") from None
    if not isinstance(result, dict):
        raise RuntimeError("Galancito local devolvió datos inválidos")
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
