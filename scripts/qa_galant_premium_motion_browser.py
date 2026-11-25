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
    expect(page.locator(".signature-login")).to_be_visible(timeout=10000)
    expect(page.locator(".signature-login__version")).to_be_visible()
    expect(page.locator(".signature-login__art")).to_have_count(1)
    assert page.get_by_text("ACCESO PRIVADO", exact=True).count() == 0, "Portada Signature sin texto redundante"
    version = page.locator(".signature-login__version").bounding_box()
    assert version and version["x"] >= 0 and version["x"] + version["width"] <= page.viewport_size["width"] + 2, "Versión alineada dentro de pantalla"
    page.get_by_label("Correo electrónico", exact=True).fill(EMAIL)
    page.get_by_label("Contraseña", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Ingresar a GALANT").click()
    expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible(timeout=30000)
    expect(page.locator(".platform")).to_be_visible()
    expect(page.locator(".nw-profile-trigger .galant-person-avatar")).to_be_visible(timeout=10000)


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
    expect(main).to_have_css("margin-left", "66px")
    check(page.locator(".platform.galant-sidebar-peek").count() == 1, "El botón despliega temporalmente sin fijar el menú")
    page.mouse.move(20, 125)
    page.mouse.move(925, 240)
    expect(sidebar).to_have_css("width", "66px", timeout=3500)
    check(page.evaluate("localStorage.getItem('galant-sidebar-pinned')") is None, "No persiste una fijación")
    screenshot(page, "01-inicio-menu-automatico.png")
    # Una preferencia fijada por versiones anteriores no puede bloquear el auto-cierre.
    page.evaluate("localStorage.setItem('galant-sidebar-pinned', 'true')")
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(".platform .sidebar")).to_have_css("width", "66px")
    check(page.evaluate("localStorage.getItem('galant-sidebar-pinned')") is None,
          "Se descarta la preferencia antigua al cargar")
    check(page.locator(".v16-automation-entry").count() == 0,
          "Inicio no ofrece configuración propia de JAVIERA")
    page.get_by_role("button", name="Proyecto JAVIERA", exact=True).click()
    expect(page.locator(".v16-automation-entry")).to_be_visible(timeout=8000)
    check(page.locator(".v16-automation-entry").count() == 1,
          "La automatización aparece solamente en Proyecto JAVIERA")
    page.locator(".sidebar").get_by_role("button", name="Inicio", exact=True).click()
    check(page.locator(".v16-automation-entry").count() == 0,
          "La automatización desaparece al salir de JAVIERA")
    page.locator(".sidebar .nav-item").filter(has=page.locator("svg")).first.click()
    expect(page.locator(".platform .sidebar")).to_be_visible()
    check(page.locator(".sidebar .nav-item[aria-current='page']").count() == 1, "Existe un solo módulo activo")
    page.get_by_role("button", name="Red de Obras", exact=True).click()
    expect(page.get_by_role("heading", name="Red de Obras.", exact=True)).to_be_visible(timeout=20000)
    page.locator(".sidebar").get_by_role("button", name="Inicio", exact=True).click()
    expect(page.locator(".galant-metric")).to_have_count(5)
    page.get_by_role("button", name="Documentos pendientes").click()
    expect(page.locator(".sidebar .nav-item[aria-current='page']")).to_contain_text("Control documental")
    check(page.locator(".platform .galant-page-view").count() == 1, "Transición de página mantiene shell compartido")
    check(measure(page)["rootWidth"] <= 1442, "Sin scroll horizontal al cambiar a documentación")
    page.locator(".sidebar").get_by_role("button", name="Inicio", exact=True).click()
    expect(page.locator(".galant-metric")).to_have_count(5)
    page.get_by_role("button", name="Trabajadores", exact=True).click()
    expect(page.locator(".workers-page .galant-person-avatar").first).to_be_visible(timeout=15000)
    check(page.locator(".workers-page .galant-person-avatar").count() >= 1, "Trabajadores muestran caritas ilustradas coherentes")
    page.locator(".sidebar").get_by_role("button", name="Inicio", exact=True).click()
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
    card = phone.locator(".galant-workers-table tbody tr").first
    expect(card).to_be_visible(timeout=15000)
    check(card.evaluate("element => getComputedStyle(element).display") == "grid",
          "Trabajadores usa tarjetas responsive en móvil, no tabla cortada")
    check(phone.locator(".galant-workers-table thead").is_hidden(),
          "Las cabeceras tabulares se ocultan en vista compacta")
    check(phone.locator(".galant-workers-table tbody tr td:nth-child(11) button").first.is_visible(),
          "El botón Ver ficha de cada trabajador permanece visible")
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
