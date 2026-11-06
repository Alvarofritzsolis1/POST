"""QA aislada de GALANT 16: motor declarativo JAVIERA y protección de documentos."""
import pytest

from app.javiera_logic import (
    DOCUMENTS, check_template_fields, eligibility,
    normalize_cargo, render_tokens, rut_valid, validate_requirements,
)
from app.javiera_api import pdf_for


def sample():
    return {
        "employer": {"name": "EMPRESA PRUEBA", "rut": "11.111.111-1"},
        "worker": {"name": "PERSONA DE PRUEBA", "rut": "11.111.111-1"},
        "site": {"name": "OBRA SINTETICA"},
        "role": "Carpintero",
        "employment_type": "dependiente",
        "event_type": "ingreso",
        "contract": {"start": "2026-11-01", "end": "2026-11-30", "salary": "650000", "hours": "42"},
        "event": {"date": "2026-11-02", "epp_items": "Casco", "pts_version": "1"},
    }


def test_document_areas_and_ten_pieces():
    assert len(DOCUMENTS) == 10
    assert len({x[0] for x in DOCUMENTS}) == len(DOCUMENTS)
    assert {x[1] for x in DOCUMENTS} == {"Zona Subcontratos", "Prevención de Riesgos"}


def test_rut_chileno_and_cargos():
    assert rut_valid("11.111.111-1")
    assert not rut_valid("11.111.111-2")
    assert not rut_valid("12.345.678-?")
    assert normalize_cargo("  techádor ") == "TECHADOR"


def test_missing_and_dates_block_export():
    data = sample()
    data["worker"]["rut"] = "12.345.678-X"
    data["contract"]["end"] = "2026-10-20"
    missing, errors = validate_requirements(
        data, ["worker.rut", "contract.start", "contract.end"])
    assert not missing
    assert "worker.rut: RUT inválido" in errors
    assert any("término anterior" in e for e in errors)


def test_readiness_needs_template_approval():
    data = sample()
    templates = {"labor_contract": {"published_version": 0, "has_body": True}}
    row = next(r for r in eligibility(data, templates) if r["code"] == "labor_contract")
    assert row["status"] == "PENDIENTE_REVISION"
    assert not row["can_issue"]
    templates["labor_contract"]["published_version"] = 1
    row = next(r for r in eligibility(data, templates) if r["code"] == "labor_contract")
    assert row["status"] == "LISTO_PARA_EMITIR"
    assert row["can_issue"]


def test_independents_not_assumed_dependent():
    data = sample()
    data["employment_type"] = "independiente"
    row = next(r for r in eligibility(data, {"labor_contract": {"published_version": 1}}) if r["code"] == "labor_contract")
    assert row["status"] == "NO_APLICA"
    assert not row["can_issue"]


def test_preventive_pts_and_irl_require_different_approved_matrices():
    templates = {
        "pts": {"published_version": 1, "has_body": True},
        "irl": {"published_version": 1, "has_body": True},
    }
    data = sample()
    rows = {r["code"]: r for r in eligibility(data, templates, {"PTS:CARPINTERO"})}
    assert rows["pts"]["status"] == "LISTO_PARA_EMITIR"
    assert rows["irl"]["status"] == "PENDIENTE_REVISION"


def test_unverified_historical_pdf_never_claimed_valid():
    data = sample()
    row = next(r for r in eligibility(data, {}, historical={"pts"}) if r["code"] == "pts")
    assert row["status"] == "EXISTENTE_POR_VERIFICAR"
    assert not row["can_issue"]


def test_issued_reused_without_overwrite():
    data = sample()
    row = next(r for r in eligibility(data, {}, existing={"labor_contract"}) if r["code"] == "labor_contract")
    assert row["status"] == "EMITIDO"
    assert not row["can_issue"]


def test_template_disallows_unsafe_tokens_and_incomplete_fields():
    assert render_tokens("Hola {{worker.name}}", sample()) == "Hola PERSONA DE PRUEBA"
    with pytest.raises(ValueError):
        check_template_fields(["worker.name"], "{{worker.name}} {{worker.rut}}")
    with pytest.raises(ValueError):
        render_tokens("{{worker.unknown}}", sample())
    with pytest.raises(ValueError):
        check_template_fields(["__class__"], "{{__class__}}")


def test_pdf_A4_preview_and_real_differ():
    import fitz
    draft = pdf_for("PTS DE PRUEBA", "Texto de ejemplo\nSegundo párrafo", True)
    approved = pdf_for("PTS DE PRUEBA", "Texto de ejemplo", False)
    assert draft.startswith(b"%PDF-")
    assert approved.startswith(b"%PDF-")
    with fitz.open(stream=draft, filetype="pdf") as doc:
        assert doc.page_count >= 1
        assert "VISTA PREVIA" in doc[0].get_text()
        assert round(doc[0].rect.width) == 595
    with fitz.open(stream=approved, filetype="pdf") as doc:
        assert "VISTA PREVIA" not in doc[0].get_text()



@pytest.mark.parametrize("when,limit", [
    ("2024-04-25", 45),
    ("2024-04-26", 44),
    ("2026-04-25", 44),
    ("2026-04-26", 42),
    ("2028-04-25", 42),
    ("2028-04-26", 40),
])
def test_jornada_general_historica_aplica_en_fecha_del_documento(when, limit):
    from app.javiera_logic import ordinary_weekly_hours_limit
    assert ordinary_weekly_hours_limit(when) == limit
    data = sample()
    data["event"]["date"] = when
    data["contract"]["hours"] = str(limit)
    missing, errors = validate_requirements(data, ["event.date", "contract.hours"])
    assert missing == []
    assert not any("contract.hours" in e for e in errors)
    data["contract"]["hours"] = str(limit + 1)
    _, errors = validate_requirements(data, ["event.date", "contract.hours"])
    assert any("contract.hours" in e for e in errors)
