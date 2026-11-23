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
from max_power_synthetic_lab import verify_dataset

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
    parser.add_argument("--synthetic-development", action="store_true",
                        help="Laboratorio aislado con datos ficticios del código; nunca producción")
    parser.add_argument("--resume", action="store_true", help="Reanuda exactamente el mismo dataset y configuración")
    parser.add_argument("--max-steps", type=int, default=40, help="Actualizaciones LoRA previstas, 1-1000")
    parser.add_argument("--checkpoint-steps", type=int, default=5, help="Guardar progreso recuperable cada N pasos")
    parser.add_argument("--max-tokens", type=int, default=192, help="Ventana pequeña para proteger la RAM")
    parser.add_argument("--telemetry-url", help="URL HTTPS opcional de GALANT")
    parser.add_argument("--telemetry-org", help="UUID organización autorizada para ver el gráfico")
    parser.add_argument("--control-file", help="Archivo interno de encendido/apagado del supervisor")
    parser.add_argument("--expected-generation", type=int, help="Generación MAX POWER que autorizó la ronda")
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
    if bool(args.control_file) != (args.expected_generation is not None):
        raise SystemExit("El control automático exige archivo y generación de sesión")
    if args.expected_generation is not None and args.expected_generation < 1:
        raise SystemExit("Generación de sesión inválida")


def safe_output(args, bundle, attestation):
    repo = Path(__file__).resolve().parents[1]
    source = Path(args.dataset).resolve()
    raw_target = Path(args.output)
    # Check symlinks BEFORE resolving; otherwise .resolve() conceals them.
    if raw_target.is_symlink():
        raise SystemExit("Directorio simbólico de salida no permitido")
    target = raw_target.resolve()
    if (not source.is_file() or source.is_relative_to(repo)
            or target.is_relative_to(repo)):
        raise SystemExit("Los datos privados y el destino no pueden estar dentro del repositorio")
    if os.name == "posix" and source.stat().st_mode & 0o077:
        raise SystemExit("El JSONL privado exige permisos 0600")
    metadata_path = target / "run-metadata.json"
    parameters = {
        "model": MODEL, "dataset_sha256": bundle["dataset_digest"],
        "data_kind": bundle.get("data_kind", "human_reviewed_real"),
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
                       and (p / "trainer_state.json").is_file()
                       and (p / "optimizer.pt").is_file()
                       and (p / "scheduler.pt").is_file()]
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


def automation_allowed(path: str | None, *, org: str | None, generation: int | None) -> bool:
    if not path:
        return True  # Manual, explicitly approved and opted-in executions only.
    from uuid import UUID
    try:
        control_path = Path(path).resolve(strict=True)
        if not control_path.is_relative_to(Path("/private").resolve()):
            return False
        data = json.loads(control_path.read_text(encoding="utf-8"))
        return (str(UUID(str(data.get("org_id")))) == str(UUID(str(org)))
                and int(data.get("generation")) == generation
                and data.get("allowed") is True)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def verified_optimizer_update(*, start_hash: str | None, end_hash: str,
                              start_step: int, end_step: int) -> bool:
    """Confirm fresh optimizer updates, NOT merely loading a prior LoRA checkpoint."""
    return (bool(start_hash) and start_hash != end_hash
            and end_step > start_step >= 0)


def prepare_supervised_example(prompt_ids: list[int], answer_ids: list[int],
                               length: int) -> dict:
    """Make a completion-only example; NEVER train on a truncated answer."""
    reserve = len(answer_ids)
    if reserve > length - 24:
        raise ValueError(
            "Respuesta autorizada supera la ventana de entrenamiento; "
            "reduce el ejemplo o aumenta --max-tokens sin exceder los límites")
    prompt_ids = prompt_ids[-min(128, length - reserve):]
    if len(prompt_ids) < 8 or not answer_ids:
        raise ValueError("Ejemplo demasiado corto para entrenamiento supervisado")
    ids = prompt_ids + answer_ids
    return {"input_ids": ids,
            "attention_mask": [1] * len(ids),
            "labels": [-100] * len(prompt_ids) + answer_ids}


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
                self.rows.append(
                    prepare_supervised_example(prompt_ids, answer_ids, length))
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
        if args.telemetry_url and args.telemetry_org:
            # A measured host/cgroup preflight, not a training run or weight
            # update.  Only authorized admins can see its signed metrics.
            report_id = str(uuid4())
            reporter = ProgressReporter(
                Path("/private") / "preflights" / report_id,
                run_id=report_id, org_id=args.telemetry_org,
                dataset_sha256="0" * 64, model=MODEL,
                telemetry_url=args.telemetry_url,
                telemetry_token=os.environ.get("GALANT_FINETUNE_TELEMETRY_TOKEN"))
            try:
                reporter.emit("preflight", step=0, total_steps=0,
                              preflight_ready=gate["ready"],
                              host_free_mb=observed["host_free_mb"],
                              cgroup_free_mb=observed["cgroup_free_mb"],
                              cgroup_limit_mb=observed["cgroup_limit_mb"],
                              disk_free_mb=observed["disk_free_mb"])
            finally:
                reporter.close()
        print(json.dumps({"mode":"cpu_lora_preflight_only","model":MODEL,
                          "weights_changed":False,**gate}, ensure_ascii=False))
        return 0 if gate["ready"] else 3
    if not args.dataset:
        raise SystemExit("Proporciona --dataset o --preflight")
    # The synthetic path is integrity-checked against code-owned examples.
    bundle = verify_dataset(args.dataset) if args.synthetic_development else load_approved(args.dataset)
    kind = "curated_synthetic" if args.synthetic_development else "human_reviewed_real"
    print(json.dumps({"status":"synthetic_lab_checked_not_trained" if args.synthetic_development
                      else "approved_examples_format_checked_not_trained", "data_kind":kind,
                      "model":MODEL,"sizes":bundle["sizes"],
                      "digest":bundle["dataset_digest"],
                      "note":"Prueba ficticia: no demuestra mejora productiva." if args.synthetic_development
                      else "Los datos reales requieren consentimiento revisado independientemente."},
                     ensure_ascii=False))
    if not args.execute:
        return 0
    if not gate["ready"]:
        raise SystemExit("Recursos insuficientes: "+",".join(gate["blockers"]))
    if (not args.output or not Path(args.output).is_absolute()
            or (not args.synthetic_development and not args.approval_manifest)):
        raise SystemExit("--execute exige --output absoluto y --approval-manifest firmado")
    if args.synthetic_development:
        if os.environ.get("GALANT_SYNTHETIC_DEV_TRAINING") != "yes":
            raise SystemExit("El laboratorio requiere GALANT_SYNTHETIC_DEV_TRAINING=yes")
        # A code-verified integrity ID, NOT a fake authorization signature.
        attestation = {"key_fingerprint": "synthetic-dev-" + bundle["dataset_digest"][:16]}
    else:
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
    if not automation_allowed(args.control_file, org=args.telemetry_org,
                              generation=args.expected_generation):
        raise SystemExit("MAX POWER apagado o permiso de sesión inválido")
    target, metadata_path, metadata, checkpoint = safe_output(args, bundle, attestation)
    torch.set_num_threads(min(2, os.cpu_count() or 1))
    torch.set_num_interop_threads(1)
    reporter = ProgressReporter(
        target,run_id=metadata["run_id"],org_id=args.telemetry_org,
        dataset_sha256=bundle["dataset_digest"],model=MODEL,
        telemetry_url=args.telemetry_url,
        telemetry_token=os.environ.get("GALANT_FINETUNE_TELEMETRY_TOKEN") if args.telemetry_url else None)
    reporter.data_kind = kind  # Propagate provenance to signed telemetry, never infer consent.
    resume_step = int(Path(checkpoint).name.rsplit("-", 1)[-1]) if checkpoint else 0
    state = {"step":resume_step,"paused":False,"weights_changed":False,
             "optimizer_start_hash":None,"optimizer_start_step":resume_step}
    try:
        reporter.emit("start",step=resume_step,total_steps=args.max_steps,
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
        _, trainable_count = hash_trainable(model,torch)
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
            def on_train_begin(self, args, state_, control, **kwargs):
                # Trainer loads the checkpoint *before* on_train_begin.
                # Hash restored adapters here, never the fresh random LoRA.
                live_model = kwargs.get("model")
                if live_model is None:
                    raise RuntimeError("No se pudo verificar el modelo entrenable")
                state["optimizer_start_hash"], _ = hash_trainable(live_model, torch)
                state["optimizer_start_step"] = int(state_.global_step)
                state["step"] = int(state_.global_step)

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
                if (should_pause(snapshot(target))
                        or not automation_allowed(
                            args.control_file, org=args.telemetry_org,
                            generation=args.expected_generation)):
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
        if not automation_allowed(args.control_file, org=args.telemetry_org,
                                  generation=args.expected_generation):
            state["paused"] = True
            reporter.emit("paused", step=state["step"], total_steps=args.max_steps,
                          cpu_memory_mb=process_memory_mb(), weights_trained=False)
            return 3
        trainer.train(resume_from_checkpoint=checkpoint)
        end_digest, _ = hash_trainable(model,torch)
        state["weights_changed"] = verified_optimizer_update(
            start_hash=state["optimizer_start_hash"],
            end_hash=end_digest,
            start_step=state["optimizer_start_step"],
            end_step=int(trainer.state.global_step))
        new_updates = max(0, int(trainer.state.global_step) - state["optimizer_start_step"])
        proof = {
            "optimizer_start_sha256": state["optimizer_start_hash"],
            "optimizer_end_sha256": end_digest,
            "optimizer_steps_new": new_updates,
        } if state["weights_changed"] else {}
        if state["paused"]:
            reporter.emit("paused",step=trainer.state.global_step,
                          total_steps=args.max_steps,cpu_memory_mb=process_memory_mb(),
                          weights_trained=state["weights_changed"], **proof)
            return 3
        if not state["weights_changed"]:
            raise RuntimeError(
                "No se verificaron pasos NUEVOS de optimización ni cambios "
                "de pesos LoRA después de restaurar el checkpoint")
        final = trainer.evaluate(eval_dataset=holdout,metric_key_prefix="holdout_after").get("holdout_after_loss")
        # Loss alone does not establish improved reasoning. Candidate stays
        # held until independently checked against reserved responses.
        report={
            "status":"synthetic_development_adapter_not_for_production" if args.synthetic_development
                     else "trained_adapter_requires_holdout_reasoning_checks",
            "data_kind":kind,
            "base_model":MODEL,"production_promoted":False,
            "weights_trained":True,
            "lora_weights_changed":True,
            "trainable_parameters":trainable_count,
            "steps":trainer.state.global_step,
            "new_optimizer_steps":new_updates,
            "optimizer_start_sha256":proof["optimizer_start_sha256"],
            "optimizer_end_sha256":proof["optimizer_end_sha256"],
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
                      weights_trained=True,candidate_accepted=False,**proof)
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
