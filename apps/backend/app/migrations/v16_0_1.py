"""JAVIERA v16.0.1: diseños Excel originales y revisión especializada."""
from ..javiera_models import JavieraExcelLayout, JavieraReviewerAuthorization, JavieraSignoff

MIGRATION_ID = "16.0.1_excel_pdf_reviews"


def upgrade(connection):
    for cls in (JavieraExcelLayout, JavieraReviewerAuthorization, JavieraSignoff):
        cls.__table__.create(bind=connection, checkfirst=True)
