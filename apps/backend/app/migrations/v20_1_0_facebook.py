"""Migración aditiva: publicaciones externas de Red de Obras."""
from ..network_models import NetworkFacebookPost

MIGRATION_ID = "20.1.0_network_facebook"

def upgrade(connection):
    NetworkFacebookPost.__table__.create(bind=connection, checkfirst=True)
