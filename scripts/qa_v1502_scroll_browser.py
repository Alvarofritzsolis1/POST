#!/usr/bin/env python3
"""QA visual GALANT 15.0.2: verifica el salto de Contratistas con Chromium y datos sintéticos."""
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
OUT = Path(os.environ.get("GALANT_SCROLL_QA_OUTPUT", "/tmp/galant-scroll-qa")).resolve()
if urlparse(URL).hostname not in {"127.0.0.1", "localhost"}:
    raise SystemExit("Solo se permite QA local con datos sintéticos")
OUT.mkdir(parents=True, exist_ok=True)

SNAPSHOT = """() => {
  const table = document.querySelector(".ops-contractor-table");
  const sidebar = document.querySelector(".platform .sidebar");
  return {
    scrollY: window.scrollY,
    tableY: table ? table.getBoundingClientRect().top : null,
    tableRows: table ? table.querySelectorAll("tbody tr").length : 0,
    sidebarY: sidebar ? sidebar.scrollTop : null,
    viewport: innerWidth,
    contentWidth: document.documentElement.scrollWidth
  };
}"""
START_PROBE = """() => {
  if (window.__galantScrollTimer) clearInterval(window.__galantScrollTimer);
  window.__galantScrollSamples = [];
  const measure = %s;
  window.__galantScrollTimer = setInterval(() => {
    if (window.__galantScrollSamples.length < 650)
      window.__galantScrollSamples.push(measure());
  }, 25);
}""" % SNAPSHOT

def end_probe(page, before, label, results):
    values = page.evaluate("""() => {
      clearInterval(window.__galantScrollTimer);
      return window.__galantScrollSamples;
    }""")
    assert len(values) >= 10, (label, "pocas muestras", len(values))
    assert before["tableY"] is not None and before["tableRows"] > 0, (label, before)
    assert before["scrollY"] > 0, (label, "no hay desplazamiento real", before)
    assert 0 <= before["tableY"] <= page.viewport_size["height"] - 20, (label, "la tabla no está visible", before)
    for i, state in enumerate(values):
        assert state["tableRows"] > 0, (label, "la tabla desapareció durante la carga", i, state)
        assert abs(state["scrollY"] - before["scrollY"]) <= 2, (
            label, "scroll vertical cambió", i, before, state)
        assert abs(state["tableY"] - before["tableY"]) <= 2, (
            label, "la tabla cambió de posición", i, before, state)
        assert state["contentWidth"] <= state["viewport"] + 2, (
            label, "desplazamiento horizontal de página", i, state)
        if state["sidebarY"] is not None and before["sidebarY"] is not None:
            assert abs(state["sidebarY"] - before["sidebarY"]) <= 2, (label, "menú se movió", i, state)
    results.append({"case":label,"samples":len(values),
                    "max_scroll_delta":max(abs(s["scrollY"] - before["scrollY"]) for s in values),
                    "max_table_delta":max(abs(s["tableY"] - before["tableY"]) for s in values)})


def scroll_to_table(page):
    page.evaluate("""() => {
      const sidebar = document.querySelector(".platform .sidebar");
      if (sidebar) sidebar.scrollTop = Math.min(60, Math.max(0,sidebar.scrollHeight-sidebar.clientHeight));
      const table = document.querySelector(".ops-contractor-table");
      if (table) {
        table.scrollIntoView({block: "start", behavior: "instant"});
        window.scrollBy({top: -130, behavior: "instant"});
      }
    }""")
    page.wait_for_timeout(120)
    return page.evaluate(SNAPSHOT)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width":1440,"height":540},
                                  reduced_motion="reduce",locale="es-CL")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append("JS: " + str(error)))
    page.on("response", lambda response: errors.append(
        f"HTTP {response.status}: {response.url}") if response.status >= 500 else None)

    # Registra restauraciones tardías de scroll en una recarga completa.
    page.add_init_script("""(() => {
      window.__reloadScroll = [];
      document.addEventListener("DOMContentLoaded", () => {
        const id = setInterval(() => window.__reloadScroll.push(window.scrollY), 25);
        setTimeout(() => clearInterval(id), 1800);
      });
    })()""")
    def delayed_contractors(route):
        result = route.fetch()
        time.sleep(0.65)
        route.fulfill(response=result)
    page.route("**/api/v1/ops/contractors?*", delayed_contractors)

    tests = []
    try:
        page.goto(URL, wait_until="domcontentloaded")
        page.get_by_label("Correo electrónico", exact=True).fill(EMAIL)
        page.get_by_label("Contraseña", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Ingresar a GALANT").click()
        expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible(timeout=20000)
        sites = context.request.get(URL + "/api/v1/ops/sites").json()
        assert sites
        site = next((s for s in sites if "concepci" in s["name"].lower()), sites[0])
        page.get_by_role("button", name="Contratistas", exact=True).click()
        page.get_by_label("Obra seleccionada", exact=True).select_option(site["id"])
        expect(page.locator(".ops-contractor-table tbody tr").first).to_be_visible(timeout=25000)
        page.wait_for_timeout(250)

        for width,height in [(1440,540),(1024,600)]:
            page.set_viewport_size({"width":width,"height":height})
            page.wait_for_timeout(300)
            before=scroll_to_table(page)
            page.screenshot(path=str(OUT / f"contratistas-antes-{width}.png"),animations="disabled")

            page.evaluate(START_PROBE)
            # Click directo: Playwright no debe desplazar la página hacia el botón antes de medir.
            page.evaluate("""() => document.querySelector('[aria-label="Actualizar lista de contratistas"]').click()""")
            page.wait_for_timeout(1500)
            end_probe(page,before,f"refresco-manual-{width}",tests)

            before=scroll_to_table(page)
            page.evaluate(START_PROBE)
            alt=context.new_page()
            alt.goto("about:blank")
            alt.bring_to_front()
            page.wait_for_timeout(600)
            page.bring_to_front()
            page.wait_for_timeout(1100)
            end_probe(page,before,f"retorno-pestana-{width}",tests)
            alt.close()
            page.screenshot(path=str(OUT / f"contratistas-despues-{width}.png"),animations="disabled")

        # Esperar el sondeo de 10 segundos que antes desmontaba la tabla completa.
        before=scroll_to_table(page)
        page.evaluate(START_PROBE)
        page.wait_for_timeout(11400)
        end_probe(page,before,"sondeo-automatico-10s",tests)

        # Cambiar módulo: no heredar la posición de la lista anterior.
        page.get_by_role("button",name="Trabajadores",exact=True).click()
        expect(page.locator(".workers-page")).to_be_visible(timeout=20000)
        assert page.evaluate("window.scrollY") <= 2, "Trabajadores heredó el scroll de contratistas"
        page.get_by_role("button",name="Contratistas",exact=True).click()
        expect(page.locator(".ops-contractor-table tbody tr").first).to_be_visible(timeout=20000)
        assert page.evaluate("window.scrollY") <= 2, "Contratistas heredó el scroll de trabajadores"

        # Restaurar la lista únicamente al cerrar la ficha del contratista.
        scroll_to_table(page)
        page.locator(".ops-contractor-table .row-open").first.click()
        expect(page.locator(".ops-isolated-detail")).to_be_visible(timeout=20000)
        page.get_by_role("button",name="Volver a contratistas",exact=True).click()
        expect(page.locator(".ops-contractor-table tbody tr").first).to_be_visible(timeout=20000)

        # Recarga real desde una posición previa profunda: el primer render parte desde arriba.
        page.evaluate("window.scrollTo({top: document.documentElement.scrollHeight, behavior:'instant'})")
        assert page.evaluate("window.scrollY") > 0
        page.reload(wait_until="domcontentloaded")
        expect(page.get_by_role("button",name="Menú de usuario")).to_be_visible(timeout=20000)
        expect(page.locator(".ops-contractor-table tbody tr").first).to_be_visible(timeout=20000)
        page.wait_for_timeout(1800)
        positions=page.evaluate("window.__reloadScroll")
        assert positions and max(positions) <= 2, ("La recarga restauró scroll antiguo",positions)
        assert page.evaluate("window.history.scrollRestoration") == "manual"
        assert page.evaluate("window.scrollY") <= 2, "La página no inició en la cabecera"
        tests.append({"case":"recarga-inicia-arriba","samples":len(positions),"max_scroll_delta":max(positions)})

        assert not errors, errors
        report={"result":"PASS","version":"15.0.2-rc1","site":site["name"],
                "tests":tests,"browser_errors":errors}
        (OUT / "scroll-flicker-report.json").write_text(
            json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except Exception as exc:
        page.screenshot(path=str(OUT / "ERROR-scroll-qa.png"),full_page=True,animations="disabled")
        (OUT / "ERROR-scroll-qa.txt").write_text(str(exc)+"\n"+repr(errors),encoding="utf-8")
        raise
    finally:
        browser.close()
