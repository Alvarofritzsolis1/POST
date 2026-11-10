"""Motor nativo HTML/CSS -> PDF de Proyecto Javiera (piloto no destructivo).

Las plantillas son HTML/CSS editables que no dependen de LibreOffice ni de
recalcular el archivo Excel. El Excel histórico permanece intacto.
Ninguna vista previa acredita entrega, inducción, recepción o firma.
"""
from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
from string import Template
from tempfile import TemporaryDirectory
from typing import Any

import fitz


TEMPLATE_PATH = Path(__file__).resolve().parent / "javiera_native_templates"
A4 = fitz.paper_rect("a4")
# A4 con margen físico >= 14 mm. El área anterior (65 pt al pie)
# dejaba firmas aisladas con PyMuPDF 1.28, pese a tener espacio imprimible.
BODY_RECT = fitz.Rect(43, 40, A4.width - 43, A4.height - 46)
DOCUMENT_TITLES = {
    "internal_rules_receipt": "RECEPCIÓN DEL REGLAMENTO INTERNO",
    "irl": "INFORMACIÓN DE RIESGOS LABORALES (IRL)",
    "induction": "REGISTRO DE INDUCCIÓN DE PREVENCIÓN",
    "labor_contract": "CONTRATO DE TRABAJO",
    "transfer_addendum": "ANEXO DE TRASLADO",
    "extension_addendum": "ANEXO DE PRÓRROGA CONTRACTUAL",
    "sworn_declaration": "DECLARACIÓN JURADA",
    "ppe_delivery": "REGISTRO DE ELEMENTOS DE PROTECCIÓN PERSONAL",
    "pts": "PROCEDIMIENTO DE TRABAJO SEGURO",
    "pts_receipt": "CONSTANCIA DE RECEPCIÓN DE PTS",
}


class NativeDocumentError(ValueError):
    """Una plantilla nativa carece de datos verificables o no cabe en A4."""


def _get(data: dict, dotted: str, *, required: bool = False) -> str:
    value: Any = data
    for part in dotted.split("."):
        if not isinstance(value, dict):
            value = None
            break
        value = value.get(part)
    if value is None or isinstance(value, (list, dict)):
        value = ""
    value = str(value).strip()
    if len(value) > 4000:
        raise NativeDocumentError("El campo " + dotted + " excede el límite documental.")
    if required and not value:
        raise NativeDocumentError("Falta completar " + dotted + " para la vista previa nativa.")
    return value


def _html(value: str) -> str:
    return escape(value, quote=True).replace("\n", "<br/>")


def _record_date(data: dict) -> str:
    value = _get(data, "event.date", required=True)
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        raise NativeDocumentError("Indica una fecha válida YYYY-MM-DD.") from None


def _template(name: str) -> Template:
    if name not in {"base", "irl_document", *DOCUMENT_TITLES}:
        raise NativeDocumentError("No existe la plantilla nativa seleccionada.")
    path = TEMPLATE_PATH / (name + ".html")
    return Template(path.read_text(encoding="utf-8"))


def _rows(kind: str, values: list[str]) -> str:
    if not values or len(values) > 80:
        raise NativeDocumentError("El contenido documental debe tener entre 1 y 80 apartados.")
    output = []
    for index, value in enumerate(values, 1):
        value = str(value).strip()
        if not value:
            raise NativeDocumentError("La sección " + str(index) + " está vacía.")
        if len(value) > 5500:
            raise NativeDocumentError("Una sección supera el tamaño imprimible admitido.")
        mark = "☐" if kind == "topics" else str(index)
        cells = "<tr><td>" + mark + "</td><td>" + _html(value) + "</td>"
        if kind == "ppe":
            cells += "<td>☐</td>"
        output.append(cells + "</tr>")
    return "".join(output)


def _irl_table_rows(values: list[str], role: str) -> str:
    """Tabla IRL con columnas reales: labor, peligro, riesgo y controles.

    Las revisiones antiguas no estructuradas se conservan textualmente en una
    fila única; nunca se reinterpretan como medidas preventivas nuevas.
    """
    from .javiera_irl import parse_irl_section
    if not values or len(values) > 1500:
        raise NativeDocumentError("La matriz IRL debe contener entre 1 y 1.500 registros válidos.")
    parts = []
    for ordinal, value in enumerate(values, 1):
        record = parse_irl_section(value, version=0, ordinal=ordinal, cargo=role)
        if record["structured"]:
            columns = "".join("<td>" + _html(record[key]) + "</td>"
                              for key in ("labor", "peligro", "riesgo", "medidas"))
        else:
            # Esta fila se imprime íntegra, sin simular una tabla validada.
            columns = '<td colspan="4">' + _html(record["original"]) + '</td>'
        parts.append("<tr>" + columns + "</tr>")
    return "".join(parts)


def _pts_table_rows(values: list[str]) -> str:
    """Imprimir apartados PTS D:T con sus encabezados técnicos originales."""
    from .javiera_pts_headers import PTS_TECHNICAL_HEADINGS
    if not values or len(values) > 17:
        raise NativeDocumentError("El PTS excede los 17 apartados técnicos documentados.")
    full = len(values) == 17
    rows = []
    for index, section in enumerate(values, 1):
        value = str(section or "").strip()
        if not value:
            raise NativeDocumentError(f"El PTS tiene vacío el apartado {index}.")
        if len(value) > 5500:
            raise NativeDocumentError(f"El apartado PTS {index} excede la longitud imprimible.")
        title = PTS_TECHNICAL_HEADINGS[index - 1] if full else f"Sección {index}"
        rows.append("<tr><th>" + str(index) + "</th><th>" + _html(title) +
                    "</th><td>" + _html(value) + "</td></tr>")
    return "".join(rows)


def _source_paragraphs(approved_text: str | None) -> str:
    """Preserve every approved clause/paragraph; escape untrusted HTML."""
    if not approved_text or not approved_text.strip():
        raise NativeDocumentError(
            "Falta el texto original publicado de este documento. "
            "Revisa y publica la plantilla textual antes de migrarla."
        )
    if len(approved_text) > 35000:
        raise NativeDocumentError("El documento supera el límite del editor documental.")
    parts = approved_text.replace("\r\n", "\n").split("\n\n")
    return "".join("<p>" + _html(part.strip()) + "</p>"
                   for part in parts if part.strip())


def _body(code: str, data: dict, matrix: list[str] | None,
          approved_text: str | None = None,
          approved_html: str | None = None,
          irl_context: dict | None = None,
          original_source: dict | None = None) -> str:
    if code == "internal_rules_receipt":
        version = _get(data, "extra.regulation_version", required=True)
        return _template(code).substitute(regulation_version=_html(version))
    if code == "irl":
        if not matrix:
            raise NativeDocumentError(
                "No existe una matriz IRL aprobada para el cargo. Completa su revisión antes de generar el PDF."
            )
        from .javiera_irl_render_context import original_context
        context = original_context(irl_context, original_source)
        return _template(code).substitute(
            risk_rows=_irl_table_rows(matrix, _get(data, "role")), **context
        )
    if code == "induction":
        topics = _get(data, "event.induction_topics")
        if not topics:
            topics = _get(data, "extra.induction_topics")
        values = [item.strip(" \t-•") for item in topics.splitlines() if item.strip(" \t-•")]
        if not values:
            raise NativeDocumentError(
                "Indica los temas reales de la inducción, uno por línea. No se permite crear un temario ficticio."
            )
        return _template(code).substitute(topic_rows=_rows("topics", values))
    if code in {
        "labor_contract", "transfer_addendum", "extension_addendum",
        "sworn_declaration", "ppe_delivery", "pts", "pts_receipt",
    }:
        # HTML editable proviene exclusivamente de la revisión administrativa
        # normalizada y verificada en javiera_native_edit.
        safe_text = approved_html if approved_html is not None else _source_paragraphs(approved_text)
        params = {"approved_text": safe_text}
        if code == "ppe_delivery":
            raw = _get(data, "event.epp_items", required=True)
            entries = [x.strip() for x in raw.splitlines() if x.strip()]
            if not entries:
                raise NativeDocumentError("Indica elementos EPP, uno por línea.")
            params["ppe_rows"] = _rows("ppe", entries)
        if code == "pts":
            if not matrix:
                raise NativeDocumentError("Falta una matriz PTS aprobada para el cargo.")
            params["matrix_rows"] = _pts_table_rows(matrix)
        if code == "pts_receipt":
            params["pts_version"] = _html(_get(data, "event.pts_version", required=True))
        return _template(code).substitute(**params)
    raise NativeDocumentError("Este tipo documental aún no fue migrado al motor nativo.")


def render_native_pdf(code: str, data: dict, *, matrix: list[str] | None = None,
                      approved_text: str | None = None,
                      approved_html: str | None = None,
                      native_intro: str | None = None,
                      irl_context: dict | None = None,
                       original_source: dict | None = None,
                       _compact: bool = False) -> bytes:
    """Genera PDF A4 desde HTML/CSS versionado; solo vista previa no firmada.

    El motor NO consulta ni muta tablas operativas, historiales o hojas Excel.
    """
    if code not in DOCUMENT_TITLES:
        raise NativeDocumentError("Formato nativo todavía no disponible.")
    if not isinstance(data, dict):
        raise NativeDocumentError("Datos del expediente no válidos.")
    company = _get(data, "employer.name", required=True)
    # El texto de origen es obligatorio para los siete formatos migrados.
    # Revisarlo primero permite informar la causa real en lugar de solicitar
    # datos de firma cuando el documento aún carece de cláusulas oficiales.
    body = _body(code, data, matrix, approved_text, approved_html, irl_context, original_source)
    if native_intro:
        # IRL, inducción y Reglamento conservan sus tablas obligatorias.
        # El HTML editable se añade sin reemplazar matrices o casillas.
        body = '<section class="native-intro">' + native_intro + '</section>' + body
    is_declaration = code == "sworn_declaration"
    worker = _get(data, "worker.name", required=not is_declaration)
    signer = _get(data, "extra.representative_name", required=is_declaration) if is_declaration else worker
    site = _get(data, "site.name", required=True)
    version_key = {
        "internal_rules_receipt": "extra.regulation_version",
        "irl": "extra.irl_revision",
        "induction": "extra.induction_version",
        "pts": "event.pts_version",
        "pts_receipt": "event.pts_version",
    }.get(code)
    version = _get(data, version_key) if version_key else ""
    html = _template("irl_document" if code == "irl" else "base").substitute(
        original_code=_html((original_source or {}).get("document_code") or "DPR-IRL-03"),
        original_version=_html((original_source or {}).get("source_version") or ""),
        irl_print_mode="irl-images-ready" if code == "irl" and (original_source or {}).get("images") else "",
        declaration=_html(((original_source or {}).get("static") or {}).get("A172", "")),
        title=_html(DOCUMENT_TITLES[code]),
        company=_html(company),
        company_rut=_html(_get(data, "employer.rut", required=True)),
        worker=_html(worker if worker else "No aplica"),
        worker_rut=_html(_get(data, "extra.representative_rut", required=True)
                         if is_declaration else _get(data, "worker.rut", required=True)),
        person_label="Representante legal" if is_declaration else "Trabajador/a",
        person_rut_label="RUT representante" if is_declaration else "RUT trabajador/a",
        signatory_label="Firma declarante" if is_declaration else "Firma trabajador/a",
        signatory_name=_html(signer),
        site=_html(site),
        role=_html(_get(data, "role")),
        date=_html(_record_date(data)),
        document_ref=_html(version),
        content=body,
    )
    if _get(data, "event.print_notes"):
        note = _get(data, "event.print_notes")
        html = html.replace(
            '<div class="signature-panel">',
            '<section class="print-notes"><h2>OBSERVACIONES</h2><p>'
            + _html(note) + '</p></section><div class="signature-panel">'
        )
    css = (TEMPLATE_PATH / "print.css").read_text(encoding="utf-8")
    if _compact:
        # Reintento automático SOLO ante firma aislada; márgenes de impresión
        # >= 13 mm, sin reducir fuentes ni omitir texto del Excel.
        css += """
        body p {margin:2pt 0 4pt;}
        body h2 {margin:7pt 0 4pt;}
        .document-head {margin-bottom:3pt;}
        .identity td, .identity th {padding:3pt 4pt;}
        .matrix td, .matrix th, .topics td, .topics th {padding:3pt 5pt;}
        .legal-copy p {margin:0 0 7pt;}
        .signature-panel {margin-top:4pt;}
        .signature-panel h2 {margin:5pt 0 4pt;}
        """
    rect = (fitz.Rect(37, 34, A4.width - 37, A4.height - 43)
            if _compact else BODY_RECT)
    html_limit = 1_500_000 if code == "irl" and original_source else 380_000
    if len(html) > html_limit:
        raise NativeDocumentError("Documento demasiado extenso para la impresión segura.")
    story = fitz.Story(html=html, user_css=css)
    with TemporaryDirectory(prefix="javiera-native-") as temporary:
        output = Path(temporary) / "preview.pdf"
        writer = fitz.DocumentWriter(str(output))
        finished = False
        try:
            for number in range(40):
                device = writer.begin_page(A4)
                more, _ = story.place(rect)
                story.draw(device)
                writer.end_page()
                if not more:
                    finished = True
                    break
        finally:
            writer.close()
        if not finished:
            raise NativeDocumentError(
                "El documento excede 40 páginas o contiene contenido no paginable."
            )
        with fitz.open(str(output)) as pdf:
            if not 1 <= pdf.page_count <= 40:
                raise NativeDocumentError("Cantidad de páginas inválida.")
            for index, page in enumerate(pdf, 1):
                # Rechazar firmas que queden solas en la última página:
                # un PDF técnicamente válido no siempre es imprimible.
                last_text = page.get_text()
                irl_folio_cierre = (
                    code == "irl" and bool((original_source or {}).get("images"))
                    and "Declaración" in last_text
                    and "Firma trabajador" in last_text and "RUT:" in last_text
                )
                if (pdf.page_count > 1 and index == pdf.page_count
                        and ("Firma trabajador" in last_text or "Firma declarante" in last_text)
                        and len(last_text.strip()) < 210 and not irl_folio_cierre):
                    if not _compact:
                        # Mantener todas las cláusulas y su tipografía; se
                        # redistribuyen únicamente márgenes y espaciados.
                        return render_native_pdf(
                            code, data, matrix=matrix,
                            approved_text=approved_text,
                            approved_html=approved_html,
                            native_intro=native_intro, irl_context=irl_context,
                            original_source=original_source, _compact=True
                        )
                    raise NativeDocumentError(
                        "La firma quedó aislada incluso tras optimizar los espacios."
                    )
                blocks = [block for block in page.get_text("blocks")
                          if len(block) > 4 and isinstance(block[4], str)
                          and block[4].strip()]
                if not blocks and not page.get_images(full=True):
                    raise NativeDocumentError("Se detectó una página sin texto ni imágenes.")
                for block in blocks:
                    if (block[0] < -0.5 or block[1] < -0.5 or
                            block[2] > A4.width + 0.5 or block[3] > A4.height + 0.5):
                        raise NativeDocumentError(
                            "Texto fuera de los límites A4 en página " + str(index)
                        )
                if pdf.page_count > 1:
                    page.insert_text(
                        (A4.width - 105, A4.height - 31),
                        "Página " + str(index) + " de " + str(pdf.page_count),
                        fontsize=8, color=(0.30, 0.35, 0.40),
                    )
            return pdf.tobytes(garbage=3, deflate=True)
