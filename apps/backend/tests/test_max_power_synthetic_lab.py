"""Regression tests for privacy-safe, authentic-but-synthetic MAX POWER lab."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import json

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from max_power_synthetic_lab import VERSION, bounded_evaluation, dataset_bytes, examples, prepare_lab, verify_dataset


def test_curated_corpus_is_large_partitioned_unique_and_never_real(tmp_path):
    lab, bundle = prepare_lab(tmp_path / "org")
    assert lab.name == "synthetic-lab-" + VERSION
    assert bundle["data_kind"] == "curated_synthetic"
    assert bundle["human_approval_independently_verified"] is False
    assert bundle["attestations_present"] is False
    assert bundle["sizes"]["train"] >= 30
    assert bundle["sizes"]["validation"] >= 10
    assert bundle["sizes"]["test"] >= 10
    cases = list(examples())
    assert len(cases) == 2384
    assert len({item["case_group"] for item in cases}) == 90
    assert sum(bundle["sizes"].values()) == 2384
    partitions = [{row["case_group"] for row in bundle["samples"][key]} for key in ("train", "validation", "test")]
    assert all(not a & b for i, a in enumerate(partitions) for b in partitions[i+1:])
    for key in ("validation", "test"):
        panel = bounded_evaluation(bundle["samples"][key])
        assert panel == bounded_evaluation(bundle["samples"][key])
        assert len(panel) == 12
        assert len({row["case_group"] for row in panel}) == min(12, len(partitions[1 if key == "validation" else 2]))
    assert all(item["source"] == "curated_synthetic" for item in cases)
    assert all("approved_by" not in item and "usage_authorized" not in item for item in cases)
    questions = [row["messages"][0]["content"].casefold() for row in cases]
    assert len(questions) == len(set(questions))
    assert (lab / "synthetic.jsonl").read_bytes() == dataset_bytes()
    assert (lab / "synthetic.jsonl").stat().st_mode & 0o077 == 0


def test_synthetic_data_cannot_be_replaced_or_confused_with_real_approval(tmp_path):
    lab, bundle = prepare_lab(tmp_path / "org")
    raw = lab / "synthetic.jsonl"
    raw.write_bytes(raw.read_bytes() + b'{"source":"human_reviewed_real"}\n')
    with pytest.raises(ValueError, match="modificado"):
        verify_dataset(raw)
    with pytest.raises(ValueError, match="modificado"):
        prepare_lab(tmp_path / "org")
    raw.unlink()
    assert prepare_lab(tmp_path / "org")[1]["dataset_digest"] == bundle["dataset_digest"]


def test_cpu_trainer_synthetic_mode_requires_explicit_switch(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("synthetic_lora_entry", SCRIPTS / "train_galancito_cpu_lora.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lab, bundle = prepare_lab(tmp_path / "org")
    monkeypatch.setattr(module, "snapshot", lambda path: {
        "host_free_mb": 9500, "cgroup_limit_mb": 5120,
        "cgroup_free_mb": 5000, "cgroup_used_mb": 120,
        "disk_free_mb": 20000
    })
    monkeypatch.delenv("GALANT_SYNTHETIC_DEV_TRAINING", raising=False)
    with pytest.raises(SystemExit, match="GALANT_SYNTHETIC_DEV_TRAINING"):
        module.main(["--dataset", str(lab / "synthetic.jsonl"),
                     "--synthetic-development", "--execute",
                     "--output", str(lab / "runs" / "pilot")])


def test_contextual_training_matches_messenger_protocol_without_leaking_partitions(tmp_path):
    from max_power_synthetic_lab import training_panel, contextual_loss_panel
    _, bundle = prepare_lab(tmp_path / "org")
    by_split = {key: [row for row in values if row.get("sample_kind") == "contextual_turn"]
                for key, values in bundle["samples"].items()}
    assert sum(map(len, by_split.values())) == 64
    assert all(by_split.values())
    for rows in by_split.values():
        for row in rows:
            turn = json.loads(row["reference_answer"])
            assert set(turn) == {"d", "i", "q", "r"}
            assert isinstance(turn["d"], dict)
            assert len(turn["r"]) <= 220
            assert turn["r"].endswith((".", "?"))
            prompt = row["messages"][0]["content"]
            for value in turn["d"].values():
                evidence = value if isinstance(value, str) else value
                if isinstance(evidence, str):
                    assert evidence in prompt
                else:
                    assert all(isinstance(item, str) for item in evidence)
                    assert evidence[-1] in prompt
    panel = training_panel(bundle["samples"]["train"], 80)
    assert len(panel) == 80
    assert sum(row.get("sample_kind") == "contextual_turn" for row in panel) == len(by_split["train"])
    assert {row["case_group"] for row in panel}.isdisjoint(
        {row["case_group"] for split in ("validation", "test") for row in bundle["samples"][split]})
    for split in ("validation", "test"):
        evaluation = contextual_loss_panel(bundle["samples"][split])
        assert len(evaluation) == 12
        assert any(row.get("sample_kind") == "contextual_turn" for row in evaluation)
