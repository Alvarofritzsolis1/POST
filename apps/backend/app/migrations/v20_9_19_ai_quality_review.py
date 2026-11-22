"""Add isolated, content-free human audit table for verified AI responses."""
from ..ai_quality_models import AIResponseReview

MIGRATION_ID = "20.9.19_ai_quality_review"


def upgrade(connection):
    AIResponseReview.__table__.create(bind=connection, checkfirst=True)
