"""Sanitize local synthetic 4B diagnostics for the organization's dashboard."""
from math import isfinite

STAGES = {"capacity_wait","starting","running","interrupted","completed","failed","retry_exhausted"}
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
    for step in (report.get("steps") or [])[:10]:
        if not isinstance(step,dict) or type(step.get("step")) is not int:
            continue
        memory = step.get("memory") or {}
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
    return {"stage":status["stage"],"at":numeric(status.get("at")),
            "phase":report.get("status") if report.get("status") in REPORT_STAGES else None,
            "model":"Qwen/Qwen3.5-4B","points":points,
            "holdout_loss_before":numeric(report.get("holdout_loss_before")),
            "holdout_loss_after":numeric(report.get("holdout_loss_after")),
            "saved_adapter_step":numeric(report.get("saved_adapter_step")),
            "adapter_changed":report.get("adapter_changed") is True,
            "comparison":measured if comparison else None,
            "production_promoted":False,
            "scope":"synthetic_4b_cpu_pilot_only"}
