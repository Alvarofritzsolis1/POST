#!/usr/bin/env python3
"""End-to-end MAX POWER smoke against isolated QA only; no Ollama/model download."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
import os
import time
from urllib.error import HTTPError
from qa_stack_smoke import Account

PATH = "/admin/ai/max-power"

def denied(account, path, status):
    try:
        account.call(path)
    except HTTPError as exc:
        assert exc.code == status, (exc.code, status)
    else:
        raise AssertionError(f"Expected HTTP {status} for {path}")

def check_export(account):
    payload = account.call(PATH + "/export")
    assert payload["schema"] == "galant.max_power.chatgpt_diagnostic.v1"
    assert payload["handling"]["raw_conversations_included"] is False
    assert payload["handling"]["secret_values_included"] is False
    integrity = payload.pop("integrity")
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                           allow_nan=False, separators=(",", ":")).encode()
    assert sha256(canonical).hexdigest() == integrity["canonical_payload_without_integrity"]
    return payload

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18612")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.url not in ("http://127.0.0.1:18612", "http://localhost:18612"):
        parser.error("MAX POWER smoke solamente acepta QA localhost")
    password = os.environ.get("QA_SMOKE_PASSWORD")
    if not password:
        parser.error("QA_SMOKE_PASSWORD es obligatorio")
    admin, resident, outside = (Account(args.url) for _ in range(3))
    admin.login("qa-admin@example.test", password)
    resident.login("qa-viewer@example.test", password)
    outside.login("qa-outside@example.test", password)
    denied(resident, PATH, 403)
    denied(resident, PATH + "/export", 403)
    assert outside.call(PATH)["enabled"] is False
    if not args.verify_only:
        before = admin.call(PATH)
        assert before["enabled"] is False and before["sessions"] == 0
        started = admin.call(PATH + "/control/on", {})
        assert started["enabled"] and started["sessions"] == 1
        began = started["first_started_at"]
        for _ in range(15):
            if admin.call(PATH)["controller_online"]:
                break
            time.sleep(2)
        else:
            raise AssertionError("MAX POWER controller did not persist a live heartbeat")
        stopped = admin.call(PATH + "/control/off", {})
        assert not stopped["enabled"]
        assert stopped["first_started_at"] == began
        restarted = admin.call(PATH + "/control/on", {})
        assert restarted["sessions"] == 2 and restarted["first_started_at"] == began
        stopped = admin.call(PATH + "/control/off", {})
        assert stopped["sessions"] == 2 and not stopped["enabled"]
        assert check_export(admin)["session"]["sessions_started"] == 2
        assert check_export(outside)["history"]["event_count_total"] == 0
        print("MAX POWER: start, heartbeat, durable OFF/ON, privacy and export OK")
    else:
        current = admin.call(PATH)
        assert current["enabled"] is False
        assert current["sessions"] == 2
        export = check_export(admin)
        assert export["session"]["sessions_started"] == 2
        assert export["session"]["first_started_at_utc"] is not None
        assert export["history"]["event_count_total"] >= 4
        print("MAX POWER state survived real Docker container restart; no lost sessions")

if __name__ == "__main__":
    main()
