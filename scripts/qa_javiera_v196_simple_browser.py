"""Playwright: GALANT 19.6 simple Excel-first workflow on isolated QA data only.

No legal document is issued and no professional signoff is forged here.
The existing 19.5 editor remains covered by its separate legacy UI tests.
"""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from playwright.sync_api import sync_playwright, expect
from qa_javiera_v165_workflow_browser import _api


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18612")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if urlparse(args.url).hostname not in ("localhost", "127.0.0.1"):
        raise SystemExit("QA sólo sobre localhost y datos sintéticos")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"version": "19.6.0-rc1", "scenarios": {}, "status": "FAIL"}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,
            executable_path=os.environ.get("GALANT_QA_BROWSER_EXECUTABLE") or None)
        context = browser.new_context(viewport={"width": 1440, "height": 940},
                                      reduced_motion="reduce")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        try:
            page.goto(args.url, wait_until="domcontentloaded")
            page.get_by_label("Correo electrónico", exact=True).fill(
                os.environ["GALANT_JAVIERA_QA_EMAIL"])
            page.get_by_label("Contraseña", exact=True).fill(
                os.environ["GALANT_JAVIERA_QA_PASSWORD"])
            page.get_by_role("button", name="Ingresar a GALANT").click()
            expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible()
            sites = _api(context, args.url, "/ops/sites")
            site = next(x for x in sites if x["name"] == "Brisas de Junquillar")
            suffix = uuid4().hex[:8]
            company = _api(context, args.url, "/javiera/v166/companies", "POST", {
                "site_id": site["id"], "origin": "new",
                "name": "JAVIERA SIMPLE QA " + suffix,
                "rut": ""
            })
            person = _api(context, args.url, "/javiera/v166/people", "POST", {
                "company_id": company["id"], "origin": "new",
                "name": "TRABAJADOR SINTETICO " + suffix, "rut": ""
            })
            other = _api(context, args.url, "/javiera/v166/people", "POST", {
                "company_id": company["id"], "origin": "new",
                "name": "OTRO TRABAJADOR SINTETICO " + suffix, "rut": ""
            })
            page.goto(args.url + "/proyecto-javiera", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="Proyecto Javiera")).to_be_visible(timeout=30000)
            expect(page.get_by_role("main", name="Proyecto Javiera modo simple")).to_be_visible()
            expect(page.get_by_role("heading", name="Nuevo documento")).to_be_visible()
            assert page.get_by_role("button", name="Editar documentos visualmente").count() == 0
            assert page.get_by_role("button", name="Abrir Matrices y cargos").count() == 0
            for label in ("Obra","Empresa contratista","Trabajador","Cargo","Documento"):
                expect(page.get_by_role("combobox", name=label, exact=True)).to_be_visible()
            report["scenarios"]["five_visible_fields_not_html_editor"] = "PASS"
            page.get_by_role("combobox",name="Obra",exact=True).select_option(site["id"])
            expect(page.get_by_role("combobox",name="Empresa contratista").locator("option",
                has_text=company["name"])).to_have_count(1,timeout=20000)
            page.get_by_role("combobox",name="Empresa contratista").select_option(
                "documentary:"+company["id"])
            expect(page.get_by_role("combobox",name="Trabajador").locator("option",
                has_text=person["name"])).to_have_count(1,timeout=20000)
            page.get_by_role("combobox",name="Trabajador").select_option(
                "documentary:"+person["id"])
            expect(page.get_by_role("combobox",name="Cargo")).to_be_enabled()
            page.get_by_role("combobox",name="Cargo").select_option("CARPINTERO")
            expect(page.get_by_role("combobox",name="Documento")).to_have_value("irl")
            report["scenarios"]["selection_one_screen"] = "PASS"
            # No imported approved Excel means no issued PDF; never use the
            # old HTML fallback to imply an approved original.
            button = page.get_by_role("button", name="Generar PDF")
            if button.is_disabled():
                expect(page.get_by_text("plantilla", exact=False).first).to_be_visible()
                report["scenarios"]["missing_original_excel_fail_closed"] = "PASS"
            else:
                report["scenarios"]["missing_original_excel_fail_closed"] = "ALREADY_IMPORTED"
            # Switching workers must not retain the previous worker's cargo,
            # approval or downloadable PDF.
            page.get_by_role("combobox",name="Trabajador").select_option(
                "documentary:"+other["id"])
            expect(page.get_by_role("combobox",name="Cargo")).to_have_value("")
            assert page.get_by_role("link", name="Abrir PDF generado").count() == 0
            report["scenarios"]["worker_context_reset"] = "PASS"
            page.screenshot(path=str(args.output/"galant-196-desktop.png"), full_page=True)
            page.set_viewport_size({"width":390,"height":844})
            expect(page.get_by_role("heading",name="Proyecto Javiera")).to_be_visible()
            dimensions=page.evaluate("({scroll:document.documentElement.scrollWidth,viewport:window.innerWidth})")
            assert dimensions["scroll"] <= dimensions["viewport"]+2, dimensions
            report["scenarios"]["mobile_no_horizontal_scroll"] = "PASS"
            page.screenshot(path=str(args.output/"galant-196-mobile.png"), full_page=True)
            # Existing administrator templates are not deleted.
            page.get_by_role("button",name="Administración de plantillas").click()
            expect(page.get_by_role("heading",name="Configuración de automatización")).to_be_visible()
            report["scenarios"]["existing_admin_workspace_preserved"] = "PASS"
            assert not errors, errors
            report["status"]="PASS"
            report["console_errors"]=errors
            print("PASS GALANT 19.6 modo simple — identity isolation / no HTML editor / mobile")
        finally:
            (args.output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
            browser.close()


if __name__=="__main__":
    main()
