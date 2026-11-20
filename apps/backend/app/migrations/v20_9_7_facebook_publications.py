"""Migración aditiva. No toca datos existentes de Messenger ni contratos."""
from ..facebook_publication_models import FacebookPostSnapshot, FacebookPostComment, FacebookPostJob

MIGRATION_ID = "20.9.7_facebook_publications"

def upgrade(connection):
    FacebookPostSnapshot.__table__.create(bind=connection, checkfirst=True)
    FacebookPostComment.__table__.create(bind=connection, checkfirst=True)
    FacebookPostJob.__table__.create(bind=connection, checkfirst=True)
