#!/usr/bin/env python3
"""Click the REAL MAX POWER UI on isolated GALANT QA, never production."""
from __future__ import annotations

import os
import re
import shutil
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

url = os.environ.get("GALANT_QA_URL", "http://127.0.0.1:18612").rstrip("/")
if urlparse(url).hostname not in {"localhost", "127.0.0.1"}:
    raise SystemExit("MAX POWER browser QA accepts localhost only")
if urlparse(url).port != 18612:
    raise SystemExit("MAX POWER browser QA requires isolated port 18612")
email = "qa-admin@example.test"
password = os.environ["QA_SMOKE_PASSWORD"]


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        executable_path=os.environ.get("GALANT_QA_CHROMIUM") or shutil.which("chromium"),
    )
    context = browser.new_context(viewport={"width": 1366, "height": 850},
                                  reduced_motion="reduce", locale="es-CL")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append("JS " + str(error)))
    page.on("response", lambda response: errors.append("HTTP " + str(response.status) + " " + response.url)
            if response.status >= 500 else None)
    page.goto(url + "/admin/ia/max-power", wait_until="domcontentloaded")
    page.get_by_label("Correo electrónico", exact=True).fill(email)
    page.get_by_label("Contraseña", exact=True).fill(password)
    with page.expect_response(lambda r: r.url.endswith("/api/v1/auth/login")) as login:
        page.get_by_role("button", name="Ingresar a GALANT").click()
    assert login.value.status == 200, login.value.text()

    expect(page.get_by_role("heading", name="MAX POWER", exact=True)).to_be_visible(timeout=20000)
    power = page.locator(".max-power-control")
    expect(power.get_by_role("button", name="Encender MAX POWER")).to_be_visible()
    api = url + "/api/v1/admin/ai/max-power"

    original = context.request.get(api)
    assert original.status == 200, original.text()
    assert original.json()["enabled"] is False, "QA button test must start OFF"
    with page.expect_response(
        lambda r: r.url.endswith("/api/v1/admin/ai/max-power/control/on")
        and r.request.method == "POST"
    ) as enabling:
        power.get_by_role("button", name="Encender MAX POWER").click()
    assert enabling.value.status == 200, enabling.value.text()
    expect(power.get_by_role("button", name="Apagar MAX POWER")).to_have_attribute("aria-pressed", "true")
    expect(power.locator("strong").first).to_contain_text("MAX POWER encendido")
    assert context.request.get(api).json()["enabled"] is True

    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="MAX POWER", exact=True)).to_be_visible(timeout=20000)
    power = page.locator(".max-power-control")
    expect(power.get_by_role("button", name="Apagar MAX POWER")).to_have_attribute("aria-pressed", "true")
    with page.expect_response(
        lambda r: r.url.endswith("/api/v1/admin/ai/max-power/control/off")
        and r.request.method == "POST"
    ) as disabling:
        power.get_by_role("button", name="Apagar MAX POWER").click()
    assert disabling.value.status == 200, disabling.value.text()
    expect(power.get_by_role("button", name="Encender MAX POWER")).to_have_attribute("aria-pressed", "false")
    expect(power.locator("strong").first).to_contain_text("MAX POWER apagado")
    assert context.request.get(api).json()["enabled"] is False

    page.reload(wait_until="domcontentloaded")
    expect(power.get_by_role("button", name="Encender MAX POWER")).to_have_attribute("aria-pressed", "false")
    for width in (390, 768, 1366):
        page.set_viewport_size({"width": width, "height": 850})
        sizes = page.evaluate("""() => ({
            width: document.documentElement.clientWidth,
            scroll: document.documentElement.scrollWidth
        })""")
        assert sizes["scroll"] <= sizes["width"] + 3, (width, sizes)
    assert not errors, errors
    print("MAX_POWER_BROWSER_BUTTON=real_click_ON_reload_OFF_reload_no_errors")
    context.close()
    browser.close()
