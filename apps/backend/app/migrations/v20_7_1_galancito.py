"""Galancito consent/handoff columns, safe on already-migrated CRM databases."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.7.1_galancito_consent"


def upgrade(connection):
    inspector = inspect(connection)
    if "facebook_leads" not in inspector.get_table_names():
        return
    names = {c["name"] for c in inspector.get_columns("facebook_leads")}
    if "ai_consent_state" not in names:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN ai_consent_state VARCHAR(20) "
            "NOT NULL DEFAULT 'not_requested'"))
    if "ai_paused" not in names:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN ai_paused BOOLEAN NOT NULL DEFAULT FALSE"))
