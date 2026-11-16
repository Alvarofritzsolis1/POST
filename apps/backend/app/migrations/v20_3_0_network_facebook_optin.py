"""Red de Obras 20.3: consentimiento por requerimiento, sin difusión retroactiva."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.3.0_network_facebook_optin"


def upgrade(connection):
    existing = {column["name"] for column in inspect(connection).get_columns("network_requirements")}
    if "publish_to_facebook" not in existing:
        connection.execute(text(
            "ALTER TABLE network_requirements "
            "ADD COLUMN publish_to_facebook BOOLEAN NOT NULL DEFAULT FALSE"
        ))
