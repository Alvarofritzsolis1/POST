"""GALANT 19.4: cinco catálogos técnicos reales del Excel fuente.

Las consultas muestran referencias, pero nunca aprueban controles preventivos,
emiten documentación laboral ni escriben empleados en módulos operativos.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.javiera_api import _check_preventive_matrix_before_approval
from app.javiera_v194_api import (
    catalog, related_catalog, reference_matrices_for_kind, related_for_role,
)
from test_control_api import env, login

EXPECTED = {"IRL": 25, "PTS": 26, "PERFILES": 26, "PUESTOS": 27, "SUSTANCIAS": 27}
COLUMNS = {"IRL": 4, "PTS": 17, "PERFILES": 1, "PUESTOS": 4, "SUSTANCIAS": 12}
ROOT = "/api/v1/javiera/v194"


def test_five_original_sheets_are_available_without_manual_upload():
    assert len(catalog()["role_order"]) == 25
    assert len(catalog()["rows"]) == 338
    assert len(related_catalog()["matrices"]) == 106
    for kind, count in EXPECTED.items():
        rows = reference_matrices_for_kind(kind)
        assert len(rows) == count, kind
        assert all(len(row["sections"]) == COLUMNS[kind] for row in rows), kind
        assert all(row["status"] == "reference" for row in rows)
        assert all(row["revision"] == 0 for row in rows)
        assert all(row["source_approved"] is False for row in rows)
        assert len({row["id"] for row in rows}) == count
    irl = reference_matrices_for_kind("IRL")
    assert sum(len(row["sections"]) for row in irl) == 338
    assert len(next(row for row in irl if row["cargo"] == "GASFITER")["sections"]) == 26
    assert len(next(row for row in irl if row["cargo"] == "PINTOR")["sections"]) == 13


def test_duplicate_original_rows_are_preserved_without_silent_merge():
    gasfiter_pts = related_for_role("PTS", "GASFITER")
    assert len(gasfiter_pts) == 2
    assert gasfiter_pts[0]["source_row"] != gasfiter_pts[1]["source_row"]
    for row in gasfiter_pts:
        assert len(row["sections"]) == 17


def test_source_irl_incomplete_carpintero_must_remain_unapproved():
    row = next(r for r in catalog()["rows"] if r["excel_row"] == 40)
    assert row["cargo"] == "CARPINTERO"
    assert not row["riesgo"] and not row["medidas"]
    irl = next(r for r in reference_matrices_for_kind("IRL") if r["cargo"] == "CARPINTERO")
    assert len(irl["sections"]) == 13
    new_draft = SimpleNamespace(kind="IRL", source="Editor visual GALANT 19.4",
                                sections=irl["sections"])
    with pytest.raises(HTTPException) as exc:
        _check_preventive_matrix_before_approval(new_draft)
    assert exc.value.status_code == 422
    assert "Riesgo" in exc.value.detail


def test_source_matrices_are_displayed_by_type_and_do_not_require_upload(env):
    client, sessions = env
    headers = login(client, "a@example.cl")
    for kind, expected in EXPECTED.items():
        res = client.get(ROOT + "/reference-matrices", params={"kind": kind}, headers=headers)
        assert res.status_code == 200, (kind, res.text)
        response = res.json()
        assert response["source_rows"] == expected, kind
        assert len(response["columns"]) == COLUMNS[kind], kind
        assert len(response["rows"]) == expected
        assert response["historical_pdfs_unchanged"] is True
        assert response["source_status"] == "reference_only_pending_preventive_review"
    pts = client.get(ROOT + "/reference-matrices", params={"kind": "PTS"}, headers=headers)
    assert any(group["cargo"] == "GASFITER" and len(group["source_rows"]) == 2
               for group in pts.json()["variants"])
    invalid = client.get(ROOT + "/reference-matrices", params={"kind": "OTRA"}, headers=headers)
    assert invalid.status_code == 422
    anonymous = client.get(ROOT + "/reference-matrices", params={"kind": "IRL"})
    assert anonymous.status_code in (401, 403)


def test_role_includes_related_reference_contents_without_approval(env):
    client, sessions = env
    headers = login(client, "a@example.cl")
    result = client.get(ROOT + "/role", params={"cargo": "PINTOR"}, headers=headers)
    assert result.status_code == 200, result.text
    detail = result.json()
    assert detail["source_excel_available"] is True
    assert detail["reference_total"] == 13
    assert len(detail["reference_records"]) == 13
    for kind, count in (("PERFILES", 1), ("PUESTOS", 4), ("SUSTANCIAS", 12)):
        matrix = detail["additional_matrices"][kind]
        assert len(matrix["sections"]) == count
    if not detail["pts"]["approved"]:
        assert detail["pts"]["reference_only"] is True
        assert len(detail["pts"]["sections"]) == 17
    if not detail["irl"]["approved"]:
        assert detail["irl"]["reference_only"] is True
        assert detail["can_preview_irl"] is False
