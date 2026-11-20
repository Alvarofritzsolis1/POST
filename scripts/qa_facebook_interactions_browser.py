"""QA visual de Centro de Interacciones con Meta sintético; sin mensajes reales."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def make_comment(*, page=False):
    return {
        "id": "22222222-2222-4222-8222-" + ("222222222222" if page else "111111111111"),
        "remote_comment_id": "1489275590928529_" + ("10002" if page else "10001"),
        "record_id": "11111111-1111-4111-8111-111111111111",
        "origin_requirement_id": "33333333-3333-4333-8333-333333333333",
        "post_title": "Maestros de carpintería",
        "post_specialty": "Carpintería",
        "post_url": "",
        "declared_profile": {"trades": [] if page else ["Carpintería"],
                             "team_size_declared": None if page else 4},
        "potential_needs": [],
        "author_name": "Página de prueba" if page else "Juan Ejemplo",
        "author_picture_url": None,
        "body": "Gracias por comentar" if page else "Soy carpintero y tengo una cuadrilla de cuatro",
        "posted_at": "2026-11-20T13:00:00+00:00",
        "parent_id": "1489275590928529_10001" if page else None,
        "like_count": 1,
        "reply_count": 0 if page else 1,
        "is_page_author": page,
        "classification": "question" if page else "interested",
        "classification_source": "rules",
        "classification_score": 75,
        "classified_at": "2026-11-20T13:00:05+00:00",
        "review_state": "new",
        "review_note": "",
        "author_activity_count": 0,
        "author_activity": [],
        "reviewed_at": None,
        "is_hidden": False,
        "is_deleted": False,
        "user_likes": False,
        "can_like": not page,
        "can_reply": not page,
        "can_hide": not page,
        "can_delete": not page,
        "can_private_reply": False,
        "private_reply_state": "not_sent",
        "lead_id": None,
        "history": [],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18612")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Únicamente QA local; nunca usar contra producción")
    args.output.mkdir(parents=True, exist_ok=True)
    errors, outreach = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900},
                                      reduced_motion="reduce")
        page = context.new_page()
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("request", lambda req: outreach.append(req.url)
                if "/comments/" in req.url
                and (req.url.endswith("/reply") or req.url.endswith("/private-reply")
                     or req.url.endswith("/hide"))
                else None)
        payload = {"rows": [make_comment(), make_comment(page=True)],
                   "limited": False, "mode": "manual"}
        page.route("**/api/v1/network/facebook/publications/interactions/inbox*",
                   lambda route: route.fulfill(status=200, content_type="application/json",
                                               body=json.dumps(payload)))
        page.route("**/api/v1/network/facebook/publications/*/comments/*/suggest",
                   lambda route: route.fulfill(status=200, content_type="application/json",
                       body=json.dumps({"draft": "¡Hola! ¿Trabajas solo o con tu cuadrilla?",
                                        "source": "template", "requires_review": True})))
        page.goto(args.url, wait_until="domcontentloaded")
        page.get_by_label("Correo electrónico", exact=True).fill(
            os.environ["GALANT_NETWORK_QA_EMAIL"])
        page.get_by_label("Contraseña", exact=True).fill(
            os.environ["GALANT_NETWORK_QA_PASSWORD"])
        page.get_by_role("button", name="Ingresar a GALANT").click()
        expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible()
        page.get_by_role("button", name="Red de Obras", exact=True).click()
        page.get_by_role("navigation", name="Red de Obras", exact=True).get_by_role(
            "button", name="Facebook", exact=True).click()
        page.get_by_role("navigation", name="Centro Facebook").get_by_role(
            "button", name="Interacciones").click()
        expect(page.get_by_role("heading", name="Centro de Interacciones")).to_be_visible()
        expect(page.get_by_role("button", name="Configuración de automatización")).to_have_count(0)
        expect(page.locator(".fbint-item")).to_have_count(1)  # Respuesta propia de la Página no genera lead
        page.locator(".fbint-item").first.click()
        expect(page.get_by_role("heading", name="Detalle del comentario")).to_be_visible()
        expect(page.get_by_text("Ficha del comentario")).to_be_visible()
        expect(page.get_by_text("Cuadrilla declarada")).to_be_visible()
        expect(page.get_by_text("Gracias por comentar")).to_be_visible()
        page.get_by_role("button", name="Sugerir texto").click()
        expect(page.get_by_label("Escribir respuesta")).to_have_value(
            "¡Hola! ¿Trabajas solo o con tu cuadrilla?")
        page.screenshot(path=str(args.output / "interacciones-escritorio.png"), full_page=True)
        page.get_by_role("button", name="Negativos", exact=True).click()
        expect(page.locator(".fbint-item")).to_have_count(0)
        page.get_by_role("button", name="Todos", exact=True).click()
        expect(page.locator(".fbint-item")).to_have_count(1)
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator(".fbint-detail")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2"), (
            "El Centro de Interacciones provocó desplazamiento horizontal")
        # El documento puede ocultar un desborde con overflow-x:clip; comprobar
        # también las cajas reales de los controles y el texto de seguimiento.
        clipped = page.locator(".fbint-detail .fbint-section-title button, .fbint-detail .fbint-source").evaluate_all(
            """els => els.filter(el => {
               const b = el.getBoundingClientRect();
               const style = getComputedStyle(el);
               return style.display !== 'none' && (
                 b.right > window.innerWidth - 2 || b.left < 0 ||
                 el.scrollWidth > el.clientWidth + 2);
             }).map(el => ({text: el.textContent.slice(0,70), rect: el.getBoundingClientRect().toJSON()}))"""
        )
        assert not clipped, ("Controles o textos cortados en móvil: " + str(clipped))
        page.screenshot(path=str(args.output / "interacciones-movil.png"), full_page=True)
        assert not errors, errors
        assert not outreach, "La QA intentó enviar o moderar mensajes reales: " + str(outreach)
        browser.close()
    (args.output / "qa.json").write_text(json.dumps({
        "result": "PASS", "cases": ["bandeja", "autor", "hilo", "ficha", "sugerencia",
                                   "filtros", "movil", "no_outreach"]}, indent=2))


if __name__ == "__main__":
    main()
