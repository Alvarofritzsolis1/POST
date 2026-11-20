"""Administración de Facebook desde GALANT sin exponer el token de Meta.

Los GET leen snapshots de la base local. Los POST solo encolan acciones para
el worker autorizado; los estados son confirmaciones reales, no optimistas.
"""
from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .facebook_publication_models import FacebookPostComment, FacebookPostJob, FacebookPostSnapshot
from .facebook_crm_models import FacebookLead
from .models import AuditEvent, User, utcnow
from .network_models import NetworkFacebookPost, NetworkRequirement
from .security import administrator

router = APIRouter(prefix="/api/v1/network/facebook/publications", tags=["Facebook · publicaciones"])


class Body(BaseModel):
    message: str = Field(min_length=1, max_length=3900)

    def text(self) -> str:
        clean = self.message.strip()
        if not clean:
            raise HTTPException(422, "Escribe un mensaje")
        return clean


def _post(db: Session, user: User, record_id: str, *, allow_failed=False):
    cfg = settings()
    post = db.scalar(select(NetworkFacebookPost).where(
        NetworkFacebookPost.id == record_id,
        NetworkFacebookPost.org_id == user.org_id,
        NetworkFacebookPost.page_id == cfg.facebook_page_id))
    if not post:
        raise HTTPException(404, "Publicación no encontrada en esta organización")
    if cfg.facebook_org_id and cfg.facebook_org_id != user.org_id:
        raise HTTPException(403, "La página está asociada a otra organización")
    if not post.post_id or not re.fullmatch(r"[0-9]+_[0-9]+", post.post_id):
        raise HTTPException(409, "La publicación no tiene un ID de Meta confirmado")
    if post.state not in ({"published", "failed"} if allow_failed else {"published"}):
        raise HTTPException(409, "Esta publicación no está disponible para esa acción")
    return post


def _comment(db: Session, post: NetworkFacebookPost, comment_id: str):
    item = db.scalar(select(FacebookPostComment).where(
        FacebookPostComment.id == comment_id,
        FacebookPostComment.org_id == post.org_id,
        FacebookPostComment.post_record_id == post.id))
    if item is None:
        raise HTTPException(404, "Comentario no encontrado en la publicación")
    return item


def _within_private_window(item: FacebookPostComment) -> bool:
    when = item.posted_at
    if when and when.tzinfo is None:
        from datetime import timezone
        when = when.replace(tzinfo=timezone.utc)
    return bool(when and utcnow() - timedelta(days=7) <= when <= utcnow() and
                item.can_reply_privately and item.private_reply_state in {"not_sent", "failed"})


def _enqueue(db, user, post, action, *, comment_id="", message=""):
    if action != "refresh":
        active = db.scalar(select(FacebookPostJob.id).where(
            FacebookPostJob.post_record_id == post.id,
            FacebookPostJob.state.in_(["pending", "sending"]),
            FacebookPostJob.action != "refresh",
        ).limit(1))
        if active:
            raise HTTPException(409, "Ya hay otra operación en curso para esta publicación")
    row = FacebookPostJob(
        org_id=user.org_id, page_id=post.page_id,
        post_record_id=post.id, created_by=user.id,
        action=action, comment_id=comment_id, message=message, state="pending")
    db.add(row)
    db.flush()
    db.commit()
    return {"id": row.id, "state": "pending",
            "message": "Solicitud en cola. Comprueba la confirmación de Meta."}


@router.get("/{record_id}")
def publication_detail(record_id: str, user: User = Depends(administrator),
                       db: Session = Depends(get_db)):
    post = _post(db, user, record_id, allow_failed=True)
    snapshot = db.get(FacebookPostSnapshot, record_id)
    comments = list(db.scalars(select(FacebookPostComment).where(
        FacebookPostComment.org_id == user.org_id,
        FacebookPostComment.post_record_id == record_id)
        .order_by(FacebookPostComment.posted_at.desc(), FacebookPostComment.id.desc()).limit(150)))
    psids = {c.messenger_psid for c in comments if c.messenger_psid}
    leads = {
        lead.psid: lead.id for lead in db.scalars(select(FacebookLead).where(
            FacebookLead.org_id == user.org_id,
            FacebookLead.page_id == post.page_id,
            FacebookLead.last_inbound_at.isnot(None),
            FacebookLead.psid.in_(psids)))
    } if psids else {}
    jobs = list(db.scalars(select(FacebookPostJob).where(
        FacebookPostJob.org_id == user.org_id,
        FacebookPostJob.post_record_id == record_id)
        .order_by(FacebookPostJob.created_at.desc(), FacebookPostJob.id.desc()).limit(12)))
    return {
        "id": post.id, "state": post.state,
        "message": snapshot.message if snapshot else "",
        "permalink_url": snapshot.permalink_url if snapshot else "",
        "comment_count": snapshot.comment_count if snapshot else None,
        "reaction_count": snapshot.reaction_count if snapshot else None,
        "share_count": snapshot.share_count if snapshot else None,
        "checked_at": snapshot.checked_at.isoformat() if snapshot and snapshot.checked_at else None,
        "comments": [{
            "id": c.id,
            "author_name": c.author_name or None,
            "body": c.body,
            "posted_at": c.posted_at.isoformat(),
            "parent_id": c.parent_id or None,
            "is_hidden": c.is_hidden,
            "like_count": c.like_count,
            "can_reply": c.can_comment and post.state == "published",
            "can_hide": c.can_hide and post.state == "published",
            "can_private_reply": (post.state == "published" and
                                  c.author_id != post.page_id and _within_private_window(c)),
            "private_reply_state": c.private_reply_state,
            "lead_id": leads.get(c.messenger_psid),
        } for c in comments],
        "comments_limited": len(comments) == 150,
        "jobs": [{"id": j.id, "action": j.action, "state": j.state,
                  "error": j.last_error, "created_at": j.created_at.isoformat()}
                 for j in jobs],
    }


@router.post("/{record_id}/refresh", status_code=202)
def refresh_publication(record_id: str, user: User = Depends(administrator),
                        db: Session = Depends(get_db)):
    post = _post(db, user, record_id)
    prior = db.scalar(select(FacebookPostJob).where(
        FacebookPostJob.post_record_id == post.id,
        FacebookPostJob.action == "refresh",
    ).order_by(FacebookPostJob.created_at.desc()).limit(1))
    if prior and prior.state in {"pending", "sending"}:
        return {"id": prior.id, "state": prior.state, "message": "Sincronización en curso"}
    if prior and prior.state == "done" and (utcnow() - prior.created_at).total_seconds() < 12:
        return {"id": prior.id, "state": "done", "message": "Actualizado recientemente"}
    return _enqueue(db, user, post, "refresh")


@router.post("/{record_id}/comments/{comment_id}/reply", status_code=202)
def reply_comment(record_id: str, comment_id: str, body: Body,
                  user: User = Depends(administrator), db: Session = Depends(get_db)):
    post = _post(db, user, record_id)
    comment = _comment(db, post, comment_id)
    if not comment.can_comment:
        raise HTTPException(409, "Meta no autorizó responder a este comentario")
    return _enqueue(db, user, post, "public_reply",
                    comment_id=comment.comment_id, message=body.text())


@router.post("/{record_id}/comments/{comment_id}/private-reply", status_code=202)
def private_reply(record_id: str, comment_id: str, body: Body,
                  user: User = Depends(administrator), db: Session = Depends(get_db)):
    post = _post(db, user, record_id)
    query = select(FacebookPostComment).where(
        FacebookPostComment.id == comment_id,
        FacebookPostComment.post_record_id == post.id,
        FacebookPostComment.org_id == user.org_id)
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    comment = db.scalar(query)
    if comment is None:
        raise HTTPException(404, "Comentario no encontrado")
    if (comment.author_id == post.page_id or not _within_private_window(comment)
            or not settings().facebook_messaging_enabled):
        raise HTTPException(409, "Meta no habilitó una respuesta privada a este comentario")
    comment.private_reply_state = "pending"
    return _enqueue(db, user, post, "private_reply",
                    comment_id=comment.comment_id, message=body.text())


@router.post("/{record_id}/comments/{comment_id}/hide", status_code=202)
def moderate_comment(record_id: str, comment_id: str,
                     user: User = Depends(administrator), db: Session = Depends(get_db)):
    post = _post(db, user, record_id)
    comment = _comment(db, post, comment_id)
    if not comment.can_hide:
        raise HTTPException(409, "Meta no permite moderar este comentario")
    return _enqueue(db, user, post, "unhide" if comment.is_hidden else "hide",
                    comment_id=comment.comment_id)


@router.post("/{record_id}/edit", status_code=202)
def edit_publication(record_id: str, body: Body, user: User = Depends(administrator),
                     db: Session = Depends(get_db)):
    post = _post(db, user, record_id)
    return _enqueue(db, user, post, "edit", message=body.text())


@router.delete("/{record_id}", status_code=202)
def delete_publication(record_id: str, user: User = Depends(administrator),
                       db: Session = Depends(get_db)):
    # El publicador existente realiza DELETE de Meta y solo marca "deleted"
    # después de una confirmación. También desactiva la publicación futura.
    post = _post(db, user, record_id, allow_failed=True)
    requirement = db.scalar(select(NetworkRequirement).where(
        NetworkRequirement.id == post.requirement_id,
        NetworkRequirement.org_id == user.org_id))
    if requirement is None:
        raise HTTPException(404, "Necesidad asociada no encontrada")
    if post.state == "failed" and post.action != "delete":
        raise HTTPException(409, "Esta publicación tiene otro error pendiente")
    requirement.publish_to_facebook = False
    requirement.version += 1
    requirement.updated_at = utcnow()
    post.target_version = requirement.version
    post.action = "delete"
    post.state = "pending"
    post.last_error = None
    post.updated_at = utcnow()
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id,
                      action="facebook_delete_requested", resource_id=post.id))
    db.commit()
    return {"state": "pending", "message": "Retiro solicitado; falta confirmación de Meta."}
