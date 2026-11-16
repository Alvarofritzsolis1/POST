"""Additive Facebook CRM migration: no existing records or posts are changed."""
from ..facebook_crm_models import FacebookLead, FacebookChatMessage

MIGRATION_ID = "20.7.0_facebook_crm"


def upgrade(connection):
    FacebookLead.__table__.create(bind=connection, checkfirst=True)
    FacebookChatMessage.__table__.create(bind=connection, checkfirst=True)
