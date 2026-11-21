"""Original Red de Obras schema (0.7.0), without tables added by later releases.

The legacy migration must never infer new tables from a name prefix:
future network_* tables may depend on Facebook/AI tables installed only by
later migrations. Keep the historical scope explicit and deterministic.
"""

from ..db import Base
from .. import network_models  # noqa: F401

MIGRATION_ID = "0.7.0"

LEGACY_NETWORK_TABLES = {
    "network_members",
    "network_memberships",
    "network_tokens",
    "network_requirements",
    "network_items",
    "network_capacities",
    "network_pending_items",
    "network_matches",
    "network_coordinations",
    "network_conversations",
    "network_participants",
    "network_messages",
    "network_awards",
    "network_notifications",
    "network_attachments",
}


def upgrade(connection):
    for table in Base.metadata.sorted_tables:
        if table.name in LEGACY_NETWORK_TABLES:
            table.create(bind=connection, checkfirst=True)
