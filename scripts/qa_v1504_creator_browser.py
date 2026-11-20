#!/usr/bin/env python3
"""GALANT Signature: portada, firma, version, recuperación y ausencia de desbordes."""
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
    for width, height in ((360, 640), (390, 844), (768, 1024), (1024, 768), (1366, 630), (1440, 900)):
        context = browser.new_context(
            viewport={"width": width, "height": height},
            locale="es-CL",
            reduced_motion="reduce",
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url, wait_until="domcontentloaded")

        root = page.locator(".signature-login")
        expect(root).to_be_visible(timeout=10000)
        expect(page.get_by_label("Correo electrónico", exact=True)).to_be_visible()
        expect(page.get_by_label("Contraseña", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Ingresar a GALANT")).to_be_visible()
        expect(page.get_by_role("link", name="¿La olvidaste?")).to_have_attribute("href", "#recuperar-clave")
        assert page.get_by_text("ACCESO PRIVADO", exact=True).count() == 0

        credit = page.locator(".signature-login__credit")
        version = page.locator(".signature-login__version")
        expect(credit).to_be_visible()
        expect(version).to_be_visible()
        expect(version).to_contain_text("Versión")
        expect(version).to_have_css("font-size", "9px")
        assert " ".join((credit.text_content() or "").split()) == "Creado por Álvaro Fritz"

        credit_box = credit.bounding_box()
        version_box = version.bounding_box()
        assert credit_box is not None and version_box is not None
        assert credit_box["x"] >= -1
        assert version_box["x"] >= credit_box["x"] + credit_box["width"]
        assert version_box["x"] + version_box["width"] <= width + 1
        assert version_box["y"] >= credit_box["y"] - 3

        sculpture = page.locator(".signature-login__art")
        if width <= 700:
            expect(sculpture).to_be_hidden()
        else:
            expect(sculpture).to_be_visible()

        doc_width = page.evaluate("document.documentElement.scrollWidth")
        assert doc_width <= width + 2, (width, doc_width)
        if width >= 768 and height >= 630:
            doc_height = page.evaluate("document.documentElement.scrollHeight")
            assert doc_height <= height + 2, (width, height, doc_height)
            assert version_box["y"] + version_box["height"] <= height + 2

        assert not errors, (width, errors)
        page.screenshot(path=str(out / f"portada-{width}x{height}.png"), full_page=True, animations="disabled")
        print(f"PASS Signature {width}x{height}: recuperación, versión, firma, sin desbordes")
        context.close()
    browser.close()
