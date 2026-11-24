"""End-to-end synthetic CPU LoRA smoke through the actual MAX POWER supervisor.

For isolated CI ONLY: the API is replaced with an in-process control stub.
The supervisor subprocess, optimizer, files, hashes and checkpoints are REAL.
No production database, Facebook, Messenger, accounts or documents are used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4
import sys

sys.path.insert(0, "/src/scripts")
from max_power_synthetic_lab import VERSION, prepare_lab
import max_power_cpu_manager as supervisor


def main():
    if os.environ.get("GALANT_MAX_POWER_SYNTHETIC_LORA") != "yes":
        raise SystemExit("Synthetic automatic training must be explicitly enabled")
    if os.environ.get("GALANT_CI_ISOLATED_CPU_SMOKE") != "yes":
        raise SystemExit("Only run the synthetic supervisor smoke in isolated CI")
    org = str(uuid4())
    secret = "7" * 64  # Ephemeral test-only secret; never a production credential.
    plan = {"enabled": True, "org_id": org, "generation": 1,
            "messenger_busy": False, "practice_busy": False}
    statuses = []

    def isolated_api(path, supplied_secret, *, body=None):
        if supplied_secret != secret:
            raise RuntimeError("Unexpected secret in isolated smoke")
        if path == "/automation/plan" and body is None:
            return plan
        if path == "/automation/status" and isinstance(body, dict):
            if body.get("org_id") != org or body.get("generation") != 1:
                raise RuntimeError("Supervisor incorrectly changed the session")
            statuses.append(body["status"])
            return {"accepted": True}
        raise RuntimeError("Unexpected API operation in isolated smoke")

    supervisor.SYNTHETIC_STEPS = 4  # CI smoke only; production uses the 40-step pilot.
    supervisor.api_call = isolated_api
    supervisor.run_once(secret, plan, "", {}, {})
    root = Path("/private") / org
    lab, bundle = prepare_lab(root)
    if lab.name != "synthetic-lab-" + VERSION:
        raise AssertionError("Unexpected lab corpus version")
    output, _, status = supervisor.select_run(lab, bundle["dataset_digest"])
    if status != "finished" or not supervisor.verified_finished_run(output, bundle["dataset_digest"]):
        raise AssertionError("MAX POWER supervisor did not create verified trained weights")
    report = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
    assert report["new_optimizer_steps"] == 4, report
    assert report["production_promoted"] is False, report
    assert report["data_kind"] == "curated_synthetic"
    assert report["optimizer_start_sha256"] != report["optimizer_end_sha256"]
    assert (output / "checkpoints/checkpoint-4/optimizer.pt").is_file()
    assert "preparing_synthetic" in statuses, statuses
    assert "finished_synthetic" in statuses, statuses
    assert "training_synthetic" in statuses, (
        "Supervisor never observed fresh optimizer evidence; status would be misleading", statuses
    )
    assert not any(s in {"training", "finished", "awaiting_approved_dataset"}
                   for s in statuses), statuses
    before = (output / "evaluation.json").read_bytes()
    supervisor.run_once(secret, plan, "", {}, {})
    assert (output / "evaluation.json").read_bytes() == before, "Repeated ON must not overwrite weights"
    assert statuses[-1] == "finished_synthetic"
    print("MAX_POWER_ONE_BUTTON_NEURAL=real_supervisor_launched_4_steps_and_persisted_verified_weights")
    print("MAX_POWER_ONE_BUTTON_STATUS=preparing_training_finished_with_no_faked_approval")


if __name__ == "__main__":
    main()
