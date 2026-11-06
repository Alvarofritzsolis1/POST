"""Prueba de navegador real GALANT JAVIERA v16.5, sin producción ni PII.

Ejecutar solamente contra stack QA local descartable en GitHub Actions.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
from qa_javiera_v165_workflow_browser import verify_guided_workflow


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:18612")
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Solo se permite GALANT QA en 127.0.0.1")
    user = os.environ["GALANT_JAVIERA_QA_EMAIL"]
    password = os.environ["GALANT_JAVIERA_QA_PASSWORD"]
    args.output.mkdir(parents=True, exist_ok=True)
    js_errors, server_errors = [], []
    report = {"version":"16.5.0-rc1", "at":datetime.now(timezone.utc).isoformat(),
              "scenarios":{}, "console_errors":[],"server_errors":[]}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True,
            executable_path=os.environ.get("GALANT_QA_BROWSER_EXECUTABLE") or None)
        context = browser.new_context(viewport={"width":1440,"height":1000},
                                      reduced_motion="reduce")
        page = context.new_page()
        page.on("pageerror",lambda error:js_errors.append(str(error)))
        page.on("response",lambda response:server_errors.append({
            "status":response.status,"path":urlparse(response.url).path
        }) if response.status >= 500 else None)
        page.goto(args.url,wait_until="domcontentloaded")
        page.get_by_label("Correo electrónico",exact=True).fill(user)
        page.get_by_label("Contraseña",exact=True).fill(password)
        page.get_by_role("button",name="Ingresar a GALANT").click()
        expect(page.get_by_role("button",name="Menú de usuario")).to_be_visible()
        automation=page.get_by_role("button",name="Configuración de automatización")
        expect(automation).to_be_visible()
        account=page.get_by_role("button",name="Menú de usuario").bounding_box()
        automation_box=automation.bounding_box()
        assert account and automation_box
        assert automation_box["x"] >= account["x"] + account["width"] - 5, (
            "Configuración debe aparecer después del menú de usuario en el extremo derecho",
            account, automation_box)
        report["scenarios"]["automation_right_header"]="PASS"
        page.goto(args.url+"/proyecto-javiera",wait_until="domcontentloaded")
        expect(page.get_by_role("heading",name="¿Para quién prepararás los documentos?")).to_be_visible()
        choices=page.locator(".j65-entry button")
        expect(choices).to_have_count(2)
        assert "Contratistas" in choices.first.inner_text()
        assert "Subcontratos" in choices.nth(1).inner_text()
        report["scenarios"]["selection"]="PASS"
        page.screenshot(path=str(args.output/"javiera_inicio.png"),full_page=True)

        choices.first.click()
        expect(page.get_by_role("heading",name="Preparar e imprimir documentos")).to_be_visible()
        expect(page.locator(".j65-entry button")).to_have_count(0)
        expect(page.locator(".j65-doc-choice")).to_have_count(6)
        expect(page.locator(".j65-tabs button.selected")).to_contain_text("Prevención de Riesgos")
        report["scenarios"]["prevention_six_documents"]="PASS"

        page.get_by_role("button",name="Procedimiento de trabajo seguro (PTS)").click()
        expect(page.get_by_role("heading",name="Procedimiento de trabajo seguro (PTS)")).to_be_visible()
        assert page.get_by_label("Sueldo base ($ CLP)").count()==0
        assert page.get_by_label("Jornada semanal (horas)").count()==0
        assert page.get_by_label("Fecha de término del contrato").count()==0
        assert page.get_by_label("Vínculo laboral").count()==0
        expect(page.get_by_role("button",name="Imprimir PDF")).to_be_disabled()
        report["scenarios"]["preventive_without_contract_fields"]="PASS"
        page.screenshot(path=str(args.output/"javiera_prevencion.png"),full_page=True)

        # Empresa y trabajador nuevos: no se exige que ya existan en GALANT.
        page.locator(".j65-editor .j65-section").first.locator("select").first.select_option(label="Brisas de Junquillar")
        suffix=uuid4().hex[:8]
        page.get_by_label("Nombre o razón social del empleador").fill("EMPRESA SINTETICA JAVIERA QA "+suffix)
        page.get_by_label("Nombre completo del trabajador").fill("TRABAJADOR SINTETICO JAVIERA QA "+suffix)
        page.get_by_label("Labor / especialidad").fill("Pintura")
        expect(page.get_by_text("Cargo reconocido:")).to_contain_text("PINTOR")
        page.get_by_role("button",name="Guardar ficha").click()
        expect(page.get_by_text("Ficha guardada. Puedes preparar el PDF seleccionado.")).to_be_visible(timeout=15000)
        assert page.get_by_role("button",name="Imprimir PDF").is_disabled()
        report["scenarios"]["new_contractor_and_worker_in_one_save"]="PASS"

        page.get_by_role("button",name="Zona Subcontratos").click()
        expect(page.locator(".j65-doc-choice")).to_have_count(4)
        page.get_by_role("button",name="Contrato de trabajo").click()
        expect(page.get_by_label("Sueldo base ($ CLP)")).to_be_visible()
        expect(page.get_by_label("Jornada semanal (horas)")).to_be_visible()
        expect(page.get_by_label("Vínculo laboral")).to_be_visible()
        expect(page.get_by_label("AFP del trabajador")).to_be_visible()
        expect(page.get_by_label("Previsión de salud (Fonasa / Isapre)")).to_be_visible()
        assert page.get_by_label("representative name").count()==0
        report["scenarios"]["labor_fields_match_excel"]="PASS"
        page.screenshot(path=str(args.output/"javiera_subcontratos_laboral.png"),full_page=True)

        # Cambio de modalidad: el empleador directo y la principal siguen separados.
        page.get_by_role("button",name="Volver a Proyecto JAVIERA").click()
        choices=page.locator(".j65-entry button")
        expect(choices).to_have_count(2)
        choices.nth(1).click()
        page.get_by_role("button",name="Zona Subcontratos").click()
        page.get_by_role("button",name="Contrato de trabajo").click()
        expect(page.get_by_label("Contratista principal (no es el empleador directo)")).to_be_visible()
        report["scenarios"]["subcontractor_mode"]="PASS"

        page.set_viewport_size({"width":390,"height":844})
        expect(page.locator(".j65-documents")).to_be_visible()
        page.screenshot(path=str(args.output/"javiera_movil.png"),full_page=True)
        width=page.evaluate("({document:document.documentElement.scrollWidth,viewport:window.innerWidth})")
        assert width["document"] <= width["viewport"]+2,width
        report["scenarios"]["mobile_no_horizontal_scroll"]="PASS"

        page.set_viewport_size({"width":1440,"height":1000})
        page.goto(args.url+"/configuracion/automatizacion",wait_until="domcontentloaded")
        expect(page.get_by_role("heading",name="Configuración de automatización")).to_be_visible()
        for tab in ["Plantillas y cláusulas","Matrices PTS / IRL",
                    "Diseños Excel originales","Revisiones y aprobaciones"]:
            expect(page.get_by_role("button",name=tab,exact=True)).to_be_visible()
        page.get_by_role("button",name="Diseños Excel originales").click()
        expect(page.get_by_role("heading",name="Diseñador de documentos Excel")).to_be_visible()
        expect(page.get_by_role("button",name="Diseños Excel originales")).to_have_attribute("aria-pressed","true")
        page.get_by_role("button",name="Revisiones y aprobaciones").click()
        expect(page.get_by_role("heading",name="Mesa de revisión laboral y preventiva")).to_be_visible()
        expect(page.get_by_role("button",name="Revisiones y aprobaciones")).to_have_attribute("aria-pressed","true")
        expect(page.get_by_role("button",name="Diseños Excel originales")).to_have_attribute("aria-pressed","false")
        report["scenarios"]["admin_configuration_tabs"]="PASS"
        page.screenshot(path=str(args.output/"javiera_configuracion.png"),full_page=True)
        try:
            verify_guided_workflow(page, context, browser, args.url, args.output, report)
        except Exception as error:
            report.update(status="FAIL", error=str(error), console_errors=js_errors, server_errors=server_errors)
            page.screenshot(path=str(args.output/"javiera_fallo.png"),full_page=True)
            (args.output/"browser-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
            raise
        assert not js_errors,js_errors
        assert not server_errors,server_errors
        report["console_errors"]=js_errors
        report["server_errors"]=server_errors
        report["status"]="PASS"
        (args.output/"browser-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print("PASS: JAVIERA 16.5 · 14 escenarios: ficha, RUT, PDF, reemisión, aislamiento, móvil y configuración")
        browser.close()


if __name__=="__main__":
    main()
