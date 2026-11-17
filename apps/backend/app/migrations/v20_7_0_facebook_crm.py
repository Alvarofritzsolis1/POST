"""Additive Facebook CRM migration: no existing records or posts are changed."""
from ..facebook_crm_models import FacebookLead, FacebookChatMessage, FacebookTradeGuide

MIGRATION_ID = "20.7.0_facebook_crm"


def upgrade(connection):
    FacebookLead.__table__.create(bind=connection, checkfirst=True)
    FacebookChatMessage.__table__.create(bind=connection, checkfirst=True)
    FacebookTradeGuide.__table__.create(bind=connection, checkfirst=True)
    # Also safe if the preview was created before the support columns existed.
    from sqlalchemy import inspect, text
    columns = {col["name"] for col in inspect(connection).get_columns("facebook_leads")}
    if "needs_support" not in columns:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN needs_support BOOLEAN NOT NULL DEFAULT FALSE"))
    if "support_reason" not in columns:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN support_reason VARCHAR(250) NOT NULL DEFAULT ''"))
    if "entity_type" not in columns:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN entity_type VARCHAR(20) NOT NULL DEFAULT 'unknown'"))
    if "has_employees" not in columns:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN has_employees BOOLEAN"))
    if "ai_consent_state" not in columns:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN ai_consent_state VARCHAR(20) NOT NULL DEFAULT 'not_requested'"))
    if "ai_paused" not in columns:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN ai_paused BOOLEAN NOT NULL DEFAULT FALSE"))


