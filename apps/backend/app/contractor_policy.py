"""Reglas de exigibilidad comunes a todos los puntos de entrada documentales.

La fecha efectiva de baja todavía no está normalizada para los registros
históricos. Evitar modificar retroactivamente meses anteriores sin evidencia.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from .ops_models import ContractorWorksite

CL_TZ = ZoneInfo("America/Santiago")


def inactive_for_period(
    association: ContractorWorksite, period: str, as_of: date | None = None
) -> bool:
    """Prevent new obligations for inactive associations in the current/future month."""
    current = as_of or datetime.now(CL_TZ).date()
    return association.contract_status != "active" and period >= current.strftime("%Y-%m")
