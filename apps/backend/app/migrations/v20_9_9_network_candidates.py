"""Additive CRM follow-up table for the Red de Obras candidate workspace.

Some legacy installations can have incomplete Facebook schema while their
historical version flags remain present. Repair only the missing parent table;
never replace an existing Facebook profile table or its data.
"""
from sqlalchemy import inspect

from ..facebook_crm_models import FacebookLead
from ..network_models import NetworkCandidateFollowUp

MIGRATION_ID = "20.9.9_network_candidates"


def upgrade(connection):
    inspector = inspect(connection)
    if not inspector.has_table("network_requirements"):
        raise RuntimeError(
            "Falta network_requirements: ejecuta primero las migraciones de Red de Obras"
        )
    # PostgreSQL verifies this foreign key at CREATE TABLE time. An incomplete
    # historical schema must not block an additive candidate migration.
    if not inspector.has_table("facebook_leads"):
        FacebookLead.__table__.create(bind=connection, checkfirst=True)
    NetworkCandidateFollowUp.__table__.create(bind=connection, checkfirst=True)
