"""Additive documentary configuration. No existing evidence or tables are rewritten."""
from sqlalchemy import inspect, select, text
from ..configuration_models import ConfigurationSettings, ConfigurationDocumentType, ConfigurationRule, GateMovement, ConfigurationObligationSnapshot
from ..configuration_service import ensure_configuration
from ..models import Organization

MIGRATION_ID = "13.1.0_documentary_configuration"


def upgrade(db):
    for model in (ConfigurationSettings, ConfigurationDocumentType, ConfigurationRule, GateMovement, ConfigurationObligationSnapshot):
        model.__table__.create(bind=db.connection(), checkfirst=True)
    columns = {column["name"] for column in inspect(db.connection()).get_columns("configuration_rules")}
    if "activation_from_period" not in columns:
        db.execute(text("ALTER TABLE configuration_rules ADD COLUMN activation_from_period VARCHAR(7)"))
    for org_id in db.scalars(select(Organization.id)).all():
        ensure_configuration(db, org_id)
