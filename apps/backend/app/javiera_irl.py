"""Estructuración determinista de labores, peligros, riesgos y controles IRL."""
from __future__ import annotations

import hashlib
import re

LABEL = re.compile(r"(?mi)^(Tarea|Peligro|Riesgo|Medidas?)\s*:")


def parse_irl_section(section: str, *, version: int, ordinal: int, cargo: str) -> dict:
    """Preservar la fuente original; 'Medida' y 'Medidas' son equivalentes."""
    text = str(section or "").strip()
    marks = list(LABEL.finditer(text))
    parts: dict[str, str] = {}
    for index, match in enumerate(marks):
        key = "medidas" if match.group(1).lower().startswith("medida") else match.group(1).lower()
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        value = text[match.end():end].strip()
        if key in parts:
            parts[key] += "\n" + value
        else:
            parts[key] = value
    valid = len(parts) == 4 and all(parts.get(key) for key in
                                    ("tarea", "peligro", "riesgo", "medidas"))
    stable = hashlib.sha256(f"{cargo}|{version}|{ordinal}|{text}".encode("utf-8")).hexdigest()[:20]
    return {
        "id": stable, "ordinal": ordinal,
        "labor": parts.get("tarea", ""), "peligro": parts.get("peligro", ""),
        "riesgo": parts.get("riesgo", ""), "medidas": parts.get("medidas", ""),
        "original": text, "structured": valid,
    }


def has_verified_irl_rows(sections: list[str]) -> bool:
    return bool(sections) and all(
        parse_irl_section(section, version=0, ordinal=n, cargo="")["structured"]
        for n, section in enumerate(sections, 1)
    )


def preventive_matrix_blocker(kind: str, sections: list[str] | None) -> str | None:
    """Bloqueo preventivo compartido por formularios y motor de PDF.

    Las revisiones históricas emitidas permanecen intactas: la comprobación
    se aplica al crear una nueva salida, no al abrir PDFs antiguos.
    """
    if not sections:
        return f"No existe matriz {kind} aprobada para el cargo."
    if kind == "IRL":
        if not has_verified_irl_rows(sections):
            return ("La matriz IRL aprobada tiene registros sin Tarea, Peligro, "
                    "Riesgo o Medida preventiva. Solicita una nueva revisión.")
    elif kind == "PTS":
        if len(sections) != 17 or any(not isinstance(s, str) or not s.strip() for s in sections):
            return "La matriz PTS aprobada debe contener sus 17 apartados completos."
    return None
