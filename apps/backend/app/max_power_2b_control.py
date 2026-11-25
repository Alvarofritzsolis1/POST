"""Single shared lock and expiring, session-scoped 2B intent. No chat data."""
import fcntl
import json
import math
import os
from pathlib import Path
from time import time
from uuid import uuid4

from .galancito_model_config import QWEN_TRAINING_MODEL

ROOT=Path("/2b-control")
MESSENGER_PAUSE_SECONDS = 300

def read(path):
    try:
        if path.is_symlink() or path.stat().st_size>256000:
            return {}
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError,TypeError):
        return {}

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name("."+path.name+"."+uuid4().hex)
    try:
        with tmp.open("x") as stream:
            json.dump(value,stream,allow_nan=False)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)

def fresh(value,age=20,now=None):
    stamp=value.get("at")
    now=time() if now is None else now
    return type(stamp) in (float,int) and math.isfinite(stamp) and 0<=now-stamp<=age

def matches(value,org,generation):
    return value.get("org")==org and value.get("generation")==generation

def authorized(value,org,generation):
    return fresh(value) and matches(value,org,generation) and value.get("allowed") is True

def deferred_by_messenger(value, org, generation):
    return (fresh(value) and matches(value, org, generation)
            and value.get("allowed") is False
            and value.get("wait_for_messenger") is True)

def lock(root=ROOT):
    root.mkdir(parents=True,exist_ok=True)
    fd=os.open(root/"engine.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise

def release(fd):
    # Closing, not LOCK_UN, preserves exclusion if a child inherited the FD.
    if fd is not None:
        os.close(fd)

def measured_report(status):
    """No raw data, exceptions or responses enter the application database."""
    stages={"awaiting_resources","waiting_turn","downloading","loading","baseline","training",
            "evaluating","paused","waiting_messenger",
            "completed","awaiting_approved_dataset","failed","retry_exhausted"}
    stage=status.get("stage")
    if stage not in stages:
        return None
    raw=status.get("report") or {}
    if not isinstance(raw,dict):
        raw={}
    def number(value):
        return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None
    points=[]
    for item in raw.get("steps",[])[:10] if isinstance(raw.get("steps"),list) else []:
        if not isinstance(item,dict) or type(item.get("step")) is not int or not 1<=item["step"]<=10:
            continue
        if item.get("adapter_changed") is not True or not number(item.get("grad_norm")):
            continue
        points.append({k:number(item.get(k)) for k in ("step","seconds","loss","grad_norm")})
    evaluation=raw.get("conversation_validation")
    if not isinstance(evaluation,dict):
        evaluation={}
    approved_eval=raw.get("approved_reserved_validation")
    if not isinstance(approved_eval,dict):
        approved_eval={}
    out={"stage":stage,"at":status.get("at"),"generation":status.get("generation"),
        "model":QWEN_TRAINING_MODEL,"points":points,"completed_steps":len(points),
        "target_steps":10,"data_kind":raw.get("data_kind") if raw.get("data_kind") in
            ("curated_synthetic","human_reviewed_real") else "curated_synthetic",
        "production_verified":False,"production_promoted":False,
        "holdout_loss_before":number(raw.get("holdout_loss_before")),
        "holdout_loss_after":number(raw.get("holdout_loss_after")),
        "baseline_restored":raw.get("baseline_restored") is True,
        "conversation_validation":{k:number(evaluation.get(k)) for k in
            ("cases","baseline_passes","candidate_passes","regressions","safety_regressions")},
        "conversation_gate":evaluation.get("lab_pass") is True,
        "approved_reserved_validation":{k:number(approved_eval.get(k)) for k in
            ("cases","baseline_passes","candidate_passes","regressions","safety_regressions")},
        "approved_gate":approved_eval.get("gate_pass") is True,
        "phase_seconds":number(status.get("phase_seconds")),
        "failure":status.get("failure") if status.get("failure") in {
            "model_download", "model_load", "optimizer", "evaluation", "timeout", "process_exit"
        } else None,
        "blockers":[v for v in status.get("blockers",[]) if v in
            ("host_free_mb","cgroup_limit_mb","cgroup_available_mb","disk_free_mb")]}
    return out
