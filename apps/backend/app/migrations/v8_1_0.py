"""Additive v8.1 migration: do not delete or alter any legacy attendance rows.

The v8.0 calendar was five fixed blocks (1-7, 8-14, ...). The new Monday-Sunday
calendar is copied into independent tables and ALWAYS marked draft/review-needed,
because a completed legacy block is not evidence of completed new weekly obligations.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from sqlalchemy import select
from ..db import Base
from .. import v81_models  # noqa: F401
from ..calendar_v81 import calendar_weeks
from ..platform_models import AttendanceWeek, AttendanceWorkerWeek
from ..v81_models import CalendarWeek, CalendarEntry

MIGRATION_ID = "8.1.0"


def upgrade(db):
    for table in Base.metadata.sorted_tables:
        if table.name in {
            "attendance_calendar_weeks", "attendance_calendar_entries",
            "attendance_calendar_duties", "attendance_monthly_assessments",
        }:
            table.create(bind=db.connection(), checkfirst=True)

    legacy_weeks = db.scalars(select(AttendanceWeek).order_by(
        AttendanceWeek.org_id, AttendanceWeek.association_id,
        AttendanceWeek.period, AttendanceWeek.week_number)).all()
    by_month = defaultdict(list)
    for old in legacy_weeks:
        by_month[(old.org_id, old.association_id, old.period)].append(old)

    for (org_id, association_id, period), history in by_month.items():
        if db.scalar(select(CalendarWeek.id).where(
            CalendarWeek.org_id == org_id, CalendarWeek.association_id == association_id,
            CalendarWeek.period == period).limit(1)):
            # Do not overwrite attendance that has already been entered in the new version.
            continue
        old_rows = db.scalars(select(AttendanceWorkerWeek).where(
            AttendanceWorkerWeek.org_id == org_id,
            AttendanceWorkerWeek.week_id.in_([old.id for old in history]))).all()
        dates_by_worker = defaultdict(set)
        has_explicit = defaultdict(list)
        for old_row in old_rows:
            dates_by_worker[old_row.worker_assignment_id].update(
                date.fromisoformat(day) for day in (old_row.signed_dates or []))
            has_explicit[old_row.worker_assignment_id].append(
                (old_row, next(w for w in history if w.id == old_row.week_id)))

        for number, (first, last) in enumerate(calendar_weeks(period), start=1):
            relevant = [old for old in history if (
                max(first.day, 1 + (old.week_number - 1) * 7)
                <= min(last.day, min(31, old.week_number * 7))
            )]
            if not relevant:
                continue
            earliest = min(relevant, key=lambda row: row.entered_at)
            latest = max(relevant, key=lambda row: row.updated_at)
            new = CalendarWeek(org_id=org_id, association_id=association_id, period=period,
                week_number=number, start_date=first, end_date=last,
                state="draft", migrated=True,
                notes="Migrado desde calendario antiguo; revisar esta semana antes de completarla.",
                entered_by=earliest.entered_by, entered_at=earliest.entered_at,
                updated_by=latest.updated_by, updated_at=latest.updated_at)
            db.add(new)
            db.flush()
            for assignment, rows in has_explicit.items():
                overlapping = [row for row, old in rows if old in relevant]
                if not overlapping:
                    continue
                clipped = sorted(day.isoformat() for day in dates_by_worker[assignment]
                                 if first <= day <= last)
                excluded = bool(overlapping) and all(row.excluded for row in overlapping) and not clipped
                reasons = " / ".join(sorted({row.reason.strip() for row in overlapping
                                              if row.reason.strip()}))
                latest_entry = max(overlapping, key=lambda row: row.updated_at)
                db.add(CalendarEntry(org_id=org_id, week_id=new.id,
                    worker_assignment_id=assignment, signed_dates=clipped, excluded=excluded,
                    reason=reasons if excluded else "", updated_by=latest_entry.updated_by,
                    updated_at=latest_entry.updated_at))
    db.flush()
