#!/usr/bin/env python3
"""One-button worker for CPU QLoRA on Qwen3.5 2B.
No DB, credentials, Docker socket, production model or Messenger data.
"""
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import sleep,time,monotonic
from uuid import UUID
from app.max_power_2b_control import (MESSENGER_PAUSE_SECONDS, ROOT, authorized,
                                     deferred_by_messenger, lock, read, release, write)
from probe_galancito_2b_cpu import blockers,PROFILE
from galant_cpu_lora_resources import snapshot

HOME=Path("/private/2b-probe")
RUN=PROFILE+"-conversation-v2"
STOP=False
HEARTBEAT=Path("/tmp/max_power_2b_heartbeat")
STAGES = {
    "downloading_model": "downloading", "loading": "loading",
    "baseline_evaluation": "baseline", "backward_pending": "training",
    "running": "training", "reserved_evaluation": "evaluating",
}
PHASE_TIMEOUTS = {"downloading": 1800, "loading": 600, "baseline": 600}
FAILURES = {
    "downloading": "model_download", "loading": "model_load",
    "baseline": "evaluation", "training": "optimizer", "evaluating": "evaluation",
}

def stop_signal(*_):
    global STOP
    STOP=True

def intent():
    value=read(ROOT/"intent.json")
    try:
        org=str(UUID(value["org"]))
        generation=value["generation"]
        if type(generation) is not int or generation<1 or not authorized(value,org,generation):
            return None
        return org,generation
    except (ValueError,KeyError,TypeError):
        return None

def status(key,stage,folder,**extra):
    report=read(folder/"latest.json")
    write(ROOT/"status.json",{"org":key[0],"generation":key[1],"at":time(),
          "stage":stage,"report":report,**extra})

def stop_child(child):
    if child.poll() is None:
        try:
            os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()

def run_child(key,folder,fd,approved=None):
    args=[sys.executable,"/src/scripts/probe_galancito_2b_cpu.py","--run",
          "--allow-download","--steps","10","--threads","2","--conversation-eval",
          "--output",str(folder),"--control-file",str(ROOT/"intent.json"),
          "--org",key[0],"--generation",str(key[1])]
    if approved:
        args.extend(["--approved-dir",str(approved[0]),"--expected-dataset-sha256",approved[1]])
    if (folder/"resume.json").is_file():
        args.append("--resume")
    child=subprocess.Popen(args,start_new_session=True,pass_fds=(fd,))
    start=monotonic()
    phase_started = start
    phase = "loading"
    pause_since=None
    try:
        while child.poll() is None:
            HEARTBEAT.touch()
            current=read(folder/"latest.json")
            now = monotonic()
            stage = STAGES.get(current.get("status"), phase)
            if stage != phase:
                phase, phase_started = stage, now
            signal_state = read(ROOT / "intent.json")
            allowed = not STOP and authorized(signal_state, *key)
            deferred = not STOP and deferred_by_messenger(signal_state, *key)
            if allowed:
                pause_since = None
                status(key, phase, folder, phase_seconds=round(now - phase_started))
            else:
                if pause_since is None:
                    pause_since = now
                status(key, "waiting_messenger" if deferred else "paused", folder,
                       phase_seconds=round(now - pause_since))
                limit = MESSENGER_PAUSE_SECONDS if deferred else 35
                if STOP or now - pause_since >= limit:
                    stop_child(child)
                    return "paused", None
            if now - start > 7200 or (allowed and now - phase_started > PHASE_TIMEOUTS.get(phase, 7200)):
                stop_child(child)
                return "failed", "timeout"
            sleep(2)
        current=read(folder/"latest.json")
        if child.returncode==0 and current.get("status")=="completed":
            return "completed", None
        if current.get("status") in {"blocked", "memory_wait"}:
            return "awaiting_resources", None
        if pause_since is not None or intent()!=key or current.get("status")=="paused":
            return "paused", None
        return "failed", FAILURES.get(STAGES.get(current.get("failed_phase"), phase), "process_exit")
    finally:
        stop_child(child)

def main():
    signal.signal(signal.SIGTERM,stop_signal)
    signal.signal(signal.SIGINT,stop_signal)
    while not STOP:
        HEARTBEAT.touch()
        key=intent()
        if key is None:
            sleep(2)
            continue
        folder=HOME/key[0]/RUN
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        def complete(report):
            return (report.get("status")=="completed" and report.get("saved_adapter_step")==10
                    and report.get("baseline_restored") is True and
                    isinstance(report.get("conversation_validation"),dict))
        approved=None
        if complete(read(folder/"latest.json")):
            source=Path("/approved")/key[0]
            try:
                from galancito_2b_approved import approved_bundle
                bundle=approved_bundle(source,os.environ.get("GALANT_DATASET_APPROVAL_PUBLIC_KEY",""))
                digest=bundle["dataset_digest"]
            except (OSError,ValueError,TypeError,RuntimeError):
                status(key,"awaiting_approved_dataset",folder)
                sleep(15)
                continue
            approved=(source,digest)
            folder=HOME/key[0]/(RUN+"-approved-"+digest)
            folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        state_path=folder/"worker.json"
        state=read(state_path)
        report=read(folder/"latest.json")
        if complete(report):
            status(key,"completed",folder)
            sleep(15)
            continue
        if state.get("failures",0)>=3:
            status(key,"retry_exhausted",folder,failure=state.get("failure"))
            sleep(15)
            continue
        if time()<state.get("retry_at",0):
            status(key,state.get("stage") or "failed",folder,
                   failure=state.get("failure"),blockers=report.get("blockers",[]))
            sleep(5)
            continue
        reasons=blockers(snapshot(folder))
        if reasons:
            status(key,"awaiting_resources",folder,blockers=reasons)
            sleep(10)
            continue
        # Request the next exclusive turn. Controller will not start new
        # practice while the request is fresh. The OS lock prevents a race.
        write(ROOT/"request.json",{"org":key[0],"generation":key[1],"at":time()})
        fd=lock()
        if fd is None:
            status(key,"waiting_turn",folder)
            sleep(2)
            continue
        try:
            if intent()!=key:
                continue
            reasons=blockers(snapshot(folder))
            if reasons:
                status(key,"awaiting_resources",folder,blockers=reasons)
                continue
            # Durable attempt reservation before launch; interrupted sessions
            # are not failures. Checkpoint and evidence survive container restart.
            failures=state.get("failures",0)+1
            write(state_path,{"failures":failures,"retry_at":time()+300})
            status(key,"loading",folder)
            outcome,failure=run_child(key,folder,fd,approved)
            if outcome!="failed":
                failures-=1
            cooldown = {"paused": 30, "awaiting_resources": 60, "failed": 300}.get(outcome, 0)
            write(state_path,{"failures":failures,"retry_at":time()+cooldown,
                              "stage":outcome,"failure":failure})
            blockers_after_run = read(folder / "latest.json").get("blockers", [])
            status(key,outcome,folder,failure=failure,blockers=blockers_after_run)
        finally:
            release(fd)
        sleep(2)

if __name__=="__main__":
    main()
