"""Javiera 20.2: new contractor wizard, PDF readiness and simplified Excel editor.

Runs only against localhost with synthetic QA accounts. It does not import a
private workbook, approve a professional review or issue a legal document.
"""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from playwright.sync_api import sync_playwright, expect
from qa_javiera_v165_workflow_browser import _api, _rut


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:18612')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if urlparse(args.url).hostname not in ('localhost', '127.0.0.1'):
        raise SystemExit('QA solo sobre localhost y datos sintéticos')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'version':'20.2', 'scenarios':{}, 'status':'FAIL'}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,
            executable_path=os.environ.get('GALANT_QA_BROWSER_EXECUTABLE') or None)
        context = browser.new_context(viewport={'width':1440,'height':940}, reduced_motion='reduce')
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        try:
            page.goto(args.url, wait_until='domcontentloaded')
            page.get_by_label('Correo electrónico', exact=True).fill(os.environ['GALANT_JAVIERA_QA_EMAIL'])
            page.get_by_label('Contraseña', exact=True).fill(os.environ['GALANT_JAVIERA_QA_PASSWORD'])
            page.get_by_role('button', name='Ingresar a GALANT').click()
            expect(page.get_by_role('button', name='Menú de usuario')).to_be_visible()
            site = next(x for x in _api(context,args.url,'/ops/sites') if x['name']=='Brisas de Junquillar')
            suffix=uuid4().hex[:8];seed=int(suffix,16)%999999
            company=_api(context,args.url,'/ops/contractors','POST',{
                'site_id':site['id'],'name':'JAVIERA 20.1 QA '+suffix,'rut':_rut(76000000+seed),
                'nature':'with_workers','historical_code':'QA201','frequency':'fixed','contract_status':'active'})
            people=[]
            for index in range(2):
                person=_api(context,args.url,'/ops/workers','POST',{
                    'site_id':site['id'],'contractor_id':company['contractor_id'],
                    'name':'PERSONA QA 20.1 '+suffix+' '+str(index),'rut':_rut(20000000+seed+index)})
                people.append(person['worker_id'])
            dossiers=[]
            for worker in people:
                row=_api(context,args.url,'/javiera/dossiers','POST',{
                    'site_id':site['id'],'employer_id':company['contractor_id'],'worker_id':worker,
                    'relationship':'contractor','data':{'role':'PINTOR QA '+suffix,'event_type':'ingreso'}})
                dossiers.append(row['id'])
            page.goto(args.url+'/proyecto-javiera',wait_until='domcontentloaded')
            page.get_by_role('button',name='Contratista nuevo').click()
            expect(page.get_by_label('Razón social',exact=True)).to_be_visible()
            expect(page.get_by_text('Selecciona la empresa',exact=True)).to_have_count(0)
            page.locator('.jv-form select').first.select_option(site['id'])
            page.get_by_label('Razón social',exact=True).fill('JAVIERA NUEVA 20.2 QA '+suffix)
            page.get_by_label('RUT de empresa',exact=True).fill(_rut(82000000+seed))
            page.get_by_role('button',name='Guardar y continuar').click()
            expect(page.locator('.jv-company-confirmed')).to_be_visible()
            expect(page.get_by_text('Selecciona la empresa',exact=True)).to_have_count(0)
            page.locator('.jv-module .jv-hero-back-row .jv-back').click()
            page.get_by_role('button',name='Contratista existente').click()
            expect(page.get_by_label('Razón social',exact=True)).to_have_count(0)
            expect(page.locator('.jv-picker-card')).to_have_count(10)
            report['scenarios']['new_existing_and_all_ten_documents']='PASS'
            page.get_by_role('button',name='Solo prevención',exact=True).click()
            expect(page.get_by_text('6 seleccionados',exact=True)).to_be_visible()
            page.get_by_role('button',name='Limpiar selección',exact=True).click()
            page.get_by_label('Buscar documento').fill('irl')
            expect(page.locator('.jv-picker-card')).to_have_count(1)
            page.locator('.jv-picker-card input').check()
            page.get_by_label('Buscar documento').fill('')
            report['scenarios']['search_and_multi_selection']='PASS'
            form=page.locator('.jv-form')
            form.locator('select').nth(0).select_option(site['id'])
            form.locator('select').nth(1).select_option(company['contractor_id'])
            form.locator('select').nth(2).select_option(people[0])
            page.locator('.jv-form input[list="javiera-cargos"]').fill('PINTOR QA '+suffix)
            page.get_by_label('Expediente anterior').select_option(dossiers[0])
            expect(page.get_by_role('button',name='Generar documentos listos')).to_be_disabled()
            report['scenarios']['recover_without_false_unsaved_changes']='PASS'
            form.locator('select').nth(2).select_option(people[1])
            expect(page.locator('.jv-form input[list="javiera-cargos"]')).to_have_value('')
            expect(page.get_by_role('button',name='Generar documentos listos')).to_be_disabled()
            report['scenarios']['worker_context_reset']='PASS'
            page.get_by_label('Generar para varios expedientes guardados').check()
            page.get_by_role('button',name='Seleccionar hasta 20 expedientes').click()
            expect(page.locator('.jv-batch-targets input:checked')).to_have_count(2)
            page.get_by_role('button',name='Generar documentos listos').click()
            expect(page.get_by_text('Lote terminado:',exact=False)).to_be_visible(timeout=30000)
            # Sparse dossiers lack required facts. Both failures must be reported;
            # no synthetic test is allowed to bypass the actual emission checks.
            expect(page.locator('.jv-batch-report p')).to_have_count(2)
            expect(page.locator('.jv-batch-report a')).to_have_count(0)
            report['scenarios']['bulk_uses_saved_dossiers_and_reports_each_failure']='PASS'
            page.screenshot(path=str(args.output/'galant-201-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
            page.screenshot(path=str(args.output/'galant-201-mobile.png'),full_page=True)
            report['scenarios']['mobile_no_horizontal_scroll']='PASS'
            page.get_by_role('button',name='Editar Excel maestro y plantillas',exact=True).click()
            expect(page.get_by_role('heading',name='Documentos y matrices')).to_be_visible()
            expect(page.get_by_role('button',name='Excel avanzado')).to_be_visible()
            expect(page.locator('.jw-grid-scroll')).to_have_count(0)
            report['scenarios']['excel_configuration_available']='PASS'
            assert not errors,errors
            report.update(status='PASS',console_errors=errors)
            print('PASS Javiera 20.2 — new/existing, readiness, simplified Excel and mobile')
        finally:
            (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            browser.close()


if __name__=='__main__':
    main()
