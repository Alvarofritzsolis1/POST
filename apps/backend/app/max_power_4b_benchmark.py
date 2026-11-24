"""Controlled isolated Ollama 4B CPU benchmark, not production latency."""
from datetime import timedelta
from math import ceil, isfinite
from time import monotonic
from types import SimpleNamespace
from sqlalchemy import select

from .db import SessionLocal
from .galancito_local import MAX_POWER_ISOLATED, generate_training_text, last_timings
from .galancito_general import QWEN_4B
from .max_power_models import MaxPowerEvent, MaxPowerState
from .models import utcnow

EVENT = "4b_cpu_benchmark"
PROTOCOL = "rc2-cpu-2-vs-4-v1"
SYSTEM = ("Atiendes a contratistas de GALANT. Responde primero la consulta en español sencillo. "
          "No inventes condiciones laborales ni pidas datos privados. Máximo dos frases.")
PROMPTS = ("No cacho qué es cuadrilla, ¿me explicas?",
           "Soy maestro pintor y trabajo solo. ¿Cómo puedo postular?",
           "Ya te dije que soy carpintero. ¿Qué significa a trato?",
           "Puedo ir con dos personas, ¿hay cupo confirmado?")


def percentile(values, p):
    if not values:
        return None
    return round(sorted(values)[max(0,ceil(len(values)*p)-1)], 2)


def measured_sample(timing, answer, elapsed):
    if str(timing.get("response_model","")).casefold() != QWEN_4B.casefold() or not answer.strip():
        raise RuntimeError("Benchmark did not confirm local Qwen 4B")
    data = {"elapsed_ms": round(elapsed*1000,2)}
    for key in ("load_ms","prompt_ms","generation_ms","ollama_total_ms","prompt_eval_count","eval_count"):
        value = timing.get(key)
        if type(value) not in (int,float) or not isfinite(value) or value < 0:
            raise RuntimeError("Benchmark measurement missing")
        data[key] = value
    if data["ollama_total_ms"] <= 0 or data["prompt_eval_count"] <= 0 or data["eval_count"] <= 0:
        raise RuntimeError("Benchmark has no completed token measurements")
    return data


def summarize_pairs(pairs):
    if len(pairs) != len(PROMPTS) or any(set(p) != {2,4} for p in pairs):
        return None
    result = {"pairs":len(pairs),"scope":"isolated_ollama_fixed_prompts_same_model",
              "production_verified":False}
    for threads in (2,4):
        values = [p[threads] for p in pairs]
        result[str(threads)] = {
            "p50_ms":percentile([r["elapsed_ms"] for r in values],.5),
            "p95_ms":percentile([r["elapsed_ms"] for r in values],.95),
            "prompt_p50_ms":percentile([r["prompt_ms"] for r in values],.5),
            "tokens_generated":sum(r["eval_count"] for r in values),
            "prompt_tokens":sum(r["prompt_eval_count"] for r in values)}
    result["observed_p50_delta_ms"] = round(result["4"]["p50_ms"]-result["2"]["p50_ms"],2)
    return result


def eligible(db, org, now):
    previous = db.scalar(select(MaxPowerEvent).where(MaxPowerEvent.org_id==org,
        MaxPowerEvent.event==EVENT,MaxPowerEvent.round_id==PROTOCOL))
    return (previous is None or ((previous.evidence or {}).get("state") != "completed"
            and (previous.evidence or {}).get("retry_at_epoch",0) <= now.timestamp()))


def run_benchmark(org, generation, guard):
    """Called under the controller's shared exclusive engine lock."""
    pairs = []
    def run(prompt, threads):
        if not guard(org,generation):
            raise RuntimeError("Benchmark deferred by controller")
        cfg = SimpleNamespace(galancito_local_model=QWEN_4B,galancito_num_ctx=2048,
            galancito_num_predict=96,galancito_num_thread=threads,galancito_keep_alive="2m")
        t = monotonic()
        answer = generate_training_text(SYSTEM,prompt,42,cfg,thinking=False)
        return measured_sample(last_timings.get(),answer,monotonic()-t)
    if not MAX_POWER_ISOLATED:
        return
    try:
        # Warm-up is deliberately excluded. Alternate order across cases.
        run("Hola, ¿me puedes orientar para postular?",4)
        for i,prompt in enumerate(PROMPTS):
            pair = {}
            for threads in ((2,4) if i%2==0 else (4,2)):
                pair[threads] = run(prompt,threads)
            pairs.append(pair)
        result = summarize_pairs(pairs)
        evidence = {"state":"completed","comparison":result}
    except (RuntimeError,ValueError,OSError):
        evidence = {"state":"deferred_or_failed","pairs_completed":len(pairs),
                    "retry_at_epoch":(utcnow()+timedelta(minutes=30)).timestamp(),
                    "production_verified":False}
    with SessionLocal.begin() as db:
        row = db.get(MaxPowerState,org)
        if not row or not row.enabled or row.session_generation != generation:
            return
        event = db.scalar(select(MaxPowerEvent).where(MaxPowerEvent.org_id==org,
                    MaxPowerEvent.event==EVENT,MaxPowerEvent.round_id==PROTOCOL))
        if event is None:
            db.add(MaxPowerEvent(org_id=org,event=EVENT,round_id=PROTOCOL,
                reason="Benchmark local Qwen 4B: 2 frente a 4 hilos",evidence=evidence))
        else:
            event.evidence = evidence
            event.created_at = utcnow()
