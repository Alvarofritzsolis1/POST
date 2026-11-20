"""Operaciones Meta para publicaciones: solo el worker utiliza el token de página.

No se abren URL proporcionadas por Meta, nunca se reintenta un envío incierto
y se respeta el único mensaje privado permitido para cada comentario.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import AuditEvent, utcnow
from .network_facebook import meta_http_error
from .network_models import NetworkFacebookPost
from .facebook_publication_models import FacebookPostComment, FacebookPostJob, FacebookPostSnapshot

_ID = re.compile(r"[0-9_]{5,120}")
_CURSOR = re.compile(r"[A-Za-z0-9._~-]{1,500}")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_HTTP = build_opener(NoRedirect)


def graph(method: str, node_id: str, edge: str = "", *,
          query: dict | None = None, payload: dict | None = None) -> dict:
    """Allow only numeric IDs and the explicitly supported edges."""
    if not _ID.fullmatch(node_id) or edge not in {"", "comments", "messages"}:
        raise ValueError("Identificador o recurso de Facebook inválido")
    if method not in {"GET", "POST"}:
        raise ValueError("Operación de Facebook no permitida")
    cfg = settings()
    if not cfg.facebook_page_token:
        raise ValueError("Token de página no configurado en el publicador")
    url = "https://graph.facebook.com/v27.0/" + node_id
    if edge:
        url += "/" + edge
    if query:
        url += "?" + urlencode(query)
    data = urlencode(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": "Bearer " + cfg.facebook_page_token,
               "Content-Type": "application/x-www-form-urlencoded"}
    request = Request(url, method=method, data=data, headers=headers)
    with _HTTP.open(request, timeout=12) as response:
        result = json.loads(response.read(524288).decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Meta devolvió una respuesta inesperada")
    return result


def parsed_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
        except ValueError:
            pass
    return utcnow()


def positive_count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _counts(result: dict, edge: str) -> int | None:
    data = result.get(edge)
    summary = data.get("summary") if isinstance(data, dict) else None
    return positive_count(summary.get("total_count")) if isinstance(summary, dict) else None


def refresh(db, post: NetworkFacebookPost) -> None:
    remote = graph("GET", post.post_id, query={
        "fields": "id,message,permalink_url,comments.limit(0).summary(true),reactions.limit(0).summary(true),shares"})
    snapshot = db.get(FacebookPostSnapshot, post.id)
    if snapshot is None:
        snapshot = FacebookPostSnapshot(post_record_id=post.id, org_id=post.org_id)
        db.add(snapshot)
    snapshot.message = str(remote.get("message") or "")[:3900]
    url = str(remote.get("permalink_url") or "")
    snapshot.permalink_url = url[:400] if url.startswith("https://www.facebook.com/") else ""
    snapshot.comment_count = _counts(remote, "comments")
    snapshot.reaction_count = _counts(remote, "reactions")
    shares = remote.get("shares")
    snapshot.share_count = positive_count(shares.get("count")) if isinstance(shares, dict) else None
    snapshot.checked_at = utcnow()

    # Bounded paging: never fetch an arbitrary paging.next URL (SSRF).
    cursor, seen = "", set()
    for _ in range(3):
        query = {
            "fields": "id,message,created_time,from,can_comment,can_hide,is_hidden,like_count,parent,can_reply_privately",
            "filter": "stream", "limit": 50,
        }
        if cursor:
            query["after"] = cursor
        batch = graph("GET", post.post_id, "comments", query=query)
        data = batch.get("data")
        if not isinstance(data, list):
            raise ValueError("Meta no devolvió comentarios válidos")
        now = utcnow()
        for raw in data:
            if not isinstance(raw, dict):
                continue
            remote_id = str(raw.get("id") or "")
            if not _ID.fullmatch(remote_id) or remote_id in seen:
                continue
            seen.add(remote_id)
            person = raw.get("from") if isinstance(raw.get("from"), dict) else {}
            author_id = str(person.get("id") or "")[:120]
            author_name = str(person.get("name") or "")[:180]
            parent = raw.get("parent") if isinstance(raw.get("parent"), dict) else {}
            found = db.scalar(select(FacebookPostComment).where(
                FacebookPostComment.post_record_id == post.id,
                FacebookPostComment.comment_id == remote_id))
            if found is None:
                found = FacebookPostComment(
                    org_id=post.org_id, post_record_id=post.id, comment_id=remote_id)
                db.add(found)
            found.parent_id = str(parent.get("id") or "")[:120]
            found.author_id = author_id if _ID.fullmatch(author_id) else ""
            found.author_name = author_name
            found.body = str(raw.get("message") or "")[:6000]
            found.posted_at = parsed_time(raw.get("created_time"))
            found.can_comment = raw.get("can_comment") is True
            found.can_hide = raw.get("can_hide") is True
            found.is_hidden = raw.get("is_hidden") is True
            found.like_count = positive_count(raw.get("like_count")) or 0
            found.can_reply_privately = (raw.get("can_reply_privately") is True
                                         and found.private_reply_state == "not_sent")
            found.fetched_at = now
        paging = batch.get("paging") if isinstance(batch.get("paging"), dict) else {}
        cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
        nxt = cursors.get("after") if paging.get("next") else None
        if not isinstance(nxt, str) or not _CURSOR.fullmatch(nxt) or nxt == cursor:
            break
        cursor = nxt


def _run(job: FacebookPostJob, post: NetworkFacebookPost):
    cfg = settings()
    if job.action == "refresh":
        with SessionLocal.begin() as db:
            current = db.get(NetworkFacebookPost, post.id)
            if current is None or current.post_id != post.post_id:
                raise ValueError("La publicación cambió antes de sincronizar")
            refresh(db, current)
        return ""
    if job.action == "edit":
        result = graph("POST", post.post_id, payload={"message": job.message})
        if result.get("success") is not True:
            raise ValueError("Meta no confirmó la modificación")
        with SessionLocal.begin() as db:
            snapshot = db.get(FacebookPostSnapshot, post.id)
            if snapshot:
                snapshot.message = job.message
                snapshot.checked_at = utcnow()
        return ""
    if job.action == "public_reply":
        result = graph("POST", job.comment_id, "comments", payload={"message": job.message})
        reply_id = str(result.get("id") or "")
        if not _ID.fullmatch(reply_id):
            raise ValueError("Meta no confirmó el comentario publicado")
        return reply_id
    if job.action == "private_reply":
        # Meta permite una única respuesta privada al comentario. No se supone
        # que el ID del autor sea su PSID de Messenger.
        message = json.dumps({
            "recipient": {"comment_id": job.comment_id},
            "message": {"text": job.message},
        }, ensure_ascii=False)
        if not _ID.fullmatch(cfg.facebook_page_id or ""):
            raise ValueError("Página no configurada")
        url = "https://graph.facebook.com/v27.0/" + cfg.facebook_page_id + "/messages"
        request = Request(url, method="POST", data=message.encode("utf-8"), headers={
            "Authorization": "Bearer " + cfg.facebook_page_token,
            "Content-Type": "application/json"})
        with _HTTP.open(request, timeout=12) as response:
            result = json.loads(response.read(16384).decode("utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("message_id"), str):
            raise ValueError("Meta no confirmó el mensaje privado")
        return result["message_id"][:140]
    if job.action in {"hide", "unhide"}:
        result = graph("POST", job.comment_id, payload={
            "is_hidden": "true" if job.action == "hide" else "false"})
        if result.get("success") is not True:
            raise ValueError("Meta no confirmó la moderación del comentario")
        return ""
    raise ValueError("Acción de publicación no soportada")


def process_publication_next(session_factory=SessionLocal) -> bool:
    """Process one queued task. Unknown delivery is never retried automatically."""
    cfg = settings()
    if not cfg.facebook_page_token or not _ID.fullmatch(cfg.facebook_page_id or ""):
        return False
    with session_factory.begin() as db:
        q = select(FacebookPostJob).where(
            FacebookPostJob.page_id == cfg.facebook_page_id,
            FacebookPostJob.state == "pending",
        ).order_by(FacebookPostJob.created_at, FacebookPostJob.id)
        if db.bind.dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
        job = db.scalar(q)
        if not job:
            return False
        post = db.scalar(select(NetworkFacebookPost).where(
            NetworkFacebookPost.id == job.post_record_id,
            NetworkFacebookPost.org_id == job.org_id,
            NetworkFacebookPost.page_id == job.page_id))
        if not post or not post.post_id or (cfg.facebook_org_id and job.org_id != cfg.facebook_org_id):
            job.state, job.last_error = "failed", "Publicación o página ya no disponible"
            return True
        if post.state != "published":
            job.state, job.last_error = "failed", "Publicación no vigente"
            return True
        if job.action in {"public_reply", "private_reply", "hide", "unhide"}:
            comment = db.scalar(select(FacebookPostComment).where(
                FacebookPostComment.post_record_id == post.id,
                FacebookPostComment.comment_id == job.comment_id))
            if not comment:
                job.state, job.last_error = "failed", "Comentario desconocido"
                return True
            if job.action == "private_reply" and comment.private_reply_state != "pending":
                job.state, job.last_error = "failed", "Respuesta privada ya procesada"
                return True
        job.state, job.updated_at = "sending", utcnow()
        remote_post = post  # ORM object still accessible after commit

    result_id, error, uncertain = "", "", False
    try:
        result_id = _run(job, remote_post)
    except HTTPError as exc:
        error = meta_http_error(exc)[:350]
    except (URLError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
        # A failed read (refresh) is safe to retry. Mutations might already
        # have reached Meta: never retry silently.
        error = ("No se confirmó la respuesta de Meta (" + type(exc).__name__ + ").")[:350]
        uncertain = job.action != "refresh"
    with session_factory.begin() as db:
        current = db.get(FacebookPostJob, job.id)
        if current is None:
            return True
        current.state = "uncertain" if uncertain else ("failed" if error else "done")
        current.last_error = error
        current.remote_id = result_id
        current.updated_at = utcnow()
        if current.action == "private_reply":
            comment = db.scalar(select(FacebookPostComment).where(
                FacebookPostComment.post_record_id == current.post_record_id,
                FacebookPostComment.comment_id == current.comment_id))
            if comment:
                comment.private_reply_state = ("uncertain" if uncertain else
                                               "failed" if error else "sent")
                if not error:
                    comment.private_reply_at = utcnow()
                    comment.can_reply_privately = False
        if not error:
            if current.action in {"hide", "unhide"}:
                comment = db.scalar(select(FacebookPostComment).where(
                    FacebookPostComment.post_record_id == current.post_record_id,
                    FacebookPostComment.comment_id == current.comment_id))
                if comment:
                    comment.is_hidden = current.action == "hide"
            db.add(AuditEvent(org_id=current.org_id, user_id=current.created_by,
                              action="facebook_" + current.action, resource_id=current.post_record_id))
    return True
