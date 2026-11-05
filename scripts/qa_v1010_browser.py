#!/usr/bin/env python3
"""Navegación real de Contratistas v10.10 contra QA aislada y datos sintéticos."""
import os
from uuid import uuid4
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

URL=os.environ.get("GALANT_QA_URL","http://127.0.0.1:18612")
if urlparse(URL).hostname not in {"localhost","127.0.0.1"}:
    raise SystemExit("Solo está permitido ejecutar esta prueba contra QA local")
EMAIL=os.environ["GALANT_QA_EMAIL"]
PASSWORD=os.environ["GALANT_QA_PASSWORD"]

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={"width":1440,"height":900},reduced_motion="reduce")
    page=context.new_page()
    errors=[]
    page.on("pageerror",lambda exc:errors.append(str(exc)))
    page.on("response",lambda res:errors.append("HTTP 500: "+res.url) if res.status>=500 else None)
    page.goto(URL)
    page.get_by_label("Correo electrónico",exact=True).fill(EMAIL)
    page.get_by_label("Contraseña",exact=True).fill(PASSWORD)
    page.get_by_role("button",name="Ingresar a GALANT").click()
    expect(page.get_by_role("button",name="Menú de usuario")).to_be_visible()
    sites=context.request.get(URL+"/api/v1/ops/sites").json()
    site=sites[0]
    csrf=next(c["value"] for c in context.cookies() if c["name"]=="galant_post_csrf")
    token=uuid4().hex[:8]
    def company(status):
        name="QA 1010 "+status+" "+token
        response=context.request.post(URL+"/api/v1/ops/contractors",headers={"X-CSRF-Token":csrf},
            data={"site_id":site["id"],"name":name,"historical_code":"CT",
                  "nature":"with_workers","frequency":"fixed","contract_status":status})
        assert response.status==201,(response.status,response.text())
        return name,response.json()
    active,active_row=company("active")
    inactive,inactive_row=company("inactive")
    # Un evento debe indicar el responsable por nombre, sin exponer correo en la UI.
    audit_response=context.request.get(URL+"/api/v1/ops/history",
        params={"entity_type":"contractor","entity_id":active_row["contractor_id"]})
    assert audit_response.status==200,(audit_response.status,audit_response.text())
    audit=audit_response.json()
    assert audit and all("actor_name" in item and "@" not in item["actor_name"] for item in audit),audit
    page.get_by_role("button",name="Contratistas",exact=True).click()
    page.get_by_label("Obra seleccionada").select_option(site["id"])
    expect(page.get_by_role("button",name="Activos",exact=True)).to_have_attribute("aria-pressed","true")
    expect(page.get_by_role("button",name="Abrir ficha de "+active)).to_be_visible()
    expect(page.get_by_role("button",name="Abrir ficha de "+inactive)).to_have_count(0)
    for i in range(4):
        page.get_by_role("button",name="Abrir ficha de "+active).click()
        expect(page.get_by_role("region",name="Ficha del contratista")).to_be_visible()
        expect(page.locator(".ops-v15-metrics > div")).to_have_count(2)
        expect(page.get_by_text("Cumplimiento documental",exact=True)).to_be_visible()
        expect(page.get_by_text("Requieren atención",exact=True)).to_be_visible()
        expect(page.get_by_role("button",name="Volver a contratistas",exact=True)).to_be_visible()
        expect(page.get_by_text("Documentación mensual",exact=True)).to_be_visible()
        expect(page.get_by_label("Filtrar por estado documental")).to_be_visible()
        expect(page.get_by_role("button",name="Contratos",exact=True)).to_be_visible()
        expect(page.get_by_role("button",name="Asistencia",exact=True)).to_be_visible()
        page.get_by_role("button",name="Asistencia",exact=True).click()
        expect(page.get_by_role("button",name="Abrir asistencia semanal")).to_be_visible()
        page.get_by_role("button",name="Documentación",exact=True).last.click()
        expect(page.get_by_role("button",name="Finiquitos",exact=True)).to_be_visible()
        selected_month = page.locator("#monthly-period").input_value()
        if i == 0:
            priority = page.locator(".ops-v15-priorities > button").first
            if priority.count():
                page.get_by_label("Filtrar por estado documental").select_option("approved")
                priority.click()
                expect(page.get_by_label("Filtrar por estado documental")).to_have_value("all")
            page.locator("#monthly-period").fill("2026-10")
            expect(page.locator(".ops-v15-identity")).to_contain_text("2026-10")
            page.get_by_role("button",name="Resumen",exact=True).click()
            page.get_by_role("button",name="Documentación",exact=True).last.click()
            expect(page.locator("#monthly-period")).to_have_value("2026-10")
            page.locator("#monthly-period").fill(selected_month)
            expect(page.locator("#monthly-period")).to_have_value(selected_month)
        page.get_by_role("button",name="Contratos",exact=True).click()
        expect(page.get_by_text("Contratos laborales",exact=True)).to_be_visible()
        page.get_by_role("button",name="Finiquitos",exact=True).click()
        expect(page.get_by_text("Finiquitos y términos de contrato",exact=True)).to_be_visible()
        page.get_by_role("button",name="Documentación",exact=True).last.click()
        expect(page.locator("#monthly-period")).to_have_value(selected_month)
        page.get_by_role("button",name="Trabajadores",exact=True).last.click()
        expect(page.get_by_text("Trabajadores y situación laboral",exact=True)).to_be_visible()
        page.get_by_role("button",name="Documentación",exact=True).last.click()
        expect(page.get_by_text("Documentación mensual",exact=True)).to_be_visible()
        page.get_by_role("button",name="Volver a contratistas",exact=True).click()
        expect(page.get_by_role("region",name="Ficha del contratista")).to_have_count(0)
    page.get_by_role("button",name="Inactivos",exact=True).click()
    expect(page.get_by_role("button",name="Abrir ficha de "+inactive)).to_be_visible()
    expect(page.get_by_role("button",name="Abrir ficha de "+active)).to_have_count(0)
    page.get_by_role("button",name="Abrir ficha de "+inactive).click()
    page.get_by_role("button",name="Documentación",exact=True).last.click()
    expect(page.get_by_text("Contratista inactivo: no se generan nuevas obligaciones documentales para este período.",exact=False)).to_be_visible()
    page.get_by_role("button",name="Volver a contratistas",exact=True).click()
    page.get_by_role("button",name="Todos",exact=True).click()
    expect(page.get_by_role("button",name="Abrir ficha de "+active)).to_be_visible()
    expect(page.get_by_role("button",name="Abrir ficha de "+inactive)).to_be_visible()
    assert not errors,errors
    print("PASS: abrir/cerrar fichas, estado ACTIVO/INACTIVO/TODOS, pestañas y ausencia de errores de React")
    browser.close()
