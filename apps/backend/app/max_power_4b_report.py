"""Sanitize local synthetic 4B diagnostics for the organization's dashboard."""
from math import isfinite

STAGES = {"capacity_wait","starting","running","interrupted","completed","failed","retry_exhausted","awaiting_approved_dataset"}
REPORT_STAGES = {"blocked","preflight_passed","loading","baseline_evaluation","running",
                 "candidate_evaluation","conversation_evaluation","completed","failed"}


def numeric(value):
    return value if type(value) in (int,float) and isfinite(value) and value >= 0 else None


def public_report(status, org, generation):
    if status.get("org") != org or status.get("generation") != generation:
        return None
    if status.get("stage") not in STAGES:
        return None
    report = status.get("report") or {}
    if not isinstance(report,dict):
        report = {}
    points = []
    steps = report.get("steps")
    for step in (steps if isinstance(steps,list) else [])[:10]:
        if not isinstance(step,dict) or type(step.get("step")) is not int:
            continue
        memory = step.get("memory") or {}
        if not isinstance(memory,dict):
            memory = {}
        points.append({"step":step["step"],"seconds":numeric(step.get("seconds")),
                       "loss":numeric(step.get("loss")),
                       "host_free_mb":numeric(memory.get("host_free_mb")),
                       "process_rss_mb":numeric(memory.get("process_rss_mb")),
                       "adapter_changed":step.get("adapter_changed") is True})
    comparison = report.get("conversation_validation") or {}
    if not isinstance(comparison,dict):
        comparison = {}
    measured = {k:numeric(comparison.get(k)) for k in
        ("cases","turns_per_variant","baseline_passes","candidate_passes","wins","regressions",
         "safety_failures","baseline_p50_seconds","candidate_p50_seconds",
         "baseline_p95_seconds","candidate_p95_seconds")}
    measured["rollback_output_equal"] = comparison.get("rollback_output_equal") is True
    measured["lab_pass"] = comparison.get("lab_pass") is True
    real = report.get("real_reserved_validation") or {}
    real = {k:numeric(real.get(k)) for k in ("cases","baseline_passes","candidate_passes","gains","regressions","safety_failures")} if isinstance(real,dict) and real else None
    return {"stage":status["stage"],"at":numeric(status.get("at")),
            "phase":report.get("status") if report.get("status") in REPORT_STAGES else None,
            "model":"Qwen/Qwen3.5-4B","points":points,
            "data_kind":report.get("data_kind") if report.get("data_kind") in {"curated_synthetic","human_reviewed_real"} else None,
            "candidate_status":report.get("candidate_status") if report.get("candidate_status") in {"lab_candidate","rejected"} else None,
            "real_reserved_validation":real,
            "holdout_loss_before":numeric(report.get("holdout_loss_before")),
            "holdout_loss_after":numeric(report.get("holdout_loss_after")),
            "saved_adapter_step":numeric(report.get("saved_adapter_step")),
            "adapter_changed":report.get("adapter_changed") is True,
            "comparison":measured if comparison else None,
            "production_promoted":False,
            "scope":"isolated_4b_cpu_not_production"}
