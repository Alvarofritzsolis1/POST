"""Editor HTML nativo seguro: fragmentos con formato, sin scripts o recursos remotos.

Solo se admiten elementos de presentación documental. HTML y PDF no ejecutan
instrucciones, no cargan URL externas ni acreditan firma o recepción.
"""
from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

from .javiera_logic import SAFE_FIELD, field

ALLOWED_TAGS = frozenset({
    "p", "h2", "h3", "strong", "b", "em", "i", "u", "ol", "ul", "li",
    "table", "thead", "tbody", "tr", "td", "th", "br", "blockquote",
})
VOID_TAGS = frozenset({"br"})
TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


class NativeHtmlError(ValueError):
    """El formato HTML tiene instrucciones o etiquetas no permitidas."""


class _DocumentHtml(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.open_tags: list[str] = []
        self.text: list[str] = []
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS or attrs:
            raise NativeHtmlError(
                "Solo se permiten párrafos, títulos, listas, tablas y estilos de texto. "
                "No se admiten enlaces, scripts, imágenes ni atributos HTML."
            )
        self.count += 1
        if self.count > 600:
            raise NativeHtmlError("El diseño supera la cantidad permitida de etiquetas.")
        self.parts.append("<" + tag + ">")
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID_TAGS or attrs:
            raise NativeHtmlError("Solo <br/> puede utilizar cierre inmediato.")
        self.parts.append("<br/>")

    def handle_endtag(self, tag):
        if not self.open_tags or self.open_tags[-1] != tag:
            raise NativeHtmlError("Corrige las etiquetas HTML sin cerrar o fuera de orden.")
        self.open_tags.pop()
        self.parts.append("</" + tag + ">")

    def handle_data(self, data):
        if any(ord(ch) < 32 and ch not in "\n\t\r" for ch in data):
            raise NativeHtmlError("No se admiten caracteres de control.")
        self.parts.append(escape(data, quote=True))
        self.text.append(data)

    def handle_comment(self, data):
        raise NativeHtmlError("No se admiten comentarios HTML.")

    def handle_decl(self, decl):
        raise NativeHtmlError("No se admiten declaraciones HTML.")

    def handle_pi(self, data):
        raise NativeHtmlError("No se admiten instrucciones ejecutables.")


def validate_native_html(fragment: str, *, allow_empty: bool = False) -> str:
    if not isinstance(fragment, str) or len(fragment) > 35000:
        raise NativeHtmlError("El diseño HTML no puede superar 35.000 caracteres.")
    if not fragment.strip():
        if allow_empty:
            return ""
        raise NativeHtmlError("Completa el contenido antes de guardar.")
    parser = _DocumentHtml()
    try:
        parser.feed(fragment)
        parser.close()
    except NativeHtmlError:
        raise
    except ValueError as exc:
        raise NativeHtmlError("El HTML contiene una estructura inválida.") from exc
    if parser.open_tags:
        raise NativeHtmlError("Hay etiquetas HTML que no tienen cierre.")
    plain = " ".join(parser.text).strip()
    if len(plain) < 20:
        raise NativeHtmlError("El formato necesita al menos 20 caracteres de texto.")
    if re.search(r"\bgalant\b", plain, re.IGNORECASE):
        raise NativeHtmlError("Los documentos imprimibles no deben incluir la marca GALANT.")
    tokens = TOKEN.findall("".join(parser.parts))
    if any(not SAFE_FIELD.fullmatch(token) for token in tokens):
        raise NativeHtmlError("Se detectó una variable documental no permitida.")
    if "{{" in TOKEN.sub("", "".join(parser.parts)) or "}}" in TOKEN.sub("", "".join(parser.parts)):
        raise NativeHtmlError("Corrige las variables con formato {{campo.nombre}}.")
    return "".join(parser.parts)


def plain_text_to_html(text: str) -> str:
    """Carga inicial fiel de cláusulas en HTML, sin inventar ni reescribir texto."""
    return "".join(
        "<p>" + escape(piece.strip()).replace("\n", "<br/>") + "</p>"
        for piece in text.replace("\r\n", "\n").split("\n\n")
        if piece.strip()
    )


def bind_native_html(fragment: str, data: dict) -> str:
    """Escapa cada dato variable antes de insertarlo en el fragmento HTML."""
    normalized = validate_native_html(fragment)

    def replace(match: re.Match) -> str:
        key = match.group(1)
        value = field(data, key)
        if value in (None, "", [], {}):
            raise NativeHtmlError("Completa el campo obligatorio: " + key)
        if isinstance(value, (dict, list)):
            raise NativeHtmlError("La variable " + key + " no contiene texto válido.")
        return escape(str(value), quote=True).replace("\n", "<br/>")

    return TOKEN.sub(replace, normalized)
