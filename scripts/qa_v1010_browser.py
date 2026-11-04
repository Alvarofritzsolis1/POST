"""QA real de ficha contratista. Exclusivo stack local descartable.

Reproduce el JSON anidado introducido en la carga masiva v10.9 y navega
entre Activos/Inactivos/Todos sin tolerar errores JavaScript ni pantallas vacías.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import Workbook
from playwright.sync_api import expect, sync_playwright


HEADERS = ["ID", "OBRA", "ESPECIALIDAD", "NOMBRECONTRATISTA", "RUT", "COD",
           "ESTADO", "TELEFONO", "CORREO", "REPRESENTANTE LEGAL", "RUTR.LEGAL"]


def rut(n: int) -> str:
    total = sum(int(d) * f for d, f in zip(str(n)[::-1], (2, 3, 4, 5, 6, 7) * 3))
    check = 11 - total % 11
    return f"{n}-" + ("0" if check == 11 else "K" if check == 10 else str(check))


def excel(rows: list[list[str]]) -> bytes:
    book = Workbook()
    book.active.append(HEADERS)
    for row in rows:
        book.active.append(row)
    buff = io.BytesIO()
    book.save(buff)
    return buff.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18612")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if urlparse(args.url).hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit("Se rechaza ejecutar navegador QA contra producción")
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    email = os.environ["GALANT_NETWORK_QA_EMAIL"]
    password = os.environ["GALANT_NETWORK_QA_PASSWORD"]
    errors: list[str] = []
    random_id = random.randint(10000, 99999)
    company = f"Prueba ficha anidada 1010 {random_id}"
    other = f"Prueba inactiva 1010 {random_id}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000},
                                  reduced_motion="reduce")
        page = ctx.new_page()
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("console", lambda msg: errors.append(msg.text)
                if msg.type == "error" and "Failed to load resource" not in msg.text else None)
        page.on("response", lambda response: errors.append(f"HTTP {response.status}: {response.url}")
                if response.status >= 500 else None)
        page.goto(args.url)
        page.get_by_label("Correo electrónico", exact=True).fill(email)
        page.get_by_label("Contraseña", exact=True).fill(password)
        page.get_by_role("button", name="Ingresar a GALANT").click()
        expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible()
        sites = ctx.request.get(args.url + "/api/v1/ops/sites")
        assert sites.ok, sites.text()
        site = sites.json()[0]
        payload = excel([
            [f"QA-{random_id}-A", site["name"], "Carpintería", company,
             rut(23000000 + random_id), "CT", "ACTIVO", "", "", "", ""],
            [f"QA-{random_id}-B", site["name"], "Pintura", other,
             rut(24000000 + random_id), "CE", "INACTIVO", "", "", "", ""],
        ])
        csrf = next(c["value"] for c in ctx.cookies() if c["name"] == "galant_post_csrf")
        preview = ctx.request.post(
            args.url + "/api/v1/ops/imports/bulk/preview",
            headers={"X-CSRF-Token": csrf},
            multipart={"kind": "contractors",
                       "file": {"name": "qa-1010.xlsx",
                                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                "buffer": payload}},
        )
        assert preview.ok, (preview.status, preview.text())
        draft = preview.json()
        assert draft["summary"]["error"] == 0, draft
        commit = ctx.request.post(
            args.url + "/api/v1/ops/imports/bulk/commit",
            headers={"X-CSRF-Token": csrf},
            data={**draft["input"], "token": draft["token"], "approve_updates": True},
        )
        assert commit.ok, (commit.status, commit.text())
        # El módulo requiere seleccionar la obra desde el filtro GLOBAL.
        # Sin esto App presenta "Selecciona una obra" y no monta Operations.
        page.get_by_label("Obra seleccionada", exact=True).select_option(site["id"])
        page.get_by_role("button", name="Contratistas", exact=True).click()
        expect(page.get_by_role("heading", name="Contratistas", exact=True).last).to_be_visible()
        expect(page.locator(".ops-toolbar select")).to_be_visible()
        page.get_by_role("button", name="Activos", exact=True).click()
        expect(page.get_by_role("button", name="Abrir ficha de " + company)).to_be_visible()
        assert page.get_by_role("button", name="Abrir ficha de " + other).count() == 0
        for _ in range(5):
            page.get_by_role("button", name="Abrir ficha de " + company).click()
            expect(page.get_by_role("heading", name=company)).to_be_visible()
            page.get_by_role("button", name="Trabajadores", exact=True).last.click()
            expect(page.get_by_text("Trabajadores asociados")).to_be_visible()
            page.get_by_role("button", name="Documentación", exact=True).last.click()
            expect(page.get_by_text("Documentación mensual")).to_be_visible()
            page.get_by_role("button", name="Cerrar ficha").click()
            expect(page.get_by_role("button", name="Abrir ficha de " + company)).to_be_visible()
        page.get_by_role("button", name="Inactivos", exact=True).click()
        expect(page.get_by_role("button", name="Abrir ficha de " + other)).to_be_visible()
        assert page.get_by_role("button", name="Abrir ficha de " + company).count() == 0
        page.get_by_role("button", name="Abrir ficha de " + other).click()
        expect(page.get_by_text("Contratista inactivo", exact=False).first).to_be_visible()
        page.get_by_role("button", name="Documentación", exact=True).last.click()
        expect(page.get_by_text("no se generan ni solicitan nuevos documentos", exact=False)).to_be_visible()
        page.screenshot(path=str(output / "contratista-inactivo.png"), full_page=True)
        page.get_by_role("button", name="Cerrar ficha").click()
        page.get_by_role("button", name="Todos", exact=True).click()
        expect(page.get_by_role("button", name="Abrir ficha de " + company)).to_be_visible()
        expect(page.get_by_role("button", name="Abrir ficha de " + other)).to_be_visible()
        page.screenshot(path=str(output / "contratistas-filtros.png"), full_page=True)
        page.reload()
        expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible()
        assert page.locator("#root").inner_text().strip(), "Pantalla blanca después de recargar"
        assert not errors, errors
        (output / "report.json").write_text(json.dumps(
            {"status": "PASS", "screens": ["contratista-inactivo.png",
                                          "contratistas-filtros.png"],
             "checks": "filtro, datos anidados, pestañas, 5 ciclos de abrir/cerrar, recarga"},
            indent=2, ensure_ascii=False))
        print("PASS: navegación, filtros y renderizados de contratistas sin pantalla blanca")
        browser.close()


if __name__ == "__main__":
    main()
