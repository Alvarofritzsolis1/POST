"""Add optional contact number, with source and anti-repeat markers."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.9.4_facebook_contact_sheet"

def upgrade(connection):
    columns = {column["name"] for column in inspect(connection).get_columns("facebook_leads")}
    for name, definition in (
        ("contact_phone", "VARCHAR(20) NOT NULL DEFAULT ''"),
        ("phone_source", "VARCHAR(16) NOT NULL DEFAULT ''"),
        ("phone_shared_at", "TIMESTAMP WITH TIME ZONE"),
        ("phone_requested_at", "TIMESTAMP WITH TIME ZONE"),
        ("phone_opt_out", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ):
        if name not in columns:
            connection.execute(text(f"ALTER TABLE facebook_leads ADD COLUMN {name} {definition}"))
