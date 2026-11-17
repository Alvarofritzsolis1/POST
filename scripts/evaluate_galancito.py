#!/usr/bin/env python3
"""Evaluate deterministic understanding with synthetic inputs; no network/LLM."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/backend"))
from app.galancito_triage import analyze, quick_reply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads((ROOT / "apps/backend/tests/fixtures/galancito_evaluation.json").read_text())
    results = []
    for case in cases:
        actual = asdict(analyze(case["message"]))
        checks = {name: actual[name] == case[name]
                  for name in ("intent", "specialty", "entity_type", "workers") if name in case}
        reply = quick_reply(case["message"])
        checks["one_question"] = not reply or reply.count("?") <= 1
        checks["bounded_reply"] = not reply or len(reply) <= 650
        results.append({"id": case["id"], "message": case["message"], "expected": case,
                        "actual": actual, "reply": reply, "checks": checks, "passed": all(checks.values())})
    report = {"type": "deterministic understanding, not LLM quality evaluation",
              "total": len(results), "passed": sum(r["passed"] for r in results), "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f'{report["passed"]}/{report["total"]} cases passed')
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
