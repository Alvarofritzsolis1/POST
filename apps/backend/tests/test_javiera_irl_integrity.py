"""Regresiones del parche IRL: no fusionar ni aprobar datos incorrectos."""
from app.javiera_irl_integrity import audit_reference_role
from app.javiera_v194_api import catalog, related_catalog


def audit(cargo):
    data = catalog()
    return audit_reference_role(cargo, data["rows"], related_catalog()["matrices"])


def test_risks_keep_all_four_fields_linked_by_source_row():
    painter = audit("PINTOR")
    assert painter["risk_count"] == 13  # La vista no trunca a 12.
    assert len(set(painter["source_excel_rows"])) == 13
    assert painter["risk_records_linked_by_row"] is True
    assert painter["incomplete_excel_rows"] == []
    for excel_row in painter["source_excel_rows"]:
        risk = next(row for row in catalog()["rows"] if row["excel_row"] == excel_row)
        assert all(risk[key] for key in ("tarea", "peligro", "riesgo", "medidas"))


def test_duplicate_gasfiter_blocks_remain_explicitly_ambiguous():
    result = audit("GASFITER")
    assert result["risk_count"] == 26
    assert len(result["duplicate_source_numbers"]) == 13
    assert result["linked"]["PERFILES"]["match_count"] == 2
    assert result["linked"]["PERFILES"]["ambiguous"] is True
    assert result["linked"]["PTS"]["ambiguous"] is True
    assert result["source_is_not_automatically_approved"] is True


def test_unresolved_carpintero_risk_is_audit_failure():
    result = audit("CARPINTERO")
    assert 40 in result["incomplete_excel_rows"]
    assert result["full_excel_parity_certified"] is False
    assert any("40" in warning for warning in result["warnings"])


def test_paisajista_alias_is_suggestion_not_automatic_chemical_matrix():
    result = audit("PAISAJISTA")
    substances = result["linked"]["SUSTANCIAS"]
    assert substances["missing"] is True
    assert substances["match_count"] == 0
    assert substances["suggested_aliases_pending_review"] == ["PAISAJISMO"]
    assert substances["source_entries"] == []


def test_source_soldador_profile_is_not_automatically_certified():
    result = audit("SOLDADOR")
    # El catálogo corregido del repo puede contener este perfil aunque
    # faltara en el XLSX original: se preserva sin considerarlo aprobación.
    assert result["linked"]["PERFILES"]["match_count"] == 1
    assert result["linked"]["PERFILES"]["source_entries"][0]["reference_only"] is True


def test_all_five_untranscribed_visual_blocks_are_disclosed():
    result = audit("PINTOR")
    assert len(result["original_visual_blocks"]) == 5
    assert all(item["status"] == "pending_html_transcription_and_review"
               for item in result["original_visual_blocks"])
    assert result["full_excel_parity_certified"] is False
    assert any("cinco bloques" in w for w in result["warnings"])
