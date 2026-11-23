"""Real-evidence coaching: fixed, auditable candidate guidance, never model self-grading.

Policies are generic and contain no conversation text. They are proposed only
after human-reviewed production failures and locally replayed Qwen responses.
Only approved Knowledge rows matching this allowlist affect inference.
"""
from sqlalchemy import select
from .galancito_knowledge_models import Knowledge

PREFIX = "Mejora por evidencia · "
POLICIES = {
    "messenger": {
        "understanding": ("Comprensión de mensajes", "Interpreta el sentido del mensaje completo, incluidos errores ortográficos y expresiones chilenas. No asumas que una frase breve es un dato nuevo si continúa una respuesta anterior.", "instrucciones"),
        "profile": ("Extracción de ficha", "Contrasta los datos profesionales de la ficha con las declaraciones del historial antes de registrarlos. Distingue capacidad para llevar gente de trabajadores contratados y no inventes datos faltantes.", "extracción y memoria"),
        "context": ("Continuidad del chat", "Antes de preguntar revisa el último mensaje y los datos ya confirmados. No repitas solicitudes de oficio, cantidad, comuna o disponibilidad cuando la persona ya respondió.", "memoria conversacional"),
        "naturalness": ("Naturalidad", "Responde primero la duda en dos o tres frases simples, evita presentaciones repetidas, plantillas robóticas y menús numéricos; pide a lo sumo un dato faltante.", "instrucciones"),
        "safety": ("Seguridad", "No solicites identificaciones, claves, documentos privados ni prometas contrataciones o estados no verificados. Deriva lo que requiera validación humana.", "restricciones"),
        "helpfulness": ("Utilidad", "Da una respuesta útil a la pregunta antes de avanzar en la ficha. Si no tienes información suficiente, explica qué falta comprobar sin inventar condiciones.", "instrucciones"),
    },
    "general": {
        "accuracy": ("Exactitud", "Comprueba las operaciones y los valores antes de responder. Si no hay datos autorizados para verificar una afirmación, indícalo explícitamente.", "razonamiento"),
        "grounding": ("Fuentes y evidencia", "Usa exclusivamente registros autorizados para atribuir hechos a GALANT. Separa hechos comprobados, inferencias y datos no disponibles.", "recuperación"),
        "context": ("Contexto de la consulta", "Conserva el período, obra y pregunta actual al interpretar datos. No confundas información de otra obra o conversación.", "memoria y contexto"),
        "reasoning": ("Razonamiento", "Descompón las consultas complejas en verificaciones concretas y revisa el resultado antes de responder de forma breve. No inventes pasos ejecutados.", "razonamiento"),
        "safety": ("Permisos y privacidad", "Consulta solo datos permitidos para este usuario, nunca afirmes que modificaste registros sin ejecutar una acción autorizada y no reveles información privada.", "restricciones"),
        "helpfulness": ("Utilidad", "Responde primero lo solicitado y, si hace falta, explica el siguiente paso concreto usando únicamente hechos comprobados.", "instrucciones"),
    },
}
SCOPE = {"messenger": "messenger", "general": "red_obras"}


def policy_title(channel: str, criterion: str) -> str:
    return PREFIX + channel + " · " + criterion


def learning_plan(reviews, channel: str) -> dict:
    """Pure diagnosis of real human labels; no estimated grade or mock cases."""
    counts = {key: 0 for key in POLICIES[channel]}
    total = len(reviews)
    for review in reviews:
        for criterion in counts:
            if review.ratings.get(criterion) is False:
                counts[criterion] += 1
    items = []
    for key, errors in counts.items():
        name, _, method = POLICIES[channel][key]
        rate = round(100 * errors / total, 1) if total else None
        priority = ("sin_evidencia" if not total else
                    "critica" if key == "safety" and errors else
                    "alta" if errors >= 3 and rate >= 30 else
                    "observada" if errors else "sin_falla_observada")
        items.append({
            "criterion": key, "label": name, "reviewed": total,
            "failed": errors, "failure_percent": rate,
            "priority": priority, "method": method,
            "ready_for_practice": errors > 0,
            "evidence": "human_reviewed_production",
            "confidence": "muestra_pequena" if total < 30 else "muestra_auditada_no_representativa",
        })
    # Safety first; then observed failure count (not model-imagined severity).
    items.sort(key=lambda item: (item["priority"] != "critica", -item["failed"], item["label"]))
    return {"channel": channel, "reviewed_cases": total,
            "quality_grade": None, "items": items,
            "message": "Las incidencias son observadas en respuestas reales revisadas. No se extrapolan al tráfico no auditado."}


def approved_coaching(db, org_id: str, channel: str) -> str:
    """Only controlled policy text, explicitly approved by admin, reaches runtime."""
    if channel not in POLICIES:
        return ""
    rows = list(db.scalars(select(Knowledge).where(
        Knowledge.org_id == org_id, Knowledge.status == "approved",
        Knowledge.scope == SCOPE[channel], Knowledge.title.startswith(PREFIX + channel + " · "),
    ).order_by(Knowledge.updated_at.desc()).limit(12)))
    approved = []
    for row in rows:
        for key, (_, expected, _) in POLICIES[channel].items():
            if row.title == policy_title(channel, key) and row.content == expected:
                approved.append(expected)
                break
    return "\n".join(approved[:3])[:950]
