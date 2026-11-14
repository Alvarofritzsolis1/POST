"""Formato único de RUT chileno para la salida documental de GALANT.

Normalizar un RUT no modifica el dígito verificador ni convierte uno inválido
en válido. La validación del módulo laboral sigue siendo independiente.
"""
from __future__ import annotations

import re


def is_rut_field(field: str) -> bool:
    return field.endswith(".rut") or field.endswith("_rut")


def format_rut(value: object) -> str:
    """Devuelve XX.XXX.XXX-DV para un RUT completo; conserva entradas inválidas.

    No se infiere un dígito verificador ausente: la capa de validación debe
    rechazar datos inválidos antes de emitir los documentos.
    """
    raw = str(value).strip() if value is not None else ""
    compact = re.sub(r"[.\-\s]", "", raw).upper()
    if not re.fullmatch(r"\d{7,8}[\dK]", compact):
        return raw
    digits, dv = compact[:-1], compact[-1]
    groups: list[str] = []
    while digits:
        groups.append(digits[-3:])
        digits = digits[:-3]
    return ".".join(reversed(groups)) + "-" + dv
