"""Only new knowledge/history/metrics tables. Never rewrites existing data."""
from sqlalchemy import text
from ..galancito_knowledge_models import Knowledge, KnowledgeVersion, AssistantRun

MIGRATION_ID = "20.7.5_galancito_learning"


def upgrade(connection):
    for model in (Knowledge, KnowledgeVersion, AssistantRun):
        model.__table__.create(bind=connection, checkfirst=True)
    if connection.dialect.name == "postgresql":
        connection.execute(text("""CREATE INDEX IF NOT EXISTS ix_galancito_knowledge_search
            ON galancito_knowledge USING gin (to_tsvector('simple', search_text))"""))
