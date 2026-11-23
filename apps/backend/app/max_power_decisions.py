"""Pure evidence-based decisions. Never equate simulations with learned model weights."""
from hashlib import sha256
import json
from math import ceil, comb

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
    # Case-level McNemar counts correlated cases from the same worksite.
    # Only a worksite-level sign test can authorize a cluster-independent gain.
    p = metrics.get("worksite_p_value")
    hints = metrics.get("real_coaching") or []
    groups = int(metrics.get("independent_worksite_groups") or 0)
    # Individual arithmetic questions within one worksite are correlated.
    # A small raw pair count alone never establishes independent evidence.
    confirmed = (bool(metrics.get("real_learning_demonstrated"))
                 and pairs >= MIN_INDEPENDENT_PAIRS and groups >= 5
                 and int(metrics.get("worksite_wins") or 0) >= 5
                 and int(metrics.get("worksite_losses") or 0) == 0
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
    elif pairs < MIN_INDEPENDENT_PAIRS or groups < 5 or p is None or float(p) > 0.05:
        code, why, next_step = "insufficient_significance", "La ganancia observada no supera el umbral de evidencia", "Obtener más casos independientes sin repetir el mismo holdout"
    elif confirmed:
        code, why, next_step = "lab_gain", "Mejora en comparación reservada; falta validar en producción", "Solicitar revisión antes de promover y medir chats posteriores"
    else:
        code, why, next_step = "not_verified", "La comparación no cumple todos los criterios de aprobación", "Revisar integridad del conjunto y criterios de seguridad"
    return {"code": code, "reason": why, "next": next_step, "holdout_pairs": pairs,
            "holdout_wins": gains, "holdout_losses": losses, "p_value": p,
            "independent_worksite_groups": groups,
            "worksite_wins": int(metrics.get("worksite_wins") or 0),
            "worksite_losses": int(metrics.get("worksite_losses") or 0),
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

QWEN_MIN_RAM_MB = 8192


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
    measured = isinstance(previous_p95_ms, (int, float)) and 0 < previous_p95_ms < 1_000_000
    # An unseen CPU-only 4B model must first establish a latency baseline on
    # eight pairs. Expand only if real measured p95 supports it.
    fast_enough = measured and previous_p95_ms < 60000
    pairs = min(12 if fast_enough and snapshot.get("available_ram_mb", 0) >= 6144
                and snapshot.get("host_cpu_percent", 100) < 45 else 8,
                available_cases // 2)
    if pairs < MIN_INDEPENDENT_PAIRS:
        raise ValueError("No hay suficientes casos reales para comparación reservada")
    p95 = previous_p95_ms if measured else 90000
    # This is a bounded ROUND budget, not the maximum MAX POWER on-time.
    # Controller may stay on indefinitely; partial rounds never claim a gain.
    minutes = max(45, min(240, ceil(pairs * 4 * p95 * 1.55 / 60000)))
    return {"cases": pairs, "cycles": 4, "minutes": minutes,
            "token_budget": max(120000, pairs * 4 * 2500),
            "basis": "resource_guard_and_recorded_p95" if measured else "conservative_initial_budget"}

def spread_live_cases_by_worksite(cases: list[dict]) -> list[dict]:
    """Round-robin real worksite groups so reserved A/B uses varied sites.

    Deterministic across restarts and only reorders existing, verified records;
    never synthesizes examples, changes expected answers or invents evidence.
    """
    sites: dict[str, list[dict]] = {}
    for case in cases:
        fields = str(case.get("id", "")).split("-")
        key = fields[1] if len(fields) >= 3 and fields[0] == "live" else "unknown"
        sites.setdefault(key, []).append(case)
    ordered = []
    for index in range(max((len(group) for group in sites.values()), default=0)):
        for key in sorted(sites):
            group = sites[key]
            if index < len(group):
                ordered.append(group[index])
    return ordered

def worksite_holdout_sign_test(baseline: list[dict], candidate: list[dict]) -> dict | None:
    """Paired sign test on independent worksite clusters, not question count.

    All records must have a traceable matching evidence hash and Boolean pass
    measurement. A single absent or mismatched pair invalidates verification.
    Group independence is an assumption, not proof of deployability.
    """
    if len(baseline) != len(candidate) or not baseline:
        return None
    groups: dict[str, int] = {}
    for before, after in zip(baseline, candidate):
        before_id = str(before.get("case_id", ""))
        after_id = str(after.get("case_id", ""))
        case_before = before_id.rsplit("-c", 1)[0]
        case_after = after_id.rsplit("-c", 1)[0]
        segments = case_before.split("-")
        evidence = before.get("evidence_hash")
        if (case_before != case_after or len(segments) < 3
                or segments[0] != "live"
                or not isinstance(evidence, str) or len(evidence) < 16
                or evidence != after.get("evidence_hash")
                or type(before.get("passed")) is not bool
                or type(after.get("passed")) is not bool):
            return None
        site = segments[1]
        groups[site] = groups.get(site, 0) + int(after["passed"]) - int(before["passed"])
    wins = sum(gain > 0 for gain in groups.values())
    losses = sum(gain < 0 for gain in groups.values())
    discordant = wins + losses
    p = sum(comb(discordant, k) for k in range(wins, discordant + 1)) / (2 ** discordant) if discordant else 1.0
    return {"independent_worksite_groups": len(groups),
            "worksite_wins": wins, "worksite_losses": losses,
            "worksite_p_value": round(p, 6),
            "sign_test_method": "paired_worksite_cluster_sign_test"}
