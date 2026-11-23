"""Keep declared employment count separate from worksite capacity."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.9.32_employee_count"


def upgrade(connection):
    columns = {column["name"] for column in inspect(connection).get_columns("facebook_leads")}
    if "employee_count" not in columns:
        connection.execute(text("ALTER TABLE facebook_leads ADD COLUMN employee_count INTEGER"))
