"""Additive, restart-safe MAX POWER state and event journal."""
from ..max_power_models import MaxPowerEvent, MaxPowerState
MIGRATION_ID = "20.9.23_max_power_master"

def upgrade(connection):
    MaxPowerState.__table__.create(bind=connection, checkfirst=True)
    MaxPowerEvent.__table__.create(bind=connection, checkfirst=True)
