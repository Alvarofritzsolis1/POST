"""Browser acceptance for the independent JAVIERA v16.6 wizard.

Only against an isolated local QA stack with synthetic identities.
"""
import argparse
import json
import os
import re
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
    report = {"version": "19.3.1-rc1", "at": datetime.now(timezone.utc).isoformat(),
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
            page.get_by_role("button", name="Editar documentos visualmente").click()
            expect(page.get_by_role("heading", name="Editor visual de documentos")).to_be_visible()
            editor = page.get_by_role("textbox", name="Documento editable")
            expect(editor).to_be_visible()
            expect(page.get_by_role("combobox", name="Insertar dato automático")).to_be_visible()
            report["scenarios"]["visual_editor_without_html"] = "PASS"
            # Regression GALANT 19.3.1: selecting IRL must render the native
            # document structure and preventive matrix, not a blank HTML canvas.
            page.get_by_role("button", name=re.compile("INFORMACIÓN DE RIESGOS LABORALES")).click()
            expect(page.get_by_role("heading", name="Formato original, datos vinculados y matriz de riesgos")).to_be_visible()
            # Seleccionar un cargo de referencia real: no aceptar una tabla vacía
            # ni una matriz heredada de otro cargo durante el cambio.
            role_selector = page.get_by_role("combobox", name="Cargo que deseas revisar")
            expect(role_selector).not_to_have_value("", timeout=15000)
            role_selector.select_option("GASFITER")
            expect(page.locator(".jir-view-toolbar strong")).to_have_text("13", timeout=20000)
            # Revisar alarmas reales de la fuente por cargo, sin aprobar ni
            # rellenar consecuencias, medidas o sustancias inventadas.
            role_selector.select_option("CARPINTERO")
            warning = page.get_by_role("region", name="Alertas preventivas de matriz original")
            expect(warning).to_contain_text("40", timeout=20000)
            expect(warning).to_contain_text("No se completarán ni aprobarán automáticamente")
            expect(warning).to_contain_text("Contacto eléctrico directo o indirecto")
            expect(warning.get_by_role("button", name="Crear borrador de 13 riesgos en GALANT")).to_be_visible()
            role_selector.select_option("PAISAJISTA")
            expect(warning).to_contain_text("PAISAJISMO (REVISAR HDS)", timeout=20000)
            expect(warning).to_contain_text("no se vincula sin revisión preventiva")
            expect(warning).to_contain_text("Inventario")
            expect(warning.get_by_role("button", name="Crear ficha editable HDS en GALANT")).to_be_visible()
            role_selector.select_option("GASFITER")
            expect(page.locator(".jir-view-toolbar strong")).to_have_text("13", timeout=20000)
            report["scenarios"]["source_risk_and_hds_alerts"] = "PASS"
            # El IRL A4 debe estar abierto desde el ingreso; antes estaba
            # contraído y la interfaz parecía vacía aunque había contenido.
            expect(page.locator("details.jir-preview")).to_have_attribute("open", "", timeout=15000)
            expect(page.locator(".jir-risk-table thead th")).to_have_count(4)
            expect(page.get_by_role("columnheader", name="Actividad")).to_be_visible()
            expect(page.get_by_role("heading", name="3 - CARACTERÍSTICAS DE PRODUCTOS Y SUSTANCIAS A MANIPULAR")).to_be_visible()
            expect(page.get_by_role("heading", name="4 - ANTECEDENTES GENERALES Y NORMAS GENERALES DE SEGURIDAD")).to_be_visible()
            expect(page.get_by_role("button", name="Abrir Matrices y cargos")).to_be_visible()
            page.get_by_role("button", name="Abrir Matrices y cargos").click()
            expect(page.get_by_role("heading", name="Matrices y cargos")).to_be_visible()
            center = page.get_by_role("region", name="Centro de control de matrices")
            expect(center).to_be_visible()
            expect(center.get_by_role("heading", name="Centro de control y aprobaciones")).to_be_visible()
            expect(center.get_by_role("button", name=re.compile("Aprobadas"))).to_be_visible()
            expect(center.get_by_role("button", name=re.compile("Listas para revisar"))).to_be_visible()
            expect(center.get_by_role("button", name=re.compile("Con campos faltantes"))).to_be_visible()
            expect(center.get_by_role("button", name=re.compile("Referencias Excel sin aprobar"))).to_be_visible()
            # Comprobar el filtro y después restaurar todo el catálogo.
            center.get_by_role("button", name=re.compile("Referencias Excel sin aprobar")).click()
            expect(page.get_by_role("combobox", name="Filtrar por estado")).to_have_value("reference")
            center.get_by_role("combobox", name="Filtrar por estado").select_option("all")
            report["scenarios"]["matrix_approval_dashboard_visible"] = "PASS"
            # GALANT 19.4: los cinco tipos ya tienen contenido del Excel
            # aunque la organización aún no importe ni apruebe las matrices.
            for kind, expected, fields in (
                ("IRL", 25, 26), ("PTS", 26, 17), ("PERFILES", 26, 1),
                ("PUESTOS", 27, 4), ("SUSTANCIAS", 27, 12),
            ):
                page.locator("#jmx-kind").select_option(kind)
                expect(page.locator(".jmx-items small").first).to_contain_text(
                    f"{expected} referencias Excel", timeout=30000
                )
                expect(page.get_by_text(
                    "Matriz precargada automáticamente desde el Excel"
                )).to_be_visible(timeout=20000)
                if kind=="IRL":
                    expect(page.locator(".jmx-irl-task-list button")).to_have_count(fields)
                    expect(page.locator(".jmx-irl-fields textarea")).to_have_count(4)
                    expect(page.get_by_role("heading", name="Editar labores y riesgos, paso a paso")).to_be_visible()
                    expect(page.get_by_role("textbox", name="Cargo / puesto")).to_have_value("GASFITER")
                    complete = page.get_by_role("region", name="Revisión de campos del IRL")
                    expect(complete).to_contain_text("Campos estructurales completos")
                    # Seleccionar la misma categoría otra vez no puede vaciar
                    # el cargo y sus 26 registros (regresión de PR #55).
                    page.locator("#jmx-kind").select_option("IRL")
                    expect(page.locator(".jmx-irl-task-list button")).to_have_count(26)
                    expect(page.get_by_role("textbox", name="Cargo / puesto")).to_have_value("GASFITER")
                    # Un cargo nuevo vacío explica exactamente qué debe llenarse.
                    page.get_by_role("button", name="Nuevo cargo").click()
                    expect(complete).to_contain_text("1 tareas incompletas")
                    expect(complete.get_by_role("button", name=re.compile("Tarea 1:"))).to_be_visible()
                else:
                    expect(page.locator(".jmx-rows textarea")).to_have_count(fields)
            report["scenarios"]["five_matrices_preloaded_from_original_excel"] = "PASS"
            page.screenshot(path=str(args.output / "javiera_194_cinco_matrices.png"),
                            full_page=True)
            page.get_by_role("button", name="Volver al editor IRL").click()
            expect(page.get_by_role("heading", name="Formato original, datos vinculados y matriz de riesgos")).to_be_visible()
            expect(page.get_by_role("button", name="Editar texto complementario del IRL (opcional)")).to_be_visible()
            assert page.get_by_role("textbox", name="Documento editable").count() == 0
            report["scenarios"]["irl_visual_format_not_blank"] = "PASS"
            page.screenshot(path=str(args.output / "javiera_irl_formato_y_matriz.png"), full_page=True)
            page.get_by_role("button", name=re.compile("RECEPCIÓN DEL REGLAMENTO INTERNO")).click()
            expect(page.get_by_role("textbox", name="Documento editable")).to_be_visible()
            editor.fill("FORMATO DOCUMENTAL DE PRUEBA: constancia de recepción para el trabajador. ")
            page.get_by_role("combobox", name="Insertar dato automático").select_option("worker.name")
            page.get_by_role("combobox", name="Insertar dato automático").select_option("employer.name")
            page.get_by_role("button", name="Guardar borrador").click()
            expect(page.get_by_text("Borrador visual guardado", exact=False)).to_be_visible(timeout=20000)
            report["scenarios"]["visual_editor_saved_from_browser"] = "PASS"
            page.get_by_label(
                "Revisé que este texto corresponde al documento original y que no faltan cláusulas."
            ).check()
            page.get_by_role("button", name="Habilitar vista previa PDF A4").click()
            expect(page.get_by_text("Diseño habilitado para vista previa", exact=False)).to_be_visible(timeout=20000)
            report["scenarios"]["native_html_enabled_without_second_admin"] = "PASS"
            page.screenshot(path=str(args.output / "javiera_editor_html.png"), full_page=True)
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
            expect(page.get_by_role("button", name="Ver PDF A4 aquí", exact=True)).to_be_visible()
            report["scenarios"]["native_preview_entrypoint_visible"] = "PASS"
            # Las vistas previas HTML no exigen ni publican documentos Excel.
            # Comprobar la petición PDF real desde el botón principal.
            assert "Diseño disponible" in page.locator(".j166-status").inner_text()
            report["scenarios"]["html_status_without_legacy_issue"] = "PASS"
            expect(page.get_by_role("button", name="Preparar paquete PDF A4 (1)")).to_be_visible()
            with page.expect_response(
                lambda response: response.url.endswith("/api/v1/javiera/v19/preview/batch")
                and response.request.method == "POST",
                timeout=30000,
            ) as response_info:
                page.get_by_role("button", name="Preparar paquete PDF A4 (1)").click()
            result = response_info.value
            assert result.status == 200, "No se pudo generar el PDF HTML A4: " + str(result.status)
            assert result.headers["content-type"].startswith("application/pdf")
            assert result.body()[:4] == b"%PDF"
            report["scenarios"]["html_a4_primary_batch_pdf"] = "PASS"
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
            # Vista previa nativa NO debe crear emisiones, firmas ni paquetes históricos.
            expect(page.get_by_text("No hay paquetes registrados para esta búsqueda.")).to_be_visible()
            report["scenarios"]["native_preview_does_not_forge_history"] = "PASS"
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
            for name in ["Plantillas y cláusulas", "Matrices y cargos",
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
