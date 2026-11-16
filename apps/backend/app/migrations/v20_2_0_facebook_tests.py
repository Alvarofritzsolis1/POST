"""Tabla aditiva y aislada para pruebas de publicaciones Facebook."""
from ..network_models import NetworkFacebookManual

MIGRATION_ID = "20.2.0_network_facebook_tests"

def upgrade(connection):
    NetworkFacebookManual.__table__.create(bind=connection, checkfirst=True)
