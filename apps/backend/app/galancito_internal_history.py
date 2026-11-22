"""Explicit opt-in GALANT internal memory, separate from Facebook and practice.

Retains only a bounded 16-turn window for at most 30 days. A user can delete
their own history; another user in the same organization cannot view it.
"""
from datetime import timedelta
import re
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .galancito_knowledge_models import InternalConversation
from .galancito_triage import private_data
from .models import utcnow

HISTORY_DAYS = 30
MAX_CONVERSATIONS = 20
MAX_TURNS = 16
SAFE_INTENTS = {"overview", "navigation", "version", "publications", "training", "help",
                "metrics", "external_unavailable", "no_sites"}
REDACTED = "Esta consulta no se almacenó por contener datos potencialmente privados."


def cleanup_expired(db: Session):
    db.execute(delete(InternalConversation).where(InternalConversation.expires_at < utcnow()))


def _owned(db: Session, user, chat_id: str, *, lock: bool = False):
    query = select(InternalConversation).where(
        InternalConversation.id == chat_id,
        InternalConversation.org_id == user.org_id,
        InternalConversation.user_id == user.id,
        InternalConversation.expires_at >= utcnow(),
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def listed(db: Session, user):
    cleanup_expired(db)
    rows = list(db.scalars(select(InternalConversation).where(
        InternalConversation.org_id == user.org_id,
        InternalConversation.user_id == user.id,
        InternalConversation.expires_at >= utcnow(),
    ).order_by(InternalConversation.updated_at.desc()).limit(MAX_CONVERSATIONS)))
    return [{
        "id": row.id, "title": row.title, "updated_at": row.updated_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "turns": len(row.turns or []),
    } for row in rows]


def get(db: Session, user, chat_id: str):
    row = _owned(db, user, chat_id)
    return {"id": row.id, "title": row.title,
            "turns": row.turns, "expires_at": row.expires_at.isoformat()} if row else None


def erase(db: Session, user, chat_id: str) -> bool:
    row = _owned(db, user, chat_id, lock=True)
    if not row:
        return False
    db.delete(row)
    db.flush()
    return True


def previous_questions(db: Session, user, chat_id: str):
    row = _owned(db, user, chat_id)
    return [turn["text"] for turn in (row.turns or [])
            if turn.get("role") == "user"][-4:] if row else None


def record(db: Session, user, *, chat_id: str | None,
           question: str, answer: str, intent: str, run_id: str,
           reportable: bool):
    cleanup_expired(db)
    now = utcnow()
    row = _owned(db, user, chat_id, lock=True) if chat_id else None
    if chat_id and not row:
        raise ValueError("Conversación no encontrada o caducada")
    # Never persist potentially sensitive prompts, personal information or
    # tool outputs even when a user has opted into general conversation memory.
    sensitive = private_data(question) or private_data(answer) or intent not in SAFE_INTENTS
    if sensitive:
        return (row.id if row else None), False
    if not row:
        count = len(list(db.scalars(select(InternalConversation.id).where(
            InternalConversation.org_id == user.org_id,
            InternalConversation.user_id == user.id,
            InternalConversation.expires_at >= now,
        ).limit(MAX_CONVERSATIONS))))
        if count >= MAX_CONVERSATIONS:
            raise ValueError("Has alcanzado 20 conversaciones. Elimina una antes de guardar otra.")
        title = re.sub(r"\s+", " ", question).strip()[:110]
        row = InternalConversation(
            org_id=user.org_id, user_id=user.id, title=title,
            turns=[], expires_at=now + timedelta(days=HISTORY_DAYS),
        )
        db.add(row)
        db.flush()
    question_copy, answer_copy = question[:800], answer[:1600]
    stored_reportable = reportable
    turns = list(row.turns or [])
    turns.extend([
        {"role": "user", "text": question_copy},
        {"role": "assistant", "text": answer_copy,
         "run_id": run_id, "reportable": stored_reportable,
         "question": question_copy},
    ])
    row.turns = turns[-MAX_TURNS:]
    row.updated_at = now
    row.expires_at = now + timedelta(days=HISTORY_DAYS)
    db.flush()
    return row.id, True
