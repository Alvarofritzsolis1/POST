"""GALANT 19.2: backend restricts visual content and never mutates operational data."""
from sqlalchemy import func, select

from app.javiera_native_edit import NativeHtmlError, validate_native_html
from app.javiera_models import JavieraDossier, JavieraMatrix
from app.ops_models import Worker, Contractor, WorkerAssignment
from test_control_api import env, login
import pytest


def test_visual_html_alignment_preserves_safe_attributes_only():
    html = '<h2 align="center">REGLAMENTO INTERNO</h2><p align="right">Constancia de entrega al trabajador.</p>'
    assert validate_native_html(html) == html
    with pytest.raises(NativeHtmlError):
        validate_native_html('<p style="color:red">Constancia de entrega al trabajador.</p>')
    with pytest.raises(NativeHtmlError):
        validate_native_html('<p align="javascript:evil">Constancia de entrega al trabajador.</p>')


def test_matrix_impact_does_not_approve_or_mutate_operational_data(env):
    client, sessions = env
    admin = login(client, "a@example.cl")
    with sessions() as db:
        initial = {cls.__name__: db.scalar(select(func.count(cls.id)))
                   for cls in (JavieraDossier, Worker, Contractor, WorkerAssignment)}

    created = client.post("/api/v1/javiera/admin/matrices",headers=admin,json={
        "kind":"IRL", "cargo":"PINTOR",
        "sections":["Tarea: Pintura\nPeligro: Caída\nRiesgo: Lesión\nMedidas: Protección"],
        "source":"Editor visual 19.2"
    })
    assert created.status_code == 200, created.text
    matrix_id = created.json()["id"]
    impact = client.get("/api/v1/javiera/v192/matrix-impact",
                        headers=admin, params={"kind":"IRL","cargo":"PINTOR"})
    assert impact.status_code == 200, impact.text
    result = impact.json()
    assert result["new_pdf_formats"] == ["irl"]
    assert result["historical_pdfs_unchanged"] is True
    assert result["needs_explicit_review"] is True
    assert result["pending_revisions"]
    with sessions() as db:
        row = db.get(JavieraMatrix,matrix_id)
        assert row.status == "draft"
        after = {cls.__name__: db.scalar(select(func.count(cls.id)))
                 for cls in (JavieraDossier, Worker, Contractor, WorkerAssignment)}
    assert initial == after


def test_impact_requires_admin_and_valid_kind(env):
    client,_ = env
    headers = login(client, "a@example.cl")
    invalid = client.get("/api/v1/javiera/v192/matrix-impact", headers=headers,
                         params={"kind":"UNKNOWN","cargo":"PINTOR"})
    assert invalid.status_code == 422
    no_cargo = client.get("/api/v1/javiera/v192/matrix-impact", headers=headers,
                          params={"kind":"PTS","cargo":" "})
    assert no_cargo.status_code == 422


def test_workbook_preview_is_read_only_and_exposes_difference_inventory(env):
    from io import BytesIO
    from openpyxl import Workbook
    client,sessions=env
    admin=login(client,"a@example.cl")
    workbook=Workbook()
    irl=workbook.active
    irl.title="MATRIZ IRL"
    irl.append(["ID","Cargo","Tarea","Peligro","Riesgo","Medidas"])
    irl.append([1,"PINTOR","Pintar","Altura","Caída","Arnés"])
    pts=workbook.create_sheet("MATRIZ PTS")
    pts.append(["Cargo","A","B"]+["Sección "+str(n) for n in range(1,18)])
    pts.append(["PINTOR",None,None]+["Apartado real "+str(n) for n in range(1,18)])
    for name in ("MATRIZ DESCRIPCION DE CARGO IRL","Matriz IRL Optimizada","Base_Datos_Sustancias"):
        workbook.create_sheet(name)
    calc=workbook.create_sheet("Calculos")
    calc["A1"]="=1+1"
    raw=BytesIO()
    workbook.save(raw)
    workbook.close()
    with sessions() as db:
        before=db.scalar(select(func.count(JavieraMatrix.id)))
    response=client.post("/api/v1/javiera/v192/workbook-preview",headers=admin,
                         files={"file":("matrices.xlsx",raw.getvalue(),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code==200,response.text
    body=response.json()
    assert body["preview_only"] is True
    assert body["irl_source_rows"]==1
    assert body["pts_source_rows"]==1
    assert body["formula_count"]==1
    assert body["new"]>=2
    assert body["can_import"] is True
    with sessions() as db:
        assert db.scalar(select(func.count(JavieraMatrix.id)))==before
