"""Regression cases from the Red de Obras audit, using synthetic records only."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.facebook_crm_models import FacebookChatMessage, FacebookLead
from app.facebook_publication_models import FacebookPostJob
from app.facebook_refresh_policy import automatic_refresh_allowed, refresh_retry_allowed
from app.galancito_knowledge_models import AssistantRun
from app.models import User, utcnow
from app.network_models import NetworkFacebookPost
from test_facebook_publications import created, PAGE
from test_network import network


@pytest.mark.parametrize("status", [401, 403])
def test_http_auth_failure_without_meta_code_requires_manual_repair(status):
    now = utcnow()
    error = f"Meta rechazó la solicitud (HTTP {status})."
    assert not refresh_retry_allowed("failed", error, now - timedelta(days=10), now)
    assert refresh_retry_allowed("done", "", now, now)


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_transient_http_errors_remain_retryable_after_cooldown(status):
    now = utcnow()
    error = f"Meta rechazó la solicitud (HTTP {status})."
    assert not refresh_retry_allowed("failed", error, now - timedelta(seconds=25), now)
    assert refresh_retry_allowed("failed", error, now - timedelta(minutes=15), now)


def test_durable_auth_block_is_reset_by_successful_manual_refresh(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    now = utcnow()
    with n["Session"].begin() as db:
        post = db.get(NetworkFacebookPost, record)
        creator = db.scalar(select(User.id).where(User.org_id == post.org_id))
        db.add(FacebookPostJob(org_id=post.org_id, page_id=PAGE,
                              post_record_id=record, created_by=creator,
                              action="refresh", state="failed",
                              last_error="Meta rechazó la solicitud (HTTP 401).",
                              updated_at=now - timedelta(days=1)))
        db.flush()
        assert not automatic_refresh_allowed(db, record, post.org_id, PAGE, now)
        db.add(FacebookPostJob(org_id=post.org_id, page_id=PAGE,
                              post_record_id=record, created_by=creator,
                              action="refresh", state="done", updated_at=now))
        db.flush()
        assert automatic_refresh_allowed(db, record, post.org_id, PAGE, now)


def test_export_reports_operational_failures_and_messenger_coverage(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    with n["Session"].begin() as db:
        post = db.get(NetworkFacebookPost, record)
        creator = db.scalar(select(User.id).where(User.org_id == post.org_id))
        lead = FacebookLead(org_id=post.org_id, page_id=PAGE,
                            psid="diagnostic-synthetic", ai_paused=True, needs_support=True)
        db.add(lead)
        db.flush()
        ids = {}
        for label, direction, state in [("in", "inbound", "received"),
                                         ("sent", "outbound", "sent"),
                                         ("failed", "outbound", "failed")]:
            message = FacebookChatMessage(org_id=post.org_id, page_id=PAGE,
                                          lead_id=lead.id, direction=direction,
                                          state=state, body="Synthetic audit")
            db.add(message)
            db.flush()
            ids[label] = message.id
        for action in ("refresh", "edit"):
            db.add(FacebookPostJob(org_id=post.org_id, page_id=PAGE,
                                  post_record_id=record, created_by=creator,
                                  action=action, state="failed"))
        # Four links: delivered, failed, wrong direction, and outside the export.
        for label, ident in [*ids.items(), ("unavailable", str(uuid4()))]:
            db.add(AssistantRun(org_id=post.org_id, channel="messenger",
                                source="fallback", elapsed_ms=10,
                                timings={"trace_version": 2, "outbound_message_id": ident}))
        db.add(AssistantRun(org_id=post.org_id, channel="messenger", source="local",
                            elapsed_ms=10, timings={}))
        db.add(AssistantRun(org_id=post.org_id, channel="red_obras", source="fallback",
                            elapsed_ms=10, timings={"trace_version": 2}))
    response = n["admin"].get("/api/v1/admin/ai/red-obras/feedback-export")
    assert response.status_code == 200, response.text
    report = response.json()
    coverage = report["coverage"]
    assert coverage["messenger_runs"] == 5
    assert coverage["runs_with_trace_v2"] == 4
    assert coverage["runs_linked_to_exported_message"] == 2
    assert coverage["runs_linked_to_sent_message"] == 1
    findings = report["findings"]
    assert findings["failed_outbound_messages"] == 1
    assert findings["failed_publication_jobs"] == 2
    assert findings["failed_publication_refreshes"] == 1
    assert findings["leads_ai_paused"] == findings["leads_needing_support"] == 1
    assert findings["messenger_runs_with_fallback"] == 4
    assert findings["red_obras_runs_with_fallback"] == 1
    assert findings["runs_without_message_link"] == 1
    assert findings["runs_with_unavailable_message_link"] == 2
    assert "galancito_ai_model" in report["runtime_configuration"]
