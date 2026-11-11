"""GALANT / Proyecto Javiera: propuestas preventivas NO APROBADAS.

Las sugerencias sólo cubren huecos explícitos del XLSX fuente, respetan
todas sus filas intactas y jamás constituyen una firma del prevencionista.
Un profesional acreditado debe verificar la faena, el EPP y las HDS antes
de autorizar la matriz para impresión real.
"""
from __future__ import annotations

from .javiera_logic import normalize_cargo

ELECTRICAL_REFERENCE = (
    "ACHS, Manual de Prevención de Riesgos Eléctricos: "
    "https://www.achs.cl/docs/librariesprovider2/empresa/centro-de-fichas/"
    "documentos-esenciales/manual-prevencion-riesgos-electricos.pdf"
)
REQUIRED_SDS_FIELDS = (
    "Nombre comercial del producto utilizado",
    "Sinónimo según ficha del proveedor",
    "Fórmula o mezcla según HDS",
    "Aspecto físico",
    "Olor",
    "Modo de empleo efectivo en obra",
    "Límites de exposición según HDS",
    "Condiciones de almacenamiento",
    "EPP exigido por ficha y evaluación de riesgos",
    "Primeros auxilios según HDS",
    "Etiquetado y clasificación DS 57 vigente",
    "Otros peligros y controles declarados en HDS",
)

CARPINTERO_ROW40_DRAFT = {
    "excel_row": 40,
    "source_cargo": "CARPINTERO",
    "status": "draft_needs_on_site_preventive_review",
    "risk_suggestion": (
        "Contacto eléctrico directo o indirecto y descarga eléctrica con "
        "posibilidad de quemaduras graves o electrocución; tropiezos, golpes "
        "y caídas al mismo nivel por extensiones dispuestas en zonas de "
        "tránsito; exposición a lesiones por uso de EPP deteriorado."
    ),
    "controls_suggestion": (
        "Realizar inspección visual de extensiones, cables, enchufes, "
        "conectores y EPP antes de cada uso; retirar de servicio, identificar "
        "y reemplazar de inmediato todo elemento dañado. Canalizar o elevar "
        "cables fuera de las zonas de circulación; cuando el cruce sea "
        "inevitable, utilizar un protector de cables apto para tránsito. "
        "Usar equipos y conexiones adecuados a la faena, tierra de protección "
        "y protección diferencial cuando corresponda; evitar humedad y "
        "sobrecarga de tomas. Prohibir reparaciones eléctricas a personal no "
        "autorizado. Mantener acopio seco y ordenado y registro de inspección "
        "y reposición de EPP. Verificar en terreno la eficacia de las medidas "
        "con el responsable de prevención antes de aprobar el IRL."
    ),
    "regulatory_basis": (
        "D.S. 44 de 2024, artículo 15, y evaluación específica de la faena."
    ),
    "technical_reference": ELECTRICAL_REFERENCE,
    "disclaimer": (
        "PROPUESTA DE APOYO, NO MATRIZ APROBADA. Las consecuencias y medidas "
        "son una inferencia preventiva y no existen en E40/F40 del Excel."
    ),
}

PAISAJISTA_HDS = {
    "status": "pending_product_inventory_and_manufacturer_sds",
    "source_cargo": "PAISAJISTA",
    "source_alias_not_accepted": "PAISAJISMO (REVISAR HDS)",
    "reason": (
        "La fila parecida no demuestra que los productos del listado se "
        "utilicen en labores de paisajismo; no trasladar pinturas o solventes "
        "por coincidencia ortográfica."
    ),
    "missing_evidence": [
        "Inventario y marcas de productos efectivamente utilizados en obra",
        "Fabricante y versión/fecha de la HDS para cada producto",
        "Condiciones de uso, dilución, exposición y almacenamiento",
        "Etiquetado, compatibilidad, medidas de emergencia y EPP",
        "Validación escrita del responsable de obra y del prevencionista",
    ],
    "fields": list(REQUIRED_SDS_FIELDS),
    "template": [{"field": label, "value": None, "source": "pendiente"}
                 for label in REQUIRED_SDS_FIELDS],
    "no_chemical_use_policy": (
        "Si el cargo no manipula productos químicos, documentar inspección "
        "y declaración expresa de la obra. No suponer ausencia de exposición."
    ),
    "regulatory_basis": (
        "D.S. 44 de 2024, artículo 15; fichas de datos de seguridad "
        "y etiquetado del producto efectivamente usado."
    ),
}


def corrective_draft_for_role(cargo: str, source_rows: list[dict]) -> dict:
    """Preparar propuesta explícita, sin modificar matriz ni persistencia."""
    role = normalize_cargo(cargo)
    if role == "CARPINTERO":
        candidates = [
            row for row in source_rows
            if row.get("cargo") == "CARPINTERO" and
            row.get("excel_row") == 40 and
            str(row.get("tarea") or "").startswith(
                "Inspección, mantención y almacenamiento de EPP"
            )
        ]
        if len(candidates) == 1 and all(
            not str(candidates[0].get(field) or "").strip()
            for field in ("riesgo", "medidas")
        ):
            return {
                "type": "risk_row",
                "proposal": dict(CARPINTERO_ROW40_DRAFT),
                "source_preserved": True,
                "approval_status": "requires_independent_prevention_signoff",
            }
    elif role == "PAISAJISTA":
        return {
            "type": "chemical_inventory",
            "proposal": dict(PAISAJISTA_HDS),
            "source_preserved": True,
            "approval_status": "requires_real_sds_and_prevention_signoff",
        }
    return {"type": "none", "approval_status": "no_corrective_draft"}


def merged_draft_sections(source_rows: list[dict], proposal: dict) -> list[str]:
    """Sólo para exportación al editor manual, nunca emisión de PDF."""
    if proposal.get("type") != "risk_row":
        return []
    change = proposal["proposal"]
    output = []
    for row in sorted(source_rows, key=lambda item: item["excel_row"]):
        if row.get("cargo") != "CARPINTERO":
            continue
        risk = row["riesgo"]
        measures = row["medidas"]
        if row["excel_row"] == change["excel_row"]:
            risk = change["risk_suggestion"]
            measures = change["controls_suggestion"]
        output.append(
            "Tarea: " + row["tarea"] + "\n"
            "Peligro: " + row["peligro"] + "\n"
            "Riesgo: " + risk + "\n"
            "Medidas: " + measures
        )
    return output
