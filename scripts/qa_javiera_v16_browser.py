"""Prueba de navegador real GALANT JAVIERA v16.0.1, sin producción ni PII.

Ejecutar solamente contra stack QA local descartable en GitHub Actions.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


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
    report = {"version":"16.0.2-rc1", "at":datetime.now(timezone.utc).isoformat(),
              "scenarios":{}, "console_errors":[],"server_errors":[]}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
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
        expect(page.get_by_role("heading",name="Proyecto JAVIERA")).to_be_visible()
        choices=page.locator(".jv-mode-cards button")
        expect(choices).to_have_count(2)
        assert "Contratistas" in choices.nth(0).inner_text()
        assert "Subcontratos" in choices.nth(1).inner_text()
        report["scenarios"]["selection"]="PASS"
        page.screenshot(path=str(args.output/"javiera_inicio.png"),full_page=True)

        choices.first.click()
        expect(page.get_by_role("heading",name="Generación documental interactiva")).to_be_visible()
        def verify_expediente_header():
            """El rótulo debe estar en otra fila, incluso durante la carga del CSS diferido."""
            layout=page.evaluate("""() => {
                const hero=document.querySelector(".jv-module .jv-hero");
                const back=hero?.querySelector(".jv-hero-back-row .jv-back");
                const context=hero?.querySelector(":scope > small");
                if(!hero || !back || !context)return null;
                const b=back.getBoundingClientRect();
                const c=context.getBoundingClientRect();
                return {
                    display:getComputedStyle(hero).display,
                    back:{x:b.x,y:b.y,width:b.width,height:b.height,bottom:b.bottom},
                    context:{x:c.x,y:c.y,width:c.width,height:c.height},
                    viewport:innerWidth
                };
            }""")
            assert layout, "Encabezado del expediente no encontrado"
            assert layout["display"]=="grid", layout
            assert layout["context"]["y"] >= layout["back"]["bottom"]-1, layout
        verify_expediente_header()
        report["scenarios"]["hero_text_not_overlapping"]="PASS"
        expect(page.locator(".jv-doc-card")).to_have_count(10)
        areas=page.locator(".jv-doc-area h4").all_inner_texts()
        assert any("Zona Subcontratos" in x for x in areas),areas
        assert any("Prevención de Riesgos" in x for x in areas),areas
        count=page.get_by_role("button",name="Generar documentos listos (0)")
        expect(count).to_be_disabled()
        expect(page.get_by_text("Guarda los cambios para habilitar la exportación de PDFs.")).to_be_visible()
        report["scenarios"]["ten_doc_cards_and_no_false_ready"]="PASS"
        page.screenshot(path=str(args.output/"javiera_documentos.png"),full_page=True)

        page.locator(".jv-hero .jv-back").click()
        expect(page.locator(".jv-mode-cards button")).to_have_count(2)
        page.locator(".jv-mode-cards button").nth(1).click()
        expect(page.get_by_role("heading",name="Generación documental interactiva")).to_be_visible()
        expect(page.get_by_label("Contratista principal")).to_be_visible()
        expect(page.locator(".jv-doc-card")).to_have_count(10)
        report["scenarios"]["subcontractor_mode"]="PASS"

        page.set_viewport_size({"width":390,"height":844})
        verify_expediente_header()
        expect(page.locator(".jv-document-panel")).to_be_visible()
        page.screenshot(path=str(args.output/"javiera_movil.png"),full_page=True)
        width=page.evaluate("({document:document.documentElement.scrollWidth,viewport:window.innerWidth})")
        assert width["document"] <= width["viewport"]+2, width
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
        assert not js_errors,js_errors
        assert not server_errors,server_errors
        report["console_errors"]=js_errors
        report["server_errors"]=server_errors
        report["status"]="PASS"
        (args.output/"browser-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print("PASS: JAVIERA modos, catálogo 10 documentos, PDF bloqueado, móvil y configuraciones")
        browser.close()


if __name__=="__main__":
    main()
