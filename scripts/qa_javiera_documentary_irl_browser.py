"""Browser QA: Javiera documentary intake is isolated from GALANT operational registry.

Use only isolated stack (localhost) and synthetic QA identities.
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
    parser.add_argument("--url", default="http://127.0.0.1:18612")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if urlparse(args.url).hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit("Solo QA aislado: nunca ejecutar sobre datos reales.")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"version": "Javiera documental + IRL", "status": "FAIL", "scenarios": {}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,
            executable_path=os.environ.get("GALANT_QA_BROWSER_EXECUTABLE") or None)
        context = browser.new_context(viewport={"width": 1440, "height": 940},
                                       reduced_motion="reduce")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(args.url, wait_until="domcontentloaded")
            page.get_by_label("Correo electrónico", exact=True).fill(os.environ["GALANT_JAVIERA_QA_EMAIL"])
            page.get_by_label("Contraseña", exact=True).fill(os.environ["GALANT_JAVIERA_QA_PASSWORD"])
            page.get_by_role("button", name="Ingresar a GALANT").click()
            expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible(timeout=15000)
            sites = _api(context, args.url, "/ops/sites")
            site = next(x for x in sites if x["name"] == "Brisas de Junquillar")
            operational_before = _api(context, args.url, "/ops/contractors?site_id=" + site["id"])
            page.goto(args.url + "/proyecto-javiera", wait_until="domcontentloaded")
            expect(page.get_by_role("button", name="Contratista nuevo")).to_be_visible()
            expect(page.get_by_role("button", name="Contratista existente")).to_be_visible()
            page.get_by_role("button", name="Contratista nuevo").click()
            expect(page.get_by_role("heading", name="Generación documental interactiva")).to_be_visible()
            expect(page.get_by_role("heading", name="¿Qué necesitas generar?")).to_be_visible()
            page.get_by_role("combobox", name="Obra", exact=True).select_option(site["id"])
            suffix = uuid4().hex[:8]
            page.get_by_label("Razón social", exact=True).fill("JAVIERA DOCUMENTAL QA " + suffix)
            page.get_by_label("RUT de empresa", exact=True).fill(_rut(78000000 + int(suffix, 16) % 999999))
            page.get_by_role("button", name="Guardar y continuar").click()
            expect(page.get_by_text("Empresa guardada solo en Proyecto Javiera", exact=False)).to_be_visible(timeout=12000)
            operational_after = _api(context, args.url, "/ops/contractors?site_id=" + site["id"])
            assert len(operational_after) == len(operational_before)
            report["scenarios"]["company_never_creates_operational_contractor"] = "PASS"

            page.get_by_label("Nombre del trabajador", exact=True).fill("RENE SINTETICO " + suffix)
            page.get_by_label("RUT del trabajador", exact=True).fill(_rut(22000000 + int(suffix, 16) % 999999))
            page.get_by_role("button", name="Guardar trabajador").click()
            expect(page.get_by_text("Trabajador guardado solo en Proyecto Javiera", exact=False)).to_be_visible(timeout=12000)
            operational_workers = _api(context, args.url, "/ops/workers?site_id=" + site["id"])
            assert not any("RENE SINTETICO " + suffix == x.get("name") for x in operational_workers)
            report["scenarios"]["worker_never_creates_operational_assignment"] = "PASS"

            page.get_by_role("textbox", name="Cargo o especialidad").fill("TECHUMBRE")
            expect(page.get_by_role("textbox", name="Cargo o especialidad")).to_have_value("TECHUMBRE")
            page.get_by_role("button", name="Solo prevención").click()
            expect(page.get_by_text("5 seleccionados", exact=False)).to_be_visible()
            page.get_by_role("button", name="Limpiar selección").click()
            page.get_by_label("Buscar documento").fill("IRL")
            expect(page.locator(".jv-picker-card")).to_have_count(1)
            page.locator(".jv-picker-card input").check()
            page.get_by_label("Buscar documento").fill("")
            report["scenarios"]["techumbre_and_multi_document"] = "PASS"
            # Existing contractor must retrieve the same independent identity.
            page.get_by_role("button", name="Proyecto JAVIERA").click()
            page.get_by_role("button", name="Contratista existente").click()
            page.get_by_role("combobox", name="Obra", exact=True).select_option(site["id"])
            company_select=page.get_by_role("combobox", name="Empresa registrada")
            company_select.locator("option",has_text="JAVIERA DOCUMENTAL QA " + suffix).wait_for()
            company_select.select_option(label="JAVIERA DOCUMENTAL QA " + suffix + " · " + _rut(78000000 + int(suffix, 16) % 999999))
            worker_select=page.get_by_role("combobox",name="Trabajador")
            worker_select.locator("option",has_text="RENE SINTETICO " + suffix).wait_for()
            worker_select.select_option(label="RENE SINTETICO " + suffix + " · " + _rut(22000000 + int(suffix, 16) % 999999))
            expect(page.get_by_text("RENE SINTETICO " + suffix,exact=False).first).to_be_visible()
            report["scenarios"]["original_new_existing_entry_reuses_documentary_identity"]="PASS"

            page.screenshot(path=str(args.output / "javiera-documental-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+2")
            page.screenshot(path=str(args.output / "javiera-documental-mobile.png"), full_page=True)
            report["scenarios"]["mobile_no_horizontal_scroll"] = "PASS"
            page.get_by_role("button", name="Editar Excel maestro y plantillas").click()
            expect(page.get_by_role("heading", name="Documentos y matrices")).to_be_visible(timeout=12000)
            report["scenarios"]["excel_master_editor_reachable"] = "PASS"
            assert not errors, errors
            report["status"] = "PASS"
            print("PASS Javiera documental — altas aisladas, TECHUMBRE, documentos y móvil")
        finally:
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            browser.close()


if __name__ == "__main__":
    main()
