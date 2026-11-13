"""Catálogo EPP del Excel maestro de Proyecto Javiera.

La hoja original tiene exactamente ocho filas de cantidad (D12:D19).
Nunca inferir elementos entregados a partir de fechas, texto libre o ejemplos.
Este módulo no depende del motor PDF y se reutiliza en el formulario y validación.
"""
from __future__ import annotations

import re
import unicodedata

EPP_NAMES = (
    "Casco de Seguridad",
    "Calzado de Seguridad",
    "Lentes de Seguridad",
    "Guantes de Cabritilla",
    "Protección Auditiva/Mascarilla",
    "Arnés de seguridad",
    "Delantal de cuero",
    "Guantes de soldador",
)

EPP_ALIASES = (
    ("casco", "casco de seguridad"),
    ("calzado de seguridad", "zapato de seguridad", "zapatos de seguridad",
     "bota de seguridad", "botas de seguridad", "botín de seguridad",
     "botines de seguridad", "botin de seguridad", "botines de seguridad"),
    ("lentes", "lentes de seguridad", "antiparras de seguridad"),
    ("guantes de cabritilla", "guante de cabritilla"),
    ("protección auditiva/mascarilla", "protección auditiva", "proteccion auditiva",
     "mascarilla", "protector auditivo"),
    ("arnés", "arnés de seguridad", "arnes", "arnes de seguridad"),
    ("delantal de cuero",),
    ("guantes de soldador", "guantes para soldador"),
)

class EppInputError(ValueError):
    """El valor no identifica de forma inequívoca un EPP realmente entregado."""


def normalize_epp(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(value).strip().casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


EPP_LOOKUP: dict[str, int] = {}
for _index, _names in enumerate(EPP_ALIASES):
    for _entry in (*_names, EPP_NAMES[_index]):
        _key = normalize_epp(_entry)
        if _key in EPP_LOOKUP and EPP_LOOKUP[_key] != _index:
            raise RuntimeError("Alias EPP duplicado: " + _key)
        EPP_LOOKUP[_key] = _index

DATE_LIKE = re.compile(r"^(?:\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})$")


def epp_quantities(raw: str) -> list[int]:
    """Acepta `2 casco; lentes`; rechaza fechas, categorías ambiguas y >30.

    No inventa entregas ni asigna cantidades por defecto fuera de lo
    declarado por el usuario. Todas las cantidades ausentes son cero.
    """
    if not isinstance(raw, str):
        raise EppInputError("Selecciona los EPP realmente entregados.")
    quantities = [0] * len(EPP_NAMES)
    for candidate in re.split(r"[,;\n]", raw):
        value = candidate.strip()
        if not value:
            continue
        if DATE_LIKE.fullmatch(value):
            raise EppInputError(
                f"«{value}» es una fecha, no un EPP. Corrige «Fecha efectiva del evento» "
                "y selecciona debajo el elemento que se entregó."
            )
        match = re.fullmatch(r"(?:(\d{1,2})\s*(?:[x×]\s*)?\s+|(?:(\d{1,2})[x×]\s*))?(.+)", value, re.I)
        if not match:
            raise EppInputError(f"No se reconoce el EPP «{value}».")
        amount = int(match.group(1) or match.group(2) or 1)
        description = normalize_epp(match.group(3))
        if DATE_LIKE.fullmatch(description):
            raise EppInputError(
                f"«{description}» es una fecha, no un EPP. Completa el elemento entregado."
            )
        index = EPP_LOOKUP.get(description)
        if index is None:
            if description in {"guantes", "guante", "proteccion", "seguridad"}:
                raise EppInputError(
                    f"«{value}» es ambiguo. Selecciona el tipo exacto de EPP "
                    "(por ejemplo, Guantes de Cabritilla o Guantes de soldador)."
                )
            raise EppInputError(
                f"EPP no reconocido: «{value}». Usa una de las ocho opciones "
                "disponibles en el formato Excel; no se añadirá ningún elemento ficticio."
            )
        if not 1 <= amount <= 30 or quantities[index] + amount > 30:
            raise EppInputError("La cantidad del EPP «" + EPP_NAMES[index] + "» debe ser de 1 a 30.")
        quantities[index] += amount
    if not sum(quantities):
        raise EppInputError("Selecciona al menos un EPP efectivamente entregado y su cantidad.")
    return quantities


def epp_catalog() -> list[dict]:
    return [
        {"name": name, "aliases": list(EPP_ALIASES[index]), "max_quantity": 30}
        for index, name in enumerate(EPP_NAMES)
    ]
