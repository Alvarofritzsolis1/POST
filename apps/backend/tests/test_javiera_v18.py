"""GALANT 18 print-profile quality checks without using private personal records."""
from io import BytesIO
from fastapi import Response
import fitz
from sqlalchemy import select

from app.config import settings
from app.javiera_models import JavieraExcelLayout
from test_control_api import env, login
from test_javiera_excel_layout import sample_xlsx

ROOT = "/api/v1/javiera/v18"


def test_all_ten_print_profiles_are_scoped_and_a4(env):
    client, _ = env
    headers = login(client, "a@example.cl")
    response = client.get(ROOT + "/print-profiles", headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["count"] == 10
    assert len(result["profiles"]) == 10
    assert all(x["size"] == "A4" and x["fit_height_pages"] == 0
               for x in result["profiles"])
    assert next(x for x in result["profiles"]
                if x["code"] == "internal_rules_receipt")["range"] == "A1:G12"
    assert next(x for x in result["profiles"]
                if x["code"] == "labor_contract")["range"] == "A1:C36"
    assert result["auto_approves"] is False


def test_preflight_reports_formula_count_and_pdf_bounds_without_approving(env, tmp_path, monkeypatch):
    client, sessions = env
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path))
    settings.cache_clear()
    headers = login(client, "a@example.cl")
    uploaded = client.post("/api/v1/javiera/v17/library/import", headers=headers, files={
        "file": ("PLANTILLAS_SINTETICAS.xlsx", sample_xlsx(),
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    })
    assert uploaded.status_code == 200, uploaded.text
    library = client.get("/api/v1/javiera/v17/library", headers=headers).json()
    layout_id = next(x["layout_id"] for x in library["documents"]
                     if x["code"] == "labor_contract")
    mock_pdf = fitz.open()
    page = mock_pdf.new_page(width=595, height=842)
    page.insert_text((45, 70), "Contrato sintetico de ensayo para comprobar integridad",
                     fontsize=11)
    content = mock_pdf.tobytes()
    mock_pdf.close()
    import app.javiera_v18_api as api
    monkeypatch.setattr(api, "layout_preview", lambda **kw: Response(
        content=content, media_type="application/pdf"))
    result = client.post(ROOT + "/layouts/" + layout_id + "/check", headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["passed"] is True
    assert data["pages"] == 1
    assert data["configured_print_area"] == "A1:C36"
    assert data["formula_count"] >= 0
    assert data["out_of_bounds"] == []
    assert data["requires_human_approval"] is True
    with sessions() as db:
        layout = db.get(JavieraExcelLayout, layout_id)
        assert layout.state == "draft"

    login(client, "outside@example.cl")
    assert client.post(ROOT + "/layouts/" + layout_id + "/check").status_code == 404
