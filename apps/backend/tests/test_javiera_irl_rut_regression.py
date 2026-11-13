"""Regresiones del resumen IRL y del RUT en Proyecto JAVIERA.

Los datos de prueba son sintéticos. No se emiten documentos legales ni se
desactivan los controles de integridad del motor Calc.
"""
import io

import pytest
from openpyxl import load_workbook

from app.javiera_excel import LayoutError, Q, cell_text, get_data, shared_strings, sheet_files
from app.javiera_logic import field, rut_valid
from app.javiera_workbook import fill_workbook, irl_continuations
from app.rut_format import format_rut
from test_javiera_workbook import master
from zipfile import ZipFile
from xml.etree import ElementTree as ET


def source_with_broken_summary(*, role="ALUMINERO", available="ALUMINIOS", continuation=False):
    book = load_workbook(io.BytesIO(master()))
    root = book["Datos Contrato"]
    root["C29"] = role
    optimized = book["Matriz IRL Optimizada"]
    optimized["A2"] = available
    for col, label in (
        ("B", "Espacio de trabajo sintético"),
        ("C", "Condiciones ambientales sintéticas"),
        ("D", "Orden y aseo sintético"),
        ("E", "Herramientas sintéticas"),
    ):
        optimized[f"{col}2"] = label
    risks = book["MATRIZ IRL"]
    risks["B2"] = role
    for col, label in (
        ("C", "Actividad sintética"),
        ("D", "Peligro sintético"),
        ("E", "Consecuencia sintética"),
        ("F", "Medida sintética"),
    ):
        risks[f"{col}2"] = label
    sheet = book["IRL"]
    sheet["A23"] = "=VLOOKUP('Datos Contrato'!C29,'Matriz IRL Optimizada'!A1:E28,2,FALSE)"
    for coord, index in (("A25", 3), ("A28", 4), ("A31", 5)):
        sheet[coord] = (
            "=IFERROR(VLOOKUP('Datos Contrato'!$C$29,#REF!,"
            + str(index) + ',FALSE),"REVISAR CARGO EN MATRIZ")'
        )
    if continuation:
        for i in range(3, 16):
            risks[f"B{i}"] = role
            for col in "CDEF":
                risks[f"{col}{i}"] = f"Dato sintético {col}{i}"
        for col in "ABCD":
            sheet[f"{col}45"] = "='MATRIZ IRL'!C2"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def formula_at(raw, sheet, address):
    with ZipFile(io.BytesIO(raw)) as archive:
        name = sheet_files(archive)[sheet]
        root = ET.fromstring(archive.read(name))
        node = root.find(".//" + Q("c") + "[@r='" + address + "']")
        formula = node.find(Q("f")) if node is not None else None
        return formula.text if formula is not None else None


def test_irl_summary_uses_verified_optimized_row_not_vlookup_or_ref():
    raw = source_with_broken_summary()
    filled = fill_workbook(raw, {"role": "ALUMINERO"}, "irl")
    for coord, column in (("A23", "B"), ("A25", "C"), ("A28", "D"), ("A31", "E")):
        assert formula_at(filled, "IRL", coord) == (
            "'Matriz IRL Optimizada'!$" + column + "$2"
        )
    # The stored master is never changed during a PDF calculation.
    assert formula_at(raw, "IRL", "A25").startswith("IFERROR(VLOOKUP")


def test_irl_continuation_inherits_repaired_summary_links():
    filled = fill_workbook(
        source_with_broken_summary(continuation=True), {"role": "ALUMINERO"}, "irl"
    )
    expanded, names = irl_continuations(filled, "ALUMINERO")
    assert names
    for name in names:
        assert formula_at(expanded, name, "A23") == (
            "'Matriz IRL Optimizada'!$B$2"
        )
        assert formula_at(expanded, name, "A31") == (
            "'Matriz IRL Optimizada'!$E$2"
        )


def test_no_unverified_irl_substitution_for_generic_waterproofing_role():
    raw = source_with_broken_summary(
        role="IMPERMEABILIZADOR", available="MEMBRANA ASFALTICA"
    )
    with pytest.raises(LayoutError, match="correspondencia única y verificada"):
        fill_workbook(raw, {"role": "IMPERMEABILIZADOR"}, "irl")


def test_unmodified_synthetic_irl_without_summary_lookup_remains_unchanged():
    raw = master()
    result = fill_workbook(raw, {"role": "CARPINTERO"}, "irl")
    assert formula_at(result, "IRL", "A23") == formula_at(raw, "IRL", "A23")


@pytest.mark.parametrize("raw, expected", [
    ("12.345.678-9", "12.345.678-9"),
    ("123456789", "12.345.678-9"),
    ("12345678k", "12.345.678-K"),
    ("9876543-2", "9.876.543-2"),
    (" 12925516-1 ", "12.925.516-1"),
    ("", ""),
    ("1234", "1234"),
])
def test_rut_format_is_idempotent_and_preserves_check_digit(raw, expected):
    assert format_rut(raw) == expected
    assert format_rut(format_rut(raw)) == expected


def test_all_javiera_excel_and_structured_rut_fields_use_same_format():
    data = {
        "employer": {"rut": "123456789"},
        "worker": {"rut": "12345678k"},
        "extra": {"representative_rut": "12925516-1"},
    }
    for key, expected in (
        ("employer.rut", "12.345.678-9"),
        ("worker.rut", "12.345.678-K"),
        ("extra.representative_rut", "12.925.516-1"),
    ):
        assert get_data(data, key) == expected
        assert field(data, key) == expected


def test_invalid_rut_does_not_become_valid_after_formatting():
    assert not rut_valid("12.345.678-9")
    assert not rut_valid(format_rut("12.345.678-9"))
