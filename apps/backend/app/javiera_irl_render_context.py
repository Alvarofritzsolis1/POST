"""Secciones nativas HTML del IRL en el orden del Excel original.

Los datos laborales son del expediente; las matrices técnicas solo se toman de
revisiones preventivas aprobadas. Los píxeles de los bloques 4–5 provienen del
XLSX privado de la organización, nunca de una imagen inventada ni de OCR.
"""
from __future__ import annotations
from html import escape
import re

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


_TABLE_ROW = re.compile(r"^\s*(0?\d{1,2})\s*\|\s*(.+?)(?:\s*\|\s*☐\s*\|\s*☐\s*\|?)?\s*$")
_NUMBERED_RULE = re.compile(
    r"^\s*(?P<box>☐|□|☑|☒|\[[xX ]?\])?\s*"
    r"(?P<number>0?\d{1,2})\s*(?:\.-|\.|-|\))\s*(?P<description>.+)$"
)


def original_editorial_html(item: dict, index: int) -> str:
    """Convert the *reviewed* transcription into real HTML without unsafe tags.

    Not a transcription or an automatic legal approval. Source images are
    preserved until a human reviewer approves the text of all five blocks.
    The first block is a semantic five-column table; safety rules are
    numbered headings followed by bullet paragraphs.
    """
    content = str(item["text"])
    title = '<h3>' + safe(item.get("title") or f"Bloque {index}") + '</h3>'
    parts: list[str] = ['<section class="irl-ed-block">', title]
    rows = content.splitlines()
    if index == 1:
        in_table = False
        for line in rows:
            text = line.strip()
            if not text:
                if in_table:
                    parts.append('</tbody></table>')
                    in_table = False
                continue
            if text.upper() in ("ANTECEDENTES GENERALES", "OTRAS CONSIDERACIONES"):
                if in_table:
                    parts.append('</tbody></table>')
                    in_table = False
                parts.append('<h4 class="irl-ed-subhead">' + safe(text) + '</h4>')
                continue
            if text.startswith(("Indique en el recuadro", "Indique en el Recuadro")):
                parts.append('<p>' + safe(text) + '</p>')
                continue
            if text.startswith("N.°") or text.startswith("N.º") or text.startswith("N.° |"):
                if in_table:
                    parts.append('</tbody></table>')
                parts.append('<table class="irl-ed-checklist"><thead><tr>' +
                    '<th>N.º</th><th>Consideración</th><th>Sí</th><th>No</th>' +
                    '<th>Observaciones / Diagnóstico / Controles / Medicamentos</th>' +
                    '</tr></thead><tbody>')
                in_table = True
                continue
            m = _TABLE_ROW.fullmatch(text)
            if m and in_table:
                fields = [v.strip() for v in text.split("|")]
                if len(fields) >= 2:
                    # Conservar opciones seleccionadas y observaciones reales
                    # (también si incluyen barras verticales) sin insertar HTML.
                    values = [
                        fields[0].rstrip(".-"), fields[1],
                        fields[2] if len(fields) > 2 and fields[2] else "□",
                        fields[3] if len(fields) > 3 and fields[3] else "□",
                        " | ".join(fields[4:]) if len(fields) > 4 else "",
                    ]
                    cells = [safe(value) for value in values]
                    parts.append('<tr>' + "".join('<td>' + c + '</td>' for c in cells) +
                                 '</tr>')
                    continue
            parts.append('<p>' + safe(text) + '</p>')
        if in_table:
            parts.append('</tbody></table>')
    else:
        for line in rows:
            text = line.strip()
            if not text:
                continue
            match = _NUMBERED_RULE.match(text)
            if match:
                parts.append('<h4 class="irl-ed-norm">' +
                             safe(match.group("box") or "□") + ' ' +
                             safe(match.group("number")) + '.- ' +
                             safe(match.group("description")) + '</h4>')
            elif text.startswith(('•','- ')):
                parts.append('<p class="irl-ed-bullet">• ' + safe(text.lstrip('•- ')) +
                             '</p>')
            else:
                parts.append('<p>' + safe(text) + '</p>')
    parts.append('</section>')
    return "".join(parts)


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
        for index, item in enumerate(editorial, 1):
            pictures.append(original_editorial_html(item, index))
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
