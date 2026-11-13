"""GALANT 20.2.1: selección explícita de documentos y reglas de emisión seguras.
Pruebas deterministas y sintéticas, sin documentos ni identidades reales.
"""
from app.javiera_logic import DOCUMENTS, eligibility


def published_templates():
    return {code: {"fields": fields, "published_version": 1, "has_body": True, "rule": {}}
            for code, _, _, _, fields in DOCUMENTS}


def data_for_extension():
    return {
        "employer": {"name": "EMPRESA DE PRUEBA", "rut": "11.111.111-1"},
        "worker": {"name": "PERSONA DE PRUEBA", "rut": "11.111.111-1"},
        "site": {"name": "OBRA DE PRUEBA"},
        "employment_type": "dependiente",
        "event_type": "ingreso",
        "contract": {"end": "2026-11-30", "new_end": "2026-12-15"},
    }


def status(data, code, templates=None):
    return next(row for row in eligibility(data, templates or published_templates())
                if row["code"] == code)


def test_explicitly_requested_extension_does_not_require_hidden_event_selector():
    data = data_for_extension()
    data["requested_documents"] = ["extension_addendum"]
    doc = status(data, "extension_addendum")
    assert doc["status"] == "LISTO_PARA_EMITIR"
    assert doc["can_issue"] is True


def test_legacy_unselected_extension_retains_previous_applicability():
    doc = status(data_for_extension(), "extension_addendum")
    assert doc["status"] == "NO_APLICA"
    assert doc["can_issue"] is False


def test_selected_extension_never_skips_new_end_requirement():
    data = data_for_extension()
    data["requested_documents"] = ["extension_addendum"]
    data["contract"]["new_end"] = ""
    doc = status(data, "extension_addendum")
    assert doc["status"] == "FALTAN_DATOS"
    assert "contract.new_end" in doc["missing_fields"]
    assert doc["can_issue"] is False


def test_selected_employment_contract_still_requires_dependent_context():
    data = data_for_extension()
    data["requested_documents"] = ["labor_contract"]
    data["employment_type"] = "independiente"
    doc = status(data, "labor_contract")
    assert doc["status"] == "NO_APLICA"
    assert doc["can_issue"] is False


def test_explicit_selection_does_not_bypass_published_custom_rules():
    data = data_for_extension()
    data["requested_documents"] = ["extension_addendum"]
    templates = published_templates()
    templates["extension_addendum"]["rule"] = {"events": ["prorroga"]}
    doc = status(data, "extension_addendum", templates)
    assert doc["status"] == "NO_APLICA"
    assert doc["can_issue"] is False


def test_selection_cannot_enable_unpublished_template():
    data = data_for_extension()
    data["requested_documents"] = ["extension_addendum"]
    templates = published_templates()
    templates["extension_addendum"]["published_version"] = 0
    doc = status(data, "extension_addendum", templates)
    assert doc["status"] == "PENDIENTE_REVISION"
    assert doc["can_issue"] is False


def test_selection_cannot_override_invalid_dates():
    data = data_for_extension()
    data["requested_documents"] = ["extension_addendum"]
    data["contract"]["new_end"] = "2026-11-01"
    doc = status(data, "extension_addendum")
    assert doc["status"] == "FALTAN_DATOS"
    assert any("contract.new_end" in message for message in doc["blocking_errors"])
