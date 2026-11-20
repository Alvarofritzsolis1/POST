"""Facebook publications: synthetic Meta, no real messages and no real token."""
from datetime import timedelta
import hashlib
import hmac
from io import BytesIO
import json

from sqlalchemy import select

from app.config import settings
from app.facebook_publication_models import FacebookPostComment, FacebookPostJob
from app.facebook_publication_worker import (
    process_publication_next, recover_interrupted_publications,
)
from app.models import User, utcnow
from app.network_models import NetworkFacebookPost, NetworkRequirement
from test_facebook_crm import enable_messaging
from test_network import network, request_body


PAGE = "1489275590928529"
POST = PAGE + "_12345678"
COMMENT = "12345678_987654321"


def created(network, monkeypatch):
    n = network
    org = enable_messaging(n, monkeypatch)
    response = n["send"](n["a"], "/requirements", request_body(n, items=1))
    assert response.status_code == 201, response.text
    req_id = response.json()["id"]
    with n["Session"].begin() as db:
        post = NetworkFacebookPost(
            org_id=org, requirement_id=req_id, page_id=PAGE, post_id=POST,
            action="publish", state="published", target_version=1)
        db.add(post)
        db.flush()
        record = post.id
    return n, record, req_id


def meta_result(method, node_id, edge="", *, query=None, payload=None):
    if method == "GET" and node_id == POST and not edge:
        return {"id": POST, "message": "Buscamos gasfíteres",
                "permalink_url": "https://www.facebook.com/" + POST,
                "comments": {"summary": {"total_count": 1}},
                "reactions": {"summary": {"total_count": 3}},
                "shares": {"count": 2}}
    if method == "GET" and node_id == POST and edge == "comments":
        return {"data": [{
            "id": COMMENT, "message": "Soy gasfíter, tengo cuadrilla",
            "created_time": utcnow().isoformat(),
            "from": {"id": "9876543210001", "name": "Juan Pérez"},
            "can_comment": True, "can_hide": True,
            "can_reply_privately": True, "is_hidden": False, "like_count": 2,
        }]}
    if method == "POST" and node_id == COMMENT and edge == "comments":
        assert payload["message"] == "Hola, ¿qué experiencia tienes?"
        return {"id": "12345678_989898"}
    if method == "POST" and node_id == POST and edge == "":
        return {"success": True}
    if method == "POST" and node_id == COMMENT and edge == "":
        return {"success": True}
    raise AssertionError("Unexpected Meta call: " + str((method, node_id, edge)))


def test_publications_admin_and_scope(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    url = "/facebook/publications/" + record
    allowed = n["send"](n["admin"], url, method="GET")
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["checked_at"] is None
    assert n["send"](n["a"], url, method="GET").status_code == 403
    # Never expose the Page token in the response.
    assert "synthetic-page-token" not in allowed.text
    assert n["send"](n["admin"], "/facebook/publications/invalid/refresh", {},
                     method="POST").status_code == 404


def test_comment_names_public_reply_and_private_window(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    monkeypatch.setattr("app.facebook_publication_worker.graph", meta_result)
    base = "/facebook/publications/" + record
    queued = n["send"](n["admin"], base + "/refresh", {})
    assert queued.status_code == 202, queued.text
    assert process_publication_next(n["Session"]) is True
    detail = n["send"](n["admin"], base, method="GET").json()
    assert detail["comment_count"] == 1
    assert detail["reaction_count"] == 3
    assert detail["share_count"] == 2
    assert detail["comments"][0]["author_name"] == "Juan Pérez"
    assert detail["comments"][0]["can_private_reply"] is True
    comment_id = detail["comments"][0]["id"]
    reply = n["send"](n["admin"], base + "/comments/" + comment_id + "/reply",
                      {"message": "Hola, ¿qué experiencia tienes?"})
    assert reply.status_code == 202, reply.text
    assert process_publication_next(n["Session"]) is True
    detail = n["send"](n["admin"], base, method="GET").json()
    assert any(x["action"] == "public_reply" and x["state"] == "done"
               for x in detail["jobs"])
    assert n["send"](n["a"], base + "/comments/" + comment_id + "/private-reply",
                     {"message": "Hola"}).status_code == 403

    # Meta alone allows one private reply to a comment; GALANT reserves it
    # durably before the network request to block double-click/concurrency.
    first = n["send"](n["admin"], base + "/comments/" + comment_id + "/private-reply",
                      {"message": "Gracias, ¿quieres conversar por Messenger?"})
    assert first.status_code == 202, first.text
    repeated = n["send"](n["admin"], base + "/comments/" + comment_id + "/private-reply",
                         {"message": "Repetir"})
    assert repeated.status_code == 409
    with n["Session"].begin() as db:
        item = db.scalar(select(FacebookPostComment).where(
            FacebookPostComment.post_record_id == record))
        assert item.private_reply_state == "pending"


def test_private_reply_sent_then_messenger_needs_user_response(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    monkeypatch.setattr("app.facebook_publication_worker.graph", meta_result)
    base = "/facebook/publications/" + record
    assert n["send"](n["admin"], base + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    comment_id = n["send"](n["admin"], base, method="GET").json()["comments"][0]["id"]
    assert n["send"](n["admin"], base + "/comments/" + comment_id + "/private-reply",
                     {"message": "Gracias. ¿Conversamos por Messenger?"}).status_code == 202

    class SyntheticHttp:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def read(self, *_):
            return json.dumps({"message_id": "mid-synthetic-private"}).encode()
    def fake_open(request, timeout):
        assert request.full_url.endswith(PAGE + "/messages")
        body = json.loads(request.data)
        assert body["recipient"] == {"comment_id": COMMENT}
        assert "Messenger" in body["message"]["text"]
        return SyntheticHttp()
    monkeypatch.setattr("app.facebook_publication_worker._HTTP.open", fake_open)
    assert process_publication_next(n["Session"]) is True
    view = n["send"](n["admin"], base, method="GET").json()
    assert view["comments"][0]["private_reply_state"] == "sent"
    assert not view["comments"][0]["can_private_reply"]
    assert not any("psid" in key for key in view["comments"][0])
    assert n["send"](n["admin"], base + "/comments/" + comment_id + "/private-reply",
                     {"message": "Repetir"}).status_code == 409


def test_meta_moderation_edit_and_deletion_request(network, monkeypatch):
    n, record, req_id = created(network, monkeypatch)
    monkeypatch.setattr("app.facebook_publication_worker.graph", meta_result)
    base = "/facebook/publications/" + record
    assert n["send"](n["admin"], base + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    comment_id = n["send"](n["admin"], base, method="GET").json()["comments"][0]["id"]
    assert n["send"](n["admin"], base + "/comments/" + comment_id + "/hide", {}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    assert n["send"](n["admin"], base, method="GET").json()["comments"][0]["is_hidden"] is True
    assert n["send"](n["admin"], base + "/edit",
                     {"message": "Convocatoria actualizada"}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    assert n["send"](n["admin"], base, method="GET").json()["message"] == "Convocatoria actualizada"
    assert n["send"](n["admin"], base, method="DELETE").status_code == 202
    with n["Session"].begin() as db:
        req = db.get(NetworkRequirement, req_id)
        post = db.get(NetworkFacebookPost, record)
        assert req.publish_to_facebook is False
        assert post.action == "delete"
        assert post.state == "pending"
    assert n["send"](n["admin"], base + "/refresh", {}).status_code == 409


def test_worker_does_not_repeat_ambiguous_outreach(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    monkeypatch.setattr("app.facebook_publication_worker.graph", meta_result)
    base = "/facebook/publications/" + record
    assert n["send"](n["admin"], base + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    comment_id = n["send"](n["admin"], base, method="GET").json()["comments"][0]["id"]
    assert n["send"](n["admin"], base + "/comments/" + comment_id + "/private-reply",
                     {"message": "Te escribimos"}).status_code == 202
    with n["Session"].begin() as db:
        job = db.scalar(select(FacebookPostJob).where(
            FacebookPostJob.post_record_id == record,
            FacebookPostJob.action == "private_reply"))
        job.state = "sending"  # Simulates process dying after a Meta call.
    assert recover_interrupted_publications(n["Session"]) == 1
    assert process_publication_next(n["Session"]) is False
    detail = n["send"](n["admin"], base, method="GET").json()
    assert detail["comments"][0]["private_reply_state"] == "uncertain"
    assert detail["comments"][0]["can_private_reply"] is False



def test_signed_feed_webhook_queues_comment_refresh_and_deduplicates(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    payload = {
        "object": "page",
        "entry": [{
            "id": PAGE,
            "changes": [{
                "field": "feed",
                "value": {
                    "item": "comment", "verb": "add",
                    "post_id": POST, "comment_id": COMMENT,
                    "from": {"id": "9876543210001", "name": "Juan Pérez"},
                },
            }],
        }],
    }
    raw = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(
        b"synthetic-test-only-meta-secret", raw, hashlib.sha256).hexdigest()
    route = "/api/v1/network/facebook/webhook"
    response = n["admin"].post(route, content=raw, headers={
        "X-Hub-Signature-256": sig, "Content-Type": "application/json"})
    assert response.status_code == 200, response.text
    response2 = n["admin"].post(route, content=raw, headers={
        "X-Hub-Signature-256": sig, "Content-Type": "application/json"})
    assert response2.status_code == 200
    with n["Session"].begin() as db:
        jobs = list(db.scalars(select(FacebookPostJob).where(
            FacebookPostJob.post_record_id == record)))
        assert len(jobs) == 1
        assert jobs[0].action == "refresh"
        # A public comment must never create a Messenger contact.
        from app.facebook_crm_models import FacebookLead
        assert not list(db.scalars(select(FacebookLead)))
    monkeypatch.setattr("app.facebook_publication_worker.graph", meta_result)
    assert process_publication_next(n["Session"])
    view = n["send"](n["admin"], "/facebook/publications/" + record,
                     method="GET").json()
    assert view["comments"][0]["author_name"] == "Juan Pérez"
