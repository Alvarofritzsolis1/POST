#!/usr/bin/env python3
"""Real, opt-in CPU LoRA on Qwen3.5-0.8B with an isolated 5GiB cgroup.

NOT QLoRA: no 4-bit GPU, no updates to production Qwen3.5-4B.
Never reads Messenger or contractor records. Requires signed, private JSONL.
No training on --preflight, --dataset-only, or without --execute.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "backend"))

from galant_cpu_lora_resources import capacity_gate, process_memory_mb, should_pause, snapshot
from galancito_lora_progress import ProgressReporter
from app.galancito_finetune_dataset import load_approved, verified_training_manifest, verified_match

MODEL = "Qwen/Qwen3.5-0.8B"
SYSTEM = "Responde en español con precisión. No inventes información ni identificadores."
MIN_TRAIN = 30
MAX_STEPS = 1000
MAX_TOKENS = 192


def args_parser():
    parser = argparse.ArgumentParser(description="GALANT · entrenamiento LoRA CPU auténtico y aislado")
    parser.add_argument("--preflight", action="store_true", help="Recursos medidos, sin entrenar ni descargar modelos")
    parser.add_argument("--dataset", help="Ejemplos reales anonimizados y autorizados, JSONL 0600")
    parser.add_argument("--approval-manifest", help="Manifest Ed25519 firmado para Qwen3.5-0.8B")
    parser.add_argument("--output", help="Directorio privado ABSOLUTO de checkpoints y métricas")
    parser.add_argument("--execute", action="store_true", help="Habilita actualizaciones REALES de pesos LoRA por CPU")
    parser.add_argument("--resume", action="store_true", help="Reanuda exactamente el mismo dataset y configuración")
    parser.add_argument("--max-steps", type=int, default=40, help="Actualizaciones LoRA previstas, 1-1000")
    parser.add_argument("--checkpoint-steps", type=int, default=5, help="Guardar progreso recuperable cada N pasos")
    parser.add_argument("--max-tokens", type=int, default=192, help="Ventana pequeña para proteger la RAM")
    parser.add_argument("--telemetry-url", help="URL HTTPS opcional de GALANT")
    parser.add_argument("--telemetry-org", help="UUID organización autorizada para ver el gráfico")
    return parser


def validate_parameters(args):
    if not 1 <= args.max_steps <= MAX_STEPS:
        raise SystemExit("--max-steps debe estar entre 1 y 1000")
    if not 1 <= args.checkpoint_steps <= 20:
        raise SystemExit("--checkpoint-steps debe estar entre 1 y 20")
    if not 96 <= args.max_tokens <= 256:
        raise SystemExit("--max-tokens debe estar entre 96 y 256")
    if args.resume and not args.execute:
        raise SystemExit("--resume requiere --execute")
    if bool(args.telemetry_url) != bool(args.telemetry_org):
        raise SystemExit("La telemetría requiere URL y organización juntas")


def safe_output(args, bundle, attestation):
    repo = Path(__file__).resolve().parents[1]
    source = Path(args.dataset).resolve()
    target = Path(args.output).resolve()
    if (not source.is_file() or source.is_relative_to(repo)
            or target.is_relative_to(repo)):
        raise SystemExit("Los datos privados y el destino no pueden estar dentro del repositorio")
    if os.name == "posix" and source.stat().st_mode & 0o077:
        raise SystemExit("El JSONL privado exige permisos 0600")
    if target.exists() and target.is_symlink():
        raise SystemExit("Directorio simbólico de salida no permitido")
    metadata_path = target / "run-metadata.json"
    parameters = {
        "model": MODEL, "dataset_sha256": bundle["dataset_digest"],
        "approval_fingerprint": attestation["key_fingerprint"],
        "max_steps": args.max_steps, "checkpoint_steps": args.checkpoint_steps,
        "max_tokens": args.max_tokens, "org_id": args.telemetry_org,
    }
    if args.resume:
        if not metadata_path.is_file():
            raise SystemExit("No existe sesión verificada para reanudar")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if any(metadata.get(key) != value for key, value in parameters.items()):
            raise SystemExit("El manifest, modelo, organización o parámetros cambiaron")
        checkpoints = [p for p in (target / "checkpoints").glob("checkpoint-*")
                       if p.is_dir() and p.name.rsplit("-", 1)[-1].isdigit()
                       and (p / "trainer_state.json").is_file()]
        if not checkpoints:
            raise SystemExit("Falta checkpoint recuperable: no se inventa progreso")
        latest = max(checkpoints, key=lambda p: int(p.name.rsplit("-", 1)[-1]))
        if int(latest.name.rsplit("-", 1)[-1]) >= args.max_steps:
            raise SystemExit("El checkpoint ya completó los pasos programados")
        resume_from = str(latest)
    else:
        if target.exists() and any(target.iterdir()):
            raise SystemExit("Utiliza un directorio nuevo y vacío para no mezclar ejecuciones")
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            target.chmod(0o700)
        metadata = {**parameters, "run_id": str(uuid4())}
        metadata_path.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
        metadata_path.chmod(0o600)
        resume_from = None
    return target, metadata_path, metadata, resume_from


def hash_trainable(model, torch):
    """Hard evidence of actual trainable tensor changes, independent of loss."""
    digest = sha256()
    found = 0
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            if "lora_" not in name:
                raise RuntimeError("Parámetro base no congelado: entrenamiento cancelado")
            tensor = parameter.detach().to(device="cpu", dtype=torch.float32).contiguous()
            digest.update(name.encode("utf-8"))
            digest.update(tensor.numpy().tobytes())
            found += tensor.numel()
    if found == 0:
        raise RuntimeError("No se encontraron pesos LoRA entrenables")
    return digest.hexdigest(), found


def encode_cases(tokenizer, cases, length):
    from torch.utils.data import Dataset
    class FixedCases(Dataset):
        def __init__(self, records):
            self.rows = []
            for case in records:
                prompt = tokenizer.apply_chat_template(
                    [{"role":"system","content":SYSTEM}, case["messages"][0]],
                    tokenize=False, add_generation_prompt=True, enable_thinking=False)
                prompt_ids = tokenizer.encode(prompt, add_special_tokens=False)
                answer_ids = tokenizer.encode(
                    case["messages"][1]["content"] + tokenizer.eos_token,
                    add_special_tokens=False)
                # Reserve at least 32 answer tokens; only completion is supervised.
                prompt_ids = prompt_ids[-min(128, length - 32):]
                answer_ids = answer_ids[:length-len(prompt_ids)]
                if not answer_ids:
                    raise RuntimeError("Ejemplo sin tokens de respuesta supervisados")
                ids = prompt_ids + answer_ids
                self.rows.append({
                    "input_ids": ids,
                    "attention_mask": [1]*len(ids),
                    "labels": [-100]*len(prompt_ids)+answer_ids,
                })
        def __len__(self): return len(self.rows)
        def __getitem__(self, index): return self.rows[index]
    return FixedCases(cases)


def main(argv=None):
    args = args_parser().parse_args(argv)
    validate_parameters(args)
    storage = Path(args.output).parent if args.output else Path("/private")
    if not storage.exists():
        storage = storage.parent if storage.parent.exists() else Path("/")
    observed = snapshot(storage)
    gate = capacity_gate(observed)
    if args.preflight:
        print(json.dumps({"mode":"cpu_lora_preflight_only","model":MODEL,
                          "weights_changed":False,**gate}, ensure_ascii=False))
        return 0 if gate["ready"] else 3
    if not args.dataset:
        raise SystemExit("Proporciona --dataset o --preflight")
    bundle = load_approved(args.dataset)
    print(json.dumps({"status":"approved_examples_format_checked_not_trained",
                      "model":MODEL,"sizes":bundle["sizes"],
                      "digest":bundle["dataset_digest"],
                      "note":"No se modifica el modelo Qwen3.5 4B; consentimiento requiere comprobación independiente."},
                     ensure_ascii=False))
    if not args.execute:
        return 0
    if not gate["ready"]:
        raise SystemExit("Recursos insuficientes: "+",".join(gate["blockers"]))
    if (not args.output or not Path(args.output).is_absolute()
            or not args.approval_manifest):
        raise SystemExit("--execute exige --output absoluto y --approval-manifest firmado")
    if os.environ.get("GALANT_OFFLINE_TRAINING_APPROVED") != "yes":
        raise SystemExit("GALANT_OFFLINE_TRAINING_APPROVED=yes es obligatorio")
    try:
        attestation = verified_training_manifest(
            args.dataset, args.approval_manifest,
            os.environ.get("GALANT_DATASET_APPROVAL_PUBLIC_KEY", ""),
            dataset_digest=bundle["dataset_digest"], training_model=MODEL)
    except ValueError as exc:
        raise SystemExit("Dataset no autorizado para Qwen3.5-0.8B: " + str(exc)) from exc
    # Heavy ML libraries load only *after* permission and hardware gates.
    try:
        import torch
        from transformers import (AutoTokenizer, Qwen3_5ForCausalLM,
                                  Trainer, TrainingArguments, TrainerCallback,
                                  DataCollatorForSeq2Seq)
        from peft import LoraConfig, get_peft_model
    except ImportError as exc:
        raise SystemExit("Faltan dependencias CPU: torch, transformers 5+, peft y accelerate") from exc
    if torch.cuda.is_available():
        raise SystemExit("Este ejecutor está diseñado solo para CPU aislada")
    target, metadata_path, metadata, checkpoint = safe_output(args, bundle, attestation)
    torch.set_num_threads(min(2, os.cpu_count() or 1))
    torch.set_num_interop_threads(1)
    reporter = ProgressReporter(
        target,run_id=metadata["run_id"],org_id=args.telemetry_org,
        dataset_sha256=bundle["dataset_digest"],model=MODEL,
        telemetry_url=args.telemetry_url,
        telemetry_token=os.environ.get("GALANT_FINETUNE_TELEMETRY_TOKEN") if args.telemetry_url else None)
    state = {"step":0,"paused":False,"weights_changed":False}
    try:
        reporter.emit("start",step=0,total_steps=args.max_steps,
                      cpu_memory_mb=process_memory_mb())
        tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=False)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        # Use the OFFICIAL Qwen text-only class with the OFFICIAL 0.8B
        # checkpoint, as tested by Hugging Face Transformers. This avoids
        # loading the vision tower, critical for our 5GiB cgroup.
        model, loading = Qwen3_5ForCausalLM.from_pretrained(
            MODEL, dtype=torch.bfloat16, low_cpu_mem_usage=True,
            trust_remote_code=False, device_map=None,
            output_loading_info=True)
        missing = [key for key in loading.get("missing_keys", ())
                   if key.startswith(("model.", "lm_head"))]
        if missing:
            raise RuntimeError("Qwen3.5 texto incompleto: se rechazan parámetros inicializados al azar")
        model.config.use_cache = False
        for parameter in model.parameters():
            parameter.requires_grad_(False)
        linear = [name for name,layer in model.named_modules()
                  if name.startswith("model.layers.")
                  and isinstance(layer,torch.nn.Linear)]
        if not linear:
            raise RuntimeError("No se localizaron capas del decodificador de texto Qwen3.5")
        model = get_peft_model(model,LoraConfig(
            r=4,lora_alpha=8,lora_dropout=0.05,bias="none",
            target_modules=linear,task_type="CAUSAL_LM"))
        if hasattr(model,"enable_input_require_grads"):
            model.enable_input_require_grads()
        start_digest, trainable_count = hash_trainable(model,torch)
        model.config.use_cache = False
        train_data = encode_cases(tokenizer,bundle["samples"]["train"],args.max_tokens)
        validation = encode_cases(tokenizer,bundle["samples"]["validation"],args.max_tokens)
        holdout = encode_cases(tokenizer,bundle["samples"]["test"],args.max_tokens)
        settings = TrainingArguments(
            output_dir=str(target/"checkpoints"),
            max_steps=args.max_steps, learning_rate=7e-5,
            per_device_train_batch_size=1,per_device_eval_batch_size=1,
            gradient_accumulation_steps=2,logging_steps=1,logging_strategy="steps",
            save_strategy="steps",save_steps=args.checkpoint_steps,
            save_total_limit=3,eval_strategy="steps",
            eval_steps=args.checkpoint_steps,
            gradient_checkpointing=True,
            dataloader_num_workers=0,report_to="none",use_cpu=True,
            fp16=False,bf16=False,remove_unused_columns=False,
            optim="adamw_torch",disable_tqdm=True,
            save_safetensors=True,seed=42,
        )
        class Monitor(TrainerCallback):
            def on_log(self, args, state_, control, logs=None, **kwargs):
                values = logs or {}
                k = "eval" if "eval_loss" in values else "metric"
                reporter.emit(k,step=state_.global_step,total_steps=state_.max_steps or args.max_steps,
                              epoch=state_.epoch,loss=values.get("loss"),
                              eval_loss=values.get("eval_loss"),
                              grad_norm=values.get("grad_norm"),
                              learning_rate=values.get("learning_rate"),
                              cpu_memory_mb=process_memory_mb())
            def on_step_end(self, args, state_, control, **kwargs):
                state["step"]=state_.global_step
                if should_pause(snapshot(target)):
                    state["paused"]=True
                    control.should_save=True
                    control.should_training_stop=True
                return control
            def on_save(self, args, state_, control, **kwargs):
                reporter.emit("checkpoint",step=state_.global_step,
                              total_steps=state_.max_steps or args.max_steps,
                              epoch=state_.epoch,cpu_memory_mb=process_memory_mb())
        trainer=Trainer(
            model=model,args=settings,
            train_dataset=train_data,eval_dataset=validation,
            data_collator=DataCollatorForSeq2Seq(
                tokenizer=tokenizer,label_pad_token_id=-100,
                pad_to_multiple_of=8),
            processing_class=tokenizer,
            callbacks=[Monitor()],
        )
        # Test split is excluded from optimizer and checkpoint selection.
        baseline = metadata.get("heldout_loss_before")
        if baseline is None:
            baseline = trainer.evaluate(eval_dataset=holdout,metric_key_prefix="holdout_before").get("holdout_before_loss")
            metadata["heldout_loss_before"]=baseline
            metadata["trainable_lora_parameters"]=trainable_count
            metadata_path.write_text(json.dumps(metadata,sort_keys=True),encoding="utf-8")
            metadata_path.chmod(0o600)
            reporter.emit("baseline",step=0,total_steps=args.max_steps,
                          holdout_loss_before=baseline,cpu_memory_mb=process_memory_mb())
        trainer.train(resume_from_checkpoint=checkpoint)
        end_digest, _ = hash_trainable(model,torch)
        state["weights_changed"] = (start_digest != end_digest)
        if state["paused"]:
            reporter.emit("paused",step=trainer.state.global_step,
                          total_steps=args.max_steps,cpu_memory_mb=process_memory_mb(),
                          weights_trained=state["weights_changed"])
            return 3
        if trainer.state.global_step < 1 or not state["weights_changed"]:
            raise RuntimeError("No se verificó actualización de tensores LoRA")
        final = trainer.evaluate(eval_dataset=holdout,metric_key_prefix="holdout_after").get("holdout_after_loss")
        # Loss alone does not establish improved reasoning. Candidate stays
        # held until independently checked against reserved responses.
        report={
            "status":"trained_adapter_requires_holdout_reasoning_checks",
            "base_model":MODEL,"production_promoted":False,
            "weights_trained":True,
            "lora_weights_changed":True,
            "trainable_parameters":trainable_count,
            "steps":trainer.state.global_step,
            "dataset_sha256":bundle["dataset_digest"],
            "heldout_loss_before":baseline,"heldout_loss_after":final,
            "reasoning_improvement_proven":False,
            "needs":"Independent exact-answer and regression evaluation before promotion",
        }
        trainer.save_model(str(target/"candidate-adapter"))
        (target/"evaluation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        reporter.emit("finished",step=trainer.state.global_step,
                      total_steps=args.max_steps,holdout_loss_before=baseline,
                      holdout_loss_after=final,cpu_memory_mb=process_memory_mb(),
                      weights_trained=True,candidate_accepted=False)
        print(json.dumps(report,ensure_ascii=False))
        return 0
    except Exception:
        # No private texts or raw stack traces are pushed to the dashboard.
        reporter.emit("failed",step=state["step"],total_steps=args.max_steps,
                      cpu_memory_mb=process_memory_mb(),
                      weights_trained=state["weights_changed"])
        raise
    finally:
        reporter.close()


if __name__=="__main__":
    raise SystemExit(main())
