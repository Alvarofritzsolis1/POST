"""Regression: Microsoft OOXML namespaces, cell styles and private batch ZIPs."""
import io
from copy import copy
import json
from hashlib import sha256
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

import pytest
from openpyxl import load_workbook

from app.javiera_excel import Q, sheet_files, LayoutError
from app.javiera_workbook import clean_master, edit_workbook, inventory, pack, repair_master
from app.xlsx_package import compatible_package, root_namespaces
from app.javiera_models import JavieraDossier, JavieraIssue
from test_control_api import env, login
from test_javiera_full_workflow import _dossier
from test_javiera_workbook import master, prepare

MC = 'http://schemas.openxmlformats.org/markup-compatibility/2006'
X14 = 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac'
XR = 'http://schemas.microsoft.com/office/spreadsheetml/2014/revision'


def microsoft_master():
    raw = master()
    with ZipFile(io.BytesIO(raw)) as z:
        files = sheet_files(z)
        changes = {}
        for path in ['xl/workbook.xml', *files.values()]:
            part = z.read(path)
            start = part.find(b'<worksheet') if path != 'xl/workbook.xml' else part.find(b'<workbook')
            insert = part.find(b' ', start)
            attrs = f' xmlns:mc="{MC}" xmlns:x14ac="{X14}" xmlns:xr="{XR}" mc:Ignorable="x14ac xr"'.encode()
            changes[path] = part[:insert] + attrs + part[insert:]
        return pack(z, changes)


def assert_namespaces(raw):
    with ZipFile(io.BytesIO(raw)) as z:
        assert z.testzip() is None
        for path in ['xl/workbook.xml', *sheet_files(z).values()]:
            content = z.read(path)
            ns = root_namespaces(content)
            root = ET.fromstring(content)
            for prefix in root.get('{'+MC+'}Ignorable', '').split():
                assert prefix in ns, (path, prefix)
        return {name:z.read(name) for name in z.namelist() if name.startswith(('xl/drawings/', 'xl/media/'))}


def test_microsoft_aliases_survive_clean_edit_and_repair():
    raw = microsoft_master(); graphics = assert_namespaces(raw)
    repaired, _ = repair_master(raw)
    cleaned = clean_master(repaired)
    edited = edit_workbook(cleaned, 'Contrato Imprimible', [{'cell':'A1', 'value':'NUEVO TÍTULO'}])
    for result in [repaired, cleaned, edited]:
        assert assert_namespaces(result) == graphics
        wb = load_workbook(io.BytesIO(result))
        assert wb['Contrato Imprimible']['B3'].data_type == 'f'
    assert load_workbook(io.BytesIO(edited))['Contrato Imprimible']['A1'].value == 'NUEVO TÍTULO'


def broken_old_revision(raw):
    # Reproduce pre-20.1 serialization, which loses aliases referenced only by mc:Ignorable.
    with ZipFile(io.BytesIO(raw)) as z:
        out = io.BytesIO()
        with ZipFile(out,'w',ZIP_DEFLATED) as target:
            for item in z.infolist():
                content=z.read(item.filename)
                if item.filename in ['xl/workbook.xml', *sheet_files(z).values()]:
                    content=ET.tostring(ET.fromstring(content),encoding='utf-8',xml_declaration=True)
                target.writestr(copy(item),content)
        return out.getvalue()


def test_recover_old_revision_from_original_without_touching_media():
    original=microsoft_master(); broken=broken_old_revision(original)
    with pytest.raises(AssertionError): assert_namespaces(broken)
    repaired=compatible_package(broken,original)
    assert assert_namespaces(repaired)==assert_namespaces(original)
    assert compatible_package(repaired,original)==repaired


def test_styles_change_one_cell_and_preserve_formula_content():
    raw=master(); before=load_workbook(io.BytesIO(raw)); count=inventory(raw)['formula_count']
    edited=edit_workbook(raw,'Contrato Imprimible',[
        {'cell':'A1','format':{'bold':True,'italic':True,'font_size':16,'fill_color':'#ffeedd','align':'center'}},
        {'cell':'B3','format':{'bold':False,'wrap':True},'row_height':42},
    ])
    wb=load_workbook(io.BytesIO(edited)); cell=wb['Contrato Imprimible']['A1']
    assert cell.font.bold and cell.font.italic and cell.font.sz==16
    assert cell.fill.fgColor.rgb=='FFFFEEDD' and cell.alignment.horizontal=='center'
    assert wb['Contrato Imprimible']['B3'].value==before['Contrato Imprimible']['B3'].value
    assert wb['Contrato Imprimible']['B3'].alignment.wrap_text
    assert wb['Contrato Imprimible']['A2'].style_id==before['Contrato Imprimible']['A2'].style_id
    assert wb['Contrato Imprimible'].row_dimensions[3].height==42
    assert inventory(edited)['formula_count']==count


def test_download_repairs_legacy_revision_using_immutable_original(env,monkeypatch,tmp_path):
    from app.javiera_workbook_models import JavieraWorkbook
    from app.javiera_workbook_api import write_revision
    from app.models import User
    from sqlalchemy import select
    client,sessions,headers,current=prepare(env,monkeypatch,tmp_path)
    original=microsoft_master(); broken=broken_old_revision(original)
    with sessions() as db:
        user=db.scalar(select(User).where(User.email=='a@example.cl'))
        orig=write_revision(db,user,original,'Original Microsoft para pruebas',current['revision'])
        latest=write_revision(db,user,broken,'Revisión antigua con defecto reproducido',orig.revision,orig)
        ident=latest.id
    response=client.get('/api/v1/javiera/workbook/'+ident+'/download')
    assert response.status_code==200
    assert_namespaces(response.content)
    assert response.headers['x-content-sha256']==sha256(response.content).hexdigest()
    with sessions() as db:
        assert db.get(JavieraWorkbook,ident).sha256==sha256(broken).hexdigest()


def test_archive_is_private_complete_and_checks_integrity(env,monkeypatch,tmp_path):
    from app.config import settings
    monkeypatch.setenv('DOCUMENT_DIR',str(tmp_path));settings.cache_clear()
    client,sessions=env;headers=login(client,'a@example.cl');ident=_dossier(client,headers)
    ids=[]
    with sessions.begin() as db:
        record=db.get(JavieraDossier,ident)
        for code in ['labor_contract','irl']:
            raw=b'%PDF-1.4 synthetic '+code.encode()
            folder=tmp_path/record.org_id/'javiera'/ident;folder.mkdir(parents=True,exist_ok=True)
            path=folder/(code+'.pdf');path.write_bytes(raw)
            item=JavieraIssue(org_id=record.org_id,dossier_id=ident,code=code,template_revision=1,dossier_revision=1,snapshot={},sha256=sha256(raw).hexdigest(),storage_path=str(path),issued_by=record.updated_by)
            db.add(item);db.flush();ids.append(item.id)
    response=client.post('/api/v1/javiera/issue/archive',headers=headers,json={'issue_ids':ids})
    assert response.status_code==200,response.text
    with ZipFile(io.BytesIO(response.content)) as z:
        manifest=json.loads(z.read('documentos.json'));assert len(manifest)==2
        for row in manifest: assert sha256(z.read(row['file'])).hexdigest()==row['sha256']
    other=login(client,'outside@example.cl')
    assert client.post('/api/v1/javiera/issue/archive',headers=other,json={'issue_ids':ids}).status_code==404
    headers=login(client,'a@example.cl');path.write_bytes(b'tampered')
    assert client.post('/api/v1/javiera/issue/archive',headers=headers,json={'issue_ids':ids}).status_code==409
    assert client.post('/api/v1/javiera/issue/archive',headers=headers,json={'issue_ids':[]}).status_code==422


def test_missing_print_areas_block_import_and_preserve_current_revision(env,monkeypatch,tmp_path):
    """Un editor Excel que borra Print_Area no debe cambiar los documentos."""
    client,sessions,headers,current=prepare(env,monkeypatch,tmp_path)
    original=master()
    with ZipFile(io.BytesIO(original)) as archive:
        workbook=ET.fromstring(archive.read('xl/workbook.xml'))
        names=workbook.find(Q('definedNames'))
        assert names is not None
        for item in list(names):
            if item.get('name') == '_xlnm.Print_Area':
                names.remove(item)
        corrupt=pack(archive,{'xl/workbook.xml':ET.tostring(workbook,encoding='utf-8')})
    response=client.post('/api/v1/javiera/workbook/import?expected_revision='+str(current['revision']),
        headers=headers,files={'file':('sin-areas-de-impresion.xlsx',corrupt,
                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code == 422, response.text
    assert 'impresión' in response.text.lower()
    after=client.get('/api/v1/javiera/workbook',headers=headers).json()
    assert after['current']['id'] == current['id']
    assert after['current']['revision'] == current['revision']


def test_invalid_control_characters_never_produce_a_corrupt_excel():
    for edit in [{'cell':'A5','value':'contenido\x01inválido'}, {'cell':'B3','formula':'"texto\x00"'}]:
        with pytest.raises(LayoutError, match='caracteres de control'):
            edit_workbook(master(),'Contrato Imprimible',[edit])


def test_failed_import_does_not_publish_a_partial_revision(env,monkeypatch,tmp_path):
    from fastapi import HTTPException
    from app import javiera_workbook_api as api
    client,sessions,headers,current=prepare(env,monkeypatch,tmp_path)
    before_files=set(tmp_path.rglob('*.xlsx'))
    before_revisions=client.get('/api/v1/javiera/workbook/revisions').json()
    original=api.write_revision
    calls=[]
    def fail_second(*args,**kwargs):
        calls.append(1)
        if len(calls)==2: raise HTTPException(503,'Fallo de escritura simulado en QA')
        return original(*args,**kwargs)
    monkeypatch.setattr(api,'write_revision',fail_second)
    response=client.post('/api/v1/javiera/workbook/import?expected_revision='+str(current['revision']),headers=headers,
        files={'file':('another.xlsx',master(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code==503
    assert client.get('/api/v1/javiera/workbook').json()['current']['id']==current['id']
    assert client.get('/api/v1/javiera/workbook/revisions').json()==before_revisions
    assert set(tmp_path.rglob('*.xlsx'))==before_files


def changed_part(raw,name,content):
    with ZipFile(io.BytesIO(raw)) as z:
        return pack(z,{name:content})


def test_malformed_worksheet_import_is_a_clear_422_and_keeps_current(env,monkeypatch,tmp_path):
    client,sessions,headers,current=prepare(env,monkeypatch,tmp_path)
    raw=master()
    with ZipFile(io.BytesIO(raw)) as z: path=sheet_files(z)['Contrato Imprimible']
    # Write invalid XML directly, without the production packer's namespace parsing.
    out=io.BytesIO()
    with ZipFile(io.BytesIO(raw)) as z, ZipFile(out,'w',ZIP_DEFLATED) as target:
        for item in z.infolist(): target.writestr(copy(item),b'<broken' if item.filename==path else z.read(item.filename))
    response=client.post('/api/v1/javiera/workbook/import?expected_revision='+str(current['revision']),headers=headers,files={'file':('broken.xlsx',out.getvalue())})
    assert response.status_code==422
    assert client.get('/api/v1/javiera/workbook').json()['current']['id']==current['id']


def test_covered_cells_missing_style_sources_and_invalid_numbers_are_rejected():
    for edit in [{'cell':'B1','value':'Oculto bajo el título'}, {'cell':'A5','style_from':'ZZZ999999'}, {'cell':'A5','value':float('inf')}, {'cell':'A5','value':'x'*32768}]:
        with pytest.raises(LayoutError):edit_workbook(master(),'Contrato Imprimible',[edit])


def test_simultaneous_dossier_saves_keep_one_revision(env,tmp_path,monkeypatch):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from fastapi import HTTPException
    from app import javiera_api as api
    client,sessions=env;headers=login(client,'a@example.cl');ident=_dossier(client,headers)
    saved=client.get('/api/v1/javiera/dossiers/'+ident).json()
    # Independent connections to one snapshot, rather than the API fixture's shared connection.
    destination=tmp_path/'concurrent.db'
    with sessions() as db:
        record=db.get(JavieraDossier,ident);actor=SimpleNamespace(id=record.updated_by,org_id=record.org_id)
        with sqlite3.connect(destination) as target: db.connection().connection.driver_connection.backup(target)
    engine=create_engine('sqlite:///'+str(destination),connect_args={'check_same_thread':False,'timeout':10})
    concurrent_sessions=sessionmaker(bind=engine,expire_on_commit=False)
    barrier=Barrier(2);original=api.dossier
    def simultaneous_read(*args):
        result=original(*args);barrier.wait(timeout=10);return result
    monkeypatch.setattr(api,'dossier',simultaneous_read)
    def save(role):
        with concurrent_sessions() as db:
            payload=api.DossierInput(site_id=saved['site_id'],employer_id=saved['employer_id'],worker_id=saved['worker_id'],relationship='contractor',expected_revision=1,data={**saved['data'],'_dossier_id':ident,'role':role})
            try:return api.save_dossier(payload,actor,db)['revision']
            except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(save,['PINTOR QA','CARPINTERO QA']))
    assert sorted(results)==[2,409]
    with concurrent_sessions() as db:
        row=db.get(JavieraDossier,ident);assert row.revision==2
        assert row.data['role'] in {'PINTOR QA','CARPINTERO QA'}
    engine.dispose()


def test_epp_accepts_equivalent_footwear_names_without_guessing_gloves():
    from app.javiera_workbook import delivery_quantities
    assert delivery_quantities('1 casco, 2 zapatos de seguridad') == [1,2,0,0,0,0,0,0]
    assert delivery_quantities('botines de seguridad') == delivery_quantities('calzado de seguridad')
    with pytest.raises(LayoutError, match='ambiguo'):
        delivery_quantities('guantes')


def test_induction_header_break_is_scoped_idempotent_and_preserves_text():
    from app.javiera_excel import protect_induction_evaluation_header,set_text
    root=ET.Element(Q('worksheet'));ET.SubElement(root,Q('sheetData'))
    set_text(root,'A458','TEST DE APRENDIZAJE   INDUCCIÓN DE SEGURIDAD')
    set_text(root,'A470','6.- ENFERMEDADES PROFESIONALES')
    assert not protect_induction_evaluation_header(root,[])
    ET.SubElement(root,Q('drawing'),{'{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id':'rId1'})
    before=ET.tostring(root.find(Q('sheetData')))
    assert protect_induction_evaluation_header(root,[])
    assert not protect_induction_evaluation_header(root,[])
    breaks=root.find(Q('rowBreaks'))
    assert [n.get('id') for n in breaks]==['467']
    assert ET.tostring(root.find(Q('sheetData')))==before
    assert list(root).index(breaks)<list(root).index(root.find(Q('drawing')))
