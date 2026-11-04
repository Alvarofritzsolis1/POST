"""0.6.0-rc1: add labor termination, contract files and backup provenance."""
from ..platform_models import (AttendanceRoster, AttendanceWeek, AttendanceWorkerWeek,
                               BackupCheckpoint, ContractAttachment, PaymentFinding, WorkerTermination)

MIGRATION_ID = "0.6.0-rc1"


def upgrade(connection):
    # CREATE TABLE IF MISSING only. No old table, column or identifier is rewritten.
    for table in (WorkerTermination.__table__, ContractAttachment.__table__,
                  BackupCheckpoint.__table__, PaymentFinding.__table__,
                  AttendanceRoster.__table__, AttendanceWeek.__table__,
                  AttendanceWorkerWeek.__table__):
        table.create(bind=connection, checkfirst=True)
