"""Paridad dinámica del subconjunto de fórmulas Excel que ya opera en el backend.

No presupone que todas las 423 fórmulas hayan sido reemplazadas. La validación
por entradas variables cubre: algoritmo RUT DV, formato de fechas A4 y selección
de campos del expediente; no cubre matrices ni montos en palabras.
"""
from datetime import date
import fitz
import pytest

from app.javiera_logic import rut_valid
from app.javiera_native import render_native_pdf


def excel_rut_dv_reference(body: int) -> str:
    """Función de referencia independiente según el cálculo Excel módulo 11."""
    digits = [int(d) for d in str(body)]
    weights = [2, 3, 4, 5, 6, 7]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        total += digit * weights[index % len(weights)]
    value = (11 - (total % 11)) % 11
    return "K" if value == 10 else str(value)


@pytest.mark.parametrize("body", [
    1000000, 1111111, 1900000, 2023456, 7000000, 8765432, 9999999,
    10000000, 12345678, 20000000, 23000000, 76000000, 99999999,
    *range(10000000, 10000200, 7),
])
def test_backend_rut_dv_matches_excel_formula_for_multiple_inputs(body):
    dv = excel_rut_dv_reference(body)
    assert rut_valid(f"{body}-{dv}")
    bad = "8" if dv != "8" else "7"
    assert not rut_valid(f"{body}-{bad}")
    assert rut_valid(f"{body:,}-{dv}".replace(",", "."))


@pytest.mark.parametrize("month", range(1, 13))
def test_backend_print_dates_match_excel_day_month_year(month):
    """Coincide día, mes y año usados en los formularios Excel originales."""
    when = date(2026, month, 9 if month % 2 else 28)
    data = {
        "employer": {"name": "EMPRESA SINTÉTICA", "rut": "76000000-0"},
        "worker": {"name": "TRABAJADOR SINTÉTICO", "rut": "20000000-0"},
        "site": {"name": "OBRA SINTÉTICA"},
        "role": "CARPINTERO",
        "event": {"date": when.isoformat()},
        "extra": {"regulation_version": "R.1"},
    }
    result = render_native_pdf("internal_rules_receipt", data)
    with fitz.open(stream=result, filetype="pdf") as document:
        content = " ".join(page.get_text() for page in document)
        # Excel: TEXT(DAY(date),"00") & "/" & TEXT(MONTH(date),"00") & "/" & YEAR(date)
        excel_reference = f"{when.day:02d}/{when.month:02d}/{when.year}"
        assert excel_reference in content
        assert "EMPRESA" in content and "TRABAJADOR" in content


def test_printed_identity_changes_with_each_input_not_a_cached_excel_value():
    def render(name):
        d = {
            "employer": {"name": "EMPRESA SINTÉTICA", "rut": "76000000-0"},
            "worker": {"name": name, "rut": "20000000-0"},
            "site": {"name": "OBRA SINTÉTICA"},
            "role": "CARPINTERO",
            "event": {"date": "2026-11-09"},
            "extra": {"regulation_version": "R.1"},
        }
        with fitz.open(stream=render_native_pdf("internal_rules_receipt", d),
                       filetype="pdf") as pdf:
            return " ".join(page.get_text() for page in pdf)
    first = render("PERSONA A")
    second = render("PERSONA B")
    assert "PERSONA A" in first and "PERSONA B" not in first
    assert "PERSONA B" in second and "PERSONA A" not in second
