#!/usr/bin/env python3
"""Reproducible *isolated* Ollama benchmark. Never downloads or activates models.

Use a private QA Ollama with the same 3 GiB / 1.5 CPU limits as production.
Answers are synthetic evaluation artifacts, never Messenger history.
"""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/backend"))
from app.facebook_ai import REPLY_INSTRUCTIONS

QUESTIONS = [
    "Explica en dos frases cómo coordinar una empresa de pintura con una obra, sin confirmar cupos.",
    "Soy independiente sin empleados. Explica por qué no corresponde exigir contratos de empleados inexistentes.",
    "Redacta una orientación breve para alguien que busca empleo y no es empresa. No hay vacantes confirmadas.",
    "Ayuda a redactar una consulta a administración por requisitos de ingreso; no hay guía aprobada para esta obra.",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://galancito-ollama:11434")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container", help="Optional isolated Docker container for resource measurements")
    parser.add_argument("--baseline", default="b4feea3", help="Git baseline containing the original prompt")
    parser.add_argument("--repeats", type=int, default=2, choices=range(1, 6))
    parser.add_argument("--idle", action="store_true", help="Compare residency after 21 seconds idle for 20s, 2m and 5m")
    parser.add_argument("--compare-only", action="store_true", help="Compare baseline and final prompts on the main model, no matrices")
    args = parser.parse_args()
    raw = subprocess.check_output(["git", "show", args.baseline + ":apps/backend/app/facebook_ai.py"], cwd=ROOT, text=True)
    tree = ast.parse(raw)
    old = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "REPLY_INSTRUCTIONS" for t in n.targets))[:3300]
    report = {"baseline_commit": args.baseline, "environment": "isolated QA, not VPS",
              "questions": QUESTIONS, "runs": [], "residency": [], "model_info": {},
              "notes": ["Transport residual includes unmeasured scheduling, not independent queue timing.",
                        "Quality requires review of answers; timings alone do not justify model replacement."]}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    def request(path, payload=None, timeout=24):
        req = Request(args.url.rstrip("/") + path,
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)

    def resources():
        if not args.container:
            return None
        try:
            # cgroup memory peak captures generation peaks, including within
            # the request. CPU is a monotonic counter, sampled per request.
            result = subprocess.check_output(["docker", "exec", args.container, "sh", "-c",
                "cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak /sys/fs/cgroup/cpu.stat"], text=True, timeout=5)
            lines = result.splitlines()
            return {"ram_bytes": int(lines[0]), "ram_peak_bytes": int(lines[1]),
                    "cpu_usec": int(next(line.split()[1] for line in lines[2:] if line.startswith("usage_usec ")))}
        except (OSError, ValueError, subprocess.SubprocessError, StopIteration):
            return None

    def chat(model, prompt, question, label, *, tokens=140, keep="20s", threads=None):
        opts = {"num_ctx": 2048, "num_predict": tokens, "temperature": .3 if label == "baseline" else .2, "seed": 42}
        if threads:
            opts["num_thread"] = threads
        payload = {"model": model, "messages": [{"role": "system", "content": prompt},
                   {"role": "user", "content": question}], "stream": False, "think": False,
                   "keep_alive": keep, "options": opts}
        before, started = resources(), time.perf_counter()
        item = {"model": model, "profile": label, "question": question, "tokens_limit": tokens,
                "keep_alive": keep, "threads": threads}
        try:
            result = request("/api/chat", payload)
            item.update({"answer": result.get("message", {}).get("content"),
                         "thinking_returned": bool(result.get("message", {}).get("thinking")),
                         "done_reason": result.get("done_reason"),
                         **{key: result.get(key) for key in ("load_duration", "total_duration", "prompt_eval_duration", "eval_duration", "eval_count", "prompt_eval_count")}})
        except (OSError, ValueError, URLError) as exc:
            item["error"] = type(exc).__name__
        elapsed = time.perf_counter() - started
        item["elapsed_ms"], item["resources"] = round(elapsed * 1000, 2), resources()
        if before and item["resources"]:
            item["cpu_percent"] = round((item["resources"]["cpu_usec"] - before["cpu_usec"]) / (elapsed * 1_000_000) * 100, 1)
        report["runs"].append(item)
        save()
        print(model, label, round(elapsed, 2), "s", item.get("error", item.get("done_reason")), flush=True)
        return item

    def unload(model):
        request("/api/chat", {"model": model, "keep_alive": 0}, timeout=10)

    available = {m["name"] for m in request("/api/tags")["models"]}
    for model in ("qwen3:1.7b", "qwen3:0.6b", "granite3.3:2b"):
        if args.compare_only and model != "qwen3:1.7b":
            continue
        if model not in available:
            report["model_info"][model] = {"state": "not installed; not downloaded"}
            continue
        info = request("/api/show", {"model": model})
        report["model_info"][model] = info.get("details")
        unload(model)
        if not args.compare_only:
            chat(model, REPLY_INSTRUCTIONS, QUESTIONS[0], "cold", tokens=80, threads=1)
        for repeat in range(args.repeats):
            for question in QUESTIONS:
                if model == "qwen3:1.7b":
                    chat(model, old, question, "baseline")
                chat(model, REPLY_INSTRUCTIONS, question, "candidate", tokens=140 if args.compare_only else 80,
                     keep="2m" if args.compare_only else "20s", threads=1)
        if model == "qwen3:1.7b" and not args.compare_only:
            for tokens in (40, 60, 80, 140):
                chat(model, REPLY_INSTRUCTIONS, QUESTIONS[0], "token_matrix", tokens=tokens, threads=1)
            for threads in (1, 2):
                chat(model, REPLY_INSTRUCTIONS, QUESTIONS[0], "thread_matrix", tokens=80, threads=threads)
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(lambda _: chat(model, REPLY_INSTRUCTIONS, QUESTIONS[0], "three_concurrent", tokens=60, threads=1), range(3)))
        unload(model)
    if args.idle and "qwen3:1.7b" in available:
        model = "qwen3:1.7b"
        for keep in ("20s", "2m", "5m"):
            unload(model)
            chat(model, REPLY_INSTRUCTIONS, QUESTIONS[0], "residency_initial", tokens=60, keep=keep, threads=1)
            time.sleep(21)
            loaded = request("/api/ps")
            item = chat(model, REPLY_INSTRUCTIONS, QUESTIONS[0], "after_21s_idle", tokens=60, keep=keep, threads=1)
            report["residency"].append({"keep_alive": keep, "loaded_after_idle": bool(loaded.get("models")),
                                         "load_duration": item.get("load_duration"), "elapsed_ms": item["elapsed_ms"]})
        unload(model)
    report["summary"] = [{"model": model, "profile": profile,
                           "samples": len(items), "median_ms": median(r["elapsed_ms"] for r in items),
                           "errors": sum("error" in r for r in items)}
        for model in available for profile in ("baseline", "candidate")
        if (items := [r for r in report["runs"] if r["model"] == model and r["profile"] == profile])]
    save()


if __name__ == "__main__":
    main()
