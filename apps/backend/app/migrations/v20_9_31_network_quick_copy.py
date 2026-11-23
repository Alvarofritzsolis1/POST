"""Additive public copy and pending-date metadata for compact Red de Obras editor."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.9.31_network_quick_copy"


def upgrade(connection):
    if "network_requirements" not in inspect(connection).get_table_names():
        return
    columns = {row["name"] for row in inspect(connection).get_columns("network_requirements")}
    if "public_summary" not in columns:
        connection.execute(text("ALTER TABLE network_requirements ADD COLUMN public_summary VARCHAR(400) NOT NULL DEFAULT ''"))
    if "start_date_pending" not in columns:
        connection.execute(text("ALTER TABLE network_requirements ADD COLUMN start_date_pending BOOLEAN NOT NULL DEFAULT FALSE"))
