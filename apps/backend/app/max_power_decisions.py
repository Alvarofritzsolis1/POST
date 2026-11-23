"""Pure evidence-based decisions. Never equate simulations with learned model weights."""
from hashlib import sha256
import json
from math import ceil

MIN_INDEPENDENT_PAIRS = 8

def evidence_fingerprint(cases):
    """Stable over time and across restarts; never includes chat content."""
    # Avoid comparing unorderable dicts in tuple tie-breakers.
    records = sorted(json.dumps((str(case["id"]), case["category"],
                      case["question"], case["expected"], case["formula"],
                      case["evidence"]["agregados_reales"]),
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                     for case in cases)
    return sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()

def classify_outcome(metrics: dict) -> dict:
    gains = int(metrics.get("real_holdout_gain_cases") or 0)
    losses = int(metrics.get("real_holdout_regressions") or 0)
    pairs = int(metrics.get("real_holdout_paired_cases") or 0)
    p = metrics.get("real_holdout_one_sided_p_value")
    hints = metrics.get("real_coaching") or []
    groups = int(metrics.get("independent_worksite_groups") or 0)
    # Individual arithmetic questions within one worksite are correlated.
    # A small raw pair count alone never establishes independent evidence.
    confirmed = (bool(metrics.get("real_learning_demonstrated"))
                 and pairs >= MIN_INDEPENDENT_PAIRS and groups >= 3
                 and gains >= 5 and losses == 0 and bool(hints)
                 and isinstance(p, (int, float)) and 0 <= p <= 0.05)
    if not pairs:
        code, why, next_step = "no_holdout", "No terminó la comparación reservada", "Revisar errores y capacidad antes de repetir"
    elif losses:
        code, why, next_step = "regression", "La candidata empeoró casos reservados", "Descartar la estrategia y revisar la causa del error"
    elif not hints:
        code, why, next_step = "no_correction", "No se generó una corrección aplicable a los errores", "Inspeccionar reglas, datos o recuperación de contexto"
    elif not gains:
        code, why, next_step = "plateau", "Las correcciones no resolvieron casos reservados adicionales", "Cambiar de estrategia o ampliar evidencia real"
    elif pairs < MIN_INDEPENDENT_PAIRS or groups < 3 or p is None or float(p) > 0.05:
        code, why, next_step = "insufficient_significance", "La ganancia observada no supera el umbral de evidencia", "Obtener más casos independientes sin repetir el mismo holdout"
    elif confirmed:
        code, why, next_step = "lab_gain", "Mejora en comparación reservada; falta validar en producción", "Solicitar revisión antes de promover y medir chats posteriores"
    else:
        code, why, next_step = "not_verified", "La comparación no cumple todos los criterios de aprobación", "Revisar integridad del conjunto y criterios de seguridad"
    return {"code": code, "reason": why, "next": next_step, "holdout_pairs": pairs,
            "holdout_wins": gains, "holdout_losses": losses, "p_value": p,
            "independent_worksite_groups": groups,
            "lab_verified": confirmed, "production_verified": False,
            "method": "instrucciones_locales_sobre_agregados_reales",
            "weights_changed": False}

def latency_diagnosis(timing: dict) -> dict:
    """Use native Ollama timings, not fabricated service times."""
    if not timing:
        return {"code": "no_latency_evidence", "reason": "Sin suficientes mediciones reales de Ollama"}
    components = {"load_ms": "Carga del modelo", "prompt_ms": "Procesamiento del contexto",
                  "generation_ms": "Generación", "transport_ms": "Transporte/espera"}
    known = {key: float(timing[key]) for key in components if isinstance(timing.get(key), (int, float)) and timing[key] >= 0}
    if not known:
        return {"code": "no_latency_evidence", "reason": "Sin descomposición de latencia verificable"}
    worst = max(known, key=known.get)
    return {"code": worst, "reason": components[worst], "measured_ms": round(known[worst], 2),
            "suggestion": {"load_ms": "Revisar recarga y memoria residente",
                           "prompt_ms": "Reducir contexto redundante sin perder hechos",
                           "generation_ms": "Revisar presupuesto de tokens, cuantización y CPU",
                           "transport_ms": "Inspeccionar cola y latencia del servicio"}[worst]}

def priority_from_reviews(reviews):
    """Priority reflects observed deficits; never pretends to know truth from unlabelled chat."""
    scores = []
    for row in reviews:
        ratings = getattr(row, "ratings", {}) or {}
        for criterion, value in ratings.items():
            if value is False:
                scores.append((getattr(row, "channel", "unknown"), criterion))
    counts = {}
    for key in scores:
        counts[key] = counts.get(key, 0) + 1
    return [{"channel": channel, "criterion": criterion, "failures": count}
            for (channel, criterion), count in sorted(counts.items(), key=lambda pair: -pair[1])][:6]

def can_run(snapshot: dict, *, messenger_pending=False):
    if messenger_pending:
        return False, "Messenger tiene prioridad sobre MAX POWER"
    available = snapshot.get("available_ram_mb")
    cpu = snapshot.get("host_cpu_percent")
    disk = snapshot.get("disk_free_mb")
    if available is None or available < 3072:
        return False, "RAM insuficiente o no medible para inferencia segura"
    if cpu is None or cpu >= 70:
        return False, "CPU ocupada o sin medición confiable"
    if snapshot.get("cpu_pressure_avg10", 0) > 25:
        return False, "Procesos esperando CPU; inferencia de prueba suspendida"
    if snapshot.get("memory_pressure_avg10", 0) > 5:
        return False, "Presión real de memoria; reserva protegida"
    if snapshot.get("io_pressure_avg10", 0) > 8:
        return False, "Demasiados procesos esperando disco"
    if disk is None or disk < 2048:
        return False, "Disco insuficiente o sin medición"
    return True, None

def select_experiment_plan(snapshot: dict, available_cases: int, previous_p95_ms=None) -> dict:
    """Select cases and bounded round budget from current capacity and observed speed."""
    pairs = min(12 if snapshot.get("available_ram_mb", 0) >= 6144
                and snapshot.get("host_cpu_percent", 100) < 45 else 8,
                available_cases // 2)
    if pairs < MIN_INDEPENDENT_PAIRS:
        raise ValueError("No hay suficientes casos reales para comparación reservada")
    p95 = previous_p95_ms if isinstance(previous_p95_ms, (int, float)) and previous_p95_ms > 0 else 30000
    minutes = max(30, min(180, ceil(pairs * 4 * p95 * 1.8 / 60000)))
    return {"cases": pairs, "cycles": 4, "minutes": minutes,
            "token_budget": max(120000, pairs * 4 * 2500),
            "basis": "resource_guard_and_recorded_p95" if previous_p95_ms else "conservative_initial_budget"}
