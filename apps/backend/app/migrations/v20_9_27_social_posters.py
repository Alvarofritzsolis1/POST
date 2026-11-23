"""Adición reversible de campos sociales; no cambia ni borra datos históricos."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.9.27_social_posters"


def upgrade(connection):
    found = {row["name"] for row in inspect(connection).get_columns("network_requirements")}
    if "public_location" not in found:
        connection.execute(text("ALTER TABLE network_requirements ADD COLUMN public_location VARCHAR(120) NOT NULL DEFAULT ''"))
    if "poster_path" not in found:
        connection.execute(text("ALTER TABLE network_requirements ADD COLUMN poster_path TEXT NOT NULL DEFAULT ''"))
    sites = {row["name"] for row in inspect(connection).get_columns("worksites")}
    if "public_area" not in sites:
        connection.execute(text("ALTER TABLE worksites ADD COLUMN public_area VARCHAR(120) NOT NULL DEFAULT ''"))
