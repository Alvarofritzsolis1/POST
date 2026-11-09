"""Prueba sin datos privados de la auditoría de fórmulas Excel OOXML."""
from pathlib import Path
from runpy import run_path
from zipfile import ZipFile

AUDITOR = run_path(str(Path(__file__).resolve().parents[3] /
                       "scripts" / "qa_javiera_formula_parity.py"))
compare_workbooks = AUDITOR["compare_workbooks"]


def _book(path, formula="SUM(1,2)", cached="3"):
    with ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", (
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Datos" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ))
        z.writestr("xl/_rels/workbook.xml.rels", (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet"'
            ' Target="worksheets/sheet1.xml"/></Relationships>'
        ))
        z.writestr("xl/worksheets/sheet1.xml", (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1"><c r="A1"><f>' + formula + '</f><v>'
            + cached + '</v></c></row></sheetData></worksheet>'
        ))


def test_formula_auditor_detects_changes_and_cached_drift(tmp_path):
    original = tmp_path / "before.xlsx"
    same = tmp_path / "same.xlsx"
    changed_formula = tmp_path / "formula.xlsx"
    changed_cache = tmp_path / "cache.xlsx"
    _book(original)
    _book(same)
    _book(changed_formula, "SUM(1,3)", "4")
    _book(changed_cache, "SUM(1,2)", "9")

    good = compare_workbooks(original, same, min_formulas=1)
    assert good["passed"] is True
    assert good["original"]["formula_count"] == 1
    assert good["changed_formula_cell_count"] == 0
    assert good["changed_cached_cell_count"] == 0

    bad_formula = compare_workbooks(original, changed_formula, min_formulas=1)
    assert bad_formula["passed"] is False
    assert bad_formula["changed_formula_cell_refs"] == ["Datos!A1"]
    bad_cache = compare_workbooks(original, changed_cache, min_formulas=1)
    assert bad_cache["passed"] is False
    assert bad_cache["changed_formula_cell_count"] == 0
    assert bad_cache["changed_cached_cell_refs"] == ["Datos!A1"]


def test_formula_auditor_requires_minimum_original_count(tmp_path):
    file = tmp_path / "file.xlsx"
    _book(file)
    assert compare_workbooks(file, file, min_formulas=423)["passed"] is False
