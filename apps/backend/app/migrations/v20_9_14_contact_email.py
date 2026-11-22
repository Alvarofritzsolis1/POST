"""Add optional email contact fields without touching existing Facebook leads."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.9.14_contact_email"

COLUMNS = {
    "contact_email": "VARCHAR(254) NOT NULL DEFAULT ''",
    "email_source": "VARCHAR(16) NOT NULL DEFAULT ''",
    "email_shared_at": "TIMESTAMP WITH TIME ZONE",
    "email_opt_out": "BOOLEAN NOT NULL DEFAULT FALSE",
}


def upgrade(connection):
    if not inspect(connection).has_table("facebook_leads"):
        raise RuntimeError("Se requiere la migración de Facebook CRM antes del correo")
    found = {column["name"] for column in inspect(connection).get_columns("facebook_leads")}
    for column, definition in COLUMNS.items():
        if column not in found:
            connection.execute(text(f"ALTER TABLE facebook_leads ADD COLUMN {column} {definition}"))
