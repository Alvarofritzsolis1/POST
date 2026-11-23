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
    (path/"checkpoints"/"checkpoint-2"/"optimizer.pt").write_bytes(b"checkpoint")
    (path/"checkpoints"/"checkpoint-2"/"scheduler.pt").write_bytes(b"checkpoint")
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
    assert "Qwen3_5ForCausalLM.from_pretrained(" in code
    assert "output_loading_info=True" in code
    assert "Qwen3_5ForConditionalGeneration" not in code
    assert "hash_trainable(model,torch)" in code
    assert "verified_optimizer_update(" in code
    assert "def on_train_begin(" in code
    assert "state[\"optimizer_start_hash\"]" in code
    assert "candidate_accepted=False" in code
    assert "reasoning_improvement_proven" in code
    assert "torch.cuda.is_available()" in code



def test_resuming_checkpoint_never_counts_old_weights_as_new_learning():
    mod = trainer()
    assert mod.verified_optimizer_update(
        start_hash="before", end_hash="after", start_step=5, end_step=6) is True
    assert mod.verified_optimizer_update(
        start_hash="before", end_hash="after", start_step=5, end_step=5) is False
    assert mod.verified_optimizer_update(
        start_hash="before", end_hash="before", start_step=5, end_step=6) is False
    assert mod.verified_optimizer_update(
        start_hash=None, end_hash="after", start_step=0, end_step=2) is False
    assert mod.verified_optimizer_update(
        start_hash="before", end_hash="after", start_step=5, end_step=3) is False


def test_full_authorized_answer_must_survive_tokenization_and_masking():
    mod = trainer()
    item = mod.prepare_supervised_example(list(range(150)), [70, 71, 72], 192)
    assert len(item["input_ids"]) == 131
    assert item["labels"].count(-100) == 128
    assert item["labels"][-3:] == [70, 71, 72]
    assert item["input_ids"][-3:] == [70, 71, 72]
    assert all(n == 1 for n in item["attention_mask"])
    with pytest.raises(ValueError, match="supera la ventana"):
        mod.prepare_supervised_example(list(range(140)), list(range(180)), 192)
    with pytest.raises(ValueError, match="demasiado corto"):
        mod.prepare_supervised_example([1, 2, 3], [99], 192)


def test_symlink_private_training_output_is_blocked(tmp_path):
    mod = trainer()
    data = tmp_path / "approved.jsonl"
    data.write_text("{}\n", encoding="utf-8")
    data.chmod(0o600)
    original = tmp_path / "original"
    original.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(original, target_is_directory=True)
    args = mod.args_parser().parse_args([
        "--dataset", str(data), "--output", str(alias)])
    with pytest.raises(SystemExit, match="simbólico"):
        mod.safe_output(args, {"dataset_digest": "d" * 64},
                        {"key_fingerprint": "f" * 16})


def test_incomplete_checkpoint_is_not_recognized_as_restorable(tmp_path):
    mod = trainer()
    data = tmp_path / "approved.jsonl"
    data.write_text("{}\n", encoding="utf-8")
    data.chmod(0o600)
    args = mod.args_parser().parse_args([
        "--dataset", str(data), "--output", str(tmp_path / "run")])
    bundle = {"dataset_digest": "d" * 64}
    approved = {"key_fingerprint": "f" * 16}
    target, _, _, _ = mod.safe_output(args, bundle, approved)
    ck = target / "checkpoints" / "checkpoint-5"
    ck.mkdir(parents=True)
    (ck / "trainer_state.json").write_text("{}")
    args.resume = True
    with pytest.raises(SystemExit, match="checkpoint recuperable"):
        mod.safe_output(args, bundle, approved)
