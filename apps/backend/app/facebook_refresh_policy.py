"""Shared automatic refresh policy. Manual retries remain possible."""
from datetime import timedelta, timezone
import re

from sqlalchemy import select
from .facebook_publication_models import FacebookPostJob

_PERMISSION_CODES = {10, 102, 190, 200, 283, 492}


def refresh_retry_allowed(state, error, updated_at, now):
    """Fail closed on permissions or inaccessible posts, back off other failures."""
    if state in {"pending", "sending", "uncertain"}:
        return False
    if state != "failed":
        return True
    code = re.search(r"código Meta (\d+)", error or "")
    subcode = re.search(r"subcódigo (\d+)", error or "")
    if code:
        number = int(code[1])
        if number in _PERMISSION_CODES or (number == 100 and subcode and int(subcode[1]) == 33):
            return False
    if updated_at is None:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - updated_at >= timedelta(minutes=15)


def automatic_refresh_allowed(db, post_id, org_id, page_id, now):
    """Both webhook and periodic worker consult the latest durable attempt.

    A manually requested successful refresh restores automatic synchronization.
    Never read jobs from another organization/page.
    """
    latest = db.scalar(select(FacebookPostJob).where(
        FacebookPostJob.org_id == org_id,
        FacebookPostJob.page_id == page_id,
        FacebookPostJob.post_record_id == post_id,
        FacebookPostJob.action == "refresh",
    ).order_by(FacebookPostJob.updated_at.desc(), FacebookPostJob.id.desc()).limit(1))
    return latest is None or refresh_retry_allowed(
        latest.state, latest.last_error, latest.updated_at, now)
