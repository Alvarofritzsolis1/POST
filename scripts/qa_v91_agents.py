#!/usr/bin/env python3
"""Validadores V9.1 independientes: reglas ejecutables, no modelos de IA."""
from __future__ import annotations
import ast
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps" / "backend"
FRONTEND = ROOT / "apps" / "frontend" / "src"


def audit_calendar():
    sys.path.insert(0, str(BACKEND))
    from app.calendar_v81 import calendar_weeks, dates_of_week
    for year in range(2024, 2030):
        for month in range(1, 13):
            period = f"{year}-{month:02d}"
            weeks = calendar_weeks(period)
            eligible = [dates_of_week(period, i) for i in range(1, len(weeks) + 1)]
            days = [day for group in eligible for day in group]
            assert len(days) == len(set(days)), period
            assert all(day.weekday() < 5 and day.strftime("%Y-%m") == period for day in days), period
            assert 4 <= sum(bool(group) for group in eligible) <= 5, period
    assert dates_of_week("2026-11", 1) == []
    assert dates_of_week("2026-11", 2)[0] == date(2026, 11, 2)
    assert len(calendar_weeks("2026-11")) == 6, "No renumerar claves históricas"
    print("Auditor calendario OK: días laborales, 4/5 semanas visibles, ordinal estable.")


def audit_ux():
    weekly = (FRONTEND / "WeeklyAttendanceV81.tsx").read_text()
    css = (FRONTEND / "weekly-v81.css").read_text()
    app = (FRONTEND / "App.tsx").read_text()
    responsive = (FRONTEND / "v91.css").read_text()
    assert 'className="weekly-v91-workers"' in weekly
    assert 'className="weekly-v81-grid"' not in weekly
    assert "setEntries" in weekly and "recorded: true" in weekly
    assert "Fecha límite:" in weekly and "fuera de plazo" in weekly
    assert "aria-label" in weekly and "aria-live" in weekly
    assert "minmax(min(100%,340px),1fr)" in css
    assert "prefers-reduced-motion" in responsive
    assert "sidebarCollapsed" in app and "setSidebarCollapsed" in app
    assert "aria-expanded" in app and 'className="v91-menu-backdrop"' in app
    print("Auditor interfaz OK: tarjetas adaptables, menú retráctil, accesibilidad.")


def audit_security():
    source = (BACKEND / "app" / "v81_api.py").read_text()
    funcs = {n.name: n for n in ast.parse(source).body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name, principal in [("save_week", "attendance_editor"),
                            ("generate_duties", "administrator"),
                            ("edit_duty", "administrator")]:
        body = ast.dump(funcs[name])
        assert f"Name(id='{principal}'" in body, name
    for needle in ["_scope(", "association_for(", "assigned_sites(", "user.org_id",
                   "Registro fuera de plazo", "revision", "audit_change",
                   "Semana sin días laborales", "if not days:", "signed_dates"]:
        assert needle in source, f"Protección ausente: {needle}"
    print("Auditor permisos OK: roles, obra, identidad y validación de fechas.")


if __name__ == "__main__":
    roles = {"calendar": audit_calendar, "ux": audit_ux, "security": audit_security}
    if len(sys.argv) != 2 or sys.argv[1] not in roles:
        raise SystemExit("Uso: qa_v91_agents.py calendar|ux|security")
    roles[sys.argv[1]]()
