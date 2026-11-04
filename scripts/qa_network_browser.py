"""Browser → API → PostgreSQL acceptance. Use only a disposable local QA stack.

GALANT_NETWORK_QA_EMAIL / GALANT_NETWORK_QA_PASSWORD identify its seeded admin.
No production hosts, credentials or documents are included in this test.
"""

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18745")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Ejecutar únicamente contra QA local descartable")
    email = os.environ["GALANT_NETWORK_QA_EMAIL"]
    password = os.environ["GALANT_NETWORK_QA_PASSWORD"]
    args.output.mkdir(parents=True, exist_ok=True)
    errors, failures = [], []
    root = "/api/v1/network"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        expect.set_options(timeout=20000)

        def context():
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
            )
            page = ctx.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    errors.append(message.text)
                    if message.type == "error"
                    and "Failed to load resource" not in message.text
                    else None
                ),
            )
            page.on(
                "response",
                lambda r: (
                    failures.append({"url": r.url, "status": r.status})
                    if r.status >= 500
                    else None
                ),
            )
            return ctx, page

        def login(page, account_email):
            page.goto(args.url)
            page.get_by_label("Correo electrónico", exact=True).fill(account_email)
            page.get_by_label("Contraseña", exact=True).fill(password)
            page.get_by_role("button", name="Ingresar a GALANT").click()
            expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible()

        admin_ctx, admin = context()
        login(admin, email)

        def api(ctx, path):
            result = ctx.request.get(args.url + root + path)
            assert result.ok, (path, result.status, result.text())
            return result.json()

        def mutation(ctx, path, body):
            csrf = next(
                c["value"] for c in ctx.cookies() if c["name"] == "galant_post_csrf"
            )
            result = ctx.request.post(
                args.url + path, data=body, headers={"X-CSRF-Token": csrf}
            )
            assert result.ok, (path, result.status, result.text())
            return result.json()

        if args.verify_only:
            report = json.loads((args.output / "browser-report.json").read_text())
            req = api(admin_ctx, "/requirements/" + report["requirement_id"])
            assert req["items"][0]["awarded"] == 100 and req["items"][0]["pending"] == 0
            assert len(req["items"][0]["awards"]) == 2
            conversation = report["conversation_id"]
            # Admins join explicitly; possession of an ID never grants message access.
            mutation(
                admin_ctx,
                root + "/conversations/" + conversation + "/participants",
                {"user_id": api(admin_ctx, "/profile")["id"]},
            )
            assert (
                len(
                    api(admin_ctx, "/conversations/" + conversation + "/messages")[
                        "rows"
                    ]
                )
                >= 2
            )
            assert api(admin_ctx, "/capacities/" + report["capacity_id"])[
                "contractor_id"
            ]
            admin.get_by_role("button", name="Red de Obras", exact=True).click()
            expect(admin.locator(".nw-kpis")).to_be_visible()
            expect(admin.get_by_text("Actualizando información compartida…", exact=True)).not_to_be_visible()
            admin.screenshot(path=str(args.output / "administrador.png"), full_page=True)
            admin.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role("button", name="Necesito contratista", exact=True).click()
            admin.get_by_role("button", name=req["title"], exact=True).click()
            expect(admin.get_by_role("dialog").get_by_text("ADJUDICADO A: " + req["items"][0]["awards"][0]["contractor"], exact=True)).to_be_visible()
            admin.screenshot(path=str(args.output / "adjudicacion.png"), full_page=True)
            resident_email = next(u["email"] for u in api(admin_ctx, "/users") if u["id"] == req["created_by"])
            _, resident = context()
            login(resident, resident_email)
            expect(resident.locator(".nw-kpis")).to_be_visible()
            expect(resident.get_by_text("Actualizando información compartida…", exact=True)).not_to_be_visible()
            resident.screenshot(path=str(args.output / "residente.png"), full_page=True)
            resident.set_viewport_size({"width": 390, "height": 844})
            assert resident.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            resident.screenshot(path=str(args.output / "movil.png"), full_page=True)
            assert not errors, errors
            assert not failures, failures
            report["restart_persistence"] = "PASS"
            (args.output / "browser-report.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False)
            )
            print(
                "PASS: usuarios, requerimiento, capacidad, conversación y dos adjudicaciones persisten después del reinicio"
            )
            browser.close()
            return
        admin.get_by_role("button", name="Red de Obras", exact=True).click()
        expect(
            admin.get_by_role("heading", name="Red de Obras.", exact=True)
        ).to_be_visible()
        catalog = api(admin_ctx, "/catalog")
        assert len(catalog["sites"]) >= 2
        destination = next(
            (s for s in catalog["sites"] if s["name"] == "Brisas de Junquillar"),
            catalog["sites"][0],
        )
        origin = next(
            (s for s in catalog["sites"] if s["name"] == "Lomas Verdes"),
            catalog["sites"][1],
        )
        run = uuid4().hex[:7]
        for company in [
            "Carpintería Robles QA " + run,
            "Terminaciones del Sur QA " + run,
        ]:
            mutation(
                admin_ctx,
                "/api/v1/ops/contractors",
                {
                    "site_id": origin["id"],
                    "name": company,
                    "nature": "with_workers",
                    "frequency": "fixed",
                },
            )
        catalog = api(admin_ctx, "/catalog")
        companies = [c for c in catalog["contractors"] if run in c["name"]]
        assert len(companies) == 2
        residents = []
        for i, site in enumerate([destination, origin]):
            account_email = f"residente-{run}-{i}@network.example.cl"
            admin.get_by_role("button", name="Menú de usuario").click()
            admin.get_by_role("button", name="Crear cuenta", exact=True).click()
            drawer = admin.get_by_role("dialog")
            drawer.get_by_label("Nombre completo", exact=True).fill(
                "Residente " + ("Destino" if i == 0 else "Origen")
            )
            drawer.get_by_label("Correo electrónico", exact=True).fill(account_email)
            drawer.get_by_label(site["name"], exact=True).check()
            drawer.get_by_role("button", name="Crear cuenta e invitación").click()
            link = drawer.get_by_label("Enlace de acceso")
            expect(link).to_be_visible()
            activation_url = link.input_value()
            drawer.get_by_role("button", name="Cerrar panel").click()
            ctx, page = context()
            page.goto(activation_url)
            page.get_by_label(
                "Nueva contraseña (mínimo 12 caracteres)", exact=True
            ).fill(password)
            page.get_by_label("Confirma la contraseña", exact=True).fill(password)
            page.get_by_role("button", name="Establecer contraseña", exact=True).click()
            expect(
                page.get_by_text("Contraseña establecida. Ya puedes iniciar sesión.")
            ).to_be_visible()
            page.get_by_role("button", name="Volver a GALANT").click()
            login(page, account_email)
            expect(
                page.get_by_role("heading", name="Red de Obras.", exact=True)
            ).to_be_visible()
            assert (
                page.get_by_role(
                    "button", name="Importación masiva", exact=True
                ).count()
                == 0
            )
            assert ctx.request.get(args.url + "/api/v1/documents").status == 403
            residents.append((ctx, page))
        a_ctx, a = residents[0]
        b_ctx, b = residents[1]
        start = (
            datetime.now(ZoneInfo("America/Santiago")).date() + timedelta(days=12)
        ).isoformat()
        end = (datetime.fromisoformat(start).date() + timedelta(days=10)).isoformat()
        title = "Carpintería para terminaciones · " + run
        a.locator(".nw-heading").get_by_role(
            "button", name="Necesito contratista", exact=True
        ).click()
        drawer = a.get_by_role("dialog")
        drawer.get_by_label("Especialidad", exact=True).fill("Carpintería")
        drawer.get_by_label("Título del requerimiento", exact=True).fill(title)
        drawer.get_by_label("Trabajadores estimados", exact=True).fill("3")
        drawer.get_by_label("Inicio necesario", exact=True).fill(start)
        drawer.get_by_label("Término estimado", exact=True).fill(end)
        drawer.get_by_label("Fecha límite del contratista", exact=True).fill(start)
        for _ in range(2):
            drawer.get_by_role("button", name="Agregar partida", exact=True).click()
        for i, (name, qty, unit) in enumerate(
            [
                ("Instalación de puertas", "100", "un"),
                ("Guardapolvos", "300", "m"),
                ("Terminaciones interiores", "1", "gl"),
            ]
        ):
            part = drawer.locator(".nw-part-form").nth(i)
            part.get_by_label("Nombre de partida", exact=True).fill(name)
            part.get_by_label("Cantidad", exact=True).fill(qty)
            part.get_by_label("Unidad", exact=True).fill(unit)
        drawer.get_by_role("button", name="Publicar requerimiento", exact=True).click()
        expect(drawer.get_by_role("heading", name=title, exact=True)).to_be_visible()
        drawer.get_by_role("button", name="Cerrar panel").click()
        req = next(
            r for r in api(a_ctx, "/requirements")["rows"] if r["title"] == title
        )
        b.locator(".nw-heading").get_by_role(
            "button", name="Tengo contratista con capacidad", exact=True
        ).click()
        drawer = b.get_by_role("dialog")
        drawer.get_by_role(
            "combobox", name="Contratista registrado", exact=True
        ).select_option(companies[0]["id"])
        drawer.get_by_label("Especialidad", exact=True).fill("Carpintería")
        drawer.get_by_label("Fecha prevista", exact=True).fill(start)
        drawer.get_by_label("Trabajadores estimados", exact=True).fill("3")
        drawer.get_by_role("button", name="Guardar capacidad", exact=True).click()
        expect(drawer).not_to_be_visible()
        cap = next(
            c
            for c in api(a_ctx, "/capacities")["rows"]
            if c["contractor_id"] == companies[0]["id"]
        )
        a.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Coincidencias", exact=True
        ).click()
        match = (
            a.locator(".nw-match-card")
            .filter(has_text=title)
            .filter(has_text=companies[0]["name"])
        )
        expect(match).to_be_visible()
        expect(match.get_by_text("Disponibilidad estimada", exact=True)).to_be_visible()
        match.get_by_role("button", name="Contactar residente", exact=True).click()
        a.get_by_label("Escribir mensaje", exact=True).fill(
            "Hola, coordinemos las fechas para instalar las puertas."
        )
        a.get_by_role("button", name="Enviar mensaje", exact=True).click()
        expect(
            a.get_by_text(
                "Hola, coordinemos las fechas para instalar las puertas.", exact=True
            )
        ).to_be_visible()
        conversation = api(a_ctx, "/conversations")["rows"][0]
        b.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Mensajes", exact=False
        ).click()
        b.locator(".nw-messaging aside").get_by_role("button").filter(
            has_text=title
        ).click()
        expect(
            b.get_by_text(
                "Hola, coordinemos las fechas para instalar las puertas.", exact=True
            )
        ).to_be_visible()
        b.get_by_label("Escribir mensaje", exact=True).fill(
            "Revisaremos la capacidad con el contratista y confirmaremos."
        )
        b.get_by_role("button", name="Enviar mensaje", exact=True).click()
        expect(
            a.get_by_text(
                "Revisaremos la capacidad con el contratista y confirmaremos.",
                exact=True,
            )
        ).to_be_visible()
        admin.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Necesito contratista", exact=True
        ).click()
        admin.get_by_role("button", name=title, exact=True).click()
        for qty, company in [("60", companies[0]), ("40", companies[1])]:
            drawer = admin.get_by_role("dialog")
            drawer.locator(".nw-detail-item").first.get_by_role(
                "button", name="Adjudicar partida", exact=True
            ).click()
            drawer.get_by_role(
                "combobox", name="Contratista", exact=True
            ).select_option(company["id"])
            drawer.get_by_label("Cantidad adjudicada (un)", exact=True).fill(qty)
            drawer.get_by_label(
                "Confirmo la adjudicación oficial de esta cantidad y contratista.",
                exact=True,
            ).check()
            drawer.get_by_role(
                "button", name="Confirmar adjudicación", exact=True
            ).click()
            expect(
                drawer.get_by_role("heading", name=title, exact=True)
            ).to_be_visible()
            expect(
                drawer.get_by_text("ADJUDICADO A: " + company["name"], exact=True)
            ).to_be_visible()
        final = api(a_ctx, "/requirements/" + req["id"])
        assert final["items"][0]["awarded"] == 100 and final["items"][0]["pending"] == 0
        assert final["items"][0]["executed"] == 0
        assert len(final["items"][0]["awards"]) == 2
        assert all(
            award["clearance"]["state"] == "pending"
            for award in final["items"][0]["awards"]
        )
        admin.screenshot(path=str(args.output / "adjudicacion.png"), full_page=True)
        admin.get_by_role("dialog").get_by_role("button", name="Cerrar panel").click()
        admin.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Inicio", exact=True
        ).click()
        expect(admin.locator(".nw-kpis")).to_be_visible()
        admin.screenshot(path=str(args.output / "administrador.png"), full_page=True)
        a.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Inicio", exact=True
        ).click()
        a.screenshot(path=str(args.output / "residente.png"), full_page=True)
        a.set_viewport_size({"width": 390, "height": 844})
        expect(a.locator(".nw-kpis")).to_be_visible()
        assert a.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        ), "Desbordamiento horizontal en móvil"
        a.screenshot(path=str(args.output / "movil.png"), full_page=True)
        a.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Calendario", exact=True
        ).click()
        expect(a.locator(".nw-calendar-grid")).to_be_visible()
        a.get_by_label("Vista de calendario", exact=True).select_option("week")
        assert a.locator(".nw-calendar-day").count() == 7
        assert not errors, errors
        assert not failures, failures
        report = {
            "result": "PASS",
            "version": "0.7.0",
            "requirement_id": req["id"],
            "capacity_id": cap["id"],
            "conversation_id": conversation["id"],
            "awarded": 100,
            "pending": 0,
            "executed": 0,
            "javascript_errors": errors,
            "server_errors": failures,
            "desktop": "PASS",
            "mobile": "PASS",
            "restart_persistence": "NOT_RUN",
        }
        (args.output / "browser-report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False)
        )
        print(
            "PASS: invitaciones, accesos, tres partidas, capacidad, coincidencia, dos residentes, mensajes, 60+40, calendario y móvil; sin errores JavaScript ni HTTP 5xx"
        )
        browser.close()


if __name__ == "__main__":
    main()
