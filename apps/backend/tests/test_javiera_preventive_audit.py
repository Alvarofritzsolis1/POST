"""Audit ALL preventive cargo rows, never approve a partial master silently."""
import pytest

from app.javiera_workbook import audit_preventive_master
from test_javiera_workbook import master
from test_javiera_all_roles_contract import all_roles_master


def test_synthetic_incomplete_source_has_exact_problem_cells():
    report = audit_preventive_master(master())
    assert report["roles_total"] >= 1
    assert report["blocking_count"] > 0
    assert any(entry["scope"] == "PTS" and entry["severity"] == "error"
               for entry in report["findings"])
    assert any(entry["scope"] == "IRL" and entry["severity"] == "error"
               for entry in report["findings"])
    assert all("role" in entry and "cell" in entry and "matrix" in entry
               for entry in report["findings"])


def test_25_synthetic_roles_reach_clean_blocking_audit():
    report = audit_preventive_master(all_roles_master.__wrapped__())
    assert report["roles_total"] == 25
    assert report["blocking_count"] == 0, report["findings"]
    assert all(entry["severity"] == "warning" for entry in report["findings"])
