"""Recover Messenger conversations missed by the signed Meta webhook.

Uses only the Page token inside facebook-publisher. This is a bounded, read-only
Graph API reconciliation. Fresh messages can queue a response through the normal worker.
Meta permissions and app review still apply. No tokens/PSIDs are written to logs.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import select, text as sql_text

from .config import settings
from .db import SessionLocal
from .facebook_ai import messenger_ai_source
from .facebook_availability_reply import availability_reply
from .facebook_worksite_reply import is_worksite_location, worksite_reply, application_reply, digital_help_reply
from .facebook_crm_models import FacebookChatMessage, FacebookLead
from .facebook_lead_insights import trace_unique_requirement
from .galancito_flow import apply_permission_reply, consented_for, explain_permission, set_permission_request, wants_human
from .galancito_escalation import flag_for_human
from .galancito_intake import declared_relative_start, identity_reply, needs_deeper_response, next_intake_reply, small_talk_reply
from .galancito_memory import (
    apply_messenger_message, approved_trade_aliases, aware, prior_delivered_prompt, profile_facts,
)
from .galancito_triage import private_data, quick_reply, everyday_question_reply
from .galancito_phone import remember_shared_phone, phone_question_when_agreed, redact_mobile_for_intake
from .galancito_links import audit_event
from .galancito_memory import note_profile_sources
from .models import Organization, utcnow
from .network_service import today


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
    params = {"fields": fields, "limit": limit}
    if edge == "conversations":
        params["platform"] = "MESSENGER"
    query = urlencode(params)
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
    page_replies: dict[str, datetime] = {}
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
            timestamp = _created_at(m.get("created_time"))
            if psid == page_id:
                page_replies[cid] = max(page_replies.get(cid, timestamp), timestamp)
                continue
            if (not re.fullmatch(r"[0-9]{5,90}", psid) or psid == page_id or
                    not isinstance(body, str) or not body.strip() or
                    not 3 <= len(mid) <= 180):
                continue
            collected.append((mid, psid, body.strip()[:3500], timestamp, cid))

    created_leads, imported, queued = 0, 0, 0
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
        latest_new = {}
        aliases = approved_trade_aliases(db, org_id)
        for mid, psid, body, timestamp, cid in collected:
            if db.scalar(select(FacebookChatMessage.id).where(
                    FacebookChatMessage.page_id == page_id,
                    FacebookChatMessage.remote_id == mid)):
                continue
            lead = leads.get(psid)
            if lead is None:
                lead = db.scalar(select(FacebookLead).where(
                    FacebookLead.org_id == org_id, FacebookLead.page_id == page_id,
                    FacebookLead.psid == psid).with_for_update())
                if lead is None:
                    lead = FacebookLead(org_id=org_id, page_id=page_id, psid=psid)
                    db.add(lead)
                    db.flush()
                    created_leads += 1
                leads[psid] = lead
            previous = aware(lead.last_inbound_at)
            fresh = previous is None or previous <= timestamp
            if fresh:
                lead.last_inbound_at = timestamp
            lead.updated_at = utcnow()
            lead.unread = True
            prior = prior_delivered_prompt(db, lead, at=timestamp, since=previous if fresh else None)
            decision = apply_permission_reply(lead, body, prior) if fresh else None
            phone_saved = fresh and remember_shared_phone(lead, body, prior, at=timestamp)
            if phone_saved:
                note_profile_sources(lead, ["contact_phone"], source="message", at=timestamp, remote_id=mid)
                audit_event(db, lead, "field_contact_phone", source="message", remote_id=mid)
            if fresh and wants_human(body):
                flag_for_human(db, lead, "Solicitó atención humana" if decision is not False
                               else "Revocó autorización de IA y pidió atención humana")
            elif decision is False:
                flag_for_human(db, lead, "Prefirió atención humana y no autorizó IA")
            changed = False
            intake_body = redact_mobile_for_intake(body) if phone_saved else body
            if decision is None and not private_data(intake_body):
                changed = apply_messenger_message(
                    db, lead, intake_body, prior, remote_id=mid, at=timestamp,
                    historical=not fresh, aliases=aliases,
                )
                if fresh and changed:
                    trace_unique_requirement(db, lead, today=today(), remote_id=mid)
            db.add(FacebookChatMessage(
                org_id=org_id, lead_id=lead.id, page_id=page_id, remote_id=mid,
                direction="inbound", state="received", body=body, created_at=timestamp,
                consent_decision=decision))
            if fresh:
                for pending in db.scalars(select(FacebookChatMessage).where(
                    FacebookChatMessage.lead_id == lead.id,
                    FacebookChatMessage.operator_id.is_(None),
                    FacebookChatMessage.direction == "outbound",
                    FacebookChatMessage.created_at < timestamp,
                    FacebookChatMessage.state.in_(["pending", "ai_pending", "drafting"]),
                )):
                    pending.state = "cancelled"
                preceding = latest_new.get(psid)
                if (preceding and decision is None and not identity_reply(body)
                        and (needs_deeper_response(preceding[1]) or is_worksite_location(preceding[1]))
                        and not (needs_deeper_response(body) or is_worksite_location(body))
                        and declared_relative_start(body) is None):
                    body, prior = preceding[1], preceding[4]
                latest_new[psid] = (lead, body, timestamp, cid, prior, decision,
                                    changed or bool(preceding and preceding[6]))
            imported += 1
        cfg = settings()
        if cfg.facebook_ai_enabled:
            for lead, body, timestamp, cid, prior, decision, changed in latest_new.values():
                last_inbound = lead.last_inbound_at
                if last_inbound and last_inbound.tzinfo is None:
                    last_inbound = last_inbound.replace(tzinfo=timezone.utc)
                if (timestamp < utcnow() - timedelta(hours=24) or
                        last_inbound != timestamp or
                        page_replies.get(cid, datetime.min.replace(tzinfo=timezone.utc)) >= timestamp or
                        (lead.ai_paused and decision is not False and not wants_human(body))
                        or private_data(body)):
                    continue
                # Do not answer if the operator already replied or a send is
                # pending/uncertain. Never replay a thread just because it was synced.
                later = db.scalar(select(FacebookChatMessage.id).where(
                    FacebookChatMessage.lead_id == lead.id,
                    FacebookChatMessage.direction == "outbound",
                    FacebookChatMessage.created_at >= timestamp,
                    FacebookChatMessage.state.in_([
                        "pending", "ai_pending", "drafting", "sending", "sent", "uncertain"]),
                ).limit(1))
                if later:
                    continue
                follow_up = availability_reply(db, lead, body, prior, timestamp)
                if not follow_up and (lead.needs_support or lead.ai_consent_state == "declined"):
                    if wants_human(body):
                        acknowledgement = ("Ya avisé al equipo para que te atienda "
                                           "una persona. No necesitas enviar documentos por aquí.")
                    elif decision is False:
                        acknowledgement = ("Entendido. No usaré IA con tus mensajes. "
                                           "Una persona del equipo podrá ayudarte.")
                    else:
                        continue
                    db.add(FacebookChatMessage(
                        org_id=org_id, lead_id=lead.id, page_id=page_id,
                        direction="outbound", state="pending", body=acknowledgement,
                        ai_generated=False))
                    queued += 1
                    continue
                direct = (follow_up or explain_permission(lead, body, prior)
                          or worksite_reply(db, lead, body, prior)
                          or application_reply(db, lead, body, prior)
                          or digital_help_reply(body, prior)
                          or everyday_question_reply(body))
                if not direct and not lead.needs_support:
                    direct = phone_question_when_agreed(lead, body)
                    if direct:
                        lead.phone_requested_at = utcnow()
                source = "disabled" if direct else messenger_ai_source(db, org_id, cfg)
                if direct:
                    state, reply = "pending", direct
                elif small_talk_reply(body):
                    # Recovered greetings use the same local fast path as the
                    # webhook, even when consent was granted in an older chat.
                    state, reply = "pending", small_talk_reply(body)
                elif consented_for(lead, source):
                    facts = profile_facts(lead, changed=changed)
                    local = next_intake_reply(body, facts, prior)
                    if not local and not needs_deeper_response(body):
                        local = quick_reply(body, known=facts)
                    state, reply = ("pending", local) if local else ("ai_pending", "")
                else:
                    facts = profile_facts(lead, changed=changed)
                    reply = small_talk_reply(body) or next_intake_reply(body, facts, prior)
                    if not reply and source == "disabled":
                        reply = quick_reply(body, known=facts)
                    if not reply and source != "disabled":
                        reply = set_permission_request(
                            lead, source, repeat=lead.ai_consent_provider == source)
                    state = "pending"
                if state == "pending" and not reply:
                    flag_for_human(db, lead,
                                   "Galancito no encontró una respuesta confirmada; revisión humana pendiente")
                    reply = ("No tengo una respuesta confirmada para eso. "
                             "Avisé al equipo para que pueda ayudarte.")
                db.add(FacebookChatMessage(
                    org_id=org_id, lead_id=lead.id, page_id=page_id,
                    direction="outbound", state=state, body=reply,
                    ai_generated=state == "ai_pending"))
                queued += 1
    return {"conversations_checked": len(conversations), "messages_imported": imported,
            "new_contacts": created_leads, "replies_queued": queued}


def periodic_recovery(stop_event, *, interval_seconds: int = 30, startup_delay: int = 5) -> None:
    """Lightweight safety net for missed webhooks, isolated from reply worker queue.

    Webhooks remain the real-time source. This thread reconciles a bounded recent
    window about every 30 seconds, never auto-replies to old messages. Failures
    automatically back off to protect Meta's request quota.
    """
    import logging
    from urllib.error import URLError
    from .config import settings

    logger = logging.getLogger("galant.facebook.inbox")
    if stop_event.wait(startup_delay):
        return
    retry_delay = interval_seconds
    while not stop_event.is_set():
        cfg = settings()
        if (cfg.facebook_messaging_enabled and cfg.facebook_page_token and
                cfg.facebook_page_id and cfg.facebook_org_id):
            try:
                sync_page_inbox(
                    page_id=cfg.facebook_page_id, page_token=cfg.facebook_page_token,
                    org_id=cfg.facebook_org_id, conversation_limit=10, message_limit=15)
                retry_delay = interval_seconds
            except HTTPError as exc:
                # Avoid hammering Meta for expired token, missing permissions or limits.
                logger.warning("Recuperación Messenger: Meta HTTP %d", exc.code)
                retry_delay = min(max(retry_delay * 2, 300), 1800)
            except (URLError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
                logger.warning("Recuperación Messenger: error %s", type(exc).__name__)
                retry_delay = min(max(retry_delay * 2, 180), 900)
            except Exception:
                # The sender loop must not crash if reconciliation fails.
                logger.error("Recuperación Messenger: error interno sin datos privados")
                retry_delay = min(max(retry_delay * 2, 180), 900)
        if stop_event.wait(retry_delay):
            return
