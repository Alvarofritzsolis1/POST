"""CPU-only LoRA guardrails run in CI without fetching model weights or installing Torch."""
from pathlib import Path
import importlib.util
import json
import sys
from uuid import uuid4
import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from galant_cpu_lora_resources import capacity_gate, should_pause
from galancito_lora_progress import ProgressReporter


def trainer():
    spec = importlib.util.spec_from_file_location("cpu_trainer", SCRIPTS / "train_galancito_cpu_lora.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normal_snapshot():
    return {"host_free_mb": 9000, "cgroup_limit_mb": 5120,
            "cgroup_free_mb": 4900, "cgroup_used_mb": 220,
            "disk_free_mb": 15000, "logical_cpu_count": 6,
            "process_rss_mb": 125}


def test_cpu_finetune_requires_real_capacity_and_never_estimates_missing_ram():
    good = normal_snapshot()
    assert capacity_gate(good)["ready"] is True
    assert should_pause(good) is False
    low_host = {**good, "host_free_mb": 3100}
    assert "host_ram_reserve" in capacity_gate(low_host)["blockers"]
    assert should_pause({**low_host, "host_free_mb": 1000}) is True
    low_cgroup = {**good, "cgroup_free_mb": 1000, "cgroup_used_mb": 4500}
    assert "cgroup_memory_headroom" in capacity_gate(low_cgroup)["blockers"]
    assert should_pause(low_cgroup) is True
    unknown = {**good, "cgroup_limit_mb": None, "cgroup_free_mb": None}
    assert capacity_gate(unknown)["ready"] is False
    assert "dedicated_cgroup_limit_missing" in capacity_gate(unknown)["blockers"]


def test_cpu_lora_preflight_has_no_model_download_or_invented_steps(monkeypatch, capsys):
    module = trainer()
    monkeypatch.setattr(module, "snapshot", lambda path: normal_snapshot())
    assert module.main(["--preflight"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "cpu_lora_preflight_only"
    assert out["weights_changed"] is False
    assert out["ready"] is True
    assert out["model"] == "Qwen/Qwen3.5-0.8B"


def test_cpu_lora_parameter_limits_reject_unbounded_or_oversized_jobs():
    module = trainer()
    for argv in (["--preflight", "--max-steps", "0"],
                 ["--preflight", "--max-steps", "1001"],
                 ["--preflight", "--max-tokens", "1024"],
                 ["--preflight", "--resume"],
                 ["--preflight", "--telemetry-url", "https://example.com"]):
        with pytest.raises(SystemExit):
            module.main(argv)


def test_cpu_lora_output_is_private_and_recoverable_only_from_matching_checkpoint(tmp_path):
    module = trainer()
    args = module.args_parser().parse_args([
        "--dataset",str(tmp_path/"signed.jsonl"),"--output",str(tmp_path/"run"),
        "--max-steps","20","--checkpoint-steps","2",
    ])
    (tmp_path/"signed.jsonl").write_text("[]\n",encoding="utf-8")
    (tmp_path/"signed.jsonl").chmod(0o600)
    bundle={"dataset_digest":"a"*64}
    attest={"key_fingerprint":"b"*16}
    path, metadata_path, info, cp = module.safe_output(args,bundle,attest)
    assert cp is None
    assert metadata_path.stat().st_mode & 0o077 == 0
    assert info["model"] == "Qwen/Qwen3.5-0.8B"
    assert info["dataset_sha256"] == "a"*64
    (path/"checkpoints"/"checkpoint-2").mkdir(parents=True)
    (path/"checkpoints"/"checkpoint-2"/"trainer_state.json").write_text("{}")
    args.resume = True
    _,_,same,checkpoint = module.safe_output(args,bundle,attest)
    assert same["run_id"] == info["run_id"]
    assert checkpoint.endswith("checkpoint-2")
    args.max_steps = 21
    with pytest.raises(SystemExit,match="cambiaron"):
        module.safe_output(args,bundle,attest)


def test_cpu_progress_is_measured_and_not_mislabeled_as_4b(tmp_path):
    run = str(uuid4())
    reporter = ProgressReporter(tmp_path,run_id=run,org_id=None,
                                dataset_sha256="c"*64,model="Qwen/Qwen3.5-0.8B")
    a=reporter.emit("metric",step=1,total_steps=10,loss=2.3,cpu_memory_mb=1398.7,
                    worker_prompt="NOT PRIVATE DATA")
    b=reporter.emit("paused",step=2,total_steps=10,cpu_memory_mb=2030.5,
                    weights_trained=True)
    reporter.close()
    assert a["model"] == "Qwen/Qwen3.5-0.8B"
    assert a["cpu_memory_mb"] == 1398.7
    assert "gpu_memory_mb" not in a
    assert "worker_prompt" not in a
    assert b["kind"] == "paused"
    assert b["weights_trained"] is True
    again=ProgressReporter(tmp_path,run_id=run,org_id=None,
                           dataset_sha256="c"*64,model="Qwen/Qwen3.5-0.8B")
    assert again.sequence == 2
    again.close()
    with pytest.raises(ValueError,match="incompatible"):
        ProgressReporter(tmp_path,run_id=run,org_id=None,
                         dataset_sha256="c"*64,model="Qwen/Qwen3.5-4B")


def test_cpu_training_script_requires_real_gradients_and_human_signed_dataset():
    code=(SCRIPTS/"train_galancito_cpu_lora.py").read_text()
    assert "verified_training_manifest(" in code
    assert "training_model=MODEL" in code
    assert "trainer.train(resume_from_checkpoint=checkpoint)" in code
    assert "hash_trainable(model,torch)" in code
    assert "start_digest != end_digest" in code
    assert "candidate_accepted=False" in code
    assert "reasoning_improvement_proven" in code
    assert "torch.cuda.is_available()" in code
