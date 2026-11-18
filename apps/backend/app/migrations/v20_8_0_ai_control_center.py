"""Non-destructive, opt-in, organization-scoped multi-provider AI registry."""
from ..ai_models import AIConnection, AIOrchestration, AIUsage

MIGRATION_ID = "20.8.0_ai_control_center"


def upgrade(connection):
    for model in (AIConnection, AIOrchestration, AIUsage):
        model.__table__.create(bind=connection, checkfirst=True)
