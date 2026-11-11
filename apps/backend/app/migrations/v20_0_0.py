"""Additive Excel workspace migration. No legacy data is deleted or rewritten."""
from ..javiera_workbook_models import (JavieraWorkbook, JavieraWorkbookHead,
    JavieraWorkbookValidation, JavieraReset, JavieraArchive)

MIGRATION_ID = "20.0.0_excel_master_workspace"


def upgrade(connection):
    for model in (JavieraWorkbook, JavieraWorkbookHead, JavieraWorkbookValidation, JavieraReset, JavieraArchive):
        model.__table__.create(bind=connection, checkfirst=True)
