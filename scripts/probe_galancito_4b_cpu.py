#!/usr/bin/env python3
"""Bounded CPU NF4 Qwen 4B feasibility experiment, not production training."""
import argparse
import hashlib
import json
import math
import os
import re
from galancito_4b_validation import evaluate_conversations, paired_report
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
    parser.add_argument("--conversation-eval", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Resume only a verified local optimizer checkpoint")
    parser.add_argument("--output", type=Path, default=Path("/private/4b-probe"))
    args = parser.parse_args()
    root = args.output
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
        from transformers import AutoConfig, AutoTokenizer, Qwen3_5ForCausalLM, BitsAndBytesConfig
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from peft.utils.save_and_load import load_peft_weights, set_peft_model_state_dict
        torch.set_num_threads(min(args.threads, os.cpu_count() or 1))
        report["threads"] = torch.get_num_threads()
        torch.set_num_interop_threads(1)
        torch.manual_seed(42)
        start = monotonic()
        report["status"] = "loading"
        write_report(report_path, report)
        options = {"trust_remote_code":False, "local_files_only":not args.allow_download}
        config = AutoConfig.from_pretrained(MODEL, **options)
        revision = getattr(config, "_commit_hash", None)
        if not isinstance(revision,str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise RuntimeError("Cannot prove exact base-model revision")
        options["revision"] = revision
        report["base_revision"] = revision
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

        dataset_hash = hashlib.sha256(json.dumps([examples,holdout],ensure_ascii=False).encode()).hexdigest()
        report["dataset_sha256"] = dataset_hash
        resume_path = root / "resume.json"
        def file_hash(path):
            with path.open("rb") as stream:
                return hashlib.file_digest(stream,"sha256").hexdigest()
        start_step = 0
        if args.resume and resume_path.exists():
            saved = json.loads(resume_path.read_text())
            name, step = saved.get("candidate_id"), saved.get("step")
            if (not isinstance(name,str) or not re.fullmatch(r"candidate-[0-9a-f]{32}",name)
                    or type(step) is not int or not 1 <= step <= args.steps
                    or saved.get("base_revision") != revision
                    or saved.get("dataset_sha256") != dataset_hash
                    or saved.get("target_steps") != args.steps):
                raise RuntimeError("Incompatible resume checkpoint")
            run_dir = root / name
            checkpoint = run_dir / ("step-" + str(step))
            for filename in ("adapter_model.safetensors","adapter_config.json","optimizer.pt"):
                path = checkpoint / filename
                if path.is_symlink() or file_hash(path) != saved["files"][filename]:
                    raise RuntimeError("Checkpoint integrity mismatch")
            if not checkpoint.resolve().is_relative_to(root.resolve()):
                raise RuntimeError("Checkpoint outside private storage")
            set_peft_model_state_dict(model, load_peft_weights(str(checkpoint),device="cpu"))
            if digest() != saved["adapter_sha256"]:
                raise RuntimeError("Restored adapter digest mismatch")
            optimizer.load_state_dict(torch.load(checkpoint / "optimizer.pt",map_location="cpu",weights_only=True))
            before = saved["initial_adapter_sha256"]
            report["initial_adapter_sha256"] = before
            report["steps"] = saved["steps"]
            report["holdout_loss_before"] = saved["holdout_loss_before"]
            report["saved_adapter_step"] = step
            report["adapter_changed"] = digest() != before
            report["latest_adapter_sha256"] = digest()
            start_step = step
        else:
            run_dir = root / ("candidate-" + uuid4().hex)
            run_dir.mkdir()
            report["status"] = "baseline_evaluation"
            write_report(report_path, report)
            report["holdout_loss_before"] = heldout_loss()
        report["candidate_id"] = run_dir.name
        report["holdout_cases"] = len(holdout)
        report["resumed_from_step"] = start_step
        write_report(report_path, report)
        model.train()
        for step in range(start_step+1, args.steps+1):
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
            # Atomic adapter + optimizer checkpoint, never auto-promoted.
            checkpoint = run_dir / ("step-" + str(step))
            staging = run_dir / (".step-" + str(step) + "-" + uuid4().hex + "-partial")
            model.save_pretrained(staging, safe_serialization=True)
            if not (staging / "adapter_model.safetensors").is_file() or not (staging / "adapter_config.json").is_file():
                raise RuntimeError("Incomplete persisted adapter")
            torch.save(optimizer.state_dict(),staging / "optimizer.pt")
            files = {name:file_hash(staging / name) for name in
                     ("adapter_model.safetensors","adapter_config.json","optimizer.pt")}
            if checkpoint.exists():
                # A crash between rename and pointer publication leaves an orphan.
                checkpoint.rename(run_dir / ("orphan-" + uuid4().hex))
            staging.rename(checkpoint)
            write_report(resume_path,{"candidate_id":run_dir.name,"step":step,
                "base_revision":revision,"dataset_sha256":dataset_hash,"target_steps":args.steps,
                "initial_adapter_sha256":before,"adapter_sha256":current,"files":files,
                "steps":report["steps"],"holdout_loss_before":report["holdout_loss_before"]})
            report["saved_adapter_step"] = step
            write_report(report_path, report)
        report["status"] = "candidate_evaluation"
        write_report(report_path, report)
        report["holdout_loss_after"] = heldout_loss()
        if args.conversation_eval:
            report["status"] = "conversation_evaluation"
            write_report(report_path, report)
            model.eval()
            def guard():
                if should_pause(snapshot(root)):
                    raise RuntimeError("Memory reserve below safe limit during generation")
            def generate(history):
                guard()
                prompt = tokenizer.apply_chat_template(history, tokenize=False,
                    add_generation_prompt=True, enable_thinking=False)
                ids = tokenizer(prompt, return_tensors="pt", add_special_tokens=False)["input_ids"]
                if ids.shape[1] > 1536:
                    raise RuntimeError("Evaluation conversation exceeds context limit")
                t = monotonic()
                with torch.no_grad():
                    out = model.generate(input_ids=ids, max_new_tokens=96, do_sample=False,
                                         pad_token_id=tokenizer.eos_token_id, use_cache=True)
                return tokenizer.decode(out[0, ids.shape[1]:], skip_special_tokens=True), monotonic()-t
            # Actual adapter on/off on exactly the same loaded base. Do not
            # compare a trained HF model against an unrelated Ollama baseline.
            with model.disable_adapter():
                base = evaluate_conversations(generate, before_turn=guard)
                reference, _ = generate([{"role":"user","content":"¿Qué significa cuadrilla?"}])
            candidate = evaluate_conversations(generate, before_turn=guard)
            with model.disable_adapter():
                restored, _ = generate([{"role":"user","content":"¿Qué significa cuadrilla?"}])
            validation = paired_report(base, candidate)
            validation["rollback_output_equal"] = reference == restored
            validation["lab_pass"] = validation["lab_pass"] and validation["rollback_output_equal"]
            report["conversation_validation"] = validation
            report["candidate_status"] = "lab_candidate" if validation["lab_pass"] else "rejected"
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
