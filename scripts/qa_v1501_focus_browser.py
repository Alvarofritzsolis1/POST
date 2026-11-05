#!/usr/bin/env python3
"""Regresión visual real de GALANT 15.0.1 en Chromium, contra QA sintética aislada."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

URL = os.environ.get("GALANT_QA_URL", "http://127.0.0.1:18612").rstrip("/")
EMAIL = os.environ["GALANT_QA_EMAIL"]
PASSWORD = os.environ["GALANT_QA_PASSWORD"]
OUT = Path(os.environ.get("GALANT_FOCUS_QA_OUTPUT", "/tmp/galant-focus-qa")).resolve()
if urlparse(URL).hostname not in {"localhost", "127.0.0.1"}:
    raise SystemExit("SEGURIDAD: solo se puede probar una instancia QA local.")
OUT.mkdir(parents=True, exist_ok=True)

PROBE = """() => {
  if (window.__galantProbeId) clearInterval(window.__galantProbeId);
  window.__galantProbe = [];
  const snapshot = () => {
    const anchor = document.querySelector(".av93-month-matrix");
    const sidebar = document.querySelector(".platform .sidebar");
    const root = document.documentElement;
    return {
      scrollY: window.scrollY,
      anchorTop: anchor ? anchor.getBoundingClientRect().top : null,
      sidebarScroll: sidebar ? sidebar.scrollTop : null,
      scrollHeight: root.scrollHeight,
      viewportWidth: window.innerWidth,
      contentWidth: root.scrollWidth
    };
  };
  window.__galantSnapshot = snapshot;
  window.__galantProbeId = setInterval(() => {
    if (window.__galantProbe.length < 500) window.__galantProbe.push(snapshot());
  }, 25);
  return snapshot();
}"""

def assert_stable(page, before, label):
    samples = page.evaluate("""() => {
      clearInterval(window.__galantProbeId);
      return [...window.__galantProbe, window.__galantSnapshot()];
    }""")
    assert len(samples) >= 5, (label, "Se registraron muy pocas muestras", len(samples))
    assert before["scrollY"] > 0, (label, "El ensayo no comprobó un desplazamiento vertical real", before)
    assert 0 <= before["anchorTop"] < page.viewport_size["height"] - 30, (
        label, "La tabla debe ser visible durante la prueba", before)
    for i, current in enumerate(samples):
        assert current["anchorTop"] is not None, (label, "Tabla desapareció durante la actualización", i, current)
        assert abs(current["scrollY"] - before["scrollY"]) <= 2, (
            label, "El desplazamiento vertical cambió", i, before, current)
        assert abs(current["anchorTop"] - before["anchorTop"]) <= 2, (
            label, "La tabla se desplazó en pantalla", i, before, current)
        assert current["contentWidth"] <= current["viewportWidth"] + 2, (
            label, "Apareció desplazamiento horizontal global", i, current)
        if before["sidebarScroll"] is not None and current["sidebarScroll"] is not None:
            assert abs(current["sidebarScroll"] - before["sidebarScroll"]) <= 2, (
                label, "El menú lateral cambió de posición", i, before, current)
    return {"label": label, "samples": len(samples),
            "scrollY": before["scrollY"], "anchorTop": before["anchorTop"],
            "maxDeltaY": max(abs(s["scrollY"] - before["scrollY"]) for s in samples),
            "maxTableShift": max(abs(s["anchorTop"] - before["anchorTop"]) for s in samples)}

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 540},
        reduced_motion="reduce", locale="es-CL")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append("JS: " + str(e)))
    page.on("response", lambda r: errors.append(f"HTTP {r.status}: {r.url}") if r.status >= 500 else None)

    # Retardo real de la API de asistencia para inspeccionar la UI durante el estado loading.
    def slow_attendance(route):
        response = route.fetch()
        time.sleep(0.45)
        route.fulfill(response=response)
    page.route("**/api/v1/attendance-v81/overview?*", slow_attendance)

    results = []
    try:
        page.goto(URL, wait_until="domcontentloaded")
        page.get_by_label("Correo electrónico", exact=True).fill(EMAIL)
        page.get_by_label("Contraseña", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Ingresar a GALANT").click()
        expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible(timeout=20000)

        sites = context.request.get(URL + "/api/v1/ops/sites").json()
        assert sites, "No se encontraron obras QA"
        site = next((s for s in sites if "concepci" in s["name"].lower()), sites[0])
        page.get_by_role("button", name="Control de asistencia", exact=True).click()
        page.get_by_label("Obra seleccionada", exact=True).select_option(site["id"])
        page.get_by_label("Período auditado", exact=True).fill("2026-11")
        expect(page.locator(".av93-month-matrix tbody tr").first).to_be_visible(timeout=25000)
        expect(page.locator(".av92-weekbar")).to_be_visible()
        page.wait_for_timeout(700)

        # Comprobar regreso desde otra pestaña y refresco explícito, con scroll real.
        for width, height in [(1440, 540), (1024, 600)]:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(250)
            page.evaluate("""() => {
              const sidebar = document.querySelector(".platform .sidebar");
              if (sidebar) sidebar.scrollTop = Math.min(85, sidebar.scrollHeight-sidebar.clientHeight);
              const table = document.querySelector(".av93-month-matrix");
              if (table) {
                table.scrollIntoView({block: "start", behavior: "instant"});
                window.scrollBy({top: -145, behavior: "instant"});
              }
            }""")
            page.wait_for_timeout(120)
            before = page.evaluate(PROBE)
            page.screenshot(path=str(OUT / f"asistencia-antes-{width}.png"), animations="disabled")

            second = context.new_page()
            second.goto("about:blank")
            second.bring_to_front()
            page.wait_for_timeout(850)
            page.bring_to_front()
            page.wait_for_timeout(1200)
            results.append(assert_stable(page, before, f"retorno-pestana-{width}"))
            second.close()
            page.screenshot(path=str(OUT / f"asistencia-despues-{width}.png"), animations="disabled")

            before = page.evaluate(PROBE)
            page.evaluate("""() => window.dispatchEvent(new Event("galant-changed"))""")
            page.wait_for_timeout(1900)
            results.append(assert_stable(page, before, f"refresco-activo-{width}"))
            expect(page.locator(".av93-month-matrix tbody tr").first).to_be_visible()

        assert not errors, errors
        report={"result":"PASS","version":"15.0.1-rc1","site":site["name"],
                "tests":results,"errors":errors}
        (OUT / "focus-layout-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as exc:
        page.screenshot(path=str(OUT / "ERROR-focus-qa.png"), full_page=True, animations="disabled")
        (OUT / "ERROR-focus-qa.txt").write_text(str(exc) + "\n" + repr(errors), encoding="utf-8")
        raise
    finally:
        browser.close()
