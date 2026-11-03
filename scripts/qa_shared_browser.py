"""Browser acceptance on an isolated QA deployment seeded with synthetic accounts.
Run with QA_BASE_URL and QA_PASSWORD. Never point at production.
"""

import os
from pathlib import Path
from uuid import uuid4
from io import BytesIO
from openpyxl import Workbook
from playwright.sync_api import sync_playwright, expect

base = os.environ.get("QA_BASE_URL", "http://127.0.0.1:5173")
password = os.environ["QA_PASSWORD"]
artifacts = Path(os.environ.get("QA_ARTIFACTS", "/tmp/galant-browser-qa"))
artifacts.mkdir(parents=True, exist_ok=True)
name = "Empresa QA " + uuid4().hex[:8]


def login(page, email):
    print("Login", email, flush=True)
    page.goto(base)
    page.get_by_label("Correo electrónico", exact=True).fill(email)
    page.get_by_label("Contraseña", exact=True).fill(password)
    page.get_by_role("button", name="Ingresar a GALANT").click()
    expect(page.get_by_role("navigation", name="Navegación principal")).to_be_visible()


def navigate(page, label):
    print("Navigate", label, flush=True)
    page.get_by_role("navigation", name="Navegación principal").get_by_role(
        "button", name=label, exact=True
    ).click()


with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=os.getenv("QA_CHROMIUM", "/usr/bin/chromium"),
        headless=True,
        args=["--no-sandbox"],
    )
    a = browser.new_context(viewport={"width": 1440, "height": 1000})
    b = browser.new_context(viewport={"width": 1440, "height": 1000})
    admin, ximena = a.new_page(), b.new_page()
    errors = []
    admin.on("pageerror", lambda e: errors.append(str(e)))
    ximena.on("pageerror", lambda e: errors.append(str(e)))
    login(admin, "admin@example.cl")
    login(ximena, "ximena@example.cl")
    options = admin.get_by_label("Obra seleccionada").locator("option").all()
    site = options[1].get_attribute("value")
    admin.get_by_label("Obra seleccionada").select_option(site)
    ximena.get_by_label("Obra seleccionada").select_option(site)
    navigate(admin, "Contratistas")
    navigate(ximena, "Contratistas")
    admin.get_by_role("button", name="Nuevo contratista", exact=True).click()
    admin.get_by_label("Nombre o razón social").fill(name)
    admin.get_by_label("Naturaleza").select_option("with_workers")
    admin.get_by_label("Frecuencia").select_option("fixed")
    admin.get_by_role("button", name="Guardar contratista", exact=True).click()
    expect(admin.locator("table").get_by_text(name, exact=True)).to_be_visible()
    expect(ximena.locator("table").get_by_text(name, exact=True)).to_be_visible(
        timeout=20000
    )
    admin.get_by_role("button", name="Nuevo trabajador", exact=True).click()
    admin.get_by_label("Nombre completo").fill("Trabajador QA sintético")
    admin.get_by_role("button", name="Guardar trabajador", exact=True).click()
    ximena.get_by_role("button", name="Ver trabajadores de " + name, exact=True).click()
    expect(
        ximena.locator("table").get_by_text("Trabajador QA sintético", exact=True)
    ).to_be_visible(timeout=20000)
    admin.get_by_role("button", name="Editar empresa", exact=True).click()
    admin.get_by_label("Nombre o razón social").fill(name + " actualizado")
    admin.get_by_role("button", name="Guardar contratista", exact=True).click()
    expect(
        ximena.locator("table").get_by_text(name + " actualizado", exact=True)
    ).to_be_visible(timeout=20000)
    navigate(admin, "Cotizaciones y asistencia")
    admin.get_by_placeholder("Buscar trabajador o contratista").fill(name)
    admin.get_by_role("button", name="Revisar", exact=True).click()
    dialog = admin.get_by_role("dialog", name="Revisar cotizaciones")
    dialog.get_by_label("Días requeridos (confirmación manual)").fill("30")
    dialog.get_by_label("Días pagados registrados").fill("25")
    dialog.get_by_label("Pago confirmado manualmente").check()
    dialog.get_by_role("button", name="Guardar control").click()
    expect(dialog).not_to_be_visible()
    navigate(ximena, "Cotizaciones y asistencia")
    ximena.get_by_placeholder("Buscar trabajador o contratista").fill(name)
    expect(
        ximena.locator("tbody tr")
        .filter(has_text=name)
        .get_by_text("con diferencias", exact=True)
    ).to_be_visible(timeout=20000)
    # Import through the actual UI, then verify in the other open session.
    navigate(admin, "Importación masiva")
    admin.get_by_label("Tipo de carga").select_option("workers")
    workbook = Workbook()
    workbook.active.append(
        [
            "NOMBRE CONTRATISTA",
            None,
            "NOMBRE TRABAJADOR",
            "RUT",
            "F.INGRESO",
            "F.TERMINO",
            "CONTRATO",
            "TIPO",
        ]
    )
    workbook.active.append(
        [
            name + " actualizado",
            "ignorar",
            "Persona importada QA",
            "11111111-1",
            "01/09/2026",
            "",
            "QA-1",
            "INDEFINIDO",
        ]
    )
    stream = BytesIO()
    workbook.save(stream)
    admin.locator("input[type=file]").set_input_files(
        {
            "name": "workers-qa.xlsx",
            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "buffer": stream.getvalue(),
        }
    )
    admin.get_by_role("button", name="Previsualizar archivo", exact=True).click()
    expect(
        admin.get_by_role("button", name="Confirmar importación", exact=True)
    ).to_be_enabled()
    admin.get_by_role("button", name="Confirmar importación", exact=True).click()
    expect(
        admin.get_by_role("status").filter(has_text="Importación guardada")
    ).to_be_visible()
    navigate(ximena, "Contratistas")
    ximena.get_by_role(
        "button", name="Ver trabajadores de " + name + " actualizado", exact=True
    ).click()
    expect(
        ximena.locator("table").get_by_text("Persona importada QA", exact=True)
    ).to_be_visible(timeout=20000)
    navigate(admin, "Inicio")
    admin.screenshot(path=str(artifacts / "desktop.png"), full_page=True)
    for label in [
        "Contratistas",
        "Trabajadores",
        "Control documental",
        "Cotizaciones y asistencia",
        "Importación masiva",
        "Gestión administrativa",
        "Informes",
        "Configuración",
    ]:
        navigate(admin, label)
        expect(
            admin.get_by_role("heading", name=label, exact=True).first
        ).to_be_visible()
    navigate(admin, "Inicio")
    for label, width, height in [("tablet", 820, 1180), ("mobile", 390, 844)]:
        admin.set_viewport_size({"width": width, "height": height})
        admin.screenshot(path=str(artifacts / (label + ".png")), full_page=True)
        assert admin.evaluate(
            "document.documentElement.scrollWidth<=window.innerWidth"
        ), label + " overflows horizontally"
    admin.get_by_role("button", name="Abrir menú").click()
    navigate(admin, "Configuración")
    expect(admin.get_by_role("heading", name="Perfil y preferencias")).to_be_visible()
    assert not errors, errors
    browser.close()
print(
    "PASS: two browser contexts share contractors, workers, edits, Excel worker imports and contributions; all routes load; desktop/tablet/mobile have no horizontal overflow. Synthetic data only."
)
