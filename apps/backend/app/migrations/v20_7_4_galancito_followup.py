"""Additive, idempotent manual follow-up fields to existing Messenger leads."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.7.4_galancito_followup"


def upgrade(connection):
    inspector = inspect(connection)
    if "facebook_leads" not in inspector.get_table_names():
        return
    fields = {c["name"] for c in inspector.get_columns("facebook_leads")}
    if "follow_up_on" not in fields:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN follow_up_on DATE"))
    if "follow_up_note" not in fields:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN follow_up_note VARCHAR(240) NOT NULL DEFAULT ''"))
    if "follow_up_by" not in fields:
        connection.execute(text(
            "ALTER TABLE facebook_leads ADD COLUMN follow_up_by VARCHAR(36)"))
