#!/usr/bin/env python3
"""Pruebas UX 2026 de GALANT: SOLO QA local y usuarios sintéticos.

Ejecuta navegación real, controles de obra, responsive y capturas para revisión.
No altera registros laborales reales ni despliega versiones.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

URL = os.environ.get("GALANT_QA_URL", "http://127.0.0.1:18612").rstrip("/")
OUT = Path(os.environ.get("GALANT_UX_OUTPUT", "/tmp/galant-ux-2026")).resolve()
EMAIL = os.environ["GALANT_QA_EMAIL"]
PASSWORD = os.environ["GALANT_QA_PASSWORD"]

if urlparse(URL).hostname not in {"localhost", "127.0.0.1"}:
    raise SystemExit("SEGURIDAD: esta prueba solo puede ejecutarse contra QA local")
OUT.mkdir(parents=True, exist_ok=True)
SCREENS = [(390, 844), (768, 1024), (1024, 768), (1366, 768), (1440, 900), (1920, 1080)]


def assert_no_horizontal_page_scroll(page, name: str) -> None:
    metrics = page.evaluate("""() => ({
        viewport: window.innerWidth,
        document: document.documentElement.scrollWidth,
        body: document.body.scrollWidth
    })""")
    assert metrics["document"] <= metrics["viewport"] + 2, (name, metrics)
    assert metrics["body"] <= metrics["viewport"] + 2, (name, metrics)


def open_sidebar_if_mobile(page, width: int) -> None:
    if width <= 760:
        menu = page.get_by_role("button", name=re.compile("Expandir menú|Contraer menú|Cerrar menú")).first
        menu.click()
        expect(page.locator(".platform.menu-open")).to_be_visible()


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        reduced_motion="reduce",
        locale="es-CL",
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append("JS: " + str(error)))
    page.on("response", lambda response: errors.append(f"HTTP {response.status}: {response.url}") if response.status >= 500 else None)
    page.goto(URL, wait_until="domcontentloaded")
    page.get_by_label("Correo electrónico", exact=True).fill(EMAIL)
    page.get_by_label("Contraseña", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Ingresar a GALANT").click()
    expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible()

    sites = context.request.get(URL + "/api/v1/ops/sites").json()
    assert sites, "No hay obras sintéticas en QA"
    site = next((site for site in sites if "concepci" in site["name"].lower()), sites[0])
    nav_contractor = page.get_by_role("button", name="Contratistas", exact=True)
    nav_contractor.click()
    select = page.get_by_label("Obra seleccionada", exact=True)
    expect(select).to_have_count(1)
    select.select_option(site["id"])
    expect(select).to_have_value(site["id"])

    # La fuente de verdad de obra es el selector global; no duplicar en el módulo.
    expect(page.get_by_label("Seleccionar obra de contratistas")).to_have_count(0)
    expect(page.get_by_role("button", name="Importar Excel o CSV", exact=True)).to_have_count(1)
    metrics = select.evaluate("""el => {
      const b = el.getBoundingClientRect();
      const s = window.getComputedStyle(el);
      return {height: b.height, width:b.width, lineHeight:s.lineHeight, text:el.selectedOptions[0]?.text || ""}
    }""")
    assert metrics["height"] >= 39, f"Selector demasiado bajo: {metrics}"
    assert metrics["width"] >= 180, f"Selector demasiado estrecho: {metrics}"
    assert site["name"] == metrics["text"], f"No seleccionó la obra esperada: {metrics}"

    # Capturas de las pantallas centrales a resolución de escritorio.
    for label in ["Contratistas", "Trabajadores", "Control de asistencia", "Control documental", "Cotizaciones y pagos", "Evaluación administrativa", "Inicio"]:
        page.get_by_role("button", name=label, exact=True).click()
        expect(page.locator(".page")).to_be_visible()
        page.screenshot(path=str(OUT / ("desktop-" + label.lower().replace(" ", "-") + ".png")), full_page=True, animations="disabled")
        assert_no_horizontal_page_scroll(page, label)

    for width, height in SCREENS:
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(120)
        open_sidebar_if_mobile(page, width)
        page.get_by_role("button", name="Contratistas", exact=True).click()
        expect(page.get_by_label("Obra seleccionada", exact=True)).to_be_visible()
        assert_no_horizontal_page_scroll(page, f"{width}x{height}")
        sel = page.get_by_label("Obra seleccionada", exact=True).bounding_box()
        assert sel and sel["height"] >= 39, (width, sel)
        assert sel["x"] >= -1 and sel["x"] + sel["width"] <= width + 2, (width, sel)
        page.screenshot(path=str(OUT / f"contractors-{width}x{height}.png"), full_page=True, animations="disabled")

    assert not errors, errors
    print("PASS UX GALANT 2026: obra, acciones únicas, 7 secciones, 6 resoluciones, capturas y errores JS/HTTP.")
    print("Capturas:", str(OUT))
    browser.close()
