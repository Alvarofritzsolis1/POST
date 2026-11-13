"""GALANT 20.2.4: validación cruzada de los diez documentos y EPP reales.

Datos 100 % sintéticos. No se eliminan aprobaciones, firmas ni matrices.
La fidelidad contra un Excel privado de producción requiere una prueba separada.
"""
import copy
import io
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest
from app.javiera_epp import EPP_NAMES, EppInputError, epp_quantities
from app.javiera_logic import DOCUMENTS, LAYOUT_REQUIRED, eligibility, validate_requirements
from app.javiera_workbook import delivery_quantities, fill_workbook
from app.javiera_excel import DOC_SHEETS, Q, sheet_files, shared_strings, cell_text
from test_javiera_workbook import master
from test_platform import rut


def complete_data(code="labor_contract"):
    data = {
        "employer": {"name": "EMPRESA FICTICIA QA", "rut": rut(10000123)},
        "worker": {"name": "PERSONA FICTICIA QA", "rut": rut(10000124)},
        "site": {"name": "OBRA DE PRUEBA"},
        "role": "CARPINTERO",
        "employment_type": "dependiente", "event_type": "ingreso",
        "requested_documents": [code],
        "contract": {
            "start": "2026-11-03", "end": "2026-12-10",
            "new_end": "2027-02-10", "transfer_date": "2026-11-14",
            "salary": "850000", "hours": "42",
            "declaration_reason": "Ausencia de trabajadores en período informado",
            "regulation_version": "Revisión aprobada de prueba",
        },
        "event": {"date": "2026-11-13", "epp_items": "1 x Casco de Seguridad",
                  "pts_version": "Revisión aprobada QA"},
        "extra": {
            "representative_name": "REPRESENTANTE SINTETICO QA",
            "representative_rut": rut(10000125), "representative_nationality": "CHILENA",
            "employer_address": "CALLE DE PRUEBA 123",
            "employer_commune": "CORONEL", "employer_city": "CONCEPCION",
            "worker_nationality": "CHILENA", "worker_birthdate": "1995-02-12",
            "worker_marital_status": "SOLTERO", "worker_address": "DOMICILIO SINTETICO",
            "worker_commune": "LOTA", "worker_city": "CONCEPCION",
            "payment_frequency": "MENSUAL", "bank_account": "TRANSFERENCIA DE PRUEBA",
            "afp": "AFP FICTICIA", "health_provider": "SISTEMA DE PRUEBA",
            "site_address": "DOMICILIO OBRA SINTETICA",
            "specialty": "CARPINTERIA", "principal_company": "MANDANTE DE PRUEBA",
            "declaration_period": "2026-10", "employer_phone": "555123456",
        },
    }
    if code == "sworn_declaration":
        data["worker"] = {"name": "", "rut": ""}
    return data


def published():
    return {
        code: {
            "fields": list(dict.fromkeys([*required, *LAYOUT_REQUIRED.get(code, [])])),
            "published_version": 1, "has_body": True, "rule": {},
        }
        for code, _, _, _, required in DOCUMENTS
    }


MATRICES = {"IRL:CARPINTERO", "PTS:CARPINTERO"}
CODES = tuple(DOC_SHEETS)


@pytest.mark.parametrize("code", CODES)
def test_ten_documents_have_valid_synthetic_inputs_and_are_not_falsely_blocked(code):
    data = complete_data(code)
    row = next(x for x in eligibility(data, published(), MATRICES) if x["code"] == code)
    assert row["status"] == "LISTO_PARA_EMITIR", (code, row)
    assert row["can_issue"] is True
    assert row["missing_fields"] == []
    assert row["blocking_errors"] == []


@pytest.mark.parametrize("code,field", [
    ("labor_contract", "contract.salary"),
    ("transfer_addendum", "contract.transfer_date"),
    ("extension_addendum", "contract.new_end"),
    ("sworn_declaration", "extra.declaration_period"),
    ("internal_rules_receipt", "extra.employer_commune"),
    ("ppe_delivery", "event.epp_items"),
    ("irl", "role"),
    ("pts", "extra.representative_rut"),
    ("pts_receipt", "event.pts_version"),
    ("induction", "extra.principal_company"),
])
def test_ten_documents_detect_missing_fact_before_pdf(code, field):
    data = complete_data(code)
    node = data
    parts = field.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = ""
    row = next(x for x in eligibility(data, published(), MATRICES) if x["code"] == code)
    assert row["status"] == "FALTAN_DATOS", (code, row)
    assert field in row["missing_fields"]
    assert row["can_issue"] is False


@pytest.mark.parametrize("bad", [
    "13-11-2026", "2026-11-13", "13/11/2026", "Guantes",
    "Ninguno", "Elementos varios", "31 x Casco de Seguridad",
])
def test_invalid_or_ambiguous_epp_are_blocked_before_pdf(bad):
    data = complete_data("ppe_delivery")
    data["event"]["epp_items"] = bad
    row = next(x for x in eligibility(data, published(), MATRICES) if x["code"] == "ppe_delivery")
    assert row["status"] == "FALTAN_DATOS", (bad, row)
    assert not row["can_issue"]
    assert any("event.epp_items" in error for error in row["blocking_errors"])
    with pytest.raises(EppInputError):
        epp_quantities(bad)


@pytest.mark.parametrize("date_value", ["13-11-2026", "2026-11-13"])
def test_date_in_epp_has_explicit_field_correction_instead_of_matrix_error(date_value):
    with pytest.raises(EppInputError, match="fecha, no un EPP"):
        epp_quantities(date_value)


def test_all_eight_epp_map_to_original_excel_rows_without_default_deliveries():
    data = complete_data("ppe_delivery")
    data["event"]["epp_items"] = "; ".join("1 x " + name for name in EPP_NAMES)
    assert epp_quantities(data["event"]["epp_items"]) == [1] * 8
    assert delivery_quantities(data["event"]["epp_items"]) == [1] * 8
    original = master()
    updated = fill_workbook(original, data, "ppe_delivery")
    with ZipFile(io.BytesIO(updated)) as z:
        doc = ET.fromstring(z.read(sheet_files(z)[DOC_SHEETS["ppe_delivery"]]))
        strings = shared_strings(z)
        for row in range(12, 20):
            cell = doc.find(".//" + Q("c") + "[@r='D" + str(row) + "']")
            assert cell_text(cell, strings) == "1"


def test_only_reported_epp_are_printed_and_date_never_becomes_quantity():
    data = complete_data("ppe_delivery")
    data["event"]["date"] = "2026-11-13"
    data["event"]["epp_items"] = "2 x Guantes de Cabritilla; 1 x Casco de Seguridad"
    expected = [1, 0, 0, 2, 0, 0, 0, 0]
    assert epp_quantities(data["event"]["epp_items"]) == expected
    updated = fill_workbook(master(), data, "ppe_delivery")
    with ZipFile(io.BytesIO(updated)) as z:
        root = ET.fromstring(z.read(sheet_files(z)[DOC_SHEETS["ppe_delivery"]]))
        strings = shared_strings(z)
        for row, amount in enumerate(expected, 12):
            cell = root.find(".//" + Q("c") + "[@r='D" + str(row) + "']")
            assert cell_text(cell, strings) == (str(amount) if amount else "")


def test_epp_legacy_aliases_preserved_but_ambiguous_shortcuts_not_allowed():
    assert epp_quantities("1 casco; 2 x zapatos de seguridad; lentes")[:3] == [1, 2, 1]
    with pytest.raises(EppInputError, match="ambiguo"):
        epp_quantities("Guantes")
    assert len(EPP_NAMES) == 8
