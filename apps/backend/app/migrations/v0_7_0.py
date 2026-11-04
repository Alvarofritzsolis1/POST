"""Red de Obras uses only new tables; existing users/documents remain intact."""

from ..db import Base
from .. import network_models  # noqa: F401

MIGRATION_ID = "0.7.0"


def upgrade(connection):
    for table in Base.metadata.sorted_tables:
        if table.name.startswith("network_"):
            table.create(bind=connection, checkfirst=True)
