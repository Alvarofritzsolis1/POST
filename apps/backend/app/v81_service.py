"""Shared monthly attendance totals from the canonical v8.1 weeks.

Reports never infer '0 attended' from missing weekly entries.
"""
from __future__ import annotations
from collections import defaultdict
from sqlalchemy import select
from .attendance_api import _context, _worker_eligible
from .calendar_v81 import calendar_weeks, dates_of_week
from .v81_models import CalendarWeek, CalendarEntry, CalendarDuty
from .ops_models import ContractorWorksite


def site_calendar_totals(db, org_id: str, site_id: str, period: str):
    """Return (calendar_exists, mapping[worker_assignment_id, int|None]).

    None means missing weekly evidence, not zero days. No business decisions
    are taken from the difference itself.
    """
    ranges = calendar_weeks(period)
    legacy_links, assignments, contracts, terms, rosters, _, _, controls, users = _context(
        db, org_id, site_id, period)
    links = {link.id: (link, contractor) for link, contractor in legacy_links}
    if not links:
        return False, {}
    weeks = db.scalars(select(CalendarWeek).where(
        CalendarWeek.org_id == org_id,
        CalendarWeek.period == period,
        CalendarWeek.association_id.in_(list(links)))).all()
    if not weeks:
        # An initialized monthly obligation with no submissions is incomplete,
        # not a reason to fall back to manually entered attendance.
        duty_exists = db.scalar(select(CalendarDuty.id).where(
            CalendarDuty.org_id == org_id, CalendarDuty.period == period,
            CalendarDuty.association_id.in_(list(links))).limit(1)) is not None
        if not duty_exists:
            return False, {}
    by_key = {(w.association_id, w.week_number): w for w in weeks}
    rows = db.scalars(select(CalendarEntry).where(
        CalendarEntry.org_id == org_id,
        CalendarEntry.week_id.in_([w.id for w in weeks]))).all()
    entries = {(r.week_id, r.worker_assignment_id): r for r in rows}
    totals = {}
    for association_id, (link, company) in links.items():
        for assignment, worker in assignments[company.id]:
            required = [
                i for i in range(1, len(ranges) + 1)
                if _worker_eligible(assignment, contracts, terms, dates_of_week(period, i))
            ]
            if not required:
                totals[assignment.id] = None
                continue
            dates = set()
            valid = True
            for i in required:
                week = by_key.get((association_id, i))
                if not week or week.state != "completed":
                    valid = False
                    break
                entry = entries.get((week.id, assignment.id))
                if entry is None:
                    valid = False
                    break
                if not entry.excluded:
                    dates.update(entry.signed_dates or [])
            totals[assignment.id] = len(dates) if valid else None
    return True, totals
