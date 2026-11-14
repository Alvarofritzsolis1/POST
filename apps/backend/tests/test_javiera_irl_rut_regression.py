"""Regresiones del resumen IRL y del RUT en Proyecto JAVIERA.

Los datos de prueba son sintéticos. No se emiten documentos legales ni se
desactivan los controles de integridad del motor Calc.
"""
import io

import pytest
from openpyxl import load_workbook

from app.javiera_excel import LayoutError, Q, cell_text, get_data, shared_strings, sheet_files
from app.javiera_logic import field, rut_valid
from app.javiera_workbook import (fill_workbook, irl_continuations, irl_risk_print_rows,
    IRL_PRINT_RISK_ROWS, convert_pdf, validate_calculated, validate_matrix_results)
from app.rut_format import format_rut
from app.javiera_native import _get as native_field
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


@pytest.mark.parametrize("role,summary_role", [
    ("CARPINTERO", "CARPINTERO"),
    ("TECHADOR", "TECHUMBRE"),
    ("OPERARIO DE HORMIGON", "OPERARIO DE HORMIGÓN"),
    ("ALUMINERO", "ALUMINIOS"),
    ("OPERARIO DE URBANIZACION", "URBANIZACION"),
    ("ESTRUCTURERO METÁLICO", "ESTRUCTURAS METALICAS"),
    ("HOJALATERO", "HOJALATERIA"),
    ("ALBAÑIL", "ALBAÑILERIA"),
    ("INSTALADOR DE EIFS", "INS EIFS"),
    ("INSTALADOR DE PANDERETAS / VIBRADOS", "VIBRADOS (PANDERETAS)"),
    ("MUEBLISTA", "INST DE MUEBLES"),
    ("PAISAJISTA", "PAISAJISMO"),
    ("OPERARIO DE OBRA GRUESA", "OBRA GRUESA"),
])
def test_verified_irl_role_equivalences_are_explicit(role, summary_role):
    raw = source_with_broken_summary(role=role, available=summary_role)
    filled = fill_workbook(raw, {"role": role}, "irl")
    assert formula_at(filled, "IRL", "A23") == (
        "'Matriz IRL Optimizada'!$B$2"
    )


def test_native_pdf_fields_use_same_chilean_rut_format():
    data = {
        "employer": {"rut": "123456789"},
        "worker": {"rut": "12345678k"},
        "extra": {"representative_rut": "12925516-1"},
    }
    for key in ("employer.rut", "worker.rut", "extra.representative_rut"):
        assert native_field(data, key) == get_data(data, key)


def realistic_irl_13_risks() -> bytes:
    """Celdas y saltos del IRL original, con DATOS SINTÉTICOS."""
    role = "ESTRUCTURERO METÁLICO"
    book = load_workbook(io.BytesIO(source_with_broken_summary(
        role=role, available="ESTRUCTURAS METALICAS"
    )))
    matrix = book["MATRIZ IRL"]
    for source_row in range(2, 15):
        matrix[f"B{source_row}"] = role
        for c, title in (
            ("C", "Actividad"), ("D", "Peligro"),
            ("E", "Consecuencia"), ("F", "Medida")
        ):
            matrix[f"{c}{source_row}"] = f"{title} sintetica unica {source_row}"
    sheet = book["IRL"]
    sheet["A34"] = "DEPARTAMENTO DE PREVENCION DE RIESGOS"
    sheet["A37"] = "2 - RIESGOS Y MEDIDAS PREVENTIVAS"
    sheet["D40"] = "Medidas Preventivas Obligatorias"
    sheet.print_area = "A1:D67"
    for target_row in IRL_PRINT_RISK_ROWS:
        for dest_col, src_col in zip("ABCD", "CDEF"):
            sheet[f"{dest_col}{target_row}"] = (
                "=IF('MATRIZ IRL'!$B$2='Datos Contrato'!$C$29,"
                "'MATRIZ IRL'!$" + src_col + "$2,\"\")"
            )
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_original_irl_print_positions_and_unused_continuation_are_exact():
    raw = realistic_irl_13_risks()
    filled = fill_workbook(raw, {"role": "ESTRUCTURERO METÁLICO"}, "irl")
    expanded, names = irl_continuations(filled, "ESTRUCTURERO METÁLICO")
    assert names == ["IRL continuación 1"]
    assert "'MATRIZ IRL'!$C$2" in formula_at(expanded, "IRL", "A39")
    assert "'MATRIZ IRL'!$C$13" in formula_at(expanded, "IRL", "A67")
    assert "'MATRIZ IRL'!$C$14" in formula_at(expanded, names[0], "A39")
    assert formula_at(expanded, names[0], "A41") is None
    assert formula_at(expanded, names[0], "A45") is None
    assert formula_at(expanded, names[0], "A23") == "'Matriz IRL Optimizada'!$B$2"
    with ZipFile(io.BytesIO(expanded)) as archive:
        files = sheet_files(archive)
        continuation = ET.fromstring(archive.read(files[names[0]]))
        assert "Medidas Preventivas Obligatorias" in cell_text(
            continuation.find(".//" + Q("c") + "[@r='D40']"),
            shared_strings(archive)
        )
        assert "CONTINUACIÓN 1" in cell_text(
            continuation.find(".//" + Q("c") + "[@r='A37']"),
            shared_strings(archive)
        )
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        print_areas = [node.text for node in workbook.findall(".//" + Q("definedName"))
                       if node.get("name") == "_xlnm.Print_Area"]
        assert "'IRL continuación 1'!$A$34:$D$39" in print_areas


def test_real_irl_layout_rejects_missing_risk_print_rows():
    book = load_workbook(io.BytesIO(realistic_irl_13_risks()))
    book["IRL"]["A41"] = ""
    out = io.BytesIO()
    book.save(out)
    filled = fill_workbook(out.getvalue(), {"role": "ESTRUCTURERO METÁLICO"}, "irl")
    with pytest.raises(LayoutError, match="incompletas o desordenadas"):
        irl_continuations(filled, "ESTRUCTURERO METÁLICO")


def test_irl_13_risks_recalculate_and_print_without_duplicates():
    """CI real: LibreOffice + PDF deben imprimir trece registros, una sola vez."""
    import shutil
    if not (shutil.which("libreoffice") or shutil.which("soffice")):
        pytest.skip("LibreOffice no instalado fuera de CI Docker")
    data = {
        "role": "ESTRUCTURERO METÁLICO",
        "employer": {"name": "EMPRESA SINTETICA QA", "rut": "12.345.678-5"},
        "worker": {"name": "TRABAJADOR SINTETICO QA", "rut": "12.345.678-5"},
        "site": {"name": "OBRA SINTETICA QA"},
        "event": {"date": "2026-11-14"},
    }
    filled = fill_workbook(realistic_irl_13_risks(), data, "irl")
    expanded, names = irl_continuations(filled, data["role"])
    pdf, report = convert_pdf(expanded, "IRL", extra_sheets=names,
                              role=data["role"], code="irl")
    assert report["matrix_verified"] is True
    assert report["printed_matrix_fields"] == 52
    assert report["pages"] >= 1
    import fitz
    with fitz.open(stream=pdf, filetype="pdf") as document:
        text = " ".join(page.get_text() for page in document)
        for source_row in range(2, 15):
            assert text.count(f"Actividad sintetica unica {source_row}") == 1, source_row
            assert text.count(f"Medida sintetica unica {source_row}") == 1, source_row
