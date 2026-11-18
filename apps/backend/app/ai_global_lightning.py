"""Platform-wide NVIDIA Lightning, isolated per organization and user role.

One encrypted master credential is stored in PostgreSQL. Never expose it through
the client. Materialized org routes remain separate for usage/budget isolation.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_models import AIGlobalCredential, AIConnection, AIOrchestration
from .models import AuditEvent, Organization, User, utcnow

GLOBAL_ID = "nvidia-lightning"
MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
NAME = "NVIDIA Lightning · plataforma"


def sync_org(db: Session, org_id: str, *, force: bool = False) -> bool:
    """Attach shared Lightning to an org without ever merging its business data.

    force=True is used only by the server-side administrator provisioner.
    In ordinary flows, preserve an explicitly configured non-Lightning route.
    """
    master = db.get(AIGlobalCredential, GLOBAL_ID)
    if not (master and master.enabled and master.encrypted_key
            and master.provider == "nvidia" and master.model == MODEL
            and master.verified_at):
        return False
    org = db.get(Organization, org_id)
    if not org:
        return False

    user = db.scalar(select(User).where(User.org_id == org_id,
                                        User.enabled.is_(True))
                     .order_by(User.email).limit(1))
    if not user:
        return False

    policy = db.get(AIOrchestration, org_id)
    routes = dict(policy.task_routes or {}) if policy else {}
    current_id = routes.get("red_obras")
    current = db.get(AIConnection, current_id) if current_id else None
    if not force and current and current.org_id == org_id and current.provider == "nvidia" and current.model == MODEL and current.enabled and current.last_status == "verified":
        return False
    if not force and current_id:
        # Organization admins may later deliberately route to another provider.
        return False

    conn = db.scalar(select(AIConnection).where(
        AIConnection.org_id == org_id, AIConnection.provider == "nvidia",
        AIConnection.model == MODEL).order_by(AIConnection.id).limit(1))
    if conn is None:
        names = set(db.scalars(select(AIConnection.name).where(
            AIConnection.org_id == org_id)))
        name = NAME
        suffix = 2
        while name in names:
            name = NAME + " #" + str(suffix)
            suffix += 1
        conn = AIConnection(org_id=org_id, name=name, provider="nvidia",
                            model=MODEL, updated_by=user.id)
        db.add(conn)
        db.flush()
    conn.encrypted_key = master.encrypted_key
    conn.enabled = True
    conn.last_status = "verified"
    conn.last_checked_at = master.verified_at
    conn.updated_by = user.id
    conn.updated_at = utcnow()

    if policy is None:
        policy = AIOrchestration(org_id=org_id, updated_by=user.id,
                                 monthly_token_limit=100000)
        db.add(policy)
    routes["red_obras"] = conn.id
    if policy.review_enabled and routes.get("review") == conn.id:
        # The same model cannot independently review its own answer.
        policy.review_enabled = False
    policy.task_routes = routes
    policy.enabled = True
    if not policy.monthly_token_limit:
        policy.monthly_token_limit = 100000
    policy.updated_by = user.id
    policy.updated_at = utcnow()
    db.add(AuditEvent(org_id=org_id, user_id=user.id,
                      action="ai.global_lightning.attach", resource_id=conn.id))
    return True


def sync_all(db: Session, *, force: bool = False) -> tuple[int, int]:
    org_ids = list(db.scalars(select(Organization.id).order_by(Organization.id)))
    linked = sum(bool(sync_org(db, org_id, force=force)) for org_id in org_ids)
    return linked, len(org_ids)
