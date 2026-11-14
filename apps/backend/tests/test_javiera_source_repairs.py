"""Source-backed repair: no reupload, no silent publication, no loss of print areas."""
import io
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl import load_workbook

from app.javiera_excel import Q, cell_text, sheet_files, shared_strings
from app.javiera_repair_catalog import proposed_repairs
from app.javiera_workbook import (
    edit_workbook, inventory, roles, pack, xml,
)
from test_control_api import env
from test_javiera_workbook import master, prepare
import test_javiera_workbook


def repairable() -> bytes:
    book = load_workbook(io.BytesIO(master()))
    risk = book["MATRIZ IRL"]
    risk["B40"] = "CARPINTERO"
    risk["C40"] = "Inspección, mantención y almacenamiento de EPP y extensiones eléctricas"
    risk["D40"] = "Cables eléctricos en el suelo expuestos al tránsito, enchufes dañados y EPP en mal estado."
    risk["E40"] = None
    risk["F40"] = None
    risk["B145"] = "IMPERMEABILIZADOR"
    risk["C145"] = "Despliegue y preparación de frentes para MEMBRANA ASFALTICA"
    risk["AN2"] = "CARPINTERO"
    optim = book["Matriz IRL Optimizada"]
    for col, value in zip("ABCDE", (
        "MEMBRANA ASFALTICA", "Losas impermeabilizadas", "Productos expuestos",
        "Segregar peligros", "Herramientas de aplicación"
    )):
        optim[f"{col}13"] = value
    book["MATRIZ PTS"]["A2"] = "='MATRIZ IRL'!AN2"
    output = io.BytesIO()
    book.save(output)
    # Real source has Excel cached text on this simple direct-reference key.
    # Reproduce this exact OOXML state without needing Calc in the fixture.
    with ZipFile(io.BytesIO(output.getvalue())) as archive:
        sheet_path = sheet_files(archive)["MATRIZ PTS"]
        root = ET.fromstring(archive.read(sheet_path))
        cell = root.find(".//" + Q("c") + "[@r='A2']")
        assert cell is not None and cell.find(Q("f")) is not None
        cell.set("t", "str")
        ET.SubElement(cell, Q("v")).text = "CARPINTERO"
        return pack(archive, {sheet_path: xml(root)})


def test_user_provided_repair_creates_derived_cells_without_changing_print_geometry():
    raw = repairable()
    before = inventory(raw)
    changes, trace = proposed_repairs(raw)
    assert len(trace) == 7, trace
    assert set(changes) == {"MATRIZ IRL", "Matriz IRL Optimizada"}
    # The imported Excel may not carry Calc cache values yet; the edited
    # revision must reconstruct this deterministic role key on its own.
    updated = raw
    for sheet, edits in changes.items():
        updated = edit_workbook(updated, sheet, edits)
    after = inventory(updated)
    assert after["media"] == before["media"]
    assert after["print_area_count"] == before["print_area_count"]
    assert after["formula_count"] == before["formula_count"]
    assert roles(updated)["CARPINTERO"]["PTS"] == [2]
    assert proposed_repairs(updated) == ({}, [])
    with ZipFile(io.BytesIO(updated)) as archive:
        sheets = sheet_files(archive)
        strings = shared_strings(archive)
        risk = ET.fromstring(archive.read(sheets["MATRIZ IRL"]))
        summary = ET.fromstring(archive.read(sheets["Matriz IRL Optimizada"]))
        assert all(cell_text(risk.find(".//"+Q("c")+f"[@r='{ref}']"), strings)
                   for ref in ("E40", "F40"))
        assert cell_text(summary.find(".//"+Q("c")+"[@r='A14']"), strings) == "IMPERMEABILIZADOR"


def test_repair_api_creates_unpublished_revision_and_never_requires_another_upload(
    env, monkeypatch, tmp_path
):
    source = repairable()
    monkeypatch.setattr(test_javiera_workbook, "master", lambda: source)
    client, sessions, headers, imported = prepare(env, monkeypatch, tmp_path)
    master_url = "/api/v1/javiera/workbook/" + imported["id"]
    response = client.post(master_url + "/repair-known-gaps", headers=headers, json={
        "expected_revision": imported["revision"],
        "confirmation": "CREAR_BORRADOR_PREVENTIVO",
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["corrected_cells"]) == 7
    assert result["ready_without_approval_step"] is True
    assert result["inventory"]["media"] == imported["inventory"]["media"]
    assert result["inventory"]["print_area_count"] == imported["inventory"]["print_area_count"]
    state = client.get("/api/v1/javiera/workbook").json()
    assert state["current"]["id"] == result["id"]
    assert state["publications"]["irl"] == result["id"]
    # No manual approval endpoint is part of the flow anymore.
    assert client.post("/api/v1/javiera/workbook/" + result["id"] + "/repair-known-gaps",
        headers=headers, json={
            "expected_revision": result["revision"],
            "confirmation": "CREAR_BORRADOR_PREVENTIVO",
        }).status_code == 409
