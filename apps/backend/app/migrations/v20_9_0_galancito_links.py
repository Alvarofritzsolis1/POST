"""Additive, reproducible migration for Galancito 20.9.0.

Preserves legacy specialty and single requirement association for compatibility.
A verified database backup remains mandatory through CLI migrate-db.
"""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import inspect, select, text

from ..facebook_crm_models import FacebookLeadTrade, FacebookNeedAssociation, FacebookLeadTrace

MIGRATION_ID = "20.9.0_galancito_links"


def upgrade(connection):
    FacebookLeadTrade.__table__.create(bind=connection, checkfirst=True)
    FacebookNeedAssociation.__table__.create(bind=connection, checkfirst=True)
    FacebookLeadTrace.__table__.create(bind=connection, checkfirst=True)

    if "facebook_leads" not in inspect(connection).get_table_names():
        return

    leads = connection.execute(text(
        "SELECT id, org_id, specialty, specialty_source, requirement_id FROM facebook_leads"
    )).all()
    now = datetime.now(timezone.utc)
    for row in leads:
        lead_id, org_id, specialty, source, requirement_id = row
        if specialty and specialty.strip():
            existing = connection.execute(
                select(FacebookLeadTrade.id).where(
                    FacebookLeadTrade.org_id == org_id,
                    FacebookLeadTrade.lead_id == lead_id,
                    FacebookLeadTrade.trade == specialty.strip()[:120],
                )
            ).first()
            if not existing:
                connection.execute(FacebookLeadTrade.__table__.insert().values(
                    id=str(uuid4()), org_id=org_id, lead_id=lead_id,
                    trade=specialty.strip()[:120],
                    source=source if source in {"manual", "message"} else "legacy",
                    active=True, first_seen_at=now, updated_at=now,
                ))
        if requirement_id:
            existing = connection.execute(select(FacebookNeedAssociation.id).where(
                FacebookNeedAssociation.org_id == org_id,
                FacebookNeedAssociation.lead_id == lead_id,
                FacebookNeedAssociation.requirement_id == requirement_id,
            )).first()
            if not existing:
                connection.execute(FacebookNeedAssociation.__table__.insert().values(
                    id=str(uuid4()), org_id=org_id, lead_id=lead_id,
                    requirement_id=requirement_id, state="linked",
                    reviewed_by=None, created_at=now, updated_at=now,
                ))
                connection.execute(FacebookLeadTrace.__table__.insert().values(
                    id=str(uuid4()), org_id=org_id, lead_id=lead_id,
                    requirement_id=requirement_id, event="legacy_link_imported",
                    source="migration", actor_id=None, created_at=now,
                ))
