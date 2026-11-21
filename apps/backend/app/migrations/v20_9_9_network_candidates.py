"""Add candidate follow-up table only after its Red de Obras and CRM parents.

This additive migration deliberately does not create or rewrite Facebook
contact tables: those are owned by the earlier CRM migrations.
"""
from sqlalchemy import inspect

from ..network_models import NetworkCandidateFollowUp

MIGRATION_ID = "20.9.9_network_candidates"


def upgrade(connection):
    inspector = inspect(connection)
    missing = [
        name for name in ("network_requirements", "facebook_leads")
        if not inspector.has_table(name)
    ]
    if missing:
        raise RuntimeError(
            "La migración de candidatos requiere tablas anteriores: "
            + ", ".join(missing)
        )
    NetworkCandidateFollowUp.__table__.create(bind=connection, checkfirst=True)
