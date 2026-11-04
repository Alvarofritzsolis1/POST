"""Pure calendar and grading rules for weekly attendance v8.1.

Weeks begin Monday, end Sunday and are clipped at calendar-month boundaries.
Persist dates, not only ordinals. All times in Chile use zoneinfo (DST-aware).
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

CL_TZ = ZoneInfo("America/Santiago")


def calendar_weeks(period: str) -> list[tuple[date, date]]:
    try:
        year, month = map(int, period.split("-"))
        assert len(period) == 7 and 1 <= month <= 12 and 2000 <= year <= 2100
    except (ValueError, AssertionError) as exc:
        raise ValueError("Período debe tener formato AAAA-MM") from exc
    last = calendar.monthrange(year, month)[1]
    current = date(year, month, 1)
    end = date(year, month, last)
    weeks = []
    while current <= end:
        sunday = current + timedelta(days=6 - current.weekday())
        clipped = min(sunday, end)
        weeks.append((current, clipped))
        current = clipped + timedelta(days=1)
    return weeks


def dates_of_week(period: str, number: int) -> list[date]:
    weeks = calendar_weeks(period)
    if number < 1 or number > len(weeks):
        raise ValueError("Esta semana no existe en el mes seleccionado")
    first, last = weeks[number-1]
    return [first + timedelta(days=n) for n in range((last-first).days + 1)]


def deadline_utc(last_day: date, grace_days: int, cutoff: str = "23:59") -> datetime:
    """Worksite deadline in Chile, converted to UTC with DST rules."""
    if not 0 <= grace_days <= 31:
        raise ValueError("Plazo semanal fuera de rango")
    try:
        hour, minute = map(int, cutoff.split(":"))
        if len(cutoff) != 5 or not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError as exc:
        raise ValueError("Hora de cierre debe estar en formato HH:MM") from exc
    local = datetime.combine(last_day + timedelta(days=grace_days), time(hour, minute, 59), CL_TZ)
    return local.astimezone(timezone.utc)


def grade(completed: int, punctual: int, required: int,
          completion_weight: Decimal = Decimal("0.70")) -> dict:
    if required < 0 or min(completed, punctual) < 0 or punctual > completed or completed > required:
        raise ValueError("Totales de cumplimiento no válidos")
    weight = Decimal(str(completion_weight))
    if weight < 0 or weight > 1:
        raise ValueError("Ponderación fuera de rango")
    if required == 0:
        return {"required": 0, "completed": 0, "punctual": 0,
                "completion": None, "punctuality": None, "grade": None}
    completion = Decimal(completed) / Decimal(required)
    punctuality = Decimal(punctual) / Decimal(required)
    index = weight * completion + (Decimal(1) - weight) * punctuality
    score = (Decimal(1) + Decimal(6) * index).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return {"required": required, "completed": completed, "punctual": punctual,
            "completion": float((completion*100).quantize(Decimal("0.01"))),
            "punctuality": float((punctuality*100).quantize(Decimal("0.01"))),
            "grade": float(score)}
