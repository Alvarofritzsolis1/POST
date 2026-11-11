"""Secciones nativas HTML del IRL en el orden del Excel original.

Los datos laborales son del expediente; las matrices técnicas solo se toman de
revisiones preventivas aprobadas. Los píxeles de los bloques 4–5 provienen del
XLSX privado de la organización, nunca de una imagen inventada ni de OCR.
"""
from __future__ import annotations
from html import escape

WORKPLACE_HEADERS = (
    "a) Espacio de trabajo",
    "b) Condiciones ambientales del puesto",
    "c) Condiciones de orden y aseo exigidas en el puesto de trabajo",
    "d) Máquinas y herramientas de trabajo que se deberán emplear",
)
SUBSTANCE_HEADERS = (
    "Nombre del producto", "Sinónimo", "Fórmula", "Aspecto", "Olor",
    "Modo de empleo", "Límites de exposición", "Forma de almacenamiento",
    "Uso correcto de EPP", "Medidas sobre primeros auxilios",
    "Información técnica de la etiqueta (DS 57 MINSAL)",
    "Otra información relevante contenida en la HDS",
)


def safe(value: object) -> str:
    return escape(str(value or "").strip(), quote=True).replace("\n", "<br/>")


def original_context(context: dict | None, source: dict | None) -> dict:
    context = context or {}
    source = source or {}
    text = source.get("static") or {}
    profile = list(context.get("PERFILES") or [])
    workplace = list(context.get("PUESTOS") or [])
    substances = list(context.get("SUSTANCIAS") or [])

    cond = []
    for index, heading in enumerate(WORKPLACE_HEADERS):
        value = workplace[index] if index < len(workplace) else ""
        cond.append("<section class=\"irl-condition\"><h3>" + safe(heading) +
                    "</h3><p>" + safe(value) + "</p></section>")
    material = []
    for index, heading in enumerate(SUBSTANCE_HEADERS):
        value = substances[index] if index < len(substances) else ""
        material.append("<tr><th>" + chr(97 + index) + ")</th><th>" +
                        safe(heading) + "</th><td>" + safe(value) + "</td></tr>")
    pictures = []
    # HTML editable solo después de la validación profesional documentada.
    editorial = source.get("approved_editable_blocks") or []
    if editorial:
        if len(editorial) != 5 or any(not str(item.get("text") or "").strip()
                                     for item in editorial):
            raise ValueError("Transcripción IRL publicada incompleta.")
        for item in editorial:
            html_lines = []
            for line in str(item["text"]).splitlines():
                html_lines.append("<p>" + safe(line) + "</p>" if line.strip()
                                  else '<div class="irl-ed-gap"></div>')
            pictures.append('<section class="irl-ed-block"><h3>' +
                            safe(item.get("title")) + '</h3>' +
                            "".join(html_lines) + '</section>')
    else:
        for image in source.get("images") or []:
            uri = str(image.get("data_uri") or "")
            if not (uri.startswith("data:image/png;base64,") or
                    uri.startswith("data:image/jpeg;base64,")):
                raise ValueError("Tipo de imagen IRL no permitido para impresión.")
            pictures.append(
                '<figure class="irl-original-picture"><img src="' + escape(uri, quote=True) +
                '" alt="' + safe(image.get("title")) + '"/></figure>'
            )
    return {
        "original_heading": safe(text.get("A4") or "INFORMACIÓN DE RIESGOS LABORALES (IRL) - DECRETO SUPREMO N° 44"),
        "legal_intro": safe(text.get("A5")),
        "legal_basis_heading": safe(text.get("A13")),
        "legal_basis_text": safe(text.get("A14")),
        "cargo_profile": safe(profile[0]) if profile else "",
        "workplace_sections": "".join(cond),
        "substance_rows": "".join(material),
        "original_images": "".join(pictures),
        "obligations": safe(text.get("A169")),
        "declaration": safe(text.get("A172")),
    }
