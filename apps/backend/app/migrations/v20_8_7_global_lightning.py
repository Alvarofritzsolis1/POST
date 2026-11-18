"""Additive migration: server-wide encrypted NVIDIA key (no organization data merged)."""
from ..ai_models import AIGlobalCredential

MIGRATION_ID = "20.8.7_global_lightning"


def upgrade(connection):
    AIGlobalCredential.__table__.create(bind=connection, checkfirst=True)
