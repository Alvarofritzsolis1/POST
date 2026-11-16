"""Regresión: impresión IRL según fórmulas de la plantilla, no filas fijas.

Verifica maquetas antiguas, del Excel fuente y de la revisión del usuario.
Los ejemplos utilizan únicamente datos sintéticos.
"""
import io
from xml.etree import ElementTree as ET

import pytest
from openpyxl import load_workbook

from app.javiera_excel import LayoutError, Q
from app.javiera_workbook import irl_risk_print_rows, irl_continuations, irl_letter_profile, read_sheet
from test_javiera_workbook import master


SOURCE_LAYOUT = (40, 42, 44, 46, 48, 50, 52, 54, 56, 63, 65, 67)
CURRENT_LAYOUT = (39, 41, 43, 45, 47, 49, 52, 54, 56, 63, 65, 67)
REPORTED_LAYOUT = tuple(range(45, 69, 2))


def test_reviewed_irl_letter_profile_fits_width_on_calc_25():
    # Fixed 96% alone produced two physical pages per section on the private
    # LibreOffice 25.2 service. The front and every continuation use this profile.
    page = ET.Element(Q("worksheet"))
    irl_letter_profile(page)
    assert page.find(Q("sheetPr") + "/" + Q("pageSetUpPr")).get("fitToPage") == "1"
    assert page.find(Q("pageSetup")).attrib.items() >= {
        "paperSize": "1", "orientation": "portrait", "fitToWidth": "1", "fitToHeight": "0"
    }.items()


def sheet_with_risks(rows):
    root = ET.Element(Q("worksheet"))
    data = ET.SubElement(root, Q("sheetData"))
    for number in rows:
        row = ET.SubElement(data, Q("row"), {"r": str(number)})
        for dest, source in zip("ABCD", "CDEF"):
            cell = ET.SubElement(row, Q("c"), {"r": f"{dest}{number}"})
            ET.SubElement(cell, Q("f")).text = (
                f"IF('MATRIZ IRL'!$B$2='Datos Contrato'!$C$29,"
                f"'MATRIZ IRL'!${source}$2,\"\")"
            )
    return root


@pytest.mark.parametrize("rows", [SOURCE_LAYOUT, CURRENT_LAYOUT, REPORTED_LAYOUT])
def test_full_irl_layouts_are_accepted_from_actual_formula_positions(rows):
    assert irl_risk_print_rows(sheet_with_risks(rows)) == (rows, True)


def test_legacy_single_risk_marker_keeps_synthetic_compatibility():
    # Fixtures v20 only represent one row of a twelve-row original.
    expected = (tuple(range(45, 69, 2)), False)
    assert irl_risk_print_rows(sheet_with_risks((45,))) == expected
    root = sheet_with_risks((45,))
    row = root.find(".//" + Q("row"))
    for cell in list(row):
        if cell.get("r") != "A45":
            row.remove(cell)
    assert irl_risk_print_rows(root) == expected


def test_incomplete_risk_row_is_rejected_instead_of_misaligned_pdf():
    root = sheet_with_risks(REPORTED_LAYOUT)
    row = root.find(".//" + Q("c") + "[@r='B55']")
    row.remove(row.find(Q("f")))
    with pytest.raises(LayoutError, match="55: faltan B"):
        irl_risk_print_rows(root)


def test_12_risk_rows_cannot_overwrite_merged_cells():
    root = sheet_with_risks(REPORTED_LAYOUT)
    merges = ET.SubElement(root, Q("mergeCells"))
    ET.SubElement(merges, Q("mergeCell"), {"ref": "A45:D45"})
    with pytest.raises(LayoutError, match="celdas combinadas"):
        irl_risk_print_rows(root)


def test_merges_in_far_columns_are_not_mistaken_for_risk_columns():
    root = sheet_with_risks(REPORTED_LAYOUT)
    merges = ET.SubElement(root, Q("mergeCells"))
    ET.SubElement(merges, Q("mergeCell"), {"ref": "AA45:AB45"})
    assert irl_risk_print_rows(root) == (REPORTED_LAYOUT, True)


def test_fixed_record_between_formula_rows_is_rebound_without_moving_headers():
    """The supplied Excel has a fixed CARPINTERO row at 61 among 11 formulas."""
    root = sheet_with_risks(tuple(row for row in REPORTED_LAYOUT if row != 61))
    data = root.find(Q("sheetData"))
    for number in (44, 60):
        heading = ET.SubElement(data, Q("row"), {"r": str(number)})
        for col in "ABCD":
            cell = ET.SubElement(heading, Q("c"), {"r": f"{col}{number}", "s": "4", "t": "inlineStr"})
            ET.SubElement(ET.SubElement(cell, Q("is")), Q("t")).text = "Actividad"
    fixed = ET.SubElement(data, Q("row"), {"r": "61"})
    for col in "ABCD":
        cell = ET.SubElement(fixed, Q("c"), {"r": f"{col}61", "t": "inlineStr"})
        ET.SubElement(ET.SubElement(cell, Q("is")), Q("t")).text = "Contenido fijo que debe sustituirse"
    assert irl_risk_print_rows(root) == (REPORTED_LAYOUT, True)
    fixed.find(Q("c") + "[@r='D61']").remove(
        fixed.find(Q("c") + "[@r='D61']/" + Q("is")))
    with pytest.raises(LayoutError, match="incompletas o desordenadas"):
        irl_risk_print_rows(root)


def test_13th_risk_uses_same_detected_rows_in_continuation_sheet():
    workbook = load_workbook(io.BytesIO(master()))
    matrix = workbook["MATRIZ IRL"]
    for index in range(2, 14):
        matrix.append([index, "CARPINTERO", f"TAREA {index}", "PELIGRO",
                       "RIESGO", "MEDIDA"])
    sheet = workbook["IRL"]
    for number in REPORTED_LAYOUT:
        for dest, source in zip("ABCD", "CDEF"):
            sheet[f"{dest}{number}"] = (
                f"=IF('MATRIZ IRL'!$B$2='Datos Contrato'!$C$29,"
                f"'MATRIZ IRL'!${source}$2,\"\")"
            )
    source = io.BytesIO()
    workbook.save(source)
    result, names = irl_continuations(source.getvalue(), "CARPINTERO")
    assert names == ["IRL continuación 1"]
    first = {cell["cell"]: cell for cell in read_sheet(result, "IRL", 45, 23)["cells"]}
    continued = {cell["cell"]: cell for cell in read_sheet(result, names[0], 45, 23)["cells"]}
    assert "'MATRIZ IRL'!$C$13" in first["A67"]["formula"]
    assert "'MATRIZ IRL'!$C$14" in continued["A45"]["formula"]
    assert "'MATRIZ IRL'!$E$14" in continued["C45"]["formula"]
