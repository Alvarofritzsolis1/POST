#!/usr/bin/env python3
"""GALANT Premium Motion: prueba real y segura en QA aislada con Chromium.

No accede a producción, no modifica información de contratistas, no despliega.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright

URL = os.environ.get("GALANT_QA_URL", "http://127.0.0.1:18612").rstrip("/")
EMAIL = os.environ["GALANT_QA_EMAIL"]
PASSWORD = os.environ["GALANT_QA_PASSWORD"]
OUT = Path(os.environ.get("GALANT_PREMIUM_QA_OUTPUT", "/tmp/galant-premium-motion")).resolve()
if urlparse(URL).hostname not in {"127.0.0.1", "localhost"}:
    raise SystemExit("SEGURIDAD: las pruebas Premium Motion solo se ejecutan en QA local")
OUT.mkdir(parents=True, exist_ok=True)
report = {"checks": [], "screenshots": [], "errors": []}


def check(condition, label):
    assert condition, label
    report["checks"].append(label)


def auth(page):
    page.goto(URL, wait_until="domcontentloaded")
    page.get_by_label("Correo electrónico", exact=True).fill(EMAIL)
    page.get_by_label("Contraseña", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Ingresar a GALANT").click()
    expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible(timeout=30000)
    expect(page.locator(".platform")).to_be_visible()


def measure(page):
    return page.evaluate("""() => {
      const el = document.querySelector(".platform .sidebar");
      const main = document.querySelector(".platform .main");
      return {
        sidebar: el.getBoundingClientRect().width,
        mainOffset: parseFloat(getComputedStyle(main).marginLeft),
        viewport: innerWidth, rootWidth: document.documentElement.scrollWidth,
        bodyWidth: document.body.scrollWidth
      };
    }""")


def screenshot(page, name):
    path = OUT / name
    page.screenshot(path=str(path), full_page=True, animations="disabled")
    report["screenshots"].append(str(path))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    desktop = browser.new_context(viewport={"width": 1440, "height": 900}, locale="es-CL")
    page = desktop.new_page()
    page.on("pageerror", lambda exc: report["errors"].append("JS: " + str(exc)))
    page.on("response", lambda resp: report["errors"].append(f"HTTP {resp.status}: {resp.url}") if resp.status >= 500 else None)
    auth(page)
    sidebar = page.locator(".platform .sidebar")
    main = page.locator(".platform .main")
    expect(sidebar).to_have_css("width", "66px", timeout=5000)
    expect(page.locator(".galant-metric")).to_have_count(5, timeout=15000)
    m = measure(page)
    check(abs(m["mainOffset"] - 66) <= 1, "El tablero usa el ancho completo al contraer menú")
    check(m["rootWidth"] <= m["viewport"] + 2, "Sin scroll horizontal inicial")
    before_rows = page.locator(".sidebar .nav-item").evaluate_all("rows => rows.map(el => el.getBoundingClientRect().top)")
    page.mouse.move(15, 120)
    expect(sidebar).to_have_css("width", "250px", timeout=3500)
    m = measure(page)
    after_rows = page.locator(".sidebar .nav-item").evaluate_all("rows => rows.map(el => el.getBoundingClientRect().top)")
    check(all(abs(a-b) <= 2 for a,b in zip(before_rows,after_rows)), "La expansión conserva posición vertical de cada módulo")
    check(abs(m["mainOffset"] - 66) <= 1, "Hover superpuesto no desplaza dashboard")
    page.mouse.move(930, 240)
    expect(sidebar).to_have_css("width", "66px", timeout=3500)
    check(not page.locator(".galant-sidebar-peek").count(), "El menú retorna a estado compacto sin quedar abierto")
    page.mouse.move(15, 120)
    expect(sidebar).to_have_css("width", "250px", timeout=3500)
    page.evaluate("window.scrollTo(0, 350)")
    expect(sidebar).to_have_css("width", "66px", timeout=3500)
    check(measure(page)["mainOffset"] == 66, "Scroll del contenido cierra menú flotante sin desplazar la vista")
    page.evaluate("window.scrollTo(0, 0)")
    page.mouse.move(900, 190)

    page.locator(".topbar .menu-toggle").click()
    expect(sidebar).to_have_css("width", "250px", timeout=3500)
    expect(main).to_have_css("margin-left", "250px")
    check(page.evaluate("localStorage.getItem('galant-sidebar-pinned')") == "true", "La fijación persiste en el almacenamiento local")
    screenshot(page, "01-inicio-menu-fijado.png")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(".platform .sidebar")).to_have_css("width", "250px")
    check(page.evaluate("localStorage.getItem('galant-sidebar-pinned')") == "true", "Preferencia recuperada tras recarga")
    page.locator(".topbar .menu-toggle").click()
    expect(page.locator(".platform .sidebar")).to_have_css("width", "66px")
    check(page.evaluate("localStorage.getItem('galant-sidebar-pinned')") == "false", "Modo automático restaurado")
    page.locator(".sidebar .nav-item").filter(has=page.locator("svg")).first.click()
    expect(page.locator(".platform .sidebar")).to_be_visible()
    check(page.locator(".sidebar .nav-item[aria-current='page']").count() == 1, "Existe un solo módulo activo")
    page.get_by_role("button", name="Red de Obras", exact=True).click()
    expect(page.get_by_role("heading", name="Red de Obras.", exact=True)).to_be_visible(timeout=20000)
    page.get_by_role("button", name="Inicio", exact=True).click()
    expect(page.locator(".galant-metric")).to_have_count(5)
    page.get_by_role("button", name="Documentos pendientes").click()
    expect(page.locator(".sidebar .nav-item[aria-current='page']")).to_contain_text("Control documental")
    check(page.locator(".platform .galant-page-view").count() == 1, "Transición de página mantiene shell compartido")
    check(measure(page)["rootWidth"] <= 1442, "Sin scroll horizontal al cambiar a documentación")
    page.get_by_role("button", name="Inicio", exact=True).click()
    expect(page.locator(".galant-metric")).to_have_count(5)
    screenshot(page, "02-inicio-menu-compacto.png")
    check(not report["errors"], "Navegación escritorio sin errores JS o HTTP 5xx")

    mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, locale="es-CL")
    phone = mobile.new_page()
    auth(phone)
    expect(phone.locator(".platform.galant-touch-nav")).to_be_visible()
    expect(phone.locator(".sidebar")).to_be_hidden()
    phone.locator(".topbar .menu-toggle").click()
    expect(phone.locator(".platform.menu-open .sidebar")).to_be_visible()
    check(phone.locator(".v91-menu-backdrop").is_visible(), "Móvil ofrece backdrop táctil")
    screenshot(phone, "03-movil-menu-abierto.png")
    phone.locator(".sidebar .nav-item").filter(has_text="Trabajadores").first.click()
    expect(phone.locator(".platform.menu-open")).to_have_count(0)
    check(measure(phone)["rootWidth"] <= 392, "Móvil sin scroll horizontal global")
    screenshot(phone, "04-movil-modulo.png")
    mobile.close()

    tablet = browser.new_context(viewport={"width": 834, "height": 1112}, is_mobile=True, has_touch=True, locale="es-CL")
    pad = tablet.new_page()
    auth(pad)
    expect(pad.locator(".galant-touch-nav")).to_be_visible()
    pad.locator(".topbar .menu-toggle").click()
    expect(pad.locator(".platform.menu-open .sidebar")).to_be_visible()
    check(measure(pad)["rootWidth"] <= 836, "Tablet táctil usa drawer sin scroll horizontal")
    screenshot(pad, "05-tablet-menu.png")
    tablet.close()

    reduced = browser.new_context(viewport={"width": 1366, "height": 768}, reduced_motion="reduce", locale="es-CL")
    quiet = reduced.new_page()
    auth(quiet)
    animation = quiet.locator(".galant-page-view").evaluate("el => getComputedStyle(el).animationName")
    check(animation == "none", "Respeta prefers-reduced-motion")
    check(measure(quiet)["rootWidth"] <= 1368, "Modo accesible sin scroll horizontal")
    reduced.close()
    desktop.close()
    browser.close()
(OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"result": "PASS", **report}, ensure_ascii=False, indent=2))
