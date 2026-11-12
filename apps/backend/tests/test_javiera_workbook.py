"""GALANT 20: native OOXML, tenant isolation, CAS, immutable history and reset."""
import io
import json
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select
from app.config import settings
from app.db import Base
from app.javiera_excel import LayoutError, Q, sheet_files, shared_strings, cell_text
from app.javiera_models import JavieraDossier, JavieraIssue
from app.javiera_workbook import (digest, edit_workbook, inventory, read_sheet, repair_master, clean_master,
                                  roles, validate_calculated, irl_continuations)
from app.javiera_workbook_models import JavieraWorkbook
from test_control_api import env, login
from test_javiera_excel_layout import sample_xlsx
from test_javiera_full_workflow import _dossier


def master():
    wb = load_workbook(io.BytesIO(sample_xlsx()))
    for name, header in (("MATRIZ IRL", ["N", "Cargo", "Actividad", "Peligro", "Riesgo", "Medida"]),
                         ("MATRIZ PTS", ["Cargo", "Plural", "Título", "Objetivo"]),
                         ("Matriz IRL Optimizada", ["Cargo", "Espacio"]),
                         ("Base_Datos_Sustancias", ["Cargo", "Producto"]),
                         ("MATRIZ DESCRIPCION DE CARGO IRL", ["N", "Cargo", "Perfil"])):
        s = wb.create_sheet(name); s.append(header)
        s.append([1, "CARPINTERO", "ACTIVIDAD QA", "PELIGRO QA", "RIESGO QA", "MEDIDA QA"] if name == "MATRIZ IRL"
                 else [1, "CARPINTERO", "PERFIL QA"] if name.startswith("MATRIZ DESCRIPCION")
                 else ["CARPINTERO", "VALOR QA"])
    # A media part that must survive every new master revision exactly.
    from PIL import Image
    from openpyxl.drawing.image import Image as ExcelImage
    logo = io.BytesIO(); Image.new("RGB", (60, 20), "navy").save(logo, format="PNG"); logo.seek(0)
    wb["Contrato Imprimible"].add_image(ExcelImage(logo), "D8")
    out = io.BytesIO(); wb.save(out); return out.getvalue()


def prepare(env, monkeypatch, tmp_path):
    client, sessions = env
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path)); settings.cache_clear()
    headers = login(client, "a@example.cl")
    response = client.post("/api/v1/javiera/workbook/import", headers=headers,
        files={"file": ("maestro.xlsx", master(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text
    return client, sessions, headers, response.json()


def test_native_edit_preserves_formulas_images_styles_merges_print_areas():
    raw = master(); before = inventory(raw)
    after = edit_workbook(raw, "Contrato Imprimible", [{"cell": "A1", "value": "TÍTULO MODIFICADO"}])
    assert inventory(after)["formula_count"] == before["formula_count"]
    assert inventory(after)["media"] == before["media"]
    with ZipFile(io.BytesIO(raw)) as old, ZipFile(io.BytesIO(after)) as new:
        assert old.read("xl/styles.xml") == new.read("xl/styles.xml")
        files = sheet_files(old); p = files["Contrato Imprimible"]
        a, b = ET.fromstring(old.read(p)), ET.fromstring(new.read(p))
        assert [m.attrib for m in a.findall(".//"+Q("mergeCell"))] == [m.attrib for m in b.findall(".//"+Q("mergeCell"))]
        for name in old.namelist():
            if name.startswith(("xl/media/", "xl/drawings/")): assert old.read(name) == new.read(name)
        assert all(c.find(Q("v")) is None for c in b.findall(".//"+Q("c")) if c.find(Q("f")) is not None)
    values = {c["cell"]: c for c in read_sheet(after, "Contrato Imprimible")["cells"]}
    assert values["A1"]["value"] == "TÍTULO MODIFICADO"
    assert values["B3"]["formula"] == "'Datos Contrato'!C17"
    with pytest.raises(LayoutError, match="calculada"):
        edit_workbook(raw, "Contrato Imprimible", [{"cell": "B3", "value": "Sobrescritura accidental"}])
    for formula in ('WEBSERVICE("https://example.test")', 'HYPERLINK("file:///etc/passwd")', "'[other.xlsx]data'!A1", "cmd|'example'!A1", 'EXEC("example")'):
        with pytest.raises(LayoutError): edit_workbook(raw, "Contrato Imprimible", [{"cell": "B3", "formula": formula}])


def test_import_cas_history_restore_and_private_tenants(env, monkeypatch, tmp_path):
    client, sessions, headers, first = prepare(env, monkeypatch, tmp_path)
    path = "/api/v1/javiera/workbook/" + first["id"]
    payload = {"expected_revision": first["revision"], "sheet": "Contrato Imprimible",
               "reason": "Corrección de título de prueba", "edits": [{"cell": "A1", "value": "TÍTULO NUEVO"}]}
    response = client.post(path+"/edit", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    second = response.json(); assert second["revision"] == first["revision"] + 1
    assert second["original_sha256"] == first["original_sha256"]
    assert client.post(path+"/edit", headers=headers, json=payload).status_code == 409
    original = client.get(path+"/download"); assert digest(original.content) == first["sha256"]
    restore = client.post(path+"/restore", headers=headers, json={"expected_revision": second["revision"], "reason": "Recuperación comprobada del original"})
    assert restore.status_code == 200 and restore.json()["sha256"] == first["sha256"]
    assert client.get(path+"/roles").json()["CARPINTERO"]["IRL"] == [2]
    login(client, "outside@example.cl")
    for suffix in ("/download", "/roles", "/sheet?name=Datos%20Contrato"):
        assert client.get(path+suffix).status_code == 404
    login(client, "c@example.cl")
    assert client.get("/api/v1/javiera/workbook").status_code == 403


def test_publication_needs_real_validation_and_independent_review(env, monkeypatch, tmp_path):
    client, _, headers, first = prepare(env, monkeypatch, tmp_path)
    body = {"expected_revision": first["revision"], "codes": ["labor_contract"]}
    path = "/api/v1/javiera/workbook/"+first["id"]+"/publish"
    assert client.post(path, headers=headers, json=body).status_code == 403
    other = login(client, "b@example.cl")
    assert client.post(path, headers=other, json=body).status_code == 403
    # An import is never a professional approval, nor a PDF compatibility proof.
    assert client.get("/api/v1/javiera/workbook").json()["publications"] == {}


def test_reset_verified_backup_preserves_other_modules_and_restores(env, monkeypatch, tmp_path):
    client, sessions, headers, first = prepare(env, monkeypatch, tmp_path)
    ident = _dossier(client, headers)
    with sessions.begin() as db:
        dossier = db.get(JavieraDossier, ident)
        pdf = tmp_path / dossier.org_id / "javiera" / ident / "old.pdf"
        pdf.parent.mkdir(parents=True); pdf.write_bytes(b"%PDF-1.4 synthetic retention fixture")
        db.add(JavieraIssue(org_id=dossier.org_id, dossier_id=ident, code="labor_contract",
            template_revision=1, dossier_revision=1, snapshot={"source": "structured"},
            sha256=digest(pdf.read_bytes()), storage_path=str(pdf), issued_by=dossier.updated_by))
    def counts():
        with sessions() as db:
            return {t.name: db.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables
                    if not t.name.startswith("javiera_") and t.name not in {"audit_events"}}
    before = counts()
    plan = client.get("/api/v1/javiera/workbook/reset/plan").json()
    assert plan["counts"] == {"dossier": 1, "issue": 1, "history": 0}
    result = client.post("/api/v1/javiera/workbook/reset/execute", headers=headers,
        json={"plan_sha256": plan["sha256"], "reason": "Reinicio sintético comprobable de Javiera"})
    assert result.status_code == 200, result.text
    assert client.get("/api/v1/javiera/dossiers").json() == []
    assert client.get("/api/v1/javiera/dossiers/"+ident).status_code == 409
    assert counts() == before
    assert pdf.is_file()  # Retention originals are protected, not destroyed.
    backup = next(tmp_path.rglob("reset-backups/*.zip"))
    assert digest(backup.read_bytes()) == result.json()["backup_sha256"]
    with ZipFile(backup) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert "javiera_workbooks" in manifest["rows"]
        for name, sha in manifest["files"].items(): assert digest(z.read("files/"+name)) == sha
    assert client.post("/api/v1/javiera/workbook/reset/execute", headers=headers,
        json={"plan_sha256": plan["sha256"], "reason": "No se permite reutilizar un plan antiguo"}).status_code == 409
    restored = client.post("/api/v1/javiera/workbook/reset/"+result.json()["id"]+"/restore", headers=headers)
    assert restored.status_code == 200, restored.text
    assert len(client.get("/api/v1/javiera/dossiers").json()) == 1
    assert counts() == before


def test_formula_errors_block_instead_of_becoming_empty():
    raw = master(); wb = load_workbook(io.BytesIO(raw)); wb['Contrato Imprimible']['A6'] = '#REF!'
    out = io.BytesIO(); wb.save(out)
    with pytest.raises(LayoutError, match="#REF!"):
        validate_calculated(out.getvalue(), "Contrato Imprimible")


def test_clean_master_removes_example_inputs_and_caches_without_losing_graphics():
    original = master(); clean = clean_master(original)
    assert inventory(original)['media'] == inventory(clean)['media']
    assert inventory(original)['formula_count'] == inventory(clean)['formula_count']
    fields = {c['cell']:c['value'] for c in read_sheet(clean,'Datos Contrato')['cells']}
    assert fields['C5'] == fields['C17'] == fields['C18'] == ''
    with ZipFile(io.BytesIO(clean)) as z:
        assert all(b'admin@example.test' not in z.read(name) for name in z.namelist() if name.endswith(('.xml','.rels')))
        for path in sheet_files(z).values():
            for cell in ET.fromstring(z.read(path)).findall('.//'+Q('c')):
                if cell.find(Q('f')) is not None:assert cell.find(Q('v')) is None


def test_cache_deduplicates_concurrent_conversion_and_invalidates_content(monkeypatch,tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading,time
    import fitz
    import app.javiera_workbook as module
    from test_javiera_excel_layout import valid_data
    calls=[];lock=threading.Lock()
    def convert(raw,sheet,**kwargs):
        with lock:calls.append(sheet)
        time.sleep(.04)
        doc=fitz.open();page=doc.new_page();page.insert_text((50,50),'EMPRESA DE PRUEBA - PERSONA NUEVA DE PRUEBA')
        return doc.tobytes(),{'elapsed_ms':40,'engine':'stub de concurrencia, no prueba de fidelidad'}
    monkeypatch.setattr(module,'convert_pdf',convert)
    raw=master();data=valid_data()
    def request_pdf(_):return module.cached_pdf(raw,'labor_contract',data,'org-test',tmp_path,True)
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(request_pdf,range(6)))
    assert len(calls)==1
    assert len({digest(pdf) for pdf,meta in results})==1
    assert sum(meta['cache_hit'] for _,meta in results)==5
    edited=edit_workbook(raw,'Contrato Imprimible',[{'cell':'A1','value':'Nueva revisión de plantilla'}])
    module.cached_pdf(edited,'labor_contract',data,'org-test',tmp_path,True)
    module.cached_pdf(raw,'labor_contract',data,'otra-org',tmp_path,True)
    assert len(calls)==3


def test_irl_continues_exact_cargo_rows_after_another_cargo_block():
    """The thirteenth matching risk must not be confused with the intervening cargo."""
    wb=load_workbook(io.BytesIO(master()));matrix=wb['MATRIZ IRL']
    for i in range(2,13):matrix.append([i,'CARPINTERO','ACTIVIDAD '+str(i),'PELIGRO','RIESGO','MEDIDA'])
    matrix.append([13,'PINTOR','OTRO CARGO','PELIGRO','RIESGO','MEDIDA'])
    matrix.append([14,'CARPINTERO','ACTIVIDAD FINAL CORRECTA','PELIGRO','RIESGO','MEDIDA'])
    for col in 'ABCD':wb['IRL'][col+'45']="='Datos Contrato'!C29"
    out=io.BytesIO();wb.save(out);result,names=irl_continuations(out.getvalue(),'CARPINTERO')
    assert len(names)==1
    cells={c['cell']:c for c in read_sheet(result,names[0],45,1)['cells']}
    assert "'MATRIZ IRL'!$B$15" in cells['A45']['formula']
    assert "'MATRIZ IRL'!$C$15" in cells['A45']['formula']
    assert "'MATRIZ IRL'!$E$15" in cells['C45']['formula']
