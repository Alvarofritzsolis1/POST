"""Add content-free Qwen trial metadata. No chat data are copied."""
from ..ai_quality_models import AIRealPracticeTrial
MIGRATION_ID = "20.9.21_real_defect_learning"

def upgrade(connection):
    AIRealPracticeTrial.__table__.create(bind=connection, checkfirst=True)
