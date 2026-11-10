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
    assert body["can_import"] is False
    assert body["formula_equivalence_verified"] is False
    assert body["formula_inventory"][0]["cell"] == "A1"
    assert any("importación bloqueada" in warning.casefold() for warning in body["warnings"])
    with sessions() as db:
        assert db.scalar(select(func.count(JavieraMatrix.id)))==before


def test_visual_editor_history_is_scoped_and_restorable_as_new_draft(env):
    client,sessions=env
    admin=login(client,"a@example.cl")
    base="/api/v1/javiera/v19/editor/internal_rules_receipt"
    first=client.put(base,headers=admin,json={
        "html":"<h2>CONSTANCIA DE ENTREGA</h2><p>Primera revisión de documento seguro.</p>",
        "reason":"Inicio de historial visual"
    })
    assert first.status_code==200,first.text
    second=client.put(base,headers=admin,json={
        "html":"<h2>CONSTANCIA DE ENTREGA</h2><p>Segunda revisión del contenido.</p>",
        "reason":"Segunda versión de control"
    })
    assert second.status_code==200,second.text
    history=client.get(base+"/history",headers=admin)
    assert history.status_code==200,history.text
    entries=history.json()["revisions"]
    assert len(entries)>=2
    assert entries[0]["revision"]==second.json()["revision"]
    assert entries[1]["revision"]==first.json()["revision"]
    assert "Primera revisión" in entries[1]["html"]
    # Restoring is a copy; the prior revision is kept forever.
    restored=client.put(base,headers=admin,json={
        "html":entries[1]["html"],
        "reason":"Recuperación de primera versión guardada"
    })
    assert restored.status_code==200
    assert restored.json()["revision"]>second.json()["revision"]
    updated=client.get(base+"/history",headers=admin)
    assert len(updated.json()["revisions"])>=3



def _complete_synthetic_workbook():
    """Sólo datos ficticios, cantidades de referencia sin Excel privado."""
    from io import BytesIO
    from openpyxl import Workbook
    wb=Workbook()
    irl=wb.active
    irl.title="MATRIZ IRL"
    irl.append(["N","Cargo","Tarea","Peligro","Riesgo","Medidas"])
    for idx in range(338):
        irl.append([idx+1,"PINTOR","Pintura "+str(idx+1),
                    "Trabajo en altura","Caída","Usar protección "+str(idx+1)])
    pts=wb.create_sheet("MATRIZ PTS")
    pts.append(["Cargo","Col B","Col C"]+["Apartado "+str(i) for i in range(1,18)])
    for idx in range(26):
        pts.append(["CARGO "+str(idx+1),"",""]+
                   ["Texto técnico de prueba "+str(idx)+"-"+str(i) for i in range(17)])
    for name in ("MATRIZ DESCRIPCION DE CARGO IRL",
                 "Matriz IRL Optimizada","Base_Datos_Sustancias"):
        wb.create_sheet(name)
    formula_sheet=wb.create_sheet("FORMULAS")
    for idx in range(423):
        formula_sheet.cell(idx+1,1,value="=1+"+str(idx+1))
    binary=BytesIO()
    wb.save(binary)
    wb.close()
    return binary.getvalue()


def test_full_import_uses_preview_checksum_and_does_not_duplicate_unchanged(env):
    client,sessions=env
    admin=login(client,"a@example.cl")
    raw=_complete_synthetic_workbook()
    filepath="matrices.xlsx"
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    preview=client.post("/api/v1/javiera/v192/workbook-preview",headers=admin,
        files={"file":(filepath,raw,mime)})
    assert preview.status_code==200,preview.text
    body=preview.json()
    assert body["can_import"] is True,body["warnings"]
    assert body["irl_source_rows"]==338
    assert body["pts_source_rows"]==26
    assert body["formula_count"]==423
    assert len(body["formula_inventory"])==423
    assert body["formula_equivalence_verified"] is False
    with sessions() as db:
        original={cls.__name__:db.scalar(select(func.count(cls.id)))
                  for cls in (JavieraDossier,Worker,Contractor,WorkerAssignment,JavieraMatrix)}
    data={"sha256":body["sha256"],"baseline_sha256":body["baseline_sha256"],"confirmed":"true"}
    mismatch=client.post("/api/v1/javiera/v192/workbook-commit",headers=admin,
        data={**data,"sha256":"incorrect"},
        files={"file":(filepath,raw,mime)})
    assert mismatch.status_code==409
    imported=client.post("/api/v1/javiera/v192/workbook-commit",headers=admin,
        data=data,files={"file":(filepath,raw,mime)})
    assert imported.status_code==200,imported.text
    assert imported.json()["created"]==27
    assert imported.json()["omissions"]==[]
    with sessions() as db:
        after={cls.__name__:db.scalar(select(func.count(cls.id)))
               for cls in (JavieraDossier,Worker,Contractor,WorkerAssignment,JavieraMatrix)}
        latest=db.scalars(select(JavieraMatrix).where(
            JavieraMatrix.org_id.is_not(None),
            JavieraMatrix.kind=="IRL",JavieraMatrix.cargo=="PINTOR",
        ).order_by(JavieraMatrix.revision.desc()).limit(1)).first()
        assert len(latest.sections)==338
        assert latest.status=="draft"
    assert after["JavieraMatrix"]==original["JavieraMatrix"]+27
    for entity in ("JavieraDossier","Worker","Contractor","WorkerAssignment"):
        assert after[entity]==original[entity]
    new_preview=client.post("/api/v1/javiera/v192/workbook-preview",headers=admin,
        files={"file":(filepath,raw,mime)})
    assert new_preview.status_code==200
    assert new_preview.json()["unchanged"]==27
    second=client.post("/api/v1/javiera/v192/workbook-commit",headers=admin,
        data={"sha256":new_preview.json()["sha256"],
              "baseline_sha256":new_preview.json()["baseline_sha256"],
              "confirmed":"true"},files={"file":(filepath,raw,mime)})
    assert second.status_code==200
    assert second.json()["created"]==0
    stale=client.post("/api/v1/javiera/v192/workbook-commit",headers=admin,
        data=data,files={"file":(filepath,raw,mime)})
    assert stale.status_code==409
    with sessions() as db:
        assert db.scalar(select(func.count(JavieraMatrix.id)))==after["JavieraMatrix"]


def test_pts_incomplete_row_is_preserved_as_draft_without_false_approval(env):
    from io import BytesIO
    from openpyxl import load_workbook
    client,sessions=env
    admin=login(client,"a@example.cl")
    wb=load_workbook(BytesIO(_complete_synthetic_workbook()))
    wb["MATRIZ PTS"]["D2"]=None
    binary=BytesIO();wb.save(binary);wb.close()
    raw=binary.getvalue()
    preview=client.post("/api/v1/javiera/v192/workbook-preview",headers=admin,
        files={"file":("missing.xlsx",raw,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert preview.status_code==200
    assert preview.json()["can_import"] is True
    assert preview.json()["incomplete_pts"]
    with sessions() as db:
        before=db.scalar(select(func.count(JavieraMatrix.id)))
    commit=client.post("/api/v1/javiera/v192/workbook-commit",headers=admin,
        data={"sha256":preview.json()["sha256"],
              "baseline_sha256":preview.json()["baseline_sha256"],"confirmed":"true"},
        files={"file":("missing.xlsx",raw,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert commit.status_code==200,commit.text
    with sessions() as db:
        assert db.scalar(select(func.count(JavieraMatrix.id)))==before+27
        row=db.scalars(select(JavieraMatrix).where(
            JavieraMatrix.kind=="PTS",JavieraMatrix.cargo=="CARGO 1",
        ).order_by(JavieraMatrix.revision.desc())).first()
        assert row.status=="draft"
        assert len(row.sections)==17
        assert row.sections[0]==""



def test_matrix_impact_counts_current_javiera_dossiers_and_cross_review(env):
    from test_javiera_v19 import _local_dossier
    client,_=env
    admin=login(client,"a@example.cl")
    local_id=_local_dossier(client,admin)
    assert local_id
    response=client.get("/api/v1/javiera/v192/matrix-impact",
                        headers=admin,params={"kind":"IRL","cargo":"CARPINTERO"})
    assert response.status_code==200,response.text
    result=response.json()
    assert result["affected_by_origin"]["current_documentary_workflow"]>=1
    assert result["affected_dossiers"]>=1
    assert result["new_pdf_formats"]==["irl"]
    assert "pts" in result["related_formats_for_review"]
    assert result["related_formats_are_advisory"] is True
    assert result["historical_pdfs_unchanged"] is True



def test_oversized_formatting_and_261_formulas_do_not_drop_valid_matrices(env):
    """Reproduce los rasgos conocidos de una auditoría anterior, sin datos reales."""
    from io import BytesIO
    from openpyxl import load_workbook
    from openpyxl.styles import Font
    client,sessions=env
    admin=login(client,"a@example.cl")
    wb=load_workbook(BytesIO(_complete_synthetic_workbook()))
    for row in range(2,25):
        wb["MATRIZ PTS"].cell(row,4).value=None
    for row in range(262,424):
        wb["FORMULAS"].cell(row,1).value=None
    # La dimensión declarada llega al último renglón, sin un dato real ahí.
    wb["MATRIZ IRL"].cell(1048576,40).font=Font(bold=True)
    binary=BytesIO();wb.save(binary);wb.close()
    raw=binary.getvalue()
    response=client.post("/api/v1/javiera/v192/workbook-preview",headers=admin,
        files={"file":("auditoria_previa.xlsx",raw,
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code==200,response.text
    report=response.json()
    assert report["irl_source_rows"]==338
    assert report["pts_source_rows"]==26
    assert report["formula_count"]==261
    assert report["formula_count_partial"] is False
    assert len(report["incomplete_pts"])==23
    assert report["draft_only_for_incomplete"] is True
    assert report["can_import"] is True,report["omissions"]
    assert any("sobredimensionadas" in warning for warning in report["warnings"])



def test_incomplete_preventive_matrices_cannot_be_approved():
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.javiera_api import _check_preventive_matrix_before_approval

    pts=SimpleNamespace(kind="PTS",source="GALANT 19.2 XLSX",sections=["Procedimiento"]*17)
    _check_preventive_matrix_before_approval(pts)
    pts.sections[4]=""
    with pytest.raises(HTTPException) as exc:
        _check_preventive_matrix_before_approval(pts)
    assert exc.value.status_code==422

    valid=("Tarea: Trabajo en altura\nPeligro: Desnivel\n"
           "Riesgo: Caída\nMedidas: Protección colectiva")
    irl=SimpleNamespace(kind="IRL",source="GALANT 19.2 XLSX",sections=[valid])
    _check_preventive_matrix_before_approval(irl)
    irl.sections=["Tarea: Trabajo en altura\nPeligro: \nRiesgo: Caída\nMedidas: Protección"]
    with pytest.raises(HTTPException) as exc:
        _check_preventive_matrix_before_approval(irl)
    assert exc.value.status_code==422
