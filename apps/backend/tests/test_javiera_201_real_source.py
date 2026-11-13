"""Optional private-source regression; the user's workbook is never committed."""
import io
import os
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import pytest
from app.config import settings
from app.javiera_workbook import inventory
from app.javiera_excel import sheet_files,Q
from app.xlsx_package import root_namespaces
from test_control_api import env,login

@pytest.mark.skipif(not os.getenv('GALANT_JAVIERA_SOURCE_XLSX'),reason='Requiere el Excel privado autorizado para QA')
def test_private_original_import_edit_download_keeps_graphics_and_namespaces(env,monkeypatch,tmp_path):
    raw=Path(os.environ['GALANT_JAVIERA_SOURCE_XLSX']).read_bytes();before=inventory(raw)
    monkeypatch.setenv('DOCUMENT_DIR',str(tmp_path));settings.cache_clear()
    client,_=env;headers=login(client,'a@example.cl')
    reply=client.post('/api/v1/javiera/workbook/import',headers=headers,files={'file':('source.xlsx',raw)})
    assert reply.status_code==200,reply.text
    current=reply.json();path='/api/v1/javiera/workbook/'+current['id']
    reply=client.post(path+'/edit',headers=headers,json={'expected_revision':current['revision'],'sheet':'Datos Contrato','reason':'Comprobar edición con el original autorizado','edits':[{'cell':'C5','value':'EMPRESA PRIVADA QA 20.1'}]})
    assert reply.status_code==200,reply.text
    download=client.get('/api/v1/javiera/workbook/'+reply.json()['id']+'/download')
    assert download.status_code==200
    assert inventory(download.content)['media']==before['media']
    with ZipFile(io.BytesIO(download.content)) as z:
        for part in ['xl/workbook.xml',*sheet_files(z).values()]:
            content=z.read(part);root=ET.fromstring(content);ns=root_namespaces(content)
            assert all(prefix in ns for prefix in root.get('{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable','').split())
        root=ET.fromstring(z.read(sheet_files(z)['INDUCCION PREVENCION']))
        assert any(b.get('id')=='467' for b in root.findall('.//'+Q('brk')))
