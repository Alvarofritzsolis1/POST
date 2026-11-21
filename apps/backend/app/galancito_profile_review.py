"""Optional, local review of declared names and trades within the training lab."""
import re

from .galancito_triage import plain, private_data

INTRODUCTION = re.compile(
    r"^\s*[¡!]?(?i:hola|ola|buenas|wena|qu[eé]\s+tal)[,.!]\s*"
    r"(?P<statement>[Ss]oy\s+(?P<name>[A-ZÁÉÍÓÚÜÑ][^,;.!?¿¡\n]+))(?P<end>[.!]?)\s*$"
)
JOB_ROLES = {"independiente", "contratista", "maestro", "maestra", "trabajador", "trabajadora"}
CONSTRUCTION_TRADES = {
    "Excavación": ("excavaciones", "excavo", "excavador", "excavadora"),
    "Terminaciones": ("terminaciones de obra",),
    "Maquinaria": ("operador de maquinaria", "operadora de maquinaria"),
    "Obras civiles": ("obra civil",),
}


def declaration_for_review(message: str) -> str:
    """Remove a greeting that hides an explicit first-person introduction."""
    if private_data(message):
        return message
    match = INTRODUCTION.fullmatch(message)
    if match and plain(match["name"]).split()[0] not in JOB_ROLES:
        return match["statement"] + match["end"]
    return message


def reviewed_trade_aliases(approved: dict) -> dict:
    """Keep the organization dictionary first when an alias is ambiguous."""
    aliases = dict(approved)
    for trade, variants in CONSTRUCTION_TRADES.items():
        aliases[trade] = list(dict.fromkeys([*aliases.get(trade, ()), *variants]))
    return aliases
