"""GALANT regression: ALBAÑILERÍA must use the approved ALBAÑIL row.

The two names are verified variants in the supplied Excel. This maps source
keys only and never grants matrix publication or professional signoff.
"""
from types import SimpleNamespace
from zipfile import ZipFile
import io
from xml.etree import ElementTree as ET

import pytest

from app.javiera_logic import normalize_cargo
from app.javiera_excel import Q, cell_text, sheet_files, shared_strings, LayoutError
from app.javiera_workbook import (
    fill_workbook, irl_continuations, matrix_records, resolve_workbook_role, roles,
)
from test_javiera_all_roles_contract import all_roles_master


@pytest.mark.parametrize("entered", ["ALBAÑILERIA", "ALBAÑILERÍA", "ALBAÑIL", "albanileria"])
@pytest.mark.parametrize("kind", ["IRL", "PTS"])
def test_preventive_albanil_alias_uses_exact_source_row(entered, kind):
    master = all_roles_master.__wrapped__()
    assert normalize_cargo(entered) == "ALBANIL"
    name = resolve_workbook_role(roles(master), entered, kind)
    assert name == "ALBAÑIL"
    rows = matrix_records(master, name, kind)
    assert len(rows) == (13 if kind == "IRL" else 1)
    assert rows[0]["values"].get("B" if kind == "IRL" else "A") == "ALBAÑIL"


def test_ir_l_pdf_master_receives_existing_role_not_unmatched_ui_label():
    master = all_roles_master.__wrapped__()
    role = resolve_workbook_role(roles(master), "ALBAÑILERÍA", "IRL")
    filled = fill_workbook(master, {"role": role}, "irl")
    expanded, names = irl_continuations(filled, role)
    assert len(names) == 1
    with ZipFile(io.BytesIO(expanded)) as archive:
        files = sheet_files(archive)
        strings = shared_strings(archive)
        root = ET.fromstring(archive.read(files["Datos Contrato"]))
        source_cell = root.find(".//" + Q("c") + "[@r='C29']")
        assert cell_text(source_cell, strings) == "ALBAÑIL"


def test_unapproved_or_ambiguous_workbook_never_becomes_an_approval():
    with pytest.raises(LayoutError, match="matriz IRL"):
        resolve_workbook_role({}, "ALBAÑILERÍA", "IRL")
    with pytest.raises(LayoutError, match="matriz IRL"):
        resolve_workbook_role({"ALBAÑIL":{"IRL":[2]},
                               "ALBAÑILERÍA":{"IRL":[3]}}, "albanileria", "IRL")


def test_approval_uses_published_workbook_but_never_approves_unpublished(
    monkeypatch,
):
    from app import javiera_api as api
    master = all_roles_master.__wrapped__()
    approved_seen = []
    def eligibility(data, templates, approved, existing, history):
        approved_seen.append(set(approved))
        return [
            {"code":code,"applicability":"aplica","can_issue":True,
             "can_preview":True,"status":"LISTO_PARA_EMITIR","reason":""}
            for code in ("irl","pts","pts_receipt")
        ]
    monkeypatch.setattr(api, "template_data", lambda db, org: {})
    monkeypatch.setattr(api, "eligibility", eligibility)
    monkeypatch.setattr(api, "workbook_roles", lambda raw: roles(master))
    monkeypatch.setattr(api, "raw_for", lambda obj: master)
    present = [False]
    monkeypatch.setattr(api, "active_workbook", lambda db, org_id, **kwargs:
        SimpleNamespace(sha256="synthetic", inventory={"matrix_pending":[]}) if present[0] else None)
    db = SimpleNamespace(execute=lambda query: SimpleNamespace(all=lambda: []))
    user = SimpleNamespace(org_id="qa-org")
    data = {"role":"ALBAÑILERÍA"}
    api.evaluated(db, user, data, dossier_id=None)
    assert not any(key.startswith("IRL:") for key in approved_seen[-1])
    present[0] = True
    api.evaluated(db, user, data, dossier_id=None)
    assert "IRL:ALBANIL" in approved_seen[-1]
    assert "PTS:ALBANIL" in approved_seen[-1]
