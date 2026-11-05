#!/usr/bin/env python3
"""Real-browser configuration acceptance against an isolated localhost QA stack.

Creates synthetic contractors/accounts only. No documents are uploaded, and no
production host is accepted. Authentication is supplied through QA environment
variables in the same way as the existing GALANT browser checks.
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright


URL = os.environ.get("GALANT_QA_URL", "http://127.0.0.1:18612").rstrip("/")
OUT = Path(os.environ.get("GALANT_CONFIG_OUTPUT", "/workspace/work/configuration-browser")).resolve()
EMAIL = os.environ["GALANT_QA_EMAIL"]
PASSWORD = os.environ["GALANT_QA_PASSWORD"]
ROOT = "/api/v1/admin/configuration"
PERIOD = datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m")

if urlparse(URL).hostname not in {"127.0.0.1", "localhost"}:
    raise SystemExit("Esta prueba solo admite un servidor QA local con datos sintéticos")
OUT.mkdir(parents=True, exist_ok=True)


def sign_in(page, email, password):
    page.get_by_label("Correo electrónico", exact=True).fill(email)
    page.get_by_label("Contraseña", exact=True).fill(password)
    with page.expect_response(lambda response: response.url.endswith("/api/v1/auth/login")) as response:
        page.get_by_role("button", name="Ingresar a GALANT").click()
    assert response.value.status == 200


def no_horizontal_scroll(page):
    metrics = page.evaluate("""() => ({viewport: innerWidth,
        document: document.documentElement.scrollWidth, body: document.body.scrollWidth})""")
    assert metrics["document"] <= metrics["viewport"] + 2, metrics
    assert metrics["body"] <= metrics["viewport"] + 2, metrics


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True, executable_path=os.environ.get("GALANT_QA_CHROMIUM") or shutil.which("chromium"),
    )
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="es-CL",
                                  reduced_motion="reduce")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append("JavaScript: " + str(error)))
    page.on("response", lambda response: errors.append("HTTP 500: " + response.url)
            if response.status >= 500 else None)
    page.goto(URL)
    sign_in(page, EMAIL, PASSWORD)
    expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible()
    csrf = next(cookie["value"] for cookie in context.cookies() if cookie["name"] == "galant_post_csrf")
    headers = {"X-CSRF-Token": csrf}
    sites = context.request.get(URL + "/api/v1/ops/sites").json()
    site = sites[0]
    token = uuid4().hex[:8]
    contractor_response = context.request.post(URL + "/api/v1/ops/contractors", headers=headers, data={
        "site_id": site["id"], "name": "QA Configuración " + token,
        "historical_code": "CT", "nature": "with_workers", "frequency": "fixed",
        "contract_status": "active",
    })
    assert contractor_response.status == 201, contractor_response.text()
    contractor = contractor_response.json()
    bootstrap = context.request.get(URL + ROOT + "/bootstrap").json()
    gate = next(row for row in bootstrap["catalog"] if row["code"] == "porteria")

    # The existing settings menu must lead to a dedicated full-width route.
    page.get_by_role("button", name="Configuración", exact=True).click()
    page.get_by_role("button", name="Configuración General", exact=True).click()
    expect(page).to_have_url(re.compile(r"/admin/configuracion(?:\?.*)?$"))
    expect(page.get_by_role("heading", name="Configuración General", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="← Volver", exact=True)).to_be_visible()
    expect(page.locator("input[type=file]")).to_have_count(0)
    expect(page.locator(".global-filters")).not_to_be_visible()
    page.screenshot(path=str(OUT / "configuracion-general-escritorio.png"), full_page=True)
    no_horizontal_scroll(page)

    # Create a catalog entry and apply an individual obligation through the
    # actual preview/confirmation UI, then verify persistence in the API.
    page.goto(URL + "/admin/configuracion/documentos")
    page.get_by_label("Nombre del documento", exact=True).fill("Certificado QA navegador " + token)
    with page.expect_response(lambda response: response.url.endswith(ROOT + "/catalog")
                              and response.request.method == "POST") as added:
        page.get_by_role("button", name="Agregar documento", exact=True).click()
    assert added.value.status == 201, added.value.text()
    custom_document = added.value.json()
    page.get_by_label(re.compile(r"^Documento de la regla")).select_option(custom_document["id"])
    page.get_by_label(re.compile(r"^Ámbito de aplicación")).select_option("association")
    page.get_by_label(re.compile(r"^Contratistas de la regla")).select_option([contractor["id"]])
    page.get_by_label("Desde el período", exact=True).fill(PERIOD)
    page.get_by_label("Motivo del cambio", exact=True).fill("Exigencia sintética confirmada desde navegador")
    with page.expect_response(lambda response: response.url.endswith(ROOT + "/rules/preview")) as preview:
        page.get_by_role("button", name="Ver impacto", exact=True).click()
    assert preview.value.status == 200, preview.value.text()
    expect(page.get_by_role("region", name="Vista previa del cambio", exact=True)).to_be_visible()
    before_rule = context.request.get(URL + ROOT + "/summary?periods=" + PERIOD).json()
    assert not any(row["required"] for row in before_rule["obligations"]
                   if row["association_id"] == contractor["id"] and row["code"] == custom_document["code"])
    with page.expect_response(lambda response: response.url.endswith(ROOT + "/rules/apply")) as applied:
        page.get_by_role("button", name="Confirmar y guardar", exact=True).click()
    assert applied.value.status == 200, applied.value.text()
    page.reload()
    after_rule = context.request.get(URL + ROOT + "/summary?periods=" + PERIOD).json()
    assert any(row["required"] for row in after_rule["obligations"]
               if row["association_id"] == contractor["id"] and row["code"] == custom_document["code"])

    # A directly addressed contractor page uses the same persisted manual review.
    detail_url = URL + "/admin/configuracion/contratistas/" + contractor["id"] + "?tab=documentos"
    page.goto(detail_url)
    expect(page.get_by_role("heading", name=contractor["name"], exact=True)).to_be_visible()
    page.get_by_role("button", name="Revisar " + gate["name"] + " " + PERIOD, exact=True).click()
    page.get_by_label(re.compile(r"^Estado de revisión")).select_option("incomplete")
    page.get_by_label("Observaciones de revisión", exact=True).fill("Revisión manual: faltan jornadas en el informe")
    with page.expect_response(lambda response: response.url.endswith(ROOT + "/reviews")
                              and response.request.method == "PUT") as saved:
        page.get_by_role("button", name="Guardar revisión", exact=True).click()
    assert saved.value.status == 200, saved.value.text()
    persisted = context.request.get(URL + ROOT + "/summary?periods=" + PERIOD).json()
    item = next(row for row in persisted["obligations"] if row["association_id"] == contractor["id"]
                and row["code"] == "porteria")
    assert item["state"] == "incomplete", item
    assert item["document_id"] is None, item
    page.reload()
    expect(page.get_by_role("heading", name=contractor["name"], exact=True)).to_be_visible()
    expect(page.locator(".gc-state-incomplete").first).to_be_visible()
    expect(page.locator("input[type=file]")).to_have_count(0)

    # Browser history and the top-left back action must work without app reloads.
    page.get_by_role("button", name="← Volver", exact=True).click()
    expect(page).to_have_url(re.compile(r"/admin/configuracion/contratistas(?:\?.*)?$"))
    page.go_back()
    expect(page.get_by_role("heading", name=contractor["name"], exact=True)).to_be_visible()
    page.goto(URL + "/admin/configuracion")
    page.get_by_label(re.compile(r"^Selección de períodos")).select_option("manual")
    # The selector operates independently of the main app's single-month filter.
    month_input = page.get_by_label("Agregar mes", exact=True)
    for month in ("2026-09", "2026-10", "2026-11"):
        month_input.fill(month)
        page.get_by_role("button", name="Agregar período", exact=True).click()
    page.get_by_role("button", name="Consultar períodos", exact=True).click()
    expect(page.locator("input[type=file]")).to_have_count(0)
    page.screenshot(path=str(OUT / "configuracion-multiperiodo.png"), full_page=True)

    for width, height in [(390, 844), (768, 1024), (1440, 1000)]:
        page.set_viewport_size({"width": width, "height": height})
        no_horizontal_scroll(page)
        page.screenshot(path=str(OUT / f"configuracion-{width}.png"), full_page=True)

    # Both non-admin roles keep their established workspace and cannot open the
    # center by typing its URL; direct API reads are also denied.
    for role in ("administrative", "resident"):
        email = f"qa-config-{role}-{token}@example.cl"
        password = "synthetic-configuration-role-2026"
        account = context.request.post(URL + "/api/v1/admin/users", headers=headers, data={
            "email": email, "password": password, "role": role,
            "name": "Persona sintética " + role, "site_ids": [site["id"]],
        })
        assert account.status == 201, account.text()
        denied_context = browser.new_context(viewport={"width": 1440, "height": 900})
        denied_page = denied_context.new_page()
        denied_page.goto(URL + "/admin/configuracion")
        sign_in(denied_page, email, password)
        expect(denied_page.get_by_role("heading", name="Configuración General", exact=True)).to_have_count(0)
        expect(denied_page.get_by_role("button", name="Confirmar y guardar", exact=True)).to_have_count(0)
        response = denied_context.request.get(URL + ROOT + "/bootstrap")
        assert response.status == 403, (role, response.status, response.text())
        denied_context.close()

    assert not errors, errors
    print("PASS: ruta independiente, revisión manual persistente, multiperíodo, responsive, historial de navegación y acceso ADMIN")
    print("Capturas:", OUT)
    context.close()
    browser.close()
