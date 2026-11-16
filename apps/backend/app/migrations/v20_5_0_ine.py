"""Migración aditiva GALANT 20.5: tablas INE sin alterar esquemas existentes."""
from ..ine_models import IneOriginal, IneSheet, IneRow, IneChange

MIGRATION_ID = "20.5.0-ine"


def upgrade(connection):
    for table in (IneOriginal.__table__, IneSheet.__table__,
                  IneRow.__table__, IneChange.__table__):
        table.create(bind=connection, checkfirst=True)
