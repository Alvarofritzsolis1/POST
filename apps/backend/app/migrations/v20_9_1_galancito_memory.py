"""Persist multiple communes and the origin of conversation facts."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.9.1_galancito_memory"


def upgrade(connection):
    columns = {col["name"] for col in inspect(connection).get_columns("facebook_leads")}
    for name, definition in (
        ("work_communes", "JSON NOT NULL DEFAULT '[]'"),
        ("profile_sources", "JSON NOT NULL DEFAULT '{}'"),
        ("ai_consent_provider", "VARCHAR(20) NOT NULL DEFAULT ''"),
    ):
        if name not in columns:
            connection.execute(text(f"ALTER TABLE facebook_leads ADD COLUMN {name} {definition}"))
    if "consent_decision" not in {col["name"] for col in inspect(connection).get_columns("facebook_chat_messages")}:
        connection.execute(text("ALTER TABLE facebook_chat_messages ADD COLUMN consent_decision BOOLEAN"))
