"""Time series from completed, bounded experiments; never an invented knowledge score."""
from math import isfinite

from .galancito_model_config import QWEN_2B

RESOURCE_EVENT = "resource_sample"
RESOURCE_KEYS = ("host_cpu_percent", "host_ram_mb", "available_ram_mb",
                 "worker_ram_mb", "disk_free_mb", "cpu_pressure_avg10",
                 "memory_pressure_avg10", "io_pressure_avg10")


def number(value):
    return value if type(value) in (int, float) and isfinite(value) and value >= 0 else None


def resource_metrics(snapshot):
    return {key: value for key in RESOURCE_KEYS
            if (value := number(snapshot.get(key))) is not None}


def general_series(events):
    """One point per distinct completed dataset. Partial runs cannot earn points."""
    points, seen = [], set()
    for event in events:
        e = event.evidence or {}
        key = e.get("dataset_hash")
        pairs = e.get("holdout_pairs")
        a, b = number(e.get("holdout_baseline_rate")), number(e.get("holdout_candidate_rate"))
        if (not isinstance(key, str) or not key or key in seen or e.get("source") != "real_db_aggregate"
                or e.get("round_state") != "completed" or type(pairs) is not int or pairs < 8
                or a is None or b is None or a > 1 or b > 1):
            continue
        seen.add(key)
        points.append({"at": event.created_at, "baseline": round(100*a, 2),
                       "candidate": round(100*b, 2), "delta": round(100*(b-a), 2),
                       "pairs": pairs, "gains": number(e.get("holdout_wins")),
                       "regressions": number(e.get("holdout_losses")),
                       "lab_verified": e.get("lab_verified") is True})
    return points


def messenger_series(trials):
    """First measured comparison per source/criterion; never count synthetic or duplicate variants."""
    points, seen = [], set()
    before = after = gains = regressions = safety = 0
    columns = {"context":"context_pass", "understanding":"answer_priority_check",
               "naturalness":"naturalness_check", "safety":"safety_check"}
    for trial in trials:
        m = trial.metrics or {}
        key = (trial.source_run_id, trial.criterion)
        col = columns.get(trial.criterion)
        a = (m.get("baseline") or {}).get(col)
        b = (m.get("candidate") or {}).get(col)
        if (not trial.source_run_id or key in seen or not col or trial.status != "completed"
                or m.get("auto_evaluated") is not True or not trial.completed_at
                or type(a) is not bool or type(b) is not bool):
            continue
        seen.add(key)
        before += int(a)
        after += int(b)
        gains += int(trial.outcome == "objective_gain")
        regressions += int(trial.outcome in ("objective_regression", "safety_regression"))
        safety += int(trial.outcome == "safety_regression")
        n = len(seen)
        points.append({"at":trial.completed_at, "pairs":n,
                       "observed_baseline":round(100*before/n, 2),
                       "observed_candidate":round(100*after/n, 2),
                       "preliminary":n < 8,
                       "baseline":round(100*before/n, 2) if n >= 8 else None,
                       "candidate":round(100*after/n, 2) if n >= 8 else None,
                       "delta":round(100*(after-before)/n, 2) if n >= 8 else None,
                       "gains":gains, "regressions":regressions, "safety_regressions":safety,
                       "net_cases":gains-regressions})
    return points


def cpu_event_blocks(evidence, recorded_at, now):
    """A turn request is not a running process. Keep real drain protection."""
    drain = number(evidence.get("draining_until_epoch"))
    if drain is not None and drain > now.timestamp():
        return True
    age = (now - recorded_at).total_seconds()
    return (0 <= age <= 55 and evidence.get("state") in
            {"training", "training_synthetic", "preparing_synthetic", "pausing"})


def synthetic_2b_series(trials):
    """Separate laboratory measurements: never count as real-chat quality."""
    points, seen = [], set()
    before = after = 0
    for trial in trials:
        m = trial.metrics or {}
        key = (m.get("dataset_sha256"), m.get("protocol"), m.get("case_id"))
        a = (m.get("baseline") or {}).get("understanding_check")
        b = (m.get("candidate") or {}).get("understanding_check")
        if (trial.status != "completed" or not trial.completed_at or not all(key)
                or key in seen or m.get("split") != "holdout"
                or str(m.get("model", "")).casefold() != "qwen3.5:2b-q4_k_m"
                or type(a) is not bool or type(b) is not bool):
            continue
        seen.add(key)
        before += int(a)
        after += int(b)
        n = len(seen)
        points.append({"at":trial.completed_at, "pairs":n,
                       "baseline":round(100*before/n,2),
                       "candidate":round(100*after/n,2),
                       "preliminary":True})
    return points


def latency_series(trials):
    points = []
    for trial in trials:
        m = trial.metrics or {}
        if trial.status != "completed" or not trial.completed_at:
            continue
        if str(m.get("model", "")).casefold() != "qwen3.5:2b-q4_k_m":
            continue
        for phase, key in (("reference", "before_timing_ms"), ("candidate", "after_timing_ms")):
            measured = m.get(key) or {}
            total = number(measured.get("ollama_total_ms"))
            if total is None or total <= 0:
                continue
            point = {"at":trial.completed_at, "phase":phase,
                     "total_seconds":round(total/1000,3)}
            for field in ("load_ms", "prompt_ms", "generation_ms"):
                value = number(measured.get(field))
                if value is not None:
                    point[field.replace("_ms","_seconds")] = round(value/1000,3)
            points.append(point)
    return points
