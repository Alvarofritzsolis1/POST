#!/usr/bin/env python3
"""One-button worker for the already verified CPU 4B engine.
No DB, credentials, Docker socket, production model or Messenger data.
"""
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import sleep,time,monotonic
from uuid import UUID
from max_power_4b_control import ROOT,read,write,fresh,matches,authorized,lock,release
from probe_galancito_4b_cpu import blockers,PROFILE
from galant_cpu_lora_resources import snapshot

HOME=Path("/private/4b-probe")
RUN=PROFILE+"-conversation-v1"
STOP=False

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

def run_child(key,folder,fd):
    args=[sys.executable,"/src/scripts/probe_galancito_4b_cpu.py","--run",
          "--allow-download","--steps","10","--threads","4","--conversation-eval",
          "--output",str(folder),"--control-file",str(ROOT/"intent.json"),
          "--org",key[0],"--generation",str(key[1])]
    if (folder/"resume.json").is_file():
        args.append("--resume")
    child=subprocess.Popen(args,start_new_session=True,pass_fds=(fd,))
    start=monotonic()
    pause_since=None
    try:
        while child.poll() is None:
            current=read(folder/"latest.json")
            stage="evaluating" if current.get("status")=="reserved_evaluation" else (
                "training" if current.get("steps") else "loading")
            if STOP or intent()!=key:
                if pause_since is None:
                    pause_since=monotonic()
                status(key,"paused",folder)
                # Give the engine time to finish and atomically save a step.
                # A stale intent stops further steps at the next guard.
                if STOP or monotonic()-pause_since>35:
                    stop_child(child)
                    return "paused"
            else:
                pause_since=None
                status(key,stage,folder)
            if monotonic()-start>7200:
                stop_child(child)
                return "failed"
            sleep(2)
        current=read(folder/"latest.json")
        if child.returncode==0 and current.get("status")=="completed":
            return "completed"
        return "paused" if pause_since is not None or intent()!=key or current.get("status")=="paused" else "failed"
    finally:
        stop_child(child)

def main():
    signal.signal(signal.SIGTERM,stop_signal)
    signal.signal(signal.SIGINT,stop_signal)
    while not STOP:
        key=intent()
        if key is None:
            sleep(2)
            continue
        folder=HOME/key[0]/RUN
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        state_path=folder/"worker.json"
        state=read(state_path)
        report=read(folder/"latest.json")
        if report.get("status")=="completed" and report.get("saved_adapter_step")==10 and report.get("baseline_restored") is True:
            status(key,"completed",folder)
            sleep(15)
            continue
        if state.get("failures",0)>=3:
            status(key,"retry_exhausted",folder)
            sleep(15)
            continue
        if time()<state.get("retry_at",0):
            status(key,"failed",folder)
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
            outcome=run_child(key,folder,fd)
            if outcome!="failed":
                failures-=1
            write(state_path,{"failures":failures,"retry_at":time()+30 if outcome=="paused" else (time()+300 if outcome=="failed" else 0)})
            status(key,outcome,folder)
        finally:
            release(fd)
        sleep(2)

if __name__=="__main__":
    main()
