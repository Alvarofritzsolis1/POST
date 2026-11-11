"""Auditoría automatizada de correcciones propuestas; nunca constituye firma profesional."""
from app.javiera_irl_corrective_drafts import (
    corrective_draft_for_role, merged_draft_sections, REQUIRED_SDS_FIELDS,
)
from app.javiera_v194_api import catalog, related_for_role, reference_detail
from test_control_api import env, login


def test_carpintero_row40_proposal_is_fully_populated_without_editing_source():
    original = [dict(row) for row in catalog()["rows"] if row["cargo"] == "CARPINTERO"]
    before = {row["excel_row"]: dict(row) for row in original}
    result = corrective_draft_for_role("CARPINTERO", original)
    assert result["type"] == "risk_row"
    assert result["approval_status"] == "requires_independent_prevention_signoff"
    proposed = result["proposal"]
    assert proposed["excel_row"] == 40
    assert "Contacto eléctrico" in proposed["risk_suggestion"]
    assert "retirar de servicio" in proposed["controls_suggestion"]
    assert "faena" in proposed["controls_suggestion"]
    assert original == list(before.values())  # Nunca mutar la referencia.
    assert before[40]["riesgo"] == before[40]["medidas"] == ""


def test_carpintero_editor_draft_has_all_thirteen_source_rows_and_four_fields():
    rows = [dict(row) for row in catalog()["rows"] if row["cargo"] == "CARPINTERO"]
    correction = corrective_draft_for_role("CARPINTERO", rows)
    sections = merged_draft_sections(rows, correction)
    assert len(sections) == 13
    for section in sections:
        for field in ("Tarea:", "Peligro:", "Riesgo:", "Medidas:"):
            assert field in section
    assert any("Inspección, mantención y almacenamiento de EPP" in section
               and "Contacto eléctrico" in section
               for section in sections)
    # El catálogo original no puede ser modificado ni aprobado por este código.
    assert [row for row in rows if row["excel_row"] == 40][0]["medidas"] == ""


def test_no_guessing_when_carpintero_original_is_already_corrected():
    rows = [dict(row) for row in catalog()["rows"] if row["cargo"] == "CARPINTERO"]
    target = next(row for row in rows if row["excel_row"] == 40)
    target["riesgo"] = "Evaluación aprobada por otra fuente"
    target["medidas"] = "Medidas realmente verificadas"
    assert corrective_draft_for_role("CARPINTERO", rows)["type"] == "none"


def test_paisajista_sds_requires_real_products_and_all_twelve_fields():
    result = corrective_draft_for_role("PAISAJISTA", catalog()["rows"])
    assert result["type"] == "chemical_inventory"
    assert result["approval_status"] == "requires_real_sds_and_prevention_signoff"
    assert related_for_role("SUSTANCIAS", "PAISAJISTA") == []
    form = result["proposal"]["template"]
    assert len(form) == len(REQUIRED_SDS_FIELDS) == 12
    assert all(item["value"] is None and item["source"] == "pendiente"
               for item in form)
    assert result["proposal"]["source_alias_not_accepted"] == "PAISAJISMO (REVISAR HDS)"


def test_other_roles_do_not_receive_carpintero_or_paisajista_facts():
    for cargo in ("PINTOR", "GASFITER", "SOLDADOR"):
        assert corrective_draft_for_role(cargo, catalog()["rows"])["type"] == "none"


def test_admin_role_api_exposes_proposals_without_changing_approval(env):
    client, _ = env
    headers = login(client, "a@example.cl")
    for cargo, expected in (("CARPINTERO", "risk_row"),
                            ("PAISAJISTA", "chemical_inventory")):
        response = client.get("/api/v1/javiera/v194/role",
                              params={"cargo": cargo}, headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()
        draft = data["corrective_draft"]
        assert draft["type"] == expected
        assert draft["source_preserved"] is True
        assert data["irl"]["approved"] is False
        if cargo == "CARPINTERO":
            assert len(draft["editor_draft_sections"]) == 13
            assert data["reference_audit"]["incomplete_excel_rows"] == [40]
        else:
            assert draft["proposal"]["template"][0]["value"] is None
            assert data["reference_audit"]["linked"]["SUSTANCIAS"]["missing"] is True
