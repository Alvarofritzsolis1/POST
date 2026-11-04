"""V9.1: control de asistencia solo lunes a viernes, sin renumerar historia."""
from datetime import date
import pytest
from pydantic import ValidationError

from app.calendar_v81 import calendar_weeks, dates_of_week
from app.v81_api import SaveWeek


def test_noviembre_domingo_no_genera_semana_exigible():
    # Conservar ordinales históricos: la semana 1 empieza el domingo 01-11.
    assert len(calendar_weeks("2026-11")) == 6
    assert dates_of_week("2026-11", 1) == []
    assert dates_of_week("2026-11", 2) == [
        date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4),
        date(2026, 11, 5), date(2026, 11, 6),
    ]
    assert sum(bool(dates_of_week("2026-11", i)) for i in range(1, 7)) == 5


@pytest.mark.parametrize("period,days", [("2026-10", 22), ("2026-11", 21), ("2021-02", 20)])
def test_solo_dias_laborales_sin_perder_lunes_viernes(period, days):
    calendar_days = [day for i in range(1, len(calendar_weeks(period)) + 1)
                     for day in dates_of_week(period, i)]
    assert len(calendar_days) == days
    assert len(calendar_days) == len(set(calendar_days))
    assert all(day.weekday() < 5 for day in calendar_days)


def test_no_se_acepta_registro_para_domingo_sin_dias_laborales():
    with pytest.raises(ValidationError, match="Semana sin días laborales"):
        SaveWeek(association_id="dummy", period="2026-11", week_number=1,
                 revision=0, complete=False, entries=[])


def test_no_se_aceptan_firmas_de_sabados_y_domingos():
    with pytest.raises(ValidationError, match="Fecha fuera de la semana"):
        SaveWeek(association_id="dummy", period="2026-10", week_number=1,
                 revision=0, complete=False,
                 entries=[{"worker_assignment_id": "x", "signed_dates": ["2026-10-03"],
                           "excluded": False, "reason": ""}])
