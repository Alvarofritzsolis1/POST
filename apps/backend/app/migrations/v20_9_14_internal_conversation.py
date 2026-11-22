"""Add optional, organization-and-user-scoped internal conversation storage.

No historical messages are imported and no Messenger/chat-lead rows are touched.
"""
from ..galancito_knowledge_models import InternalConversation

MIGRATION_ID = "20.9.14_galancito_internal_conversation"


def upgrade(connection):
    InternalConversation.__table__.create(bind=connection, checkfirst=True)
