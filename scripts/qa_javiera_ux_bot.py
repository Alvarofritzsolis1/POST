"""GALANT / Proyecto JAVIERA: evaluador reproducible de experiencia IRL.

No es un modelo que sustituya una inspección humana ni una revisión legal.
Puntúa comportamientos observables de la interfaz en el stack QA aislado,
documenta fallos y genera capturas en varios tamaños de pantalla.
El 100/100 aquí NO autoriza emisión preventiva ni despliegue.
"""
import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect


RUBRIC = {
    "Acceso y navegación": 15,
    "Integridad documental visible": 30,
    "Interacción intuitiva": 15,
    "Diseño responsivo": 20,
    "Accesibilidad básica": 10,
    "Estabilidad de ejecución": 10,
}
BREAKPOINTS = (("escritorio", 1440, 900),
               ("tablet", 1024, 768),
               ("movil", 390, 844),
               ("movil_estrecho", 360, 740))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18612")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if urlparse(args.url).hostname not in ("localhost", "127.0.0.1"):
        raise SystemExit("El bot solamente funciona contra el stack QA local.")
    args.output.mkdir(parents=True, exist_ok=True)

    report = {
        "name": "GALANT UX Auditor Bot - IRL",
        "mode": "evaluación determinista Playwright, no certificación profesional",
        "at": datetime.now(timezone.utc).isoformat(),
        "source_commit": os.getenv("GITHUB_SHA", "local"),
        "rubric": RUBRIC,
        "checks": [],
        "score": 0,
        "out_of": 100,
        "critical_failures": [],
        "recommendations": [],
        "release_ready": False,
        "manual_release_gates": [
            "74 fórmulas verificadas con entradas y resultados del Excel",
            "cinco bloques gráficos transcritos y cotejados línea a línea",
            "riesgo CARPINTERO, fila 40, completado y aprobado técnicamente",
            "matrices por cargo y HDS aprobadas por responsable autorizado",
            "comparación visual PDF A4 y respaldo/recuperación en entorno real",
        ],
    }

    def record(category, label, points, passed, evidence="", critical=False):
        report["checks"].append({
            "category": category, "check": label, "points": points,
            "earned": points if passed else 0,
            "status": "PASS" if passed else "FAIL",
            "evidence": str(evidence)[:500],
            "critical": critical,
        })
        if passed:
            report["score"] += points
        else:
            report["recommendations"].append(
                f"{category}: corregir {label.lower()}. {evidence}")
            if critical:
                report["critical_failures"].append(label)
        return passed

    errors, server_errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=os.getenv("GALANT_QA_BROWSER_EXECUTABLE") or None)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            reduced_motion="reduce",
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("response", lambda response: server_errors.append({
            "status": response.status, "url": urlparse(response.url).path,
        }) if response.status >= 500 else None)

        try:
            try:
                page.goto(args.url, wait_until="domcontentloaded", timeout=20000)
                page.get_by_label("Correo electrónico", exact=True).fill(
                    os.environ["GALANT_JAVIERA_QA_EMAIL"])
                page.get_by_label("Contraseña", exact=True).fill(
                    os.environ["GALANT_JAVIERA_QA_PASSWORD"])
                page.get_by_role("button", name="Ingresar a GALANT").click()
                expect(page.get_by_role("button", name="Menú de usuario")).to_be_visible(
                    timeout=15000)
                record("Acceso y navegación", "Inicio de sesión y acceso autorizado",
                       7, True, critical=True)
            except Exception as error:
                record("Acceso y navegación", "Inicio de sesión y acceso autorizado",
                       7, False, str(error), critical=True)
                raise

            try:
                page.goto(args.url + "/proyecto-javiera?legacy=1",
                          wait_until="domcontentloaded", timeout=20000)
                page.get_by_role("button", name="Editar documentos visualmente").click()
                page.get_by_role(
                    "button", name=re.compile("INFORMACIÓN DE RIESGOS LABORALES")).click()
                expect(page.get_by_role(
                    "heading", name="Formato original, datos vinculados y matriz de riesgos"
                )).to_be_visible(timeout=12000)
                record("Acceso y navegación", "Ruta al IRL desde Proyecto Javiera",
                       8, True, critical=True)
            except Exception as error:
                record("Acceso y navegación", "Ruta al IRL desde Proyecto Javiera",
                       8, False, str(error), critical=True)
                raise

            role = page.get_by_role("combobox", name="Cargo que deseas revisar")
            try:
                role.select_option("PINTOR", timeout=15000)
                expect(page.locator(".jir-risk-table tbody tr")).to_have_count(
                    13, timeout=20000)
                record("Integridad documental visible",
                       "13 actividades del cargo PINTOR visibles y sin truncamiento",
                       15, True, critical=True)
            except Exception as error:
                count = page.locator(".jir-risk-table tbody tr").count()
                record("Integridad documental visible",
                       "13 actividades del cargo PINTOR visibles y sin truncamiento",
                       15, False, f"Filas visibles: {count}; {error}", critical=True)

            try:
                expect(page.locator(".jir-risk-table thead th")).to_have_count(4)
                record("Integridad documental visible",
                       "Cuatro columnas de riesgos con encabezados",
                       9, True, critical=True)
            except Exception as error:
                record("Integridad documental visible",
                       "Cuatro columnas de riesgos con encabezados",
                       9, False, str(error), critical=True)

            record("Integridad documental visible",
                   "Estado explícito de aprobación y origen Excel",
                   6, page.locator(".jir-original-status").is_visible() and
                   page.locator(".jir-view-toolbar").inner_text().find("Referencia") >= 0
                   or (page.locator(".jir-original-status").is_visible() and
                       page.locator(".jir-view-toolbar").inner_text().find("Matriz aprobada") >= 0),
                   "Debe distinguir fuente original, matriz aprobada y referencia por aprobar.")

            record("Interacción intuitiva",
                   "Acceso a Matrices y cargos desde el IRL",
                   8, page.get_by_role(
                       "button", name="Abrir Matrices y cargos").is_visible())

            record("Interacción intuitiva",
                   "Vista A4 abierta y opción de copiar matriz",
                   7, page.locator("details.jir-preview").get_attribute("open") is not None
                   and page.get_by_role(
                       "button", name="Copiar matriz para Excel").is_enabled())

            issues = page.evaluate("""() => {
              const root = document.querySelector('.jir-root');
              if (!root) return [{tag: 'root', label: 'IRL no encontrado'}];
              return [...root.querySelectorAll('button, select, input, textarea')]
                .filter(el => {
                  const s = getComputedStyle(el), b = el.getBoundingClientRect();
                  return b.width > 0 && b.height > 0 &&
                         s.visibility !== 'hidden' && s.display !== 'none';
                })
                .filter(el => {
                  const label = el.labels && el.labels.length > 0;
                  const named = (el.getAttribute('aria-label') || '').trim() ||
                    (el.getAttribute('title') || '').trim() ||
                    (el.textContent || '').trim() || label;
                  return !named;
                })
                .slice(0, 15)
                .map(el => ({
                  tag: el.tagName, type: el.getAttribute('type'),
                  id: el.id, className: typeof el.className === 'string' ?
                    el.className.slice(0, 70) : ''
                }));
            }""")
            record("Accesibilidad básica",
                   "Controles visibles con etiqueta accesible",
                   10, len(issues) == 0, json.dumps(issues, ensure_ascii=False))

            for label, width, height in BREAKPOINTS:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(450)
                sizes = page.evaluate("""() => ({
                  viewport: window.innerWidth,
                  pageWidth: document.documentElement.scrollWidth,
                  bodyWidth: document.body.scrollWidth,
                  previewScroll: document.querySelector('.jir-scroll')?.scrollWidth,
                })""")
                overflow = max(sizes["pageWidth"], sizes["bodyWidth"]) - sizes["viewport"]
                # La tabla A4 interna puede tener scroll propio, pero la
                # página principal no puede desplazarse lateralmente.
                record("Diseño responsivo",
                       f"Sin desplazamiento horizontal global en {label} ({width}px)",
                       5, overflow <= 8, f"Desborde: {overflow}px; {sizes}",
                       critical=overflow > 80)
                page.screenshot(path=str(args.output / f"irl_{label}.png"),
                                full_page=False, animations="disabled")

        except Exception as error:
            report["critical_failures"].append(
                "No se pudo completar el recorrido del usuario: " + str(error)[:300])
        finally:
            record("Estabilidad de ejecución",
                   "Sin excepciones JavaScript ni respuestas HTTP 5xx",
                   10, not errors and not server_errors,
                   f"Errores JS: {errors[:5]}; HTTP 5xx: {server_errors[:5]}",
                   critical=True)
            browser.close()

    report["status"] = (
        "PASS_UX_AUTOMATION" if report["score"] >= 95 and
        not report["critical_failures"] else "FAIL_UX_AUTOMATION"
    )
    report["release_ready"] = False  # Requiere comprobaciones externas y actas.
    (args.output / "informe_ux_bot.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = [
        "# GALANT · Evaluación automatizada de interfaz IRL",
        "",
        f"**Resultado UX:** {report['score']}/100 | **Estado:** {report['status']}",
        "",
        "La nota evalúa solo controles, navegación y legibilidad mecánica. "
        "No sustituye certificación legal, matriz preventiva ni impresión definitiva.",
        "",
        "## Comprobaciones",
    ]
    for item in report["checks"]:
        summary.append(
            f"- {item['status']} ({item['earned']}/{item['points']}) — "
            f"{item['category']}: {item['check']}.")
    summary += ["", "## Mejoras detectadas"]
    summary += ["- " + item for item in report["recommendations"]] or [
        "- Sin problemas automatizados detectados. Revisión visual humana aún necesaria."]
    summary += ["", "## Requisitos externos pendientes de liberación"]
    summary += ["- " + item for item in report["manual_release_gates"]]
    summary += ["", "**Se prohíbe inferir aptitud de producción desde esta puntuación.**"]
    (args.output / "informe_ux_bot.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8")
    print(json.dumps({
        "score": report["score"], "status": report["status"],
        "critical_failures": report["critical_failures"],
        "recommendations": report["recommendations"],
        "report": str(args.output / "informe_ux_bot.md"),
    }, ensure_ascii=False, indent=2))
    if report["status"] != "PASS_UX_AUTOMATION":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
