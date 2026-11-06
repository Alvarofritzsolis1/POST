"""Regresiones de JAVIERA 16.5 contra QA local y cuentas sintéticas.

Se invoca desde qa_javiera_v16_browser.py; nunca usa documentos ni datos reales.
"""
import hashlib
import os
from uuid import uuid4

from playwright.sync_api import expect


def _rut(number):
    total = sum(int(n) * (2 + i % 6) for i, n in enumerate(reversed(str(number))))
    digit = 11 - total % 11
    return f"{number}-{'0' if digit == 11 else 'K' if digit == 10 else digit}"


def _api(context, url, path, method="GET", data=None):
    token = next((c["value"] for c in context.cookies() if c["name"] == "galant_post_csrf"), "")
    response = context.request.fetch(url + "/api/v1" + path, method=method,
        data=data, headers={"X-CSRF-Token": token})
    assert response.ok, (method, path, response.status, response.text()[:1200])
    return response.json()


def _publish_pts(context, browser, url):
    reviewer = browser.new_context()
    try:
        _api(reviewer, url, "/auth/login", "POST", {
            "email": os.environ.get("GALANT_JAVIERA_QA_REVIEWER_EMAIL", "qa-reviewer@example.test"),
            "password": os.environ.get("GALANT_JAVIERA_QA_REVIEWER_PASSWORD",
                                       os.environ["GALANT_JAVIERA_QA_PASSWORD"]),
        })
        user = _api(reviewer, url, "/auth/me")
        _api(context, url, "/javiera/admin/reviews/reviewers", "PUT", {
            "user_id": user["id"], "specialty": "prevencion", "active": True,
            "designation": "Responsable de simulación QA con datos sintéticos, sin valor profesional",
        })
        check = next(x for x in _api(context, url, "/javiera/admin/reviews/checklists")
                     if x["specialty"] == "prevencion")

        def approve(kind, resource):
            _api(reviewer, url, "/javiera/admin/reviews/signoff", "POST", {
                "resource_kind": kind, "resource_id": resource, "specialty": "prevencion",
                "verdict": "approved", "checklist": {k: True for k in check["requirements"]},
                "comments": "Simulación automatizada de revisión sobre contenido de prueba. No acredita revisión profesional ni eventos reales.",
                "regulatory_basis": check["legal_reference"],
            })

        fields = ["employer.name", "employer.rut", "worker.name", "worker.rut", "site.name",
                  "role", "event.date", "extra.representative_name", "extra.representative_rut"]
        draft = _api(context, url, "/javiera/admin/templates/pts", "PUT", {
            "title": "PTS sintético para QA", "area": "Prevención de Riesgos",
            "body": "SIMULACIÓN QA. Persona {{worker.name}}, RUT {{worker.rut}}, empresa {{employer.name}}, RUT {{employer.rut}}, obra {{site.name}}. Labor {{role}}. Fecha {{event.date}}. Representante {{extra.representative_name}}, {{extra.representative_rut}}.",
            "fields": fields, "rule": {}, "layout": {},
            "reason": "Plantilla sintética para comprobar navegador, guardado y reemisión",
        })
        template = next(t for t in _api(context, url, "/javiera/admin/templates") if t["code"] == "pts")
        revision = next(r for r in template["revisions"] if r["revision"] == draft["revision"])
        approve("template", revision["id"])
        _api(reviewer, url, f"/javiera/admin/templates/pts/approve/{draft['revision']}", "POST")
        matrix = _api(context, url, "/javiera/admin/matrices", "POST", {
            "kind": "PTS", "cargo": "Pintura", "source": "Simulación QA sin riesgos reales",
            "sections": [f"Sección sintética de prueba {i + 1}." for i in range(17)],
        })
        approve("matrix", matrix["id"])
        _api(reviewer, url, f"/javiera/admin/matrices/{matrix['id']}/approve", "POST")
    finally:
        reviewer.close()


def verify_guided_workflow(page, context, browser, url, output, report):
    """Comprueba PDF real, ficha incompleta, reemisión y respuestas tardías."""
    _publish_pts(context, browser, url)
    sites = _api(context, url, "/ops/sites")
    site = next(x for x in sites if x["name"] == "Brisas de Junquillar")
    suffix = uuid4().hex[:8]
    identity_seed = int(suffix, 16) % 999999
    company_rut, worker_rut, representative_rut = (
        _rut(76000000 + identity_seed), _rut(20000000 + identity_seed), _rut(15000000 + identity_seed))
    page.goto(url + "/proyecto-javiera", wait_until="domcontentloaded")
    page.locator(".j65-entry button").first.click()
    page.get_by_role("button", name="Procedimiento de trabajo seguro (PTS)").click()
    page.get_by_label("Obra", exact=True).select_option(site["id"])
    page.get_by_label("Nombre o razón social del empleador").fill("EMPRESA QA " + suffix)
    page.get_by_label("Nombre completo del trabajador").fill("PERSONA QA " + suffix)
    with page.expect_response(lambda r: r.url.endswith("/javiera/dossiers") and r.request.method == "POST") as created:
        page.get_by_role("button", name="Guardar ficha", exact=True).click()
    dossier_id = created.value.json()["id"]
    expect(page.get_by_role("status")).to_contain_text("Ficha guardada")
    # Se puede completar la ficha después de guardarla sin abandonar JAVIERA.
    page.get_by_label("RUT del empleador", exact=True).fill(company_rut)
    page.get_by_label("RUT del trabajador", exact=True).fill(worker_rut)
    page.get_by_label("Nombre del representante legal", exact=True).fill("REPRESENTANTE QA")
    page.get_by_label("RUT del representante legal", exact=True).fill(representative_rut)
    page.get_by_label("Labor / especialidad", exact=True).fill("Pintura")
    page.get_by_label("Fecha efectiva del documento", exact=True).fill("2026-11-06")
    expect(page.get_by_role("button", name="Vista previa", exact=True)).to_be_enabled()
    with context.expect_page() as preview_tab:
        with page.expect_response(lambda r: r.url.endswith("/javiera/preview")) as preview:
            page.get_by_role("button", name="Vista previa", exact=True).click()
    assert preview.value.ok and preview.value.headers.get("content-type") == "application/pdf"
    preview_link = page.get_by_role("link", name="Abrir vista previa del PDF", exact=True)
    expect(preview_link).to_be_visible()
    prefix = page.evaluate("""async url => {
        const bytes = new Uint8Array(await (await fetch(url)).arrayBuffer());
        return new TextDecoder().decode(bytes.slice(0, 5));
    }""", preview_link.get_attribute("href"))
    assert prefix == "%PDF-", prefix
    preview_tab.value.close()
    dossier = _api(context, url, f"/javiera/dossiers/{dossier_id}")
    assert dossier["data"]["employer"]["rut"] == company_rut
    assert dossier["data"]["worker"]["rut"] == worker_rut
    assert dossier["data"]["contract"] == {}
    assert dossier["data"]["role"] == "PINTOR"
    report["scenarios"]["complete_missing_rut_and_preview_without_contract"] = "PASS"

    with page.expect_download() as download:
        page.get_by_role("button", name="Descargar PDF", exact=True).click()
    first_path = output / "pts-sintetico-inicial.pdf"
    download.value.save_as(first_path)
    original = first_path.read_bytes()
    assert original.startswith(b"%PDF-")
    expect(page.locator(".j65-issued")).to_have_count(1)
    first_issue = _api(context, url, f"/javiera/dossiers/{dossier_id}")["issues"][0]["id"]
    with context.expect_page() as printed:
        page.get_by_role("button", name="Imprimir PDF", exact=True).click()
    print_link = page.get_by_role("link", name="Abrir PDF para imprimir", exact=True)
    expect(print_link).to_be_visible()
    printable = context.request.get(url + print_link.get_attribute("href"))
    assert printable.ok and printable.body().startswith(b"%PDF-")
    assert printable.headers.get("content-disposition", "").startswith("inline")
    printed.value.close()
    report["scenarios"]["download_and_print_approved_pdf"] = "PASS"

    page.get_by_label("Fecha efectiva del documento", exact=True).fill("2026-11-07")
    page.get_by_role("button", name="Guardar cambios", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Ficha guardada")
    reason = page.get_by_label("Motivo de reemisión", exact=True)
    expect(reason).to_be_visible()
    expect(page.get_by_role("button", name="Descargar PDF", exact=True)).to_be_disabled()
    reason.fill("Corrección de la fecha efectiva en el documento sintético de QA.")
    with page.expect_download() as corrected:
        page.get_by_role("button", name="Descargar PDF", exact=True).click()
    revised_path = output / "pts-sintetico-corregido.pdf"
    corrected.value.save_as(revised_path)
    assert revised_path.read_bytes().startswith(b"%PDF-")
    assert hashlib.sha256(original).digest() != hashlib.sha256(revised_path.read_bytes()).digest()
    assert context.request.get(url + f"/api/v1/javiera/issued/{first_issue}/pdf").body() == original
    report["scenarios"]["explicit_reissue_preserves_original_pdf"] = "PASS"

    # Una declaración es otro expediente; volver al PTS recupera el mismo trabajador.
    page.get_by_role("button", name="Zona Subcontratos", exact=True).click()
    page.locator(".j65-documents").get_by_role("button", name="Declaración jurada").click()
    page.get_by_role("button", name="Guardar ficha", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Ficha guardada")
    assert _api(context, url, f"/javiera/dossiers/{dossier_id}")["worker_id"] == dossier["worker_id"]
    page.get_by_role("button", name="Prevención de Riesgos", exact=True).click()
    page.get_by_role("button", name="Procedimiento de trabajo seguro (PTS)").click()
    expect(page.get_by_label("Buscar trabajador", exact=True)).to_have_value(dossier["worker_id"])
    report["scenarios"]["company_declaration_preserves_worker_dossier"] = "PASS"

    # Construir una ficha con datos personales únicos y retener su respuesta.
    company = _api(context, url, "/ops/contractors", "POST", {
        "site_id": site["id"], "name": "EMPRESA AISLAMIENTO " + suffix,
        "rut": None, "historical_code": "", "nature": "unclassified",
        "frequency": "unclassified", "contract_status": "active",
    })
    person = _api(context, url, "/ops/workers", "POST", {
        "site_id": site["id"], "contractor_id": company["contractor_id"],
        "name": "PERSONA AISLAMIENTO " + suffix, "rut": None,
    })
    private = _api(context, url, "/javiera/dossiers", "POST", {
        "site_id": site["id"], "employer_id": company["contractor_id"],
        "worker_id": person["worker_id"], "relationship": "contractor",
        "data": {"event_type": "ingreso", "extra": {
            "worker_address": "DOMICILIO SOLO PERSONA ANTERIOR " + suffix,
            "worker_nationality": "NACIONALIDAD SOLO PERSONA ANTERIOR",
        }},
    })
    private_data = _api(context, url, f"/javiera/dossiers/{private['id']}")
    page.goto(url + "/proyecto-javiera", wait_until="domcontentloaded")
    page.locator(".j65-entry button").first.click()
    page.get_by_role("button", name="Zona Subcontratos", exact=True).click()
    page.locator(".j65-documents").get_by_role("button", name="Contrato de trabajo").click()
    page.get_by_label("Obra", exact=True).select_option(site["id"])
    page.get_by_role("button", name="Ya existe en GALANT", exact=True).click()
    page.get_by_label("Buscar empresa", exact=True).select_option(company["contractor_id"])
    expect(page.get_by_label("Expedientes guardados", exact=True)).to_be_visible()
    page.get_by_role("button", name="Ya registrado", exact=True).click()
    held = []
    endpoint = url + f"/api/v1/javiera/dossiers/{private['id']}"
    page.route(endpoint, lambda route: held.append(route))
    page.get_by_label("Buscar trabajador", exact=True).select_option(person["worker_id"])
    expect(page.get_by_label("Buscar trabajador", exact=True)).to_have_value(person["worker_id"])
    # Una consulta independiente deja que Playwright entregue la solicitud retenida.
    expect(page.get_by_label("Domicilio del trabajador", exact=True)).to_be_visible()
    for _ in range(20):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "No se interceptó la carga de antecedentes del trabajador"
    page.get_by_role("button", name="Empresa nueva", exact=True).click()
    for route in held:
        route.fulfill(status=200, json=private_data)
    page.unroute(endpoint)
    page.wait_for_timeout(150)  # Permitir que se apliquen respuestas tardías antes de comprobar el aislamiento.
    expect(page.get_by_label("Domicilio del trabajador", exact=True)).to_have_value("")
    expect(page.get_by_label("Nacionalidad del trabajador", exact=True)).to_have_value("")
    assert "DOMICILIO SOLO PERSONA ANTERIOR" not in page.locator(".j65").inner_text()
    report["scenarios"]["late_worker_response_cannot_cross_company"] = "PASS"
    page.screenshot(path=str(output / "javiera_flujo_verificado.png"), full_page=True)
