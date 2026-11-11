"""Auditoría de integridad por cargo del IRL, sin aprobar ni mutar matrices.

No se infiere equivalencia preventiva a partir de coincidencia ortográfica.
Las cinco imágenes del Excel original siguen pendientes de transcripción y
revisión, por lo que NO se certifica paridad integral del formato.
"""
from __future__ import annotations

from collections import Counter

from .javiera_logic import normalize_cargo
from .javiera_irl_consolidation import consolidate_reference_risks, identical_variants

KINDS = ("PERFILES", "PUESTOS", "SUSTANCIAS", "PTS")
REQUIRED_FIELDS = ("tarea", "peligro", "riesgo", "medidas")
ORIGINAL_VISUAL_BLOCKS = (
    "Antecedentes generales y otras consideraciones",
    "Normas generales de seguridad: apartados 1–3",
    "Normas generales de seguridad: apartados 4–6",
    "Normas generales de seguridad: apartados 7–9",
    "Normas generales de seguridad: apartados 10–13",
)
# Estos son candidatos que debe aprobar un prevencionista. No son aliases activos.
SUGGESTED_SOURCE_EQUIVALENCES = {
    ("PAISAJISTA", "SUSTANCIAS"): ("PAISAJISMO",),
}


def audit_reference_role(cargo: str, irl_rows: list[dict],
                         related_rows: list[dict]) -> dict:
    """Retornar la auditoría y la procedencia sin alterar una sola matriz.

    Los cuatro campos técnicos se conservan unidos por excel_row; nunca
    se recorre una columna con un índice de riesgo distinto a las otras.
    """
    canonical = normalize_cargo(cargo)
    risks = sorted((row for row in irl_rows
                    if normalize_cargo(row.get("cargo")) == canonical),
                   key=lambda row: int(row["excel_row"]))
    display_risks, collapsed = consolidate_reference_risks(risks, cargo)
    ids = [int(row["excel_row"]) for row in risks]
    incomplete = [int(row["excel_row"]) for row in risks
                  if any(not str(row.get(key) or "").strip() for key in REQUIRED_FIELDS)]
    warnings: list[str] = []
    if not risks:
        warnings.append("El cargo no tiene riesgos en la referencia; no se pueden inventar.")
    if len(ids) != len(set(ids)):
        warnings.append("Existen identificadores de fila duplicados en la matriz IRL.")
    if incomplete:
        warnings.append(
            "Riesgos incompletos en filas Excel: " + ", ".join(map(str, incomplete)) +
            ". Se requiere revisión preventiva antes de aprobar."
        )
    source_numbers = Counter(str(row.get("n", "")) for row in risks)
    duplicates = sorted(number for number, count in source_numbers.items()
                        if count > 1 and number)
    if duplicates:
        warnings.append(
            "La matriz fuente repite numeración de tareas (" +
            ", ".join(duplicates) + "); conserva los registros y revisa si son bloques distintos."
        )

    linked: dict[str, dict] = {}
    for kind in KINDS:
        matches = [row for row in related_rows
                   if row.get("kind") == kind and
                   normalize_cargo(row.get("cargo")) == canonical]
        candidates = list(SUGGESTED_SOURCE_EQUIVALENCES.get((canonical, kind), ()))
        entries = [{
            "source_sheet": row["source_sheet"],
            "source_row": row["source_row"],
            "source_cargo": row["cargo"],
            "sections": list(row.get("sections", [])),
            "reference_only": True,
        } for row in matches]
        resolved = identical_variants(matches) if len(matches) > 1 else bool(matches)
        linked[kind] = {
            "match_count": len(entries),
            "source_entries": entries,
            "ambiguous": len(entries) > 1 and not resolved,
            "duplicate_identical": len(entries) > 1 and resolved,
            "resolved_source": entries[0] if resolved else None,
            "missing": not entries,
            "suggested_aliases_pending_review": candidates,
        }
        if not entries:
            explanation = (f"Falta {kind} vinculada al cargo {cargo}. "
                           "Las semejanzas entre nombres requieren aprobación.")
            if candidates:
                explanation += " Posible equivalente sin validar: " + ", ".join(candidates) + "."
            warnings.append(explanation)
        elif len(entries) > 1 and not resolved:
            warnings.append(
                f"{kind} contiene {len(entries)} filas para {cargo}. "
                "No escoger una automáticamente sin resolver la duplicidad."
            )

    # Las secciones embebidas son parte integrante del Excel entregado por el
    # usuario, pero la plantilla irl.html del motor nativo aún no las incorpora.
    # Este campo evita declarar paridad visual o documental del 100 %.
    warnings.append(
        "Los cinco bloques gráficos de antecedentes y normas generales del "
        "Excel original aún no están reconstruidos y validados en HTML editable."
    )
    return {
        "cargo": cargo,
        "risk_count": len(risks),
        "display_risk_count": len(display_risks),
        "collapsed_risk_groups": collapsed,
        "source_excel_rows": ids,
        "incomplete_excel_rows": incomplete,
        "duplicate_source_numbers": duplicates,
        "risk_records_linked_by_row": True,
        "linked": linked,
        "original_visual_blocks": [
            {"title": title, "status": "pending_html_transcription_and_review"}
            for title in ORIGINAL_VISUAL_BLOCKS
        ],
        "full_excel_parity_certified": False,
        "source_is_not_automatically_approved": True,
        "warnings": warnings,
    }
