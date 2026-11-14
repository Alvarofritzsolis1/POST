"""Regression: original Excel has 23 PTS role formulas + a shared Gasfiter row.

Missing cached results are NOT missing technical procedures. This test
recreates the actual OOXML relation without bundling any private worker data.
"""
import io
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app.javiera_excel import Q, ensure_cell, set_text, sheet_files, shared_strings
from app.javiera_workbook import (
    _matrix_rows, audit_preventive_master, edit_workbook,
    matrix_records, pack, roles, xml,
)
from test_javiera_all_roles_contract import ROLES, all_roles_master


def synthetic_uncached_pts() -> bytes:
    raw = all_roles_master.__wrapped__()
    with ZipFile(io.BytesIO(raw)) as archive:
        paths = sheet_files(archive)
        irl = ET.fromstring(archive.read(paths["MATRIZ IRL"]))
        pts = ET.fromstring(archive.read(paths["MATRIZ PTS"]))
        for row, role in enumerate(ROLES, start=2):
            ref = "AN" + str(row + 3)
            set_text(irl, ref, role)
            cell = ensure_cell(pts, "A" + str(row))
            for child in list(cell):
                cell.remove(child)
            cell.set("t", "str")
            ET.SubElement(cell, Q("f")).text = "'MATRIZ IRL'!" + ref
            # Deliberately OMIT the cached <v>, as clean_master() does.
        set_text(pts, "A27", "GASFITER")
        # Same-sheet copy from the existing Gasfiter procedure on row 2.
        for col in "DEFGHIJKLMNOPQRST":
            address = col + "27"
            cell = ensure_cell(pts, address)
            for child in list(cell):
                cell.remove(child)
            cell.set("t", "str")
            f = ET.SubElement(cell, Q("f"), {"t": "shared", "si": "11"})
            if col == "D":
                f.set("ref", "D27:T27")
                f.text = "D2"
        return pack(archive, {
            paths["MATRIZ IRL"]: xml(irl),
            paths["MATRIZ PTS"]: xml(pts),
        })


def test_25_roles_and_shared_pts_are_valid_without_cached_formula_results():
    raw = synthetic_uncached_pts()
    index = roles(raw)
    assert {role for role in index if "PTS" in index[role]} == set(ROLES)
    assert index["GASFITER"]["PTS"] == [2, 27]
    gas = matrix_records(raw, "GASFITER", "PTS")
    assert len(gas) == 2
    for col in "DEFGHIJKLMNOPQRST":
        assert gas[0]["values"][col] == gas[1]["values"][col]
    report = audit_preventive_master(raw)
    assert report["roles_total"] == 25
    assert report["blocking_count"] == 0, report["findings"]


def test_unrelated_edit_does_not_invent_25_pts_errors():
    raw = synthetic_uncached_pts()
    updated = edit_workbook(raw, "Datos Contrato", [])
    result = audit_preventive_master(updated)
    assert result["blocking_count"] == 0, result["findings"]
    assert len([role for role in roles(updated) if "PTS" in roles(updated)[role]]) == 25


def test_real_missing_pts_field_is_still_reported():
    raw = synthetic_uncached_pts()
    from app.javiera_workbook import edit_workbook
    updated = edit_workbook(raw, "MATRIZ PTS", [
        {"cell": "K3", "value": ""}
    ])
    report = audit_preventive_master(updated)
    assert any(entry["code"] == "EMPTY_PTS"
               and entry["role"] == ROLES[1] and entry["cell"] == "K3"
               for entry in report["findings"])
