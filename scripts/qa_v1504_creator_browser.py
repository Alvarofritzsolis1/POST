#!/usr/bin/env python3
"""GALANT 15.0.4: firma pública visible en escritorio y móvil, sin desbordes."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

url = os.environ.get("GALANT_QA_URL", "http://127.0.0.1:18612").rstrip("/")
out = Path(os.environ.get("GALANT_CREATOR_QA_OUTPUT", "/tmp/galant-creator-qa")).resolve()
if urlparse(url).hostname not in {"localhost", "127.0.0.1"}:
    raise SystemExit("SEGURIDAD: pruebas de portada únicamente contra QA local")
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for width, height in ((390, 844), (768, 1024), (1024, 768), (1440, 900)):
        context = browser.new_context(
            viewport={"width": width, "height": height},
            locale="es-CL",
            reduced_motion="reduce",
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url, wait_until="domcontentloaded")
        expect(page.locator(".login-page")).to_be_visible(timeout=10000)
        expect(page.get_by_label("Correo electrónico", exact=True)).to_be_visible()
        expect(page.get_by_label("Contraseña", exact=True)).to_be_visible()

        desktop = page.locator(".login-decoration-foot .login-author-credit")
        mobile = page.locator(".login-author-credit--mobile")
        visible = mobile if width <= 780 else desktop
        hidden = desktop if width <= 780 else mobile
        expect(visible).to_be_visible()
        expect(hidden).to_be_hidden()
        assert visible.inner_text() == "Creado por Álvaro Fritz"
        box = visible.bounding_box()
        assert box is not None and box["width"] > 100, (width, box)
        assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1, (width, box)
        assert box["y"] >= -1, (width, box)
        doc_width = page.evaluate("document.documentElement.scrollWidth")
        assert doc_width <= width + 2, (width, doc_width)
        assert not errors, (width, errors)
        page.screenshot(path=str(out / f"portada-{width}x{height}.png"), full_page=True, animations="disabled")
        print(f"PASS portada {width}x{height}: firma visible, sin desbordes")
        context.close()
    browser.close()
