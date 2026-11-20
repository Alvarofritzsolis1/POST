"""Red de Obras: bandeja y moderación manual con Meta sintético."""
from sqlalchemy import select

from app.facebook_publication_models import FacebookPostJob
from app.facebook_publication_worker import process_publication_next
from app.models import utcnow
from test_facebook_publications import COMMENT, PAGE, POST, created, meta_result
from test_network import network


def test_manual_inbox_classification_review_and_reply(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    monkeypatch.setattr("app.facebook_publication_worker.graph", meta_result)
    path = "/facebook/publications/" + record
    assert n["send"](n["admin"], path + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"]) is True

    inbox = n["send"](n["admin"], "/facebook/publications/interactions/inbox", method="GET")
    assert inbox.status_code == 200, inbox.text
    assert n["send"](n["a"], "/facebook/publications/interactions/inbox", method="GET").status_code == 403
    row = inbox.json()["rows"][0]
    assert row["author_name"] == "Juan Pérez"
    assert row["classification"] == "interested"
    assert row["classification_source"] == "rules"
    assert row["can_reply"] is True
    assert row["lead_id"] is None  # un comentario NO abre Messenger
    assert row["history"] == []
    assert inbox.json()["mode"] == "manual"

    cid = row["id"]
    result = n["send"](n["admin"], path + "/comments/" + cid + "/review",
                       {"review_state": "review", "classification": "question"}, method="PATCH")
    assert result.status_code == 200, result.text
    assert result.json()["classification_source"] == "manual"
    assert n["send"](n["admin"], path + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    updated = n["send"](n["admin"], "/facebook/publications/interactions/inbox", method="GET").json()["rows"][0]
    assert updated["classification"] == "question"
    assert updated["review_state"] == "review"
    assert updated["classification_source"] == "manual"

    assert n["send"](n["admin"], path + "/comments/" + cid + "/review",
                     {"review_state": "unknown"}, method="PATCH").status_code == 422
    assert n["send"](n["a"], path + "/comments/" + cid + "/review",
                     {"review_state": "handled"}, method="PATCH").status_code == 403
    assert n["send"](n["admin"], path + "/comments/" + cid + "/reply",
                     {"message": "Hola, ¿qué experiencia tienes?"}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    after = n["send"](n["admin"], "/facebook/publications/interactions/inbox", method="GET").json()["rows"][0]
    assert after["history"][0]["action"] == "public_reply"
    assert after["history"][0]["state"] == "done"


def test_comment_delete_is_explicit_and_confirmed(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    calls = []

    def graph(method, node_id, edge="", *, query=None, payload=None):
        if method == "DELETE":
            calls.append((method, node_id))
            return {"success": True}
        return meta_result(method, node_id, edge, query=query, payload=payload)

    monkeypatch.setattr("app.facebook_publication_worker.graph", graph)
    path = "/facebook/publications/" + record
    assert n["send"](n["admin"], path + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    cid = n["send"](n["admin"], path, method="GET").json()["comments"][0]["id"]
    delete_url = path + "/comments/" + cid
    assert n["send"](n["a"], delete_url, method="DELETE").status_code == 403
    result = n["send"](n["admin"], delete_url, method="DELETE")
    assert result.status_code == 202, result.text
    with n["Session"].begin() as db:
        job = db.scalar(select(FacebookPostJob).where(FacebookPostJob.action == "delete_comment"))
        assert job and job.state == "pending"
    assert calls == []  # HTTP solo lo realiza el worker
    assert process_publication_next(n["Session"]) is True
    assert calls == [("DELETE", COMMENT)]
    after = n["send"](n["admin"], path, method="GET").json()["comments"][0]
    assert after["is_deleted"] is True
    assert after["can_delete"] is False
    assert after["can_reply"] is False
    assert n["send"](n["admin"], delete_url, method="DELETE").status_code == 409


def test_comment_photo_is_optional_and_whitelisted(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    def fake(method, node_id, edge="", *, query=None, payload=None):
        response = meta_result(method, node_id, edge, query=query, payload=payload)
        if method == "GET" and node_id == POST and edge == "comments":
            response["data"][0]["from"]["picture"] = {
                "data": {"url": "https://scontent.xx.fbcdn.net/safe-profile.jpg"}}
        return response

    monkeypatch.setattr("app.facebook_publication_worker.graph", fake)
    path = "/facebook/publications/" + record
    assert n["send"](n["admin"], path + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    row = n["send"](n["admin"], "/facebook/publications/interactions/inbox", method="GET").json()["rows"][0]
    assert row["author_picture_url"].startswith("https://scontent.xx.fbcdn.net")

    def unsafe(method, node_id, edge="", *, query=None, payload=None):
        response = fake(method, node_id, edge, query=query, payload=payload)
        if method == "GET" and edge == "comments":
            response["data"][0]["from"]["picture"]["data"]["url"] = "https://fbcdn.net.evil.invalid/fake.jpg"
        return response
    monkeypatch.setattr("app.facebook_publication_worker.graph", unsafe)
    assert n["send"](n["admin"], path + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    row = n["send"](n["admin"], "/facebook/publications/interactions/inbox", method="GET").json()["rows"][0]
    assert row["author_picture_url"].startswith("https://scontent.xx.fbcdn.net")


def test_suggest_never_sends_and_requires_review(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    monkeypatch.setattr("app.facebook_publication_worker.graph", meta_result)
    monkeypatch.setattr("app.ai_gateway.orchestrated_text", lambda *args, **kwargs: None)
    path = "/facebook/publications/" + record
    assert n["send"](n["admin"], path + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"]) is True
    cid = n["send"](n["admin"], path, method="GET").json()["comments"][0]["id"]
    suggested = n["send"](n["admin"], path + "/comments/" + cid + "/suggest", {})
    assert suggested.status_code == 200, suggested.text
    assert suggested.json()["requires_review"] is True
    assert suggested.json()["source"] == "template"
    assert suggested.json()["draft"]
    with n["Session"].begin() as db:
        jobs = list(db.scalars(select(FacebookPostJob).where(
            FacebookPostJob.action.in_(["public_reply", "private_reply"]))))
        assert jobs == []


def test_batch_refresh_creates_no_outbound_messages(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    request = n["send"](n["admin"], "/facebook/publications/interactions/refresh", {})
    assert request.status_code == 202, request.text
    assert request.json()["queued"] == 1
    second = n["send"](n["admin"], "/facebook/publications/interactions/refresh", {})
    assert second.json()["queued"] == 0
    with n["Session"].begin() as db:
        jobs = list(db.scalars(select(FacebookPostJob)))
        assert len(jobs) == 1
        assert jobs[0].action == "refresh"


def test_page_like_requires_meta_user_likes_and_worker_confirmation(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    sent = []
    def graph(method, node_id, edge="", *, query=None, payload=None):
        if edge == "likes":
            sent.append((method, node_id, edge))
            return {"success": True}
        response = meta_result(method, node_id, edge, query=query, payload=payload)
        if method == "GET" and edge == "comments":
            response["data"][0]["user_likes"] = False if not sent else True
        return response

    monkeypatch.setattr("app.facebook_publication_worker.graph", graph)
    base = "/facebook/publications/" + record
    assert n["send"](n["admin"], base + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"])
    row = n["send"](n["admin"], base, method="GET").json()["comments"][0]
    assert row["can_like"] and row["user_likes"] is False
    like = base + "/comments/" + row["id"] + "/like"
    assert n["send"](n["a"], like, {}).status_code == 403
    assert n["send"](n["admin"], like, {}).status_code == 202
    assert sent == []
    assert process_publication_next(n["Session"])
    assert sent == [("POST", COMMENT, "likes")]
    view = n["send"](n["admin"], base, method="GET").json()["comments"][0]
    assert view["user_likes"] is True
    assert n["send"](n["admin"], like, {}).status_code == 409
    unlike = base + "/comments/" + row["id"] + "/unlike"
    assert n["send"](n["admin"], unlike, {}).status_code == 202
    assert process_publication_next(n["Session"])
    assert sent[-1] == ("DELETE", COMMENT, "likes")
    assert n["send"](n["admin"], base, method="GET").json()["comments"][0]["user_likes"] is False


def test_optional_ai_classification_never_sends_and_preserves_manual_override(network, monkeypatch):
    n, record, _ = created(network, monkeypatch)
    monkeypatch.setattr("app.facebook_publication_worker.graph", meta_result)
    base = "/facebook/publications/" + record
    assert n["send"](n["admin"], base + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"])
    row = n["send"](n["admin"], base, method="GET").json()["comments"][0]
    path = base + "/comments/" + row["id"]
    from app import ai_gateway, galancito_runtime
    monkeypatch.setattr(ai_gateway, "orchestrated_text", lambda *args, **kwargs: '{"category":"negative"}')
    monkeypatch.setattr(galancito_runtime, "infer", lambda db, callback, **kwargs: callback())
    result = n["send"](n["admin"], path + "/analyze", {})
    assert result.status_code == 200, result.text
    # AI no puede anular una señal de interés laboral explícita por alta confianza de reglas.
    assert result.json()["classification"] == "interested"
    assert result.json()["source"] == "ai"
    assert result.json()["requires_review"] is True
    with n["Session"].begin() as db:
        assert list(db.scalars(select(FacebookPostJob).where(
            FacebookPostJob.action.in_(["public_reply", "private_reply"])))) == []
    assert n["send"](n["admin"], path + "/review", {
        "review_state": "handled", "classification": "question"
    }, method="PATCH").status_code == 200
    after = n["send"](n["admin"], path + "/analyze", {})
    assert after.status_code == 200
    assert after.json()["classification"] == "question"
    assert after.json()["source"] == "manual"


def test_comment_signal_rules_distinguish_interest_and_ambiguous():
    from app.facebook_comment_intelligence import classify_comment
    assert classify_comment("ola soi carpintreo, busco pega")[0] == "interested"
    assert classify_comment("tengo cuadrilla y hago gasfitería")[0] == "interested"
    assert classify_comment("hola")[0] == "ambiguous"
    assert classify_comment("excelente proyecto")[0] == "positive"
    assert classify_comment("no pagan")[0] == "negative"
    assert classify_comment("¿Dónde publican los requisitos?")[0] == "question"


def test_interaction_profile_matches_only_explicit_trades(network, monkeypatch):
    n, record, req_id = created(network, monkeypatch)
    monkeypatch.setattr("app.facebook_publication_worker.graph", meta_result)
    base = "/facebook/publications/" + record
    assert n["send"](n["admin"], base + "/refresh", {}).status_code == 202
    assert process_publication_next(n["Session"])
    rows = n["send"](n["admin"], "/facebook/publications/interactions/inbox", method="GET").json()["rows"]
    row = rows[0]
    assert row["origin_requirement_id"] == req_id
    assert "Gasfitería" in row["declared_profile"]["trades"]
    assert any(need["id"] == req_id for need in row["potential_needs"])
    assert row["is_page_author"] is False


def test_public_profile_does_not_infer_trade_from_publication():
    from app.facebook_comment_intelligence import declared_profile
    assert declared_profile("hola")["trades"] == []
    assert declared_profile("me interesa")["trades"] == []
    profile = declared_profile("Soy carpintero y también hago pintura, somos 4")
    assert "Carpintería" in profile["trades"]
    assert "Pintura" in profile["trades"]
    assert profile["team_size_declared"] == 4
