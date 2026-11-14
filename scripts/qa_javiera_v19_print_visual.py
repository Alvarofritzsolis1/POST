#!/usr/bin/env python3
"""Auditoría A4 de los diez formatos nativos con identidades sintéticas.

Cada PDF y cada página se guardan como imágenes para que un revisor real pueda
inspeccionarlas. No contiene empleados, contratos ni datos privados.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "backend"))
from app.javiera_native import DOCUMENT_TITLES, render_native_pdf, NativeDocumentError  # noqa: E402


def sample_data():
    return {
        "employer": {"name": "CONSTRUCTORA SINTÉTICA PARA CONTROL DE CALIDAD SPA",
                     "rut": "76000000-0"},
        "worker": {"name": "TRABAJADOR DE PRUEBA CON APELLIDOS LARGOS",
                   "rut": "20000000-5"},
        "site": {"name": "OBRA DE ENSAYO A4"},
        "role": "CARPINTERO",
        "event": {
            "date": "2026-11-09",
            "induction_topics": "\n".join([
                "Uso y conservación de EPP",
                "Riesgos de caída en superficies elevadas",
                "Señalización, accesos y zonas restringidas",
                "Identificación de medidas de control y procedimientos",
                "Reporte de incidentes y comunicación de emergencias",
            ]),
            "epp_items": "Casco: 1\nGuantes: 2 pares\nLentes de seguridad: 1\nZapatos: 1 par",
            "pts_version": "ENSAYO-PTS-01",
        },
        "extra": {
            "regulation_version": "VERSIÓN SINTÉTICA DE ENSAYO",
            "representative_name": "REPRESENTANTE DE EMPRESA SINTÉTICA",
            "representative_rut": "15000000-9",
        },
    }


def inspect_pdf(code, raw, output):
    failures = []
    pages = []
    with fitz.open(stream=raw, filetype="pdf") as doc:
        if not 1 <= doc.page_count <= 40:
            failures.append("número de páginas fuera de rango")
        all_text = "\n".join(p.get_text() for p in doc)
        compact = " ".join(all_text.split())
        # La declaración empresarial no contiene un trabajador de PRUEBA:
        # comprobar los datos que realmente corresponden a cada documento.
        expected = ["CONSTRUCTORA", "SINTÉTICA", "OBRA"]
        expected.append("REPRESENTANTE" if code == "sworn_declaration" else "PRUEBA")
        for word in expected:
            if word not in compact:
                failures.append("falta texto obligatorio: " + word)
        if "GALANT" in compact:
            failures.append("marca interna visible en PDF")
        if code == "sworn_declaration":
            # La identidad de la empresa debe indicar a su REPRESENTANTE,
            # nunca el nombre del trabajador ni "No aplica".
            if "Representante legal No aplica" in compact:
                failures.append("declaración jurada omite nombre del representante legal")
            if ("Representante legal REPRESENTANTE DE EMPRESA SINTÉTICA" not in compact):
                failures.append("nombre del representante incompleto en ficha documental")
            if "RUT representante 15.000.000-9" not in compact:
                failures.append("RUT del representante ausente o mal formateado")
        if code == "ppe_delivery":
            if "Recibido en físico" not in compact:
                failures.append("cabecera de recepción EPP truncada o no impresa")

        # La vista previa está en la interfaz; el documento impreso no debe
        # contener ninguna leyenda técnica ni advertencia de firma ficticia.
        normalized = compact.casefold()
        for forbidden in (
            "vista previa", "no acredita", "formato para completar",
            "espacios para firma física", "firmar físicamente",
            "este pdf", "observaciones para revisión",
            "contenido del formato aprobado", "documento que se prepara",
        ):
            if forbidden in normalized:
                failures.append("texto interno visible en PDF: " + forbidden)
        if "Firma" not in compact:
            failures.append("no se encuentra espacio para firma")
        if code in {"pts", "irl"} and "Sección aprobada 01" not in compact:
            failures.append("falta contenido preventivo de prueba")
        if code in {"labor_contract", "extension_addendum", "transfer_addendum",
                    "sworn_declaration", "ppe_delivery", "pts", "pts_receipt"}:
            if "PRIMERA" not in compact or "SEGUNDA" not in compact:
                failures.append("faltan cláusulas de prueba")
        for index, page in enumerate(doc, 1):
            if abs(page.rect.width - 595.28) > 1 or abs(page.rect.height - 841.89) > 1:
                failures.append("página no es tamaño A4: " + str(index))
            text = page.get_text()
            spans = [
                sp for block in page.get_text("dict")["blocks"] if block.get("type") == 0
                for line in block.get("lines", []) for sp in line.get("spans", [])
                if sp.get("text", "").strip()
            ]
            smallest = min((sp["size"] for sp in spans), default=0)
            if not spans:
                failures.append("página vacía: " + str(index))
            if spans and smallest < 7.2:
                failures.append("letra demasiado pequeña: página " + str(index))
            for b in page.get_text("blocks"):
                if len(b) > 4 and isinstance(b[4], str) and b[4].strip():
                    if min(b[:2]) < -0.5 or b[2] > page.rect.width+0.5 or b[3] > page.rect.height+0.5:
                        failures.append("texto fuera del A4: página " + str(index))
            if index == doc.page_count and doc.page_count > 1 and "Firma" in text and len(text.strip()) < 210:
                failures.append("firma aislada en última página")
            preview = output / f"{code}_pagina_{index:02d}.png"
            page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False).save(preview)
            pages.append({"number": index, "text_characters": len(text.strip()),
                          "min_font_pt": round(smallest, 2), "preview": preview.name})
        (output / (code+".pdf")).write_bytes(raw)
    return {"code": code, "page_count": len(pages), "pages": pages,
            "failures": failures, "passed": not failures}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    tests = []
    approved = (
        "PRIMERA: Cláusula sintética únicamente para la validación de impresión. "
        "El texto laboral real debe provenir de la versión documental publicada.\n\n"
        "SEGUNDA: La salida impresa se firma posteriormente de forma manuscrita. "
        "Esta cláusula es solo una prueba de estructura y saltos de línea."
    )
    for code in DOCUMENT_TITLES:
        record = sample_data()
        if code == "sworn_declaration":
            record["worker"] = {"name": "", "rut": ""}
        matrix = ([f"Sección aprobada {i:02d}: controles preventivos sintéticos de ensayo."
                   for i in range(1, 19 if code == "irl" else 18)] if code in {"irl","pts"} else None)
        source = approved if code not in {"internal_rules_receipt","irl","induction"} else None
        try:
            raw = render_native_pdf(code, record, matrix=matrix, approved_text=source)
            tests.append(inspect_pdf(code, raw, args.output))
        except (NativeDocumentError, ValueError, RuntimeError) as exc:
            tests.append({"code": code, "passed": False, "failures": [str(exc)], "pages": []})
    report = {"formats_total": len(DOCUMENT_TITLES),
              "formats_passed": sum(int(t["passed"]) for t in tests),
              "all_passed": len(tests) == 10 and all(t["passed"] for t in tests),
              "scope": "Revisión geométrica automática, más PNG por página para revisión visual humana.",
              "not_certified": "No es homologación de textos laborales reales ni firma efectuada.",
              "formats": tests}
    (args.output / "reporte_impresion.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"total": report["formats_total"],
                      "passed": report["formats_passed"],
                      "failures": {t["code"]: t["failures"] for t in tests if not t["passed"]}},
                     ensure_ascii=False))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
