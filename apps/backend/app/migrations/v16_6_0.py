"""JAVIERA 16.6: only new independent documentary tables; no operational writes."""
from ..javiera_v166_models import (JavieraLocalCompany, JavieraLocalPerson,
    JavieraLocalDossier, JavieraLocalIssue, JavieraLocalBatch)

MIGRATION_ID = "16.6.0_independent_documental"

def upgrade(connection):
    for model in (JavieraLocalCompany, JavieraLocalPerson, JavieraLocalDossier,
                  JavieraLocalIssue, JavieraLocalBatch):
        model.__table__.create(bind=connection, checkfirst=True)
