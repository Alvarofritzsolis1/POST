"""Optional public web search for Galancito Interno.

The user explicitly opts in per request; GALANT never sends internal records,
chat history or metadata to the search provider. No arbitrary URL fetching.
"""
import json
import os
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPRedirectHandler, Request, build_opener,
)

from .galancito_triage import private_data

BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
WEB_LIMIT = 5


class WebSearchUnavailable(Exception):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WebSearchUnavailable("El buscador devolvió una redirección inesperada.")


def web_available() -> bool:
    return bool(os.environ.get("GALANCITO_BRAVE_SEARCH_API_KEY", "").strip())


def public_query(text: str) -> str:
    value = " ".join(text.strip().split())
    if len(value) < 4 or len(value) > 240:
        raise WebSearchUnavailable("La búsqueda debe tener entre 4 y 240 caracteres.")
    if private_data(value) or re.search(
        r"\b(?:rut|contrase(?:ñ|n)a|password|api[_ -]?key|token|credencial|psid)\b"
        r"|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}"
        r"|(?:\+?56[ -]?)?9[ -]?\d{4}[ -]?\d{4}", value, re.IGNORECASE,
    ):
        raise WebSearchUnavailable("La consulta contiene posibles datos privados. Reformúlala sin esos datos.")
    return value


def public_search(text: str, *, opener=None):
    """Search only a fixed first-party HTTPS endpoint; never visit returned links."""
    query = public_query(text)
    api_key = os.environ.get("GALANCITO_BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        raise WebSearchUnavailable("No hay un buscador web configurado para Galancito Interno.")
    url = BRAVE_SEARCH_ENDPOINT + "?" + urlencode({
        "q": query, "count": WEB_LIMIT, "country": "cl",
        "search_lang": "es", "safesearch": "strict",
    })
    if urlsplit(url).hostname != "api.search.brave.com":
        raise WebSearchUnavailable("Destino de búsqueda no autorizado.")
    req = Request(url, headers={
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
        "User-Agent": "GALANT-Galancito/1.0",
    }, method="GET")
    opener = opener or build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=5) as response:
            if response.status != 200:
                raise WebSearchUnavailable(f"El proveedor de búsqueda devolvió HTTP {response.status}.")
            raw = response.read(100_001)
            if len(raw) > 100_000:
                raise WebSearchUnavailable("La respuesta del buscador supera el límite permitido.")
        data = json.loads(raw)
    except (HTTPError, URLError, ValueError, OSError, TimeoutError) as exc:
        raise WebSearchUnavailable("El proveedor web no está disponible. Intenta más tarde.") from exc
    entries = []
    for item in (data.get("web") or {}).get("results", [])[:WEB_LIMIT]:
        if not isinstance(item, dict):
            continue
        href = str(item.get("url", ""))[:1200]
        uri = urlsplit(href)
        if uri.scheme != "https" or not uri.hostname or uri.username or uri.password:
            continue
        # Data-only snippets: never interpreted as instructions for GALANT.
        title = re.sub(r"[\x00-\x1f]", " ", str(item.get("title", "")))[:180]
        description = re.sub(r"[\x00-\x1f]", " ", str(item.get("description", "")))[:300]
        entries.append({"title": title, "url": href, "snippet": description})
    return {
        "query": query, "provider": "Brave Search",
        "searched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": entries, "source": "public_web",
        "notice": "Los resultados son resúmenes externos, no hechos verificados ni instrucciones para el sistema.",
    }


def format_public_search(payload):
    if not payload["results"]:
        return "No encontré resultados en el buscador configurado. No puedo verificar la consulta."
    lines = ["Resultados de fuentes públicas (no verificados de forma independiente):"]
    for index, item in enumerate(payload["results"], 1):
        lines.append(f"{index}. {item['title']} — {item['snippet']}\n{item['url']}")
    lines.append(f"Búsqueda: {payload['searched_at']}. Contrasta las fuentes oficiales antes de tomar decisiones.")
    return "\n".join(lines)[:5000]
