"""Operaciones Meta para publicaciones: solo el worker utiliza el token de página.

No se abren URL proporcionadas por Meta, nunca se reintenta un envío incierto
y se respeta el único mensaje privado permitido para cada comentario.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import AuditEvent, utcnow
from .network_facebook import meta_http_error
from .network_models import NetworkFacebookPost, NetworkRequirement
from .facebook_publication_models import FacebookPostComment, FacebookPostJob, FacebookPostSnapshot
from .facebook_comment_intelligence import classify_comment

_ID = re.compile(r"[0-9_]{5,120}")
_CURSOR = re.compile(r"[A-Za-z0-9._~-]{1,500}")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_HTTP = build_opener(NoRedirect)


def graph(method: str, node_id: str, edge: str = "", *,
          query: dict | None = None, payload: dict | None = None) -> dict:
    """Allow only numeric IDs and the explicitly supported edges."""
    if not _ID.fullmatch(node_id) or edge not in {"", "comments", "messages", "likes"}:
        raise ValueError("Identificador o recurso de Facebook inválido")
    if method not in {"GET", "POST", "DELETE"}:
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
    try:
        remote = graph("GET", post.post_id, query={
            "fields": "id,message,permalink_url,comments.limit(0).summary(true),reactions.limit(0).summary(true),shares"})
    except HTTPError as exc:
        # Some post types cannot expose reaction/share summaries even with
        # valid Page permissions. Keep comments available in that case.
        if exc.code != 400:
            raise
        remote = graph("GET", post.post_id, query={
            "fields": "id,message,permalink_url"})
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
        query = {"filter": "stream", "limit": 50}
        if cursor:
            query["after"] = cursor
        # Algunas versiones/tareas de Página no exponen picture, user_likes
        # ni can_reply_privately. Degradar solo los campos opcionales.
        variants = (
            "id,message,created_time,from{id,name,picture},can_comment,can_hide,is_hidden,like_count,parent,can_reply_privately,user_likes",
            "id,message,created_time,from,can_comment,can_hide,is_hidden,like_count,parent,can_reply_privately,user_likes",
            "id,message,created_time,from,can_comment,can_hide,is_hidden,like_count,parent,can_reply_privately",
            "id,message,created_time,from,can_comment,can_hide,is_hidden,like_count,parent",
        )
        for i, fields in enumerate(variants):
            query["fields"] = fields
            try:
                batch = graph("GET", post.post_id, "comments", query=query)
                break
            except HTTPError as exc:
                if exc.code != 400 or i == len(variants) - 1:
                    raise
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
            picture = person.get("picture")
            picture_data = picture.get("data") if isinstance(picture, dict) else None
            picture_url = picture_data.get("url") if isinstance(picture_data, dict) else ""
            if isinstance(picture_url, str) and len(picture_url) <= 1000:
                parsed = urlsplit(picture_url)
                host = (parsed.hostname or "").lower()
                if (parsed.scheme == "https" and
                        (host == "facebook.com" or host.endswith(".facebook.com")
                         or host == "fbcdn.net" or host.endswith(".fbcdn.net"))):
                    found.author_picture_url = picture_url
            found.body = str(raw.get("message") or "")[:6000]
            if found.classification_source != "manual":
                found.classification, found.classification_score = classify_comment(found.body)
                found.classification_source = "rules"
            found.posted_at = parsed_time(raw.get("created_time"))
            found.can_comment = raw.get("can_comment") is True
            found.can_hide = raw.get("can_hide") is True
            found.is_hidden = raw.get("is_hidden") is True
            found.like_count = positive_count(raw.get("like_count")) or 0
            found.user_likes = raw.get("user_likes") if type(raw.get("user_likes")) is bool else None
            found.can_reply_privately = (raw.get("can_reply_privately") is True
                                         and (found.private_reply_state or "not_sent") in {"not_sent", "failed"})
            found.fetched_at = now
        paging = batch.get("paging") if isinstance(batch.get("paging"), dict) else {}
        cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
        nxt = cursors.get("after") if paging.get("next") else None
        if not isinstance(nxt, str) or not _CURSOR.fullmatch(nxt) or nxt == cursor:
            break
        cursor = nxt


def _run(job: FacebookPostJob, post: NetworkFacebookPost, session_factory=SessionLocal):
    cfg = settings()
    if job.action == "refresh":
        with session_factory.begin() as db:
            current = db.get(NetworkFacebookPost, post.id)
            if current is None or current.post_id != post.post_id:
                raise ValueError("La publicación cambió antes de sincronizar")
            refresh(db, current)
        return ""
    if job.action == "edit":
        result = graph("POST", post.post_id, payload={"message": job.message})
        if result.get("success") is not True:
            raise ValueError("Meta no confirmó la modificación")
        with session_factory.begin() as db:
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
        recipient = str(result.get("recipient_id") or "")
        # Only the PSID returned by Meta may link to Messenger, never a public
        # commenter ID or a name similarity.
        return (result["message_id"][:140],
                recipient if re.fullmatch(r"[0-9]{5,90}", recipient) else "")
    if job.action in {"like", "unlike"}:
        result = graph("POST" if job.action == "like" else "DELETE",
                       job.comment_id, "likes", payload={} if job.action == "like" else None)
        if result.get("success") is not True:
            raise ValueError("Meta no confirmó la reacción al comentario")
        return ""
    if job.action == "delete_comment":
        result = graph("DELETE", job.comment_id)
        if result.get("success") is not True:
            raise ValueError("Meta no confirmó la eliminación del comentario")
        return ""
    if job.action in {"hide", "unhide"}:
        result = graph("POST", job.comment_id, payload={
            "is_hidden": "true" if job.action == "hide" else "false"})
        if result.get("success") is not True:
            raise ValueError("Meta no confirmó la moderación del comentario")
        return ""
    raise ValueError("Acción de publicación no soportada")


def recover_interrupted_publications(session_factory=SessionLocal) -> int:
    """After a worker restart never resend a possibly delivered mutation."""
    cfg = settings()
    if not cfg.facebook_page_id:
        return 0
    recovered = 0
    with session_factory.begin() as db:
        jobs = list(db.scalars(select(FacebookPostJob).where(
            FacebookPostJob.page_id == cfg.facebook_page_id,
            FacebookPostJob.state == "sending")))
        for job in jobs:
            if job.action == "refresh":
                job.state = "pending"
            else:
                job.state = "uncertain"
                job.last_error = "Worker interrumpido: verifica en Meta antes de repetir."
                if job.action == "private_reply":
                    comment = db.scalar(select(FacebookPostComment).where(
                        FacebookPostComment.post_record_id == job.post_record_id,
                        FacebookPostComment.comment_id == job.comment_id))
                    if comment:
                        comment.private_reply_state = "uncertain"
            job.updated_at = utcnow()
            recovered += 1
    return recovered


_next_periodic_refresh_at = 0.0


def queue_periodic_comment_refresh(session_factory=SessionLocal) -> bool:
    """Recuperación automática acotada, sin afectar la cola de Messenger.

    Se espacia una publicación cada 25s y solo se leen posts recientes.
    Los webhooks siguen siendo la vía principal para novedades.
    """
    global _next_periodic_refresh_at
    now_tick = time.monotonic()
    if now_tick < _next_periodic_refresh_at:
        return False
    _next_periodic_refresh_at = now_tick + 25.0
    cfg = settings()
    if not cfg.facebook_page_token or not _ID.fullmatch(cfg.facebook_page_id or ""):
        return False
    with session_factory.begin() as db:
        now = utcnow()
        rows = db.execute(select(
            NetworkFacebookPost.id, NetworkFacebookPost.org_id,
            NetworkFacebookPost.page_id, NetworkRequirement.created_by,
            FacebookPostSnapshot.checked_at,
        ).join(NetworkRequirement,
               NetworkRequirement.id == NetworkFacebookPost.requirement_id)
          .outerjoin(FacebookPostSnapshot,
                     FacebookPostSnapshot.post_record_id == NetworkFacebookPost.id)
          .where(NetworkFacebookPost.page_id == cfg.facebook_page_id,
                 NetworkFacebookPost.state == "published",
                 NetworkFacebookPost.post_id.isnot(None),
                 NetworkFacebookPost.updated_at >= now - timedelta(days=45),
                 *([NetworkFacebookPost.org_id == cfg.facebook_org_id]
                   if cfg.facebook_org_id else []))
          .order_by(NetworkFacebookPost.updated_at.desc()).limit(40)).all()
        if not rows:
            return False
        current = {item for item in db.scalars(select(FacebookPostJob.post_record_id).where(
            FacebookPostJob.page_id == cfg.facebook_page_id,
            FacebookPostJob.state.in_(["pending", "sending"])))}
        for post_id, org_id, page_id, creator_id, checked_at in rows:
            if post_id in current:
                continue
            if checked_at is not None:
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
                if now - checked_at < timedelta(minutes=15):
                    continue
            db.add(FacebookPostJob(org_id=org_id, page_id=page_id,
                                   post_record_id=post_id, created_by=creator_id,
                                   action="refresh", state="pending"))
            return True
    return False


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
        if job.action in {"public_reply", "private_reply", "hide", "unhide", "delete_comment", "like", "unlike"}:
            comment = db.scalar(select(FacebookPostComment).where(
                FacebookPostComment.post_record_id == post.id,
                FacebookPostComment.comment_id == job.comment_id))
            if not comment:
                job.state, job.last_error = "failed", "Comentario desconocido"
                return True
            if comment.is_deleted:
                job.state, job.last_error = "failed", "El comentario ya fue eliminado"
                return True
            if job.action in {"like", "unlike"} and comment.user_likes is None:
                job.state, job.last_error = "failed", "Meta no confirmó disponibilidad de reacciones"
                return True
            if job.action == "delete_comment" and not comment.can_hide:
                job.state, job.last_error = "failed", "Meta no permitió moderar este comentario"
                return True
            if job.action == "private_reply" and comment.private_reply_state != "pending":
                job.state, job.last_error = "failed", "Respuesta privada ya procesada"
                return True
        job.state, job.updated_at = "sending", utcnow()
        remote_post = post  # ORM object still accessible after commit

    result_id, recipient_psid, error, uncertain = "", "", "", False
    try:
        confirmed = _run(job, remote_post, session_factory)
        if isinstance(confirmed, tuple):
            result_id, recipient_psid = confirmed
        else:
            result_id = confirmed
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
                    comment.messenger_psid = recipient_psid
                    comment.can_reply_privately = False
        if not error:
            if current.action in {"hide", "unhide", "delete_comment", "like", "unlike"}:
                comment = db.scalar(select(FacebookPostComment).where(
                    FacebookPostComment.post_record_id == current.post_record_id,
                    FacebookPostComment.comment_id == current.comment_id))
                if comment:
                    if current.action == "delete_comment":
                        comment.is_deleted = True
                    elif current.action in {"like", "unlike"}:
                        comment.user_likes = current.action == "like"
                        comment.like_count = max(0, comment.like_count + (1 if current.action == "like" else -1))
                    else:
                        comment.is_hidden = current.action == "hide"
            db.add(AuditEvent(org_id=current.org_id, user_id=current.created_by,
                              action="facebook_" + current.action, resource_id=current.post_record_id))
    return True
