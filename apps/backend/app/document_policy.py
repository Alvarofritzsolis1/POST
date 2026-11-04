"""Política conservadora de documentación mensual por contratista/obra.

No se presume una fecha histórica de baja a partir del estado actual. Los
períodos anteriores solo conservan exigibilidad si hay evidencia registrada
o una decisión expresa, auditable, sobre ese mes.
"""
from datetime import datetime
from zoneinfo import ZoneInfo


def current_period() -> str:
    return datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m")


def is_operationally_active(association) -> bool:
    return association.contract_status == "active"


def is_historical(period: str) -> bool:
    return period < current_period()


def historical_review_allowed(association, period: str, *, has_evidence: bool,
                              explicit_applicability: bool = False) -> bool:
    """Permite corregir históricos sin reactivar obligaciones futuras.

    Para estados legados como suspended/offboarding se usa la misma protección
    conservadora de los inactivos, sin mutar su dato original.
    """
    return (is_operationally_active(association) or
            (is_historical(period) and (has_evidence or explicit_applicability)))
