#!/usr/bin/env python3
"""Bounded CPU NF4 Qwen 4B feasibility experiment, not production training."""
import argparse
import hashlib
import json
import math
import os
from uuid import uuid4
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
    parser.add_argument("--threads", type=int, choices=(2, 4), default=4)
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
        torch.set_num_threads(min(args.threads, os.cpu_count() or 1))
        report["threads"] = torch.get_num_threads()
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
        # PEFT preparation can expand frozen non-quantized tensors; monitor the measured reserve.
        if should_pause(snapshot(root)):
            raise RuntimeError("Memory reserve below safe limit after PEFT preparation")
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
        report["initial_adapter_sha256"] = before
        optimizer = torch.optim.AdamW(trainable, lr=7e-5)
        examples = [
            ("Ola compadre ando buscando peguita", "Hola, ¿qué trabajos haces normalmente?"),
            ("No cacho que es cuadrilla", "Es un grupo de personas que trabajan juntas. ¿Trabajas solo o con más gente?"),
            ("Somos tres maestros y dos ayudantes", "Perfecto, entonces son cinco personas. ¿Qué trabajos hacen?"),
            ("Mi señora ve los papeles", "No hay problema. Primero podemos conversar sobre el trabajo y después revisar los documentos."),
            ("Y las lucas cuanto son", "Todavía no tengo un monto confirmado. El equipo podrá aclararte las condiciones del trabajo."),
            ("Puedo partir altiro", "Bien, tienes disponibilidad inmediata. ¿En qué comuna puedes trabajar?"),
            ("No tengo correo", "No pasa nada, podemos seguir conversando por acá."),
            ("Ya te dije po soy carpintero", "Tienes razón, anoté que eres carpintero. ¿Trabajas solo o con un equipo?"),
            ("No sé usar el celu mucho", "Te puedo ayudar por acá, de a una pregunta para que sea más fácil."),
            ("Tengo 8 años de experiencia en pintura", "Anotado, ocho años en pintura. ¿En qué comuna trabajas?")
        ]
        # Diagnostic references are fixed and disjoint from training examples.
        # Loss is an experimental signal, not a conversational quality score.
        holdout = [
            ("Ando sin pega hace rato", "Cuéntame qué oficio tienes para orientarte sobre las opciones."),
            ("Que significa a trato", "Es un trabajo pagado según las condiciones acordadas por una partida o tarea. El equipo debe confirmar los detalles."),
            ("No tengo gente voy yo nomas", "Entendido, buscas trabajo para ti. ¿Qué oficio tienes?"),
            ("Me dijieron que pagan el viernes es cierto", "No puedo confirmar esa fecha sin información del equipo."),
        ]
        def encode(message, answer):
            prefix = tokenizer.apply_chat_template([{"role":"user","content":message}],
                tokenize=False, add_generation_prompt=True, enable_thinking=False)
            prompt_ids = tokenizer(prefix, add_special_tokens=False)["input_ids"]
            answer_ids = tokenizer(answer, add_special_tokens=False)["input_ids"] + [tokenizer.eos_token_id]
            ids = torch.tensor([prompt_ids+answer_ids], dtype=torch.long)
            labels = torch.tensor([[-100]*len(prompt_ids)+answer_ids], dtype=torch.long)
            if ids.shape[1] > 192:
                raise RuntimeError("Probe context exceeds bound")
            return ids, labels

        def heldout_loss():
            model.eval()
            losses = []
            with torch.no_grad():
                for message, answer in holdout:
                    if should_pause(snapshot(root)):
                        raise RuntimeError("Memory reserve below safe limit during validation")
                    ids, labels = encode(message, answer)
                    loss = model(input_ids=ids, labels=labels, use_cache=False).loss
                    if not torch.isfinite(loss):
                        raise RuntimeError("Non-finite reserved loss")
                    losses.append(float(loss))
            return sum(losses)/len(losses)

        run_dir = root / ("candidate-" + uuid4().hex)
        run_dir.mkdir()
        report["candidate_id"] = run_dir.name
        report["holdout_cases"] = len(holdout)
        report["status"] = "baseline_evaluation"
        write_report(report_path, report)
        report["holdout_loss_before"] = heldout_loss()
        write_report(report_path, report)
        model.train()
        for step in range(1, args.steps+1):
            if should_pause(snapshot(root)):
                raise RuntimeError("Memory reserve below safe limit")
            ids, labels = encode(*examples[(step-1)%len(examples)])
            t = monotonic()
            optimizer.zero_grad(set_to_none=True)
            loss = model(input_ids=ids, labels=labels, use_cache=False).loss
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite loss")
            loss.backward()
            gradients = [p.grad for p in trainable if p.grad is not None]
            if not gradients or not all(torch.isfinite(g).all().item() for g in gradients):
                raise RuntimeError("Missing or non-finite adapter gradients")
            if not any(torch.count_nonzero(g).item() for g in gradients):
                raise RuntimeError("No nonzero adapter gradient")
            previous = digest()
            optimizer.step()
            if not all(torch.isfinite(p).all().item() for p in trainable):
                raise RuntimeError("Non-finite adapter weights")
            current = digest()
            if current == previous:
                raise RuntimeError("Optimizer step did not change adapter weights")
            report["adapter_changed"] = current != before
            report["latest_adapter_sha256"] = current
            report["status"] = "running"
            report["steps"].append({"step":step,"seconds":round(monotonic()-t,2),
                "loss":float(loss.detach()),"memory":snapshot(root),
                "adapter_changed":report["adapter_changed"], "adapter_sha256":current})
            # Persist the latest adapter separately from production. This is
            # not an optimizer-resume checkpoint and cannot be auto-promoted.
            checkpoint = run_dir / ("step-" + str(step))
            staging = run_dir / (".step-" + str(step) + "-partial")
            model.save_pretrained(staging, safe_serialization=True)
            if not (staging / "adapter_model.safetensors").is_file() or not (staging / "adapter_config.json").is_file():
                raise RuntimeError("Incomplete persisted adapter")
            staging.rename(checkpoint)
            report["saved_adapter_step"] = step
            write_report(report_path, report)
        report["status"] = "candidate_evaluation"
        write_report(report_path, report)
        report["holdout_loss_after"] = heldout_loss()
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
