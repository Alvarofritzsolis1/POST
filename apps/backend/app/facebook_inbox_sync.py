"""Recover Messenger conversations missed by the signed Meta webhook.

Uses only the Page token inside facebook-publisher. This is a bounded, read-only
Graph API reconciliation; it never replies, runs AI, or overwrites human edits.
Meta permissions and app review still apply. No tokens/PSIDs are written to logs.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import select, text as sql_text

from .db import SessionLocal
from .facebook_crm_models import FacebookChatMessage, FacebookLead
from .models import Organization, utcnow


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_NoRedirect)


def _graph_get(token: str, resource_id: str, edge: str, fields: str, limit: int) -> dict:
    """Only call fixed Meta Graph endpoints with a bearer token (never URL tokens)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,120}", resource_id):
        raise ValueError("Identificador de Messenger inválido")
    if edge not in {"conversations", "messages"}:
        raise ValueError("Ruta de Messenger no permitida")
    query = urlencode({"fields": fields, "limit": limit})
    url = f"https://graph.facebook.com/v27.0/{resource_id}/{edge}?{query}"
    request = Request(url, headers={"Authorization": "Bearer " + token}, method="GET")
    with _OPENER.open(request, timeout=8) as response:
        payload = json.loads(response.read(262145).decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Meta devolvió una respuesta de Messenger inesperada")
    return payload


def _created_at(value: object) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return utcnow()


def sync_page_inbox(*, page_id: str, page_token: str, org_id: str,
                    session_factory=SessionLocal,
                    conversation_limit: int = 15, message_limit: int = 20) -> dict:
    """Import only recent incoming text messages; deduplicate by Page/Messenger ID.

    The Graph requests finish before the database transaction/lock begins.
    Meta may refuse this API for users outside the app's permitted audience.
    """
    if not re.fullmatch(r"[0-9]{5,40}", page_id) or not page_token or not org_id:
        raise ValueError("Página, token u organización de Messenger no configurados")
    if not 1 <= conversation_limit <= 25 or not 1 <= message_limit <= 30:
        raise ValueError("Límite de sincronización inválido")

    conversations = _graph_get(page_token, page_id, "conversations", "id,updated_time",
                               conversation_limit)["data"]
    collected = []
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        cid = str(conversation.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{5,120}", cid):
            continue
        messages = _graph_get(page_token, cid, "messages", "id,message,from,created_time",
                              message_limit)["data"]
        for m in messages:
            if not isinstance(m, dict):
                continue
            mid = str(m.get("id") or "")
            sender = m.get("from") or {}
            psid = str(sender.get("id") or "") if isinstance(sender, dict) else ""
            body = m.get("message")
            if (not re.fullmatch(r"[0-9]{5,90}", psid) or psid == page_id or
                    not isinstance(body, str) or not body.strip() or
                    not 3 <= len(mid) <= 180 or not re.fullmatch(r"[A-Za-z0-9_:-]{3,180}", mid)):
                continue
            collected.append((mid, psid, body.strip()[:3500], _created_at(m.get("created_time"))))

    created_leads, imported = 0, 0
    # Oldest first avoids clobbering a newer last_inbound_at.
    collected.sort(key=lambda x: x[3])
    with session_factory.begin() as db:
        if db.get(Organization, org_id) is None:
            raise ValueError("Organización de Messenger desconocida")
        # Share one lock with webhook writes to prevent duplicate first-contact
        # insertion when a new message arrives during reconciliation.
        if db.bind.dialect.name == "postgresql":
            db.execute(sql_text("SELECT pg_advisory_xact_lock(2075003)"))
        leads = {}
        for mid, psid, body, timestamp in collected:
            if db.scalar(select(FacebookChatMessage.id).where(
                    FacebookChatMessage.page_id == page_id,
                    FacebookChatMessage.remote_id == mid)):
                continue
            lead = leads.get(psid)
            if lead is None:
                lead = db.scalar(select(FacebookLead).where(
                    FacebookLead.org_id == org_id, FacebookLead.page_id == page_id,
                    FacebookLead.psid == psid))
                if lead is None:
                    lead = FacebookLead(org_id=org_id, page_id=page_id, psid=psid)
                    db.add(lead)
                    db.flush()
                    created_leads += 1
                leads[psid] = lead
            previous = lead.last_inbound_at
            if previous is None or (previous.replace(tzinfo=timezone.utc)
                                    if previous.tzinfo is None else previous) < timestamp:
                lead.last_inbound_at = timestamp
            lead.updated_at = utcnow()
            lead.unread = True
            db.add(FacebookChatMessage(
                org_id=org_id, lead_id=lead.id, page_id=page_id, remote_id=mid,
                direction="inbound", state="received", body=body, created_at=timestamp))
            imported += 1
        # No AI follow-up: recovery is not a fresh user-initiated conversation.
    return {"conversations_checked": len(conversations), "messages_imported": imported,
            "new_contacts": created_leads}


def periodic_recovery(stop_event, *, interval_seconds: int = 600) -> None:
    """Lightweight safety net for missed webhooks, isolated from reply worker queue.

    Webhooks remain the real-time source. This thread reconciles a bounded recent
    window every ten minutes, never auto-replies to messages recovered this way.
    """
    import logging
    from urllib.error import URLError
    from .config import settings

    logger = logging.getLogger("galant.facebook.inbox")
    if stop_event.wait(45):
        return
    while not stop_event.is_set():
        cfg = settings()
        if (cfg.facebook_messaging_enabled and cfg.facebook_page_token and
                cfg.facebook_page_id and cfg.facebook_org_id):
            try:
                sync_page_inbox(
                    page_id=cfg.facebook_page_id, page_token=cfg.facebook_page_token,
                    org_id=cfg.facebook_org_id, conversation_limit=10, message_limit=15)
            except HTTPError as exc:
                # Never log exception strings: URLs/request bodies may contain secrets.
                logger.warning("Recuperación Messenger: Meta HTTP %d", exc.code)
            except (URLError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
                logger.warning("Recuperación Messenger: error %s", type(exc).__name__)
            except Exception:
                # The sender loop must not crash if a reconciliation fails.
                logger.error("Recuperación Messenger: error interno sin datos privados")
        if stop_event.wait(interval_seconds):
            return
