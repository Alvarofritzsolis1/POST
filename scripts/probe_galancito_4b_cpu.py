#!/usr/bin/env python3
"""Bounded CPU NF4 Qwen 4B feasibility experiment, not production training."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from time import monotonic, time

from galant_cpu_lora_resources import snapshot, should_pause

MODEL = "Qwen/Qwen3.5-4B"


def blockers(measured):
    required = {"host_free_mb": 8500, "cgroup_limit_mb": 7500,
                "cgroup_available_mb": 7000, "disk_free_mb": 16000}
    return [name for name, minimum in required.items()
            if type(measured.get(name)) not in (int, float)
            or not math.isfinite(measured[name]) or measured[name] < minimum]


def write_report(path, report):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="Explicitly execute optimizer steps")
    parser.add_argument("--allow-download", action="store_true", help="Download public model weights only")
    parser.add_argument("--steps", type=int, choices=range(1, 11), default=10)
    args = parser.parse_args()
    root = Path("/private/4b-probe")
    root.mkdir(parents=True, exist_ok=True)
    # No chat or private dataset is used. Never overwrite production checkpoints.
    report_path = root / "latest.json"
    measured = snapshot(root)
    reasons = blockers(measured)
    report = {"model": MODEL, "kind": "synthetic_capacity_probe", "timestamp": time(),
              "status": "blocked" if reasons else "preflight_passed",
              "blockers": reasons, "preflight": measured, "steps": [],
              "production_verified": False, "quality_improvement_verified": False,
              "adapter_changed": False}
    write_report(report_path, report)
    if reasons or not args.run:
        print(json.dumps(report))
        return 2 if reasons else 0
    try:
        import torch
        import bitsandbytes as bnb
        from transformers import AutoTokenizer, Qwen3_5ForCausalLM, BitsAndBytesConfig
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        torch.set_num_interop_threads(1)
        torch.manual_seed(42)
        start = monotonic()
        report["status"] = "loading"
        write_report(report_path, report)
        options = {"trust_remote_code":False, "local_files_only":not args.allow_download}
        tokenizer = AutoTokenizer.from_pretrained(MODEL, **options)
        model, loading = Qwen3_5ForCausalLM.from_pretrained(
            MODEL, dtype=torch.bfloat16, device_map={"":"cpu"}, low_cpu_mem_usage=True,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True,
                bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16), output_loading_info=True, **options)
        if any(k.startswith(("model.", "lm_head")) for k in loading.get("missing_keys", ())):
            raise RuntimeError("Missing text weights")
        quantized = sum(isinstance(layer, bnb.nn.Linear4bit) for layer in model.modules())
        if not quantized or not getattr(model, "is_loaded_in_4bit", False):
            raise RuntimeError("No verified 4-bit layers")
        report["quantized_layers"] = quantized
        report["load_seconds"] = round(monotonic()-start, 2)
        if should_pause(snapshot(root)):
            raise RuntimeError("Memory reserve below safe limit after loading")
        model.config.use_cache = False
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
        # Avoid converting every frozen bf16 embedding to fp32 permanently.
        model = get_peft_model(model, LoraConfig(r=4,lora_alpha=8,lora_dropout=0,
            target_modules=["q_proj","v_proj"],task_type="CAUSAL_LM"))
        trainable = [p for p in model.parameters() if p.requires_grad]
        if not trainable:
            raise RuntimeError("No trainable adapter")
        def digest():
            h = hashlib.sha256()
            for p in trainable:
                h.update(p.detach().float().contiguous().cpu().numpy().tobytes())
            return h.hexdigest()
        before = digest()
        optimizer = torch.optim.AdamW(trainable, lr=7e-5)
        examples = [("Ola compadre ando buscando peguita", "Hola, ¿qué trabajos haces normalmente?"),
                    ("No cacho que es cuadrilla", "Es un grupo de personas que trabajan juntas. ¿Trabajas solo o con más gente?")]
        model.train()
        for step in range(1, args.steps+1):
            if should_pause(snapshot(root)):
                raise RuntimeError("Memory reserve below safe limit")
            message, answer = examples[(step-1)%len(examples)]
            prefix = tokenizer.apply_chat_template([{"role":"user","content":message}],
                tokenize=False, add_generation_prompt=True, enable_thinking=False)
            prompt_ids = tokenizer(prefix, add_special_tokens=False)["input_ids"]
            answer_ids = tokenizer(answer, add_special_tokens=False)["input_ids"] + [tokenizer.eos_token_id]
            ids = torch.tensor([prompt_ids+answer_ids], dtype=torch.long)
            labels = torch.tensor([[-100]*len(prompt_ids)+answer_ids], dtype=torch.long)
            if ids.shape[1] > 192:
                raise RuntimeError("Probe context exceeds bound")
            t = monotonic()
            optimizer.zero_grad(set_to_none=True)
            loss = model(input_ids=ids, labels=labels, use_cache=False).loss
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite loss")
            loss.backward()
            if not any(p.grad is not None and torch.count_nonzero(p.grad).item() for p in trainable):
                raise RuntimeError("No nonzero adapter gradient")
            optimizer.step()
            current = digest()
            report["adapter_changed"] = current != before
            report["status"] = "running"
            report["steps"].append({"step":step,"seconds":round(monotonic()-t,2),
                "loss":float(loss.detach()),"memory":snapshot(root),
                "adapter_changed":report["adapter_changed"]})
            write_report(report_path, report)
        report["status"] = "completed" if report["adapter_changed"] else "failed"
    except Exception as exc:
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)[:300]
    write_report(report_path, report)
    print(json.dumps(report))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
