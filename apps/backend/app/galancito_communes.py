"""Chilean communes according to SUBDERE's CUT_2018_v04 (346 entries)."""
from pathlib import Path
import re

from .galancito_triage import plain


_COMMUNES = {plain(name): name for name in
             Path(__file__).with_name("comunas_chile.txt").read_text(encoding="utf-8").splitlines()}
_ALIASES = {
    "conce": "Concepción", "talcawano": "Talcahuano", "talca huano": "Talcahuano",
    "stgo": "Santiago", "pto montt": "Puerto Montt", "valpo": "Valparaíso",
}
_NAMES = {**_COMMUNES, **_ALIASES}
_PATTERN = re.compile(r"\b(?:" + "|".join(
    re.escape(name) for name in sorted(_NAMES, key=len, reverse=True)
) + r")\b")


def commune_mentions(value: str):
    """Return literal spans and canonical commune names in normalized text."""
    return ((match, _NAMES[match[0]]) for match in _PATTERN.finditer(value))


def find_communes(text: str) -> list[str]:
    return list(dict.fromkeys(name for _, name in commune_mentions(plain(text))))
