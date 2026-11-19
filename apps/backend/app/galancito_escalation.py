"""One durable, organization-scoped alert per Messenger handoff."""
from uuid import uuid4
from sqlalchemy import select

from .facebook_crm_models import FacebookLead
from .models import User
from .network_models import NetworkNotification


def flag_for_human(db, lead: FacebookLead, reason: str) -> None:
    first_alert = not lead.needs_support
    lead.needs_support = True
    lead.support_reason = reason[:250]
    if not first_alert:
        return
    event_key = "facebook_help:" + lead.id + ":" + uuid4().hex[:12]
    admin_ids = db.scalars(select(User.id).where(
        User.org_id == lead.org_id, User.role == "admin",
        User.enabled.is_(True))).all()
    for admin_id in admin_ids:
        db.add(NetworkNotification(
            org_id=lead.org_id, user_id=admin_id,
            event_key=event_key,
            title="Facebook: un interesado necesita ayuda para avanzar",
            resource_type="facebook", resource_id=lead.id))
