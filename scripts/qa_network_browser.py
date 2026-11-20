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

        # Premium UI: la barra lateral debe ampliar sobre el contenido, no moverlo.
        def shell_geometry():
            return admin.evaluate("""() => {
              const aside = document.querySelector(".platform .sidebar");
              const main = document.querySelector(".platform .main");
              return {
                aside: aside?.getBoundingClientRect().width,
                asideBackground: aside ? getComputedStyle(aside).backgroundColor : null,
                mainLeft: main?.getBoundingClientRect().left,
                scrollWidth: document.documentElement.scrollWidth,
                innerWidth: innerWidth
              };
            }""")

        admin.mouse.move(1100, 300)
        rail_before = shell_geometry()
        assert rail_before["aside"] is not None and rail_before["aside"] <= 85, rail_before
        assert rail_before["asideBackground"] == "rgb(255, 255, 255)", rail_before
        assert rail_before["scrollWidth"] <= rail_before["innerWidth"], rail_before
        admin.locator(".platform .sidebar").hover(position={"x":28, "y":45})
        # CSS hover transition is allowed to animate; assert its final settled state.
        admin.wait_for_function(
            "() => document.querySelector('.platform .sidebar')?.getBoundingClientRect().width >= 230",
            timeout=2500,
        )
        rail_open = shell_geometry()
        assert abs(rail_open["mainLeft"] - rail_before["mainLeft"]) <= 1, (rail_before, rail_open)
        admin.mouse.move(1100, 300)
        admin.wait_for_function(
            "() => document.querySelector('.platform .sidebar')?.getBoundingClientRect().width <= 85",
            timeout=2500,
        )
        rail_after = shell_geometry()
        assert abs(rail_after["mainLeft"] - rail_before["mainLeft"]) <= 1, (rail_before, rail_after)

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

        def update_requirement(ctx, record_id, body):
            csrf = next(c["value"] for c in ctx.cookies() if c["name"] == "galant_post_csrf")
            response = ctx.request.put(
                args.url + root + "/requirements/" + record_id,
                data=body,
                headers={"X-CSRF-Token": csrf},
            )
            assert response.ok, (response.status, response.text())
            return response.json()

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
            admin.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role("button", name="Necesidades", exact=True).click()
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
        a.locator(".nw-publish-need").click()
        drawer = a.get_by_role("dialog")
        expect(drawer.get_by_role("heading", name="Nueva necesidad")).to_be_visible()
        # La ventana amplia debe ocupar gran parte de la pantalla.
        assert drawer.evaluate("(el) => el.getBoundingClientRect().width") >= 1000
        # Una sola obra asignada: se muestra la obra sin permitir cambiar el origen.
        expect(drawer.get_by_text(destination["name"], exact=True)).to_be_visible()
        assert drawer.get_by_role("combobox", name="Obra", exact=True).count() == 0
        drawer.get_by_label("Oficio o especialidad", exact=True).fill("Carpintería")
        drawer.locator(".nw-quick-more summary").click()
        drawer.get_by_label("Título personalizado", exact=True).fill(title)
        drawer.get_by_label("Trabajadores aprox.", exact=True).fill("3")
        drawer.get_by_label("Inicio estimado", exact=True).fill(start)
        drawer.get_by_label("¿Qué labores se realizarán?", exact=True).fill(
            "Instalación de puertas, guardapolvos y terminaciones interiores."
        )
        fb = drawer.get_by_role("checkbox", name="Publicar también en Facebook")
        assert fb.is_checked(), "Facebook debe estar preseleccionado inicialmente"
        fb.uncheck()
        assert not fb.is_checked()
        # Un clic fuera del panel no debe cerrar ni perder el formulario.
        a.mouse.click(3, 3)
        expect(drawer.get_by_label("Título personalizado", exact=True)).to_have_value(title)
        # Cerrar con cambios requiere confirmación; rechazarla mantiene lo escrito.
        a.once("dialog", lambda prompt: prompt.dismiss())
        drawer.get_by_role("button", name="Cerrar panel").click()
        expect(drawer).to_be_visible()
        expect(drawer.get_by_label("Título personalizado", exact=True)).to_have_value(title)
        drawer.get_by_role("button", name="Publicar necesidad", exact=True).click()
        # La publicación vuelve al feed, sin abrir otro diálogo.
        expect(drawer).to_have_count(0)
        expect(a.locator(".nw-success")).to_contain_text("Necesidad publicada solo en GALANT.")
        card = a.locator(".nw-feed-card").filter(has_text=title)
        expect(card).to_be_visible()
        card.get_by_role("button", name="Ver solicitud").click()
        drawer = a.get_by_role("dialog")
        expect(drawer.get_by_role("heading", name=title, exact=True)).to_be_visible()
        assert drawer.locator(".nw-history pre").count() == 0
        drawer.get_by_role("button", name="Cerrar panel").click()
        req = next(r for r in api(a_ctx, "/requirements")["rows"] if r["title"] == title)
        assert req["publish_to_facebook"] is False
        # El alta es deliberadamente rápida: confirmar fechas y cantidades
        # mediante la API antes de una adjudicación real, sin falsos datos.
        item = api(a_ctx, "/requirements/" + req["id"])["items"][0]
        items = [
            {"id": item["id"], "name": "Instalación de puertas", "quantity": 100, "unit": "un",
             "start_date": start, "end_date": end, "notes": ""},
            {"name": "Guardapolvos", "quantity": 300, "unit": "m",
             "start_date": start, "end_date": end},
            {"name": "Terminaciones interiores", "quantity": 1, "unit": "gl",
             "start_date": start, "end_date": end},
        ]
        req = update_requirement(a_ctx, req["id"], {
            "site_id": destination["id"], "specialty": "Carpintería", "title": title,
            "description": "Instalación de puertas, guardapolvos y terminaciones interiores.",
            "workers": 3, "priority": "normal",
            "start_date": start, "end_date": end, "deadline": start,
            "items": items, "state": "published", "publish_to_facebook": False,
            "version": req["version"], "reason": "Detalles técnicos confirmados antes de adjudicar",
        })
        assert len(req["items"]) == 3
        # Otro residente ve el requerimiento de Junquillar con su origen intacto.
        external = api(b_ctx, "/requirements/" + req["id"])
        assert external["site_id"] == destination["id"]
        assert external["site"] == destination["name"]
        assert api(b_ctx, "/overview")["requirements"] >= 1
        b.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Necesidades", exact=True
        ).click()
        foreign_card = b.locator(".nw-card").filter(has_text=title)
        expect(foreign_card).to_be_visible()
        expect(foreign_card).to_contain_text(destination["name"])
        b.locator(".nw-heading").get_by_role(
            "button", name="Tengo contratista disponible", exact=True
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
            "button", name="Seguimiento", exact=True
        ).click()
        expect(a.get_by_role("navigation", name="Seguimiento de las necesidades")).to_be_visible()
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
            "button", name="Seguimiento", exact=True
        ).click()
        b.get_by_role("navigation", name="Seguimiento de las necesidades").get_by_role(
            "button", name="Mensajes", exact=True
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
            "button", name="Necesidades", exact=True
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
            "button", name="Feed", exact=True
        ).click()
        expect(admin.locator(".nw-kpis")).to_be_visible()
        admin.screenshot(path=str(args.output / "administrador.png"), full_page=True)
        a.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Feed", exact=True
        ).click()
        a.screenshot(path=str(args.output / "residente.png"), full_page=True)
        a.set_viewport_size({"width": 390, "height": 844})
        expect(a.locator(".nw-kpis")).to_be_visible()
        assert a.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        ), "Desbordamiento horizontal en móvil"
        a.screenshot(path=str(args.output / "movil.png"), full_page=True)
        a.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Seguimiento", exact=True
        ).click()
        a.get_by_role("navigation", name="Seguimiento de las necesidades").get_by_role(
            "button", name="Calendario", exact=True
        ).click()
        expect(a.locator(".nw-calendar-grid")).to_be_visible()
        a.get_by_label("Vista de calendario", exact=True).select_option("week")
        assert a.locator(".nw-calendar-day").count() == 7
        assert not errors, errors
        assert not failures, failures
        # GALANT 20.9.4: synthetic visual/interaction test only, no Meta tokens.
        fb_ctx, fb_page = context()
        login(fb_page, email)
        fake_id = "qa-facebook-contact-visual"
        fake_lead = {
            "id": fake_id, "name": "Contacto QA", "company": "",
            "specialty": "Carpintería", "trades": ["Carpintería", "Pintura"],
            "workers": 2, "availability": "Próxima semana", "experience": "3 años",
            "documents_state": "unverified", "status": "contacting",
            "requirement_id": None, "linked_needs": [],
            "entity_type": "individual", "interest_type": "service_offer",
            "team_available": True, "has_employees": False,
            "work_area": "Coronel", "work_communes": ["Coronel"],
            "follow_up_on": None, "follow_up_note": "", "last_inbound_at": None,
            "contact_phone": "", "phone_source": "", "phone_requested_at": None,
            "ai_consent": False, "ai_consent_state": "not_requested",
            "ai_paused": False, "support_reason": "", "last_message": None,
            "analysis": {"label":"Sin necesidad","state":"unlinked",
                "requirement": None,"checks":[],"missing":[],"human_review_required":True},
            "phone_opt_out": False, "can_reply": False, "unread": True,
            "profile": {
                "summary": "Ofrece carpintería, declara experiencia y trabaja con equipo.",
                "percent": 75, "completed": 6, "total": 8, "missing": ["Disponibilidad exacta"],
                "evidence": "Datos sintéticos de QA; requieren confirmación humana."
            },
        }
        fake_tracking = {
            "total": 1, "urgent": 1, "needs_human": 0, "unlinked": 1,
            "overdue": 0, "by_category": {"Carpintería": 1},
            "by_stage": {"Responder": 1}, "by_requirement": {}, "limited": False,
            "disclaimer": "Datos de prueba", "rows": [{
                "id": fake_id, "name": "Contacto QA", "company": "",
                "category": "Carpintería", "stage": "Responder",
                "urgency": "high", "next_action": "Confirmar disponibilidad",
                "trades": ["Carpintería", "Pintura"], "links": [], "matches": [],
                "needs_support": False, "unread": True, "requirement_id": None,
                "follow_up_on": None, "profile_state": "Ficha parcial"
            }]
        }
        fake_center = {
            "automatic_enabled": False, "manual_enabled": False,
            "messaging_enabled": True, "ai_enabled": False,
            "auto_reply_enabled": False, "page_id": "qa-only",
            "pending_ads": [], "publications": [], "leads": [fake_lead],
            "guides_approved": 0,
            "counts": {"pending_ads": 0, "published_ads": 0,
                "failed_ads": 0, "total_ads": 0, "contacts": 1,
                "unread": 1, "review": 0, "support": 0}
        }
        def mock_json(payload):
            def respond(route):
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(payload, ensure_ascii=False))
            return respond
        fb_root = "**/api/v1/network/facebook/"
        fb_ctx.route(fb_root + "center", mock_json(fake_center))
        fb_ctx.route(fb_root + "galancito/seguimiento", mock_json(fake_tracking))
        fb_ctx.route(fb_root + "leads/" + fake_id, mock_json({"lead":fake_lead,"messages":[]}))
        fb_ctx.route(fb_root + "leads/" + fake_id + "?include_messages=false",
                     mock_json({"lead":fake_lead,"messages":[]}))
        fb_ctx.route(fb_root + "leads/" + fake_id + "/insights", mock_json({
            "contact_id":fake_id, "next_action":"Confirmar disponibilidad","matches":[],
            "suggestions": [], "missing": [], "source": "reglas_locales",
            "review_required": True, "changes_applied": False,
            "summary": {"name":"Contacto QA","specialty":"Carpintería","workers":2,
                        "availability":"Próxima semana","stage":"Responder"}}))
        fb_ctx.route(fb_root + "leads/" + fake_id + "/trace", mock_json([]))
        fb_ctx.route(fb_root + "leads/" + fake_id + "/conversation-brief", mock_json({
            "summary": "Ofrece servicios en carpintería. Trabaja con equipo. Experiencia: 3 años.",
            "facts": [
                {"key":"specialty", "label":"Oficio principal", "value":"Carpintería",
                 "source":"chat", "at":None, "source_message_id":"qa-inbound"},
                {"key":"experience", "label":"Experiencia declarada", "value":"3 años",
                 "source":"chat", "at":None, "source_message_id":"qa-inbound"}
            ],
            "missing":["Disponibilidad exacta"],
            "evidence":[{"id":"qa-msg-1","text":"Hago carpintería, llevo 3 años y tengo cuadrilla",
                         "at":None,"source_message_id":"qa-inbound"}],
            "message_count":1,"messages_reviewed":1,"limited":False,
            "fingerprint":"qa-stable-brief","ai_eligible":False,"ai":None,
            "review_required":True,"source":"datos_y_conversacion",
            "last_inbound_at":None,"trades":["Carpintería","Pintura"],
        }))

        fb_page.get_by_role("button", name="Red de Obras", exact=True).click()
        fb_page.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Facebook", exact=True).click()
        fb_page.get_by_role("navigation", name="Centro Facebook").get_by_role(
            "button", name="Seguimiento", exact=True).click()
        expect(fb_page.get_by_role("button", name="Ver ficha").first).to_be_visible()
        fb_page.get_by_role("button", name="Ver contactos de Carpintería").click()
        expect(fb_page.get_by_role("searchbox", name="Buscar personas u oficios")).to_have_value("Carpintería")
        fb_page.get_by_role("button", name="Limpiar filtros").click()
        fb_page.get_by_role("button", name="Filtrar seguimiento: Responder").click()
        expect(fb_page.get_by_role("searchbox", name="Buscar personas u oficios")).to_have_value("Responder")
        fb_page.get_by_role("button", name="Limpiar filtros").click()
        fb_page.get_by_role("button", name="Ver ficha").first.click()
        sheet = fb_page.get_by_role("dialog", name="Ficha de Contacto QA")
        expect(sheet).to_be_visible()
        expect(sheet.get_by_role("heading", name="Datos generales")).to_be_visible()
        expect(sheet.get_by_role("heading", name="Galancito · Resumen del chat")).to_be_visible()
        expect(sheet.get_by_text("Hago carpintería, llevo 3 años y tengo cuadrilla")).to_be_visible()
        expect(sheet.get_by_role("heading", name="Datos identificados en la conversación")).to_be_visible()
        expect(sheet.get_by_role("button", name="Ver chat")).to_be_visible()
        assert not fb_page.locator(".fbc-inbox").is_visible(), "La ficha no debe navegar al chat"
        fb_page.screenshot(path=str(args.output / "ficha-facebook-qa.png"), full_page=True)
        # Los datos editados no se descartan al abrir el chat sin confirmación.
        sheet.get_by_role("button", name="Editar seguimiento").click()
        sheet.get_by_role("textbox", name="Nota interna").fill("Nota sintética sin guardar")
        fb_page.once("dialog", lambda prompt: prompt.dismiss())
        sheet.get_by_role("button", name="Ver chat").click()
        expect(sheet).to_be_visible()
        fb_page.once("dialog", lambda prompt: prompt.accept())
        sheet.get_by_role("button", name="Ver chat").click()
        expect(sheet).not_to_be_visible()
        expect(fb_page.locator(".fbc-inbox")).to_be_visible()
        fb_page.set_viewport_size({"width":390,"height":844})
        fb_page.get_by_role("navigation", name="Centro Facebook").get_by_role(
            "button", name="Seguimiento", exact=True).click()
        fb_page.get_by_role("button", name="Ver ficha").first.click()
        expect(fb_page.get_by_role("dialog", name="Ficha de Contacto QA")).to_be_visible()
        assert fb_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
            "Ficha Facebook: desbordamiento horizontal en móvil")
        fb_page.screenshot(path=str(args.output / "ficha-facebook-movil-qa.png"), full_page=True)
        fb_page.get_by_role("button", name="Cerrar ficha").click()
        fb_ctx.close()
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
