"""Add fields for volunteered work-area and ability to work with a team."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.8.8_galancito_intake"


def upgrade(connection):
    inspector = inspect(connection)
    if "facebook_leads" not in inspector.get_table_names():
        return
    names = {col["name"] for col in inspector.get_columns("facebook_leads")}
    if "team_available" not in names:
        connection.execute(text("ALTER TABLE facebook_leads ADD COLUMN team_available BOOLEAN"))
    if "work_area" not in names:
        connection.execute(text("ALTER TABLE facebook_leads ADD COLUMN work_area VARCHAR(120) NOT NULL DEFAULT ''"))
