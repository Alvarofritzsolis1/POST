"""Add the isolated Galancito simulation queue and measurements."""
from ..galancito_training_models import TrainingCase, TrainingRound, TrainingWorker

MIGRATION_ID = "20.9.8_galancito_training"


def upgrade(connection):
    for model in (TrainingRound, TrainingCase, TrainingWorker):
        model.__table__.create(bind=connection, checkfirst=True)
