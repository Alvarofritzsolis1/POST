#!/usr/bin/env python3
"""Opt-in, one-button 4B synthetic neural pilot. No DB, no Docker socket.

An exclusive shared flock prevents overlapping isolated Qwen evaluation. The
controller heartbeat is the only authority to start or continue a child.
"""
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep, time
from uuid import UUID

from galant_cpu_lora_resources import snapshot
from probe_galancito_4b_cpu import blockers
from max_power_4b_slot import CONTROL, acquire_slot, atomic_json, read_json, release_slot, valid_intent

PILOT = "contractors-multiturn-v1"
ROOT = Path("/private/4b-probe")
MAX_ATTEMPTS = 3
COOLDOWN = 900


def intent():
    value = read_json(CONTROL / "intent.json")
    if not valid_intent(value):
        return None
    try:
        return (str(UUID(value["org"])), value["generation"])
    except (ValueError, TypeError):
        return None


def status(key, stage, **extra):
    atomic_json(CONTROL / "status.json", {"org":key[0],"generation":key[1],
                "at":time(),"stage":stage,**extra})


def stop_child(child):
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()


def supervise(key, folder, fd):
    # Inherit the lock FD: a surviving subprocess cannot silently free the
    # engine slot if the supervisor is terminated.
    child = subprocess.Popen([sys.executable, "/src/scripts/probe_galancito_4b_cpu.py",
        "--run","--allow-download","--steps","4","--threads","4","--conversation-eval","--resume",
        "--output",str(folder)], start_new_session=True, pass_fds=(fd,))
    started = monotonic()
    try:
        while child.poll() is None:
            report = read_json(folder / "latest.json")
            status(key, "running", report=report)
            if intent() != key or monotonic()-started > 7200:
                interrupted = intent() != key
                stop_child(child)
                status(key, "interrupted" if interrupted else "failed", report=read_json(folder / "latest.json"))
                return "interrupted" if interrupted else "failed"
            sleep(2)
        report = read_json(folder / "latest.json")
        ok = child.returncode == 0 and report.get("status") == "completed"
        status(key, "completed" if ok else "failed", report=report)
        return "completed" if ok else "failed"
    finally:
        stop_child(child)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    waiting_since = None
    waiting_key = None
    while True:
        key = intent()
        if key is None:
            waiting_since = waiting_key = None
            sleep(2)
            continue
        org, generation = key
        folder = ROOT / org / PILOT
        folder.mkdir(parents=True, exist_ok=True)
        state_path = folder / "supervisor.json"
        state = read_json(state_path)
        if state.get("completed") or int(state.get("attempts",0)) >= MAX_ATTEMPTS:
            status(key, "completed" if state.get("completed") else "retry_exhausted",
                   report=read_json(folder / "latest.json"))
            sleep(30)
            continue
        if time() < float(state.get("retry_at",0)):
            sleep(5)
            continue
        if waiting_key != key:
            waiting_key, waiting_since = key, monotonic()
        if monotonic()-waiting_since > 150:
            atomic_json(state_path,{**state,"retry_at":time()+COOLDOWN})
            status(key,"capacity_wait",blockers=blockers(snapshot(folder)))
            waiting_since = waiting_key = None
            continue
        # Bounded request lets the isolated Ollama expire its warm model.
        atomic_json(CONTROL / "request.json", {"org":org,"generation":generation,"at":time()})
        fd = acquire_slot()
        if fd is None:
            sleep(1)
            continue
        try:
            if intent() != key:
                continue
            reasons = blockers(snapshot(folder))
            if reasons:
                status(key,"capacity_wait",blockers=reasons)
                sleep(2)
                continue
            # Count each actual launch before starting, so a restart cannot
            # cause unbounded retries. No repeat of a completed fixed corpus.
            state = {"attempts":int(state.get("attempts",0))+1,"retry_at":time()+COOLDOWN}
            atomic_json(state_path,state)
            status(key,"starting")
            outcome = supervise(key,folder,fd)
            # Normal priority changes are not model failures. Crash and actual
            # timeout attempts remain bounded; resume a verified checkpoint.
            if outcome == "interrupted":
                state["attempts"] = max(0,state["attempts"]-1)
            atomic_json(state_path,{**state,"completed":outcome=="completed","retry_at":time()+COOLDOWN})
            waiting_since = waiting_key = None
        finally:
            release_slot(fd)
        sleep(2)


if __name__ == "__main__":
    main()
