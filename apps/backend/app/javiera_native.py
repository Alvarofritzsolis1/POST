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
BODY_RECT = fitz.Rect(43, 47, A4.width - 43, A4.height - 65)
DOCUMENT_TITLES = {
    "internal_rules_receipt": "RECEPCIÓN DEL REGLAMENTO INTERNO",
    "irl": "INFORMACIÓN DE RIESGOS LABORALES (IRL)",
    "induction": "REGISTRO DE INDUCCIÓN DE PREVENCIÓN",
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
    if name not in {"base", *DOCUMENT_TITLES}:
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
        output.append("<tr><td>" + mark + "</td><td>" + _html(value) + "</td></tr>")
    return "".join(output)


def _body(code: str, data: dict, matrix: list[str] | None) -> str:
    if code == "internal_rules_receipt":
        version = _get(data, "extra.regulation_version", required=True)
        return _template(code).substitute(regulation_version=_html(version))
    if code == "irl":
        if not matrix:
            raise NativeDocumentError(
                "No existe una matriz IRL aprobada para el cargo. Completa su revisión antes de generar el PDF."
            )
        return _template(code).substitute(risk_rows=_rows("risk", matrix))
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
    raise NativeDocumentError("Este tipo documental aún no fue migrado al motor nativo.")


def render_native_pdf(code: str, data: dict, *, matrix: list[str] | None = None) -> bytes:
    """Genera PDF A4 desde HTML/CSS versionado; solo vista previa no firmada.

    El motor NO consulta ni muta tablas operativas, historiales o hojas Excel.
    """
    if code not in DOCUMENT_TITLES:
        raise NativeDocumentError("Formato nativo todavía no disponible.")
    if not isinstance(data, dict):
        raise NativeDocumentError("Datos del expediente no válidos.")
    company = _get(data, "employer.name", required=True)
    worker = _get(data, "worker.name", required=True)
    site = _get(data, "site.name", required=True)
    body = _body(code, data, matrix)
    version = (_get(data, "extra.regulation_version")
               if code == "internal_rules_receipt" else
               _get(data, "extra.irl_revision") if code == "irl" else
               _get(data, "extra.induction_version"))
    html = _template("base").substitute(
        title=_html(DOCUMENT_TITLES[code]),
        company=_html(company),
        company_rut=_html(_get(data, "employer.rut", required=True)),
        worker=_html(worker),
        worker_rut=_html(_get(data, "worker.rut", required=True)),
        site=_html(site),
        role=_html(_get(data, "role") or "Por indicar"),
        date=_html(_record_date(data)),
        document_ref=_html(version or "Por indicar"),
        content=body,
    )
    css = (TEMPLATE_PATH / "print.css").read_text(encoding="utf-8")
    if len(html) > 380_000:
        raise NativeDocumentError("Documento demasiado extenso para la impresión segura.")
    story = fitz.Story(html=html, user_css=css)
    with TemporaryDirectory(prefix="javiera-native-") as temporary:
        output = Path(temporary) / "preview.pdf"
        writer = fitz.DocumentWriter(str(output))
        finished = False
        try:
            for number in range(40):
                device = writer.begin_page(A4)
                more, _ = story.place(BODY_RECT)
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
                if (pdf.page_count > 1 and index == pdf.page_count
                        and "Firma trabajador" in last_text
                        and len(last_text.strip()) < 210):
                    raise NativeDocumentError(
                        "La firma quedó aislada en la última página; revisa el diseño."
                    )
                blocks = [block for block in page.get_text("blocks")
                          if len(block) > 4 and isinstance(block[4], str)
                          and block[4].strip()]
                if not blocks:
                    raise NativeDocumentError("Se detectó una página sin contenido.")
                for block in blocks:
                    if (block[0] < -0.5 or block[1] < -0.5 or
                            block[2] > A4.width + 0.5 or block[3] > A4.height + 0.5):
                        raise NativeDocumentError(
                            "Texto fuera de los límites A4 en página " + str(index)
                        )
                page.insert_text(
                    (43, A4.height - 31),
                    "Vista previa documental · Página " + str(index) + " de " + str(pdf.page_count),
                    fontsize=8, color=(0.30, 0.35, 0.40),
                )
            return pdf.tobytes(garbage=3, deflate=True)
