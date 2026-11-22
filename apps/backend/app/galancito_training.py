"""Scheduling, metrics and resource limits shared by the admin API and worker."""
from datetime import datetime, timedelta
import os
from pathlib import Path
from math import ceil, sqrt
import shutil
import subprocess
from zoneinfo import ZoneInfo

from .galancito_memory import aware
from .galancito_training_eval import WEIGHTS
from .galancito_internal_training import INTERNAL_WEIGHTS

CHILE = ZoneInfo("America/Santiago")
LEASE_SECONDS = 180
LOCAL_CONTEXT_LIMIT = 2048
LOCAL_OUTPUT_LIMIT = 140
DETAIL_DAYS = 30
HISTORY_DAYS = 180
WORKER_STALE_SECONDS = 150


def eligible_at(config: dict, now: datetime) -> datetime:
    """Apply the civil clock across Chilean seasonal time changes."""
    if not config["night"]:
        return now
    start, end = config["night_start"], config["night_end"]
    current = now
    for _ in range(26 * 60):
        hour = current.astimezone(CHILE).hour
        inside = start <= hour < end if start < end else hour >= start or hour < end
        if inside:
            return current
        current = current.replace(second=0, microsecond=0) + timedelta(minutes=1)
    raise ValueError("Ventana nocturna inválida")


def case_confidence(passed: int, count: int) -> list[float] | None:
    if not count:
        return None
    z = 1.96
    probability = passed / count
    denominator = 1 + z**2 / count
    center = (probability + z**2 / (2 * count)) / denominator
    margin = z * sqrt(probability * (1 - probability) / count + z**2 / (4 * count**2)) / denominator
    return [round(max(0, center - margin), 4), round(min(1, center + margin), 4)]


def inference_percentile_ms(samples: list[float], percentile: float) -> float | None:
    """Nearest-rank percentile of measured turns, never an estimated result."""
    values = sorted(float(sample) for sample in samples
                    if isinstance(sample, (int, float)) and sample >= 0)
    if not values:
        return None
    index = max(0, min(len(values) - 1, ceil(percentile * len(values)) - 1))
    return round(values[index], 1)


def summarize(metrics: dict, profile: str = "postulantes") -> dict:
    turns = metrics.get("turns", 0)
    fields = metrics.get("fields", 0)
    questions = metrics.get("questions", 0)
    dimensions = metrics.get("dimensions", {})
    weights = INTERNAL_WEIGHTS if profile == "interno" else WEIGHTS
    denominators = {key: turns for key in weights}
    if profile != "interno":
        denominators["naturalness"] = metrics.get("judged_turns", 0)
    ratios = {key: round(dimensions.get(key, 0) / count, 4) if count else None
              for key, count in denominators.items()}
    measured = {key: weight for key, weight in weights.items() if ratios[key] is not None}
    score = round(100 * sum(ratios[key] * weight for key, weight in measured.items()) /
                  sum(measured.values()), 2) if measured else None
    samples = metrics.get("ollama_timing_samples", 0)
    timing_totals = metrics.get("ollama_timing_totals", {})
    measured_ollama = {
        key: round(value / samples, 2) for key, value in timing_totals.items()
    } if samples else None
    actual_inference = metrics.get("inference_samples_ms", [])
    cases = metrics.get("passed", 0) + metrics.get("failed", 0)
    evidence_type = metrics.get("evidence_type", "synthetic")
    score_basis = "weighted_dimensions"
    if profile == "interno":
        # Transparent share of fully passing cases, rather than a composite
        # which counted correlated dimensions as independent evidence.
        score = round(metrics.get("passed", 0) * 100 / cases, 2) if cases else None
        score_basis = ("verified_numeric_case_pass_rate" if evidence_type == "live_database"
                       else "synthetic_case_pass_rate")
    elif evidence_type == "live_database":
        score = round(metrics.get("passed", 0) * 100 / cases, 2) if cases else None
        score_basis = "verified_numeric_case_pass_rate"
    return {
        "case_pass_interval_95": case_confidence(metrics.get("passed", 0), cases),
        "passed": metrics.get("passed", 0), "failed": metrics.get("failed", 0),
        "turns": turns, "fields": fields, "correct_fields": metrics.get("correct_fields", 0),
        "profile_accuracy": round(metrics.get("correct_fields", 0) / fields, 4) if fields else None,
        "dimensions": ratios, "score": score, "score_basis": score_basis,
        "cycles": metrics.get("cycles", {}), "early_stop": metrics.get("early_stop"),
        "questions": questions, "repeated_questions": metrics.get("repeated_questions", 0),
        "repetition_rate": round(metrics.get("repeated_questions", 0) / questions, 4) if questions else None,
        "pending_prompt_repeats": metrics.get("pending_repeats"),
        "reply_sources": metrics.get("reply_sources"),
        "critical": metrics.get("critical", 0), "error_counts": metrics.get("errors", {}),
        "judged_cases": metrics.get("judged_cases", 0), "judged_turns": metrics.get("judged_turns", 0),
        "average_latency_ms": round(metrics.get("latency_ms", 0) / turns, 1) if turns else None,
        "inference_p50_ms": inference_percentile_ms(actual_inference, 0.5),
        "inference_p95_ms": inference_percentile_ms(actual_inference, 0.95),
        "inference_samples": len(actual_inference),
        "inference_sample_window": "latest_512_turns",
        "ollama_timing_samples": samples,
        "ollama_timing_avg": measured_ollama,
        "input_tokens": metrics.get("input_tokens", 0), "output_tokens": metrics.get("output_tokens", 0),
        "reserved_tokens": metrics.get("reserved_tokens", 0),
        "estimated_cost_usd": round(metrics.get("cost", 0), 6),
        "reserved_cost_usd": round(metrics.get("reserved_cost_usd", 0), 6),
        "elapsed_seconds": round(metrics.get("elapsed_seconds", 0), 1),
        "evidence_type": metrics.get("evidence_type", "synthetic"),
        "synthetic_coaching": metrics.get("synthetic_coaching", []),
        "synthetic_category_coaching": metrics.get("synthetic_category_coaching", []),
        "synthetic_coached_cases": metrics.get("synthetic_coached_cases", 0),
        "real_coaching": metrics.get("real_coaching", []),
        "messenger_coaching_count": len(metrics.get("messenger_coaching", [])),
        "synthetic_holdout_baseline_rate": metrics.get("synthetic_holdout_baseline_rate"),
        "synthetic_holdout_candidate_rate": metrics.get("synthetic_holdout_candidate_rate"),
        "synthetic_holdout_gains": metrics.get("synthetic_holdout_gains"),
        "synthetic_holdout_regressions": metrics.get("synthetic_holdout_regressions"),
        "synthetic_improvement_observed": metrics.get("synthetic_improvement_observed", False),
        "real_learning_demonstrated": metrics.get("real_learning_demonstrated", False),
        "real_holdout_pass_rate": metrics.get("real_holdout_pass_rate"),
        "real_holdout_baseline_pass_rate": metrics.get("real_holdout_baseline_pass_rate"),
        "real_holdout_gain_cases": metrics.get("real_holdout_gain_cases"),
        "real_holdout_paired_cases": metrics.get("real_holdout_paired_cases"),
        "real_holdout_one_sided_p_value": metrics.get("real_holdout_one_sided_p_value"),
        "real_holdout_observed_gain": metrics.get("real_holdout_observed_gain", False),
        "real_holdout_regressions": metrics.get("real_holdout_regressions"),
        "peak_worker_ram_mb": metrics.get("peak_worker_ram_mb"),
        "peak_host_cpu_percent": metrics.get("peak_host_cpu_percent"),
    }


def round_view(row):
    return {"id": row.id, "state": row.state, "reason": row.reason, "target": row.target,
            "completed": row.completed, "previous_id": row.previous_id, "created_at": aware(row.created_at),
            "finished_at": aware(row.finished_at), "next_at": aware(row.next_at), "leased": bool(row.lease),
            "dataset_hash": row.dataset_hash, "system_version": row.system_version,
            "prompt_version": row.prompt_version,
            "knowledge_version": [{"id": item["id"], "version": item["version"]} for item in row.knowledge],
            "config": row.config, "metrics": summarize(row.metrics, row.config.get("profile", "postulantes"))}


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def _number(path):
    value = _read(path)
    return int(value) if value.isdecimal() else None


def _cpu_ticks():
    first = _read("/proc/stat").splitlines()
    if not first or not first[0].startswith("cpu "):
        return None
    ticks = [int(t) for t in first[0].split()[1:9]]
    return sum(ticks), ticks[3] + ticks[4]


class ResourceSampler:
    def __init__(self):
        self.previous_cpu = _cpu_ticks()
        self.gpu = None
        self.gpu_checked = False

    def sample(self):
        mem = dict(line.split(":", 1) for line in _read("/proc/meminfo").splitlines() if ":" in line)
        def mem_mb(key):
            return int(mem[key].split()[0]) // 1024 if key in mem else None
        limit = _number("/sys/fs/cgroup/memory.max")
        current = _number("/sys/fs/cgroup/memory.current")
        memory_stats = dict(line.split(maxsplit=1) for line in _read("/sys/fs/cgroup/memory.stat").splitlines())
        inactive_file = int(memory_stats.get("inactive_file", 0))
        working_set = max(0, current - inactive_file) if current is not None else None
        cpu_max = _read("/sys/fs/cgroup/cpu.max").split()
        cores = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
        if len(cpu_max) == 2 and cpu_max[0].isdecimal():
            cores = min(cores or 1, int(cpu_max[0]) / int(cpu_max[1]))
        ticks = _cpu_ticks()
        cpu = None
        if ticks and self.previous_cpu and ticks[0] > self.previous_cpu[0]:
            cpu = round(100 * (1 - (ticks[1] - self.previous_cpu[1]) / (ticks[0] - self.previous_cpu[0])), 1)
        self.previous_cpu = ticks
        if not self.gpu_checked:
            self.gpu_checked = True
            if binary := shutil.which("nvidia-smi"):
                try:
                    output = subprocess.run([binary, "--query-gpu=name,memory.total",
                                             "--format=csv,noheader,nounits"], capture_output=True,
                                            text=True, timeout=2, check=True).stdout
                    self.gpu = [{"name": field.rsplit(",", 1)[0], "vram_mb": int(field.rsplit(",", 1)[1])}
                                for field in output.splitlines()]
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
        disk = shutil.disk_usage("/")
        return {"host_ram_mb": mem_mb("MemTotal"), "available_ram_mb": mem_mb("MemAvailable"),
                "worker_ram_mb": working_set // 2**20 if working_set is not None else None,
                "worker_memory_charge_mb": current // 2**20 if current is not None else None,
                "worker_ram_limit_mb": limit // 2**20 if limit is not None else None,
                "host_cpu_percent": cpu, "host_cores": os.cpu_count(), "worker_cores": cores,
                "disk_free_mb": disk.free // 2**20, "gpu": self.gpu}


def resource_slots(config, snapshot, reserve_mb) -> tuple[int, str | None]:
    available = snapshot["available_ram_mb"]
    used, limit = snapshot["worker_ram_mb"], snapshot["worker_ram_limit_mb"]
    local = "ollama" in (config["model"]["id"], config["judge"]["id"], config.get("corrector", {}).get("id"))
    floor = reserve_mb + (1536 if local else 0)
    if available is None or available < floor:
        return 0, "En espera de la reserva de RAM de GALANT"
    effective_limit = min(limit or float("inf"), config["ram_limit_mb"] or float("inf"))
    if used is not None and effective_limit - used < 40:
        return 0, "En espera de memoria disponible del trabajador"
    cpu = snapshot["host_cpu_percent"]
    if cpu is not None and cpu >= config["cpu_limit_percent"]:
        return 0, "En espera de capacidad de CPU"
    if snapshot["disk_free_mb"] < 512:
        return 0, "En espera de espacio para guardar resultados"
    if (config["model"]["id"] != "guided" or config["judge"]["id"] != "rules"
            or config.get("corrector", {}).get("id", "rules") != "rules"):
        return 1, None
    cores = max(1, ceil(snapshot["worker_cores"] or 1))
    ram_slots = max(1, int((effective_limit - (used or 0)) // 40)) if effective_limit != float("inf") else 4
    return min(config["concurrency"] or 4, cores, ram_slots, 4), None
