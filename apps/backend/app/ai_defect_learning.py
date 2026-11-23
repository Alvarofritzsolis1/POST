"""Real-evidence coaching: fixed, auditable candidate guidance, never model self-grading.

Policies are generic and contain no conversation text. They are proposed only
after human-reviewed production failures and locally replayed Qwen responses.
Only approved Knowledge rows matching this allowlist affect inference.
"""
from sqlalchemy import select
from .galancito_knowledge_models import Knowledge
from .models import AuditEvent

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
        Knowledge.scope == SCOPE[channel],
        Knowledge.category == "Práctica real auditada",
        Knowledge.title.startswith(PREFIX + channel + " · "),
    ).order_by(Knowledge.updated_at.desc()).limit(12)))
    approved = []
    for row in rows:
        for key, (_, expected, _) in POLICIES[channel].items():
            if (row.title == policy_title(channel, key) and
                    row.content in {expected, ALTERNATIVE_POLICIES[channel][key]} and
                    db.scalar(select(AuditEvent.id).where(
                        AuditEvent.org_id == org_id,
                        AuditEvent.resource_id == row.id,
                        AuditEvent.action == "ai.real_learning.proposed",
                    )) is not None):
                approved.append(row.content)
                break
    return "\n".join(approved[:3])[:950]


# Different interventions, not synthetic conversation/answers. The model must
# execute each alternative against a human-audited original exchange.
ALTERNATIVE_POLICIES = {
    "messenger": {
        "understanding": "Resume mentalmente la intención del último mensaje y relaciona respuestas cortas con la pregunta previa; responde a la intención confirmada sin asumir otra.",
        "profile": "Antes de agregar un campo a la ficha, identifica la frase exacta donde la persona lo declaró. Si no lo declaró, mantenlo pendiente y no lo deduzcas.",
        "context": "Revisa en orden los últimos turnos y los datos profesionales confirmados; si ya existe un dato, avanza a lo pendiente, sin volver a preguntarlo.",
        "naturalness": "Usa palabras cotidianas de Chile y una respuesta corta y pertinente; evita saludo repetitivo y una segunda pregunta si la primera consulta ya quedó resuelta.",
        "safety": "Prioriza privacidad y no promesas: si falta confirmación administrativa, indica que está pendiente. Nunca pidas identificaciones ni credenciales por chat.",
        "helpfulness": "Entrega primero el dato o instrucción concreta solicitada. Solo pregunta por un detalle adicional si realmente impide avanzar.",
    },
    "general": {
        "accuracy": "Comprueba números y operaciones solo sobre las evidencias aportadas. Si la consulta no proporciona valores verificables, explica el límite antes de concluir.",
        "grounding": "Distingue cada dato verificado por GALANT de las deducciones. No presentes una deducción como consulta efectuada a la base de datos.",
        "context": "Antes de analizar, conserva explícitamente obra, período y rol solicitados y evita combinar conjuntos de datos de ámbitos diferentes.",
        "reasoning": "Evalúa las relaciones entre hechos verificables, revisa contradicciones y entrega una conclusión concisa sin afirmar acciones no realizadas.",
        "safety": "Nunca divulgues registros de otra organización o usuario ni afirmes que hiciste cambios. Deriva operaciones que necesitan permisos o aprobación.",
        "helpfulness": "Entrega una recomendación accionable basada en la evidencia y una limitación clara cuando falte un dato crítico.",
    },
}
VARIANTS = ("focused", "alternative")
REPLAY_LIMIT_PER_CRITERION = 4
MIN_HOLDOUT_WINS = 4


def candidate_policy(channel: str, criterion: str, variant: str) -> str:
    """Allowlist: replay cannot inject arbitrary model-generated instructions."""
    if channel not in POLICIES or criterion not in POLICIES[channel] or variant not in VARIANTS:
        raise ValueError("Corrección experimental no permitida")
    return (POLICIES[channel][criterion][1] if variant == "focused"
            else ALTERNATIVE_POLICIES[channel][criterion])


def diagnostic_route(run, criterion: str) -> dict:
    """A route-based hypothesis; never pretend a trace proves cognitive causality."""
    if run is None:
        return {"source": "sin_traza", "hypothesis": "causa_desconocida",
                "mechanism": "recopilar_traza", "replay_fidelity": "parcial",
                "reason": "No existe telemetría vinculada al mensaje original."}
    source = str(getattr(run, "source", "") or "")
    timings = getattr(run, "timings", {}) or {}
    if isinstance(timings, dict):
        if timings.get("context_truncated") is True:
            return {"source": source, "hypothesis": "contexto_truncado",
                    "mechanism": "reducir_contexto_o_priorizar_memoria",
                    "replay_fidelity": "parcial",
                    "reason": "La telemetría confirma que el prompt superó el máximo; falta comprobar si el recorte causó este error."}
        if (criterion == "context" and timings.get("model_requested") is True and
                timings.get("context_turns") == 0):
            return {"source": source, "hypothesis": "sin_historial_en_prompt",
                    "mechanism": "revisar_recuperacion_de_memoria", "replay_fidelity": "parcial",
                    "reason": "La telemetría confirma que no entraron turnos previos; debe revisarse la memoria."}
    if source in {"verified_local", "knowledge", "fallback", "local", "social_context", "greeting"}:
        return {"source": source, "hypothesis": "ruta_sin_modelo",
                "mechanism": "revisar_logica_o_datos", "replay_fidelity": "parcial",
                "reason": "La respuesta original no se generó mediante el mismo Qwen; un ajuste de prompt no corrige necesariamente esa ruta."}
    if source == "external_api":
        return {"source": source, "hypothesis": "modelo_externo",
                "mechanism": "revisar_proveedor", "replay_fidelity": "parcial",
                "reason": "Se utilizó otro proveedor; Qwen no reproduce el motor original."}
    return {"source": source or "desconocida",
            "hypothesis": "modelo_contexto_o_reglas",
            "mechanism": "practica_qwen_exploratoria",
            "replay_fidelity": "parcial",
            "reason": "El origen es compatible con inferencia, pero no existe instantánea completa del prompt y la ficha del turno de producción."}


def eligible_for_proposal(trials, *, min_holdout=MIN_HOLDOUT_WINS) -> dict:
    """Count distinct sources, disjoint practice/holdout, no negative outcomes.

    Human review remains exploratory; approval must still be manual.
    """
    by_variant = {}
    for trial in trials:
        if trial.outcome not in {"better", "same", "worse"}:
            continue
        if getattr(trial, "provenance", "") != "model_verified":
            continue
        variant = getattr(trial, "variant", "focused")
        if variant not in VARIANTS:
            continue
        record = by_variant.setdefault(variant, {"practice": set(), "holdout": set(), "worse": 0})
        if trial.outcome == "worse":
            record["worse"] += 1
        if (trial.outcome == "better" and
                bool(getattr(trial, "criterion_resolved", False)) and
                bool(getattr(trial, "safety_passed", False))):
            record[trial.stage if trial.stage in {"practice", "holdout"} else "practice"].add(trial.review_id)
    for variant, record in by_variant.items():
        if (len(record["practice"]) >= 2 and len(record["holdout"]) >= min_holdout
                and not (record["practice"] & record["holdout"]) and record["worse"] == 0):
            return {"ready": True, "variant": variant,
                    "practice_wins": len(record["practice"]),
                    "holdout_wins": len(record["holdout"]), "regressions": 0}
    return {"ready": False, "variant": None,
            "practice_wins": max((len(x["practice"]) for x in by_variant.values()), default=0),
            "holdout_wins": max((len(x["holdout"]) for x in by_variant.values()), default=0),
            "regressions": sum(x["worse"] for x in by_variant.values())}
