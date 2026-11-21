"""Additive CRM follow-up table for the Red de Obras candidate workspace."""
from ..network_models import NetworkCandidateFollowUp

MIGRATION_ID = "20.9.9_network_candidates"


def upgrade(connection):
    NetworkCandidateFollowUp.__table__.create(bind=connection, checkfirst=True)
