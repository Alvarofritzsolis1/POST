"""Additive opt-in two-model review, never enables external calls automatically."""
from sqlalchemy import inspect, text
from ..ai_models import AIOrchestration

MIGRATION_ID = "20.8.1_ai_collaboration"


def upgrade(connection):
    AIOrchestration.__table__.create(bind=connection, checkfirst=True)
    columns = {col["name"] for col in inspect(connection).get_columns("ai_orchestration")}
    if "review_enabled" not in columns:
        connection.execute(text(
            "ALTER TABLE ai_orchestration ADD COLUMN review_enabled BOOLEAN NOT NULL DEFAULT FALSE"
        ))
