"""Cache acotado y cola durable para administrar posts/comentarios de Facebook.

El Page Access Token no sale del worker ni se almacena aquí.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import uid, utcnow


class FacebookPostSnapshot(Base):
    __tablename__ = "facebook_post_snapshots"

    post_record_id: Mapped[str] = mapped_column(
        ForeignKey("network_facebook_posts.id"), primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    permalink_url: Mapped[str] = mapped_column(String(400), default="")
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reaction_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    share_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FacebookPostComment(Base):
    __tablename__ = "facebook_post_comments"
    __table_args__ = (
        UniqueConstraint("post_record_id", "comment_id", name="uq_fb_comment_post_remote"),
        Index("ix_fb_comment_post_time", "post_record_id", "posted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    post_record_id: Mapped[str] = mapped_column(
        ForeignKey("network_facebook_posts.id"), index=True)
    comment_id: Mapped[str] = mapped_column(String(120))
    parent_id: Mapped[str] = mapped_column(String(120), default="")
    author_id: Mapped[str] = mapped_column(String(120), default="")
    author_name: Mapped[str] = mapped_column(String(180), default="")
    author_picture_url: Mapped[str] = mapped_column(String(1000), default="")
    classification: Mapped[str] = mapped_column(String(24), default="ambiguous")
    classification_source: Mapped[str] = mapped_column(String(16), default="rules")
    classification_score: Mapped[int] = mapped_column(Integer, default=0)
    review_state: Mapped[str] = mapped_column(String(20), default="new")
    review_by: Mapped[str] = mapped_column(String(36), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[str] = mapped_column(Text, default="")
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    can_comment: Mapped[bool] = mapped_column(Boolean, default=False)
    can_hide: Mapped[bool] = mapped_column(Boolean, default=False)
    can_reply_privately: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    user_likes: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    messenger_psid: Mapped[str] = mapped_column(String(90), default="")  # solo si Meta lo devuelve
    private_reply_state: Mapped[str] = mapped_column(String(18), default="not_sent")
    private_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FacebookPostJob(Base):
    __tablename__ = "facebook_post_jobs"
    __table_args__ = (
        Index("ix_fb_post_jobs_pending", "page_id", "state", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    post_record_id: Mapped[str] = mapped_column(
        ForeignKey("network_facebook_posts.id"), index=True)
    page_id: Mapped[str] = mapped_column(String(40))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(24))
    comment_id: Mapped[str] = mapped_column(String(120), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(18), default="pending")
    last_error: Mapped[str] = mapped_column(String(350), default="")
    remote_id: Mapped[str] = mapped_column(String(140), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
