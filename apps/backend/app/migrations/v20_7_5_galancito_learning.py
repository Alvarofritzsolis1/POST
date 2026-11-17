"""Additive knowledge tables and trade provenance; preserve existing records."""
from sqlalchemy import text, inspect
from ..galancito_knowledge_models import Knowledge, KnowledgeVersion, AssistantRun

MIGRATION_ID = "20.7.5_galancito_learning"


def upgrade(connection):
    for model in (Knowledge, KnowledgeVersion, AssistantRun):
        model.__table__.create(bind=connection, checkfirst=True)
    inspector = inspect(connection)
    if "facebook_leads" in inspector.get_table_names() and "specialty_source" not in {
        column["name"] for column in inspector.get_columns("facebook_leads")
    }:
        connection.execute(text("ALTER TABLE facebook_leads ADD COLUMN specialty_source "
                                "VARCHAR(16) NOT NULL DEFAULT 'manual'"))
    if connection.dialect.name == "postgresql":
        connection.execute(text("""CREATE INDEX IF NOT EXISTS ix_galancito_knowledge_search
            ON galancito_knowledge USING gin (to_tsvector('simple', search_text))"""))
