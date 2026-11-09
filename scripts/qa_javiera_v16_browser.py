"""Browser acceptance for the independent JAVIERA v16.6 wizard.

Only against an isolated local QA stack with synthetic identities.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
from qa_javiera_v165_workflow_browser import _publish_pts, _api, _rut


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:18612")
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Solo se permite QA local en 127.0.0.1")
    args.output.mkdir(parents=True, exist_ok=True)
    failures, responses = [], []
    report = {"version": "19.1.0-rc1", "at": datetime.now(timezone.utc).isoformat(),
              "scenarios": {}, "console_errors": [], "server_errors": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=os.environ.get("GALANT_QA_BROWSER_EXECUTABLE") or None)
        context = browser.new_context(viewport={"width": 1440, "height": 1000},
                                      reduced_motion="reduce", accept_downloads=True)
        page = context.new_page()
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.on("response", lambda response: responses.append({
            "status": response.status, "path": urlparse(response.url).path
        }) if response.status >= 500 else None)
        try:
            page.goto(args.url, wait_until="domcontentloaded")
            page.get_by_label("Correo electrónico", exact=True).fill(
                os.environ["GALANT_JAVIERA_QA_EMAIL"])
            page.get_by_label("Contraseña", exact=True).fill(
                os.environ["GALANT_JAVIERA_QA_PASSWORD"])
            page.get_by_role("button", name="Ingresar a GALANT").click()
            expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible()
            report["scenarios"]["login"] = "PASS"
            # Synthetic approved template and matrix; NEVER makes legal claims.
            _publish_pts(context, browser, args.url)
            sites = _api(context, args.url, "/ops/sites")
            site = next(s for s in sites if s["name"] == "Brisas de Junquillar")
            suffix = uuid4().hex[:8]
            seed = int(suffix, 16) % 999999
            page.goto(args.url + "/proyecto-javiera", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="Documentos listos para preparar e imprimir")).to_be_visible()
            expect(page.get_by_role("heading", name="¿La empresa es nueva o ya existe?")).to_be_visible()
            report["scenarios"]["html_primary_without_excel_import"] = "PASS"
            page.get_by_role("button", name="Editar formatos HTML").click()
            expect(page.get_by_role("heading", name="Editor de formatos HTML")).to_be_visible()
            expect(page.get_by_label("Texto y estructura HTML")).to_be_visible()
            report["scenarios"]["html_editor_in_main_workflow"] = "PASS"
            page.get_by_role("button", name="Volver a documentos").click()
            expect(page.get_by_role("heading", name="¿La empresa es nueva o ya existe?")).to_be_visible()
            expect(page.get_by_role("heading", name="Generador de documentos PDF A4")).to_be_visible()
            report["scenarios"]["new_or_existing_first"] = "PASS"
            page.screenshot(path=str(args.output / "javiera_inicio.png"), full_page=True)

            page.locator(".j166-panel label.j166-field:has(span:text-is(\"Obra\")) select").select_option(site["id"])
            page.get_by_label("Razón social").fill("EMPRESA DOCUMENTAL QA " + suffix)
            page.get_by_label("RUT de empresa (si se conoce)").fill(_rut(76000000 + seed))
            page.get_by_role("button", name="Continuar a documentos").click()
            expect(page.get_by_role("heading", name="¿Qué documentos quieres preparar?")).to_be_visible()
            report["scenarios"]["company_created_documentary_only"] = "PASS"
            expect(page.locator(".j166-doc")).to_have_count(10)
            for area in ["Zona Subcontratos", "Prevención de Riesgos"]:
                expect(page.get_by_role("heading", name=area)).to_be_visible()
            report["scenarios"]["ten_documents_two_areas"] = "PASS"

            page.get_by_text("Procedimiento de Trabajo Seguro (PTS)", exact=True).click()
            assert page.locator(".j166-doc input:checked").count() == 1
            page.get_by_role("button", name="Continuar", exact=True).click()
            expect(page.get_by_role("heading", name="Completar antecedentes una sola vez")).to_be_visible()
            report["scenarios"]["checkbox_selection"] = "PASS"
            page.screenshot(path=str(args.output / "javiera_antecedentes.png"), full_page=True)
            page.get_by_label("Nombre completo", exact=True).fill("PERSONA DOCUMENTAL QA " + suffix)
            page.get_by_label("RUT", exact=True).fill(_rut(20000000 + seed))
            page.get_by_label("Labor / especialidad").fill("Pintura")
            page.get_by_label("Nombre del representante legal").fill("REPRESENTANTE SINTÉTICO")
            page.get_by_label("RUT del representante legal").fill(_rut(15000000 + seed))
            page.get_by_label("Fecha efectiva del documento").fill("2026-11-09")
            assert page.locator("details.j166-doc-accordion").count() == 1
            assert page.locator("details.j166-doc-accordion").first.get_attribute("open") is not None
            report["scenarios"]["editable_accordion_document_fields"] = "PASS"
            assert page.get_by_label("Sueldo base ($ CLP)").count() == 0
            report["scenarios"]["no_labor_fields_for_pts"] = "PASS"
            page.get_by_role("button", name="Revisar documentos").click()
            expect(page.get_by_role("heading", name="Revisión e impresión")).to_be_visible(timeout=20000)
            report["scenarios"]["dossier_saved_independent"] = "PASS"
            # La ayuda y el botón comparten la misma frase: seleccionar
            # por rol accesible evita la ambigüedad de texto en Playwright.
            expect(page.get_by_role("button", name="Vista previa A4", exact=True)).to_be_visible()
            report["scenarios"]["native_preview_entrypoint_visible"] = "PASS"
            assert "Listo para emitir" in page.locator(".j166-status").inner_text(), (
                "PTS no está listo con plantilla y matriz sintéticas aprobadas")
            report["scenarios"]["eligibility_document_specific"] = "PASS"
            expect(page.get_by_role("button", name="Preparar paquete PDF A4 (1)")).to_be_visible()
            report["scenarios"]["html_a4_primary_batch"] = "PASS"
            page.locator("details.j166-excel-legacy summary").click()
            page.get_by_role("button", name="Generar 1 documentos elegibles (Excel)").click()
            expect(page.get_by_text("Resultado del paquete")).to_be_visible(timeout=20000)
            expect(page.get_by_role("link", name="Imprimir paquete PDF")).to_be_visible()
            report["scenarios"]["batch_pdf_generated"] = "PASS"
            href = page.get_by_role("link", name="Imprimir paquete PDF").get_attribute("href")
            reply = context.request.get(args.url + href)
            assert reply.status == 200 and reply.headers["content-type"].startswith("application/pdf")
            assert reply.body()[:4] == b"%PDF"
            report["scenarios"]["packet_print_url_serves_pdf"] = "PASS"
            page.screenshot(path=str(args.output / "javiera_paquete.png"), full_page=True)

            # The new workflow cannot have created active operational records.
            local_companies = _api(context, args.url, "/javiera/v166/sources",
                                   data=None)
            assert any(c["name"] == "EMPRESA DOCUMENTAL QA " + suffix
                       for c in local_companies["companies"])
            assert not any(c["name"] == "EMPRESA DOCUMENTAL QA " + suffix
                           for c in local_companies["operational_companies"])
            report["scenarios"]["no_operational_contractor"] = "PASS"
            page.get_by_role("button", name="Historial", exact=True).click()
            expect(page.get_by_role("heading", name="Documentos emitidos")).to_be_visible()
            assert page.locator(".j166-result a").count() >= 2
            report["scenarios"]["immutable_history"] = "PASS"
            page.screenshot(path=str(args.output / "javiera_historial.png"), full_page=True)

            # Switching worker must clear old worker's private data and detach old dossier.
            page.get_by_role("button", name="Volver", exact=True).click()
            page.get_by_role("button", name="Corregir antecedentes").click()
            page.get_by_role("button", name="Existente", exact=True).click()
            page.get_by_role("button", name="Nueva", exact=True).click()
            expect(page.get_by_label("Nombre completo", exact=True)).to_have_value("")
            expect(page.get_by_label("RUT", exact=True)).to_have_value("")
            expect(page.get_by_label("Labor / especialidad")).to_have_value("")
            report["scenarios"]["person_switch_private_data_reset"] = "PASS"

            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(args.url + "/proyecto-javiera", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="Documentos listos para preparar e imprimir")).to_be_visible()
            widths = page.evaluate("({document:document.documentElement.scrollWidth,viewport:window.innerWidth})")
            assert widths["document"] <= widths["viewport"] + 2, widths
            report["scenarios"]["mobile_no_horizontal_scroll"] = "PASS"
            page.screenshot(path=str(args.output / "javiera_movil.png"), full_page=True)
            page.goto(args.url + "/configuracion/automatizacion", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="Configuración de automatización")).to_be_visible()
            for name in ["Plantillas y cláusulas", "Matrices PTS / IRL",
                         "Diseños Excel originales", "Habilitar PDF / revisiones"]:
                expect(page.get_by_role("button", name=name)).to_be_visible()
            report["scenarios"]["config_legacy_compatible"] = "PASS"
            page.get_by_role("button", name="Habilitar PDF / revisiones").click()
            expect(page.get_by_role("heading", name="Habilitar documentos para imprimir")).to_be_visible()
            report["scenarios"]["single_admin_pilot_print_validation_screen"] = "PASS"
            page.screenshot(path=str(args.output / "javiera_admin_piloto.png"), full_page=True)
            assert not failures, failures
            assert not responses, responses
            report.update(status="PASS", console_errors=failures, server_errors=responses)
            print("PASS: JAVIERA 19 · wizard, native PDF entrypoint, isolated identities and mobile")
        except Exception as exc:
            report.update(status="FAIL", error=str(exc), console_errors=failures,
                          server_errors=responses)
            page.screenshot(path=str(args.output / "javiera_fallo.png"), full_page=True)
            raise
        finally:
            (args.output / "browser-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2))
            browser.close()


if __name__ == "__main__":
    main()
