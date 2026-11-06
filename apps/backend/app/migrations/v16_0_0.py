"""Migración aditiva JAVIERA v16. No modifica ni elimina tablas anteriores."""
from ..javiera_models import (JavieraTemplate, JavieraRevision, JavieraMatrix,
                              JavieraDossier, JavieraIssue, JavieraHistory)

MIGRATION_ID = "16.0.0"


def upgrade(connection):
    for model in (JavieraTemplate, JavieraRevision, JavieraMatrix,
                  JavieraDossier, JavieraIssue, JavieraHistory):
        model.__table__.create(bind=connection, checkfirst=True)
