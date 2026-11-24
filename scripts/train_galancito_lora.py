#!/usr/bin/env python3
"""Optional OFFLINE LoRA fine-tuning of Qwen3.5-2B on human-approved examples.

Never run on the live Ollama service. No model is automatically promoted.
Dry-run validates the real dataset without installing Torch/TRL or reading
production chats. --execute requires a dedicated CUDA GPU and explicit action.
"""
import argparse
import json
import os
from math import ceil
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "backend"))
from galancito_lora_progress import ProgressReporter
from app.galancito_finetune_dataset import (MODEL, load_approved, verified_match,
                                             verified_training_manifest)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="GALANT · entrenamiento neuronal supervisado aislado")
    p.add_argument("--dataset", required=True, help="JSONL privado, curado, con permisos explícitos")
    p.add_argument("--output", help="Directorio privado de resultados (obligatorio para --execute)")
    p.add_argument("--approval-manifest",
                   help="Manifest firmado independientemente que autoriza exactamente el SHA256 del JSONL")
    p.add_argument("--execute", action="store_true",
                   help="Ejecuta gradientes LoRA con GPU, sin afectar el modelo de producción")
    p.add_argument("--epochs", type=int, default=1, choices=[1, 2, 3])
    p.add_argument("--resume", action="store_true", help="Reanuda un checkpoint de la misma ejecución autorizada")
    p.add_argument("--telemetry-url", help="URL HTTPS del endpoint firmado de GALANT")
    p.add_argument("--telemetry-org", help="UUID de organización que verá las métricas")
    args = p.parse_args(argv)
    bundle = load_approved(args.dataset)
    print(json.dumps({
        "status": "format_and_attestations_checked_not_trained",
        "model": MODEL, "sizes": bundle["sizes"],
        "criteria": bundle["criteria"], "digest": bundle["dataset_digest"],
        "warning": "La autoría, consentimiento y procedencia NO se autentican criptográficamente; "
                   "el operador debe verificar la evidencia y el permiso de cada ejemplo. "
                   "El script jamás extrae conversaciones de Messenger.",
    }, ensure_ascii=False))
    if not args.execute:
        return 0
    if not args.approval_manifest:
        raise SystemExit("--execute exige --approval-manifest Ed25519 firmado por un responsable")
    key = os.environ.get("GALANT_DATASET_APPROVAL_PUBLIC_KEY", "")
    try:
        attestation = verified_training_manifest(args.dataset, args.approval_manifest,
                                                 key, dataset_digest=bundle["dataset_digest"])
    except ValueError as exc:
        raise SystemExit("Dataset NO autorizado: " + str(exc)) from exc
    if not args.output or not Path(args.output).is_absolute():
        raise SystemExit("--execute exige --output con ruta absoluta y privada")
    repo_root = Path(__file__).resolve().parents[1]
    source = Path(args.dataset).resolve()
    if source.is_relative_to(repo_root):
        raise SystemExit("El JSONL privado no puede estar dentro del repositorio")
    if os.name == "posix" and (source.stat().st_mode & 0o077):
        raise SystemExit("El JSONL requiere permisos 0600 para que otros usuarios no lo lean")
    if not os.environ.get("GALANT_OFFLINE_TRAINING_APPROVED") == "yes":
        raise SystemExit("Se requiere GALANT_OFFLINE_TRAINING_APPROVED=yes")
    if Path(args.output).resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise SystemExit("No guardes adaptadores ni datos privados dentro del repositorio")
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, prepare_model_for_kbit_training, get_peft_model
        from transformers import AutoTokenizer, BitsAndBytesConfig, Qwen3_5ForConditionalGeneration, TrainerCallback
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise SystemExit("Instala PyTorch CUDA, Transformers 5+, datasets, peft y trl "
                         "en una máquina de entrenamiento aislada") from exc
    if not torch.cuda.is_available():
        raise SystemExit("Sin GPU CUDA: no se entrena en el VPS de atención")
    free, _ = torch.cuda.mem_get_info()
    if free < 16 * 1024 ** 3:
        raise SystemExit("Menos de 16 GiB libres de GPU: insuficiente para habilitar este perfil "
                         "conservador QLoRA; se recomienda una GPU dedicada con más margen")
    output_dir = Path(args.output).resolve()
    metadata_path = output_dir / "run-metadata.json"
    if args.resume:
        if not metadata_path.is_file():
            raise SystemExit("--resume requiere un manifiesto previo con el mismo dataset autorizado")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (metadata.get("dataset_sha256") != bundle["dataset_digest"]
                or metadata.get("approval_fingerprint") != attestation["key_fingerprint"]
                or metadata.get("epochs") != args.epochs or metadata.get("base_model") != MODEL
                or metadata.get("telemetry_org") != args.telemetry_org):
            raise SystemExit("El checkpoint no coincide con el dataset, permiso, organización o parámetros")
        checkpoints = sorted(
            (output_dir / "checkpoints").glob("checkpoint-*"),
            key=lambda path: int(path.name.rsplit("-", 1)[-1])
            if path.name.rsplit("-", 1)[-1].isdigit() else -1
        )
        if not checkpoints:
            raise SystemExit("No existe un checkpoint neuronal recuperable")
        resume_checkpoint = str(checkpoints[-1])
    else:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise SystemExit("El directorio de salida debe estar vacío para evitar mezclar versiones")
        output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        metadata = {
            "run_id": str(uuid4()), "base_model": MODEL,
            "dataset_sha256": bundle["dataset_digest"],
            "approval_fingerprint": attestation["key_fingerprint"],
            "epochs": args.epochs, "telemetry_org": args.telemetry_org,
        }
        metadata_path.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
        metadata_path.chmod(0o600)
        resume_checkpoint = None
    reporter = ProgressReporter(
        output_dir, run_id=metadata["run_id"],
        org_id=args.telemetry_org, dataset_sha256=bundle["dataset_digest"],
        telemetry_url=args.telemetry_url,
        telemetry_token=os.environ.get("GALANT_FINETUNE_TELEMETRY_TOKEN") if args.telemetry_url else None,
    )
    def gpu_metrics():
        return {
            "gpu_memory_mb": round(torch.cuda.memory_allocated() / 1048576, 2),
            "gpu_memory_reserved_mb": round(torch.cuda.memory_reserved() / 1048576, 2),
        }
    reporter.emit("start", step=0, total_steps=0, **gpu_metrics())
    tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=False)
    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=compute_dtype,
    )
    model = Qwen3_5ForConditionalGeneration.from_pretrained(
        MODEL, dtype=compute_dtype, quantization_config=quantization,
        device_map={"": torch.cuda.current_device()}, trust_remote_code=False,
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    # Qwen3.5-2B is multimodal. PEFT must target the genuine language decoder
    # in the official ConditionalGeneration architecture, not the vision
    # tower and not a differently mapped text-only wrapper.
    decoder_linear = [
        name for name, layer in model.named_modules()
        if "language_model" in name and isinstance(layer, torch.nn.Linear)
        and not name.endswith(("lm_head", "output"))
    ]
    if not decoder_linear:
        raise SystemExit("Arquitectura Qwen3.5 incompatible: no se localizaron capas lineales del decodificador")
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=decoder_linear, bias="none", task_type="CAUSAL_LM",
    ))
    if any("visual" in name or "vision" in name
           for name, weight in model.named_parameters() if weight.requires_grad):
        raise SystemExit("La torre visual no debe actualizarse en el entrenamiento de texto")
    SYSTEM_POLICY = "Responde en español. Razona con evidencias sin inventar hechos."
    def formatted_prompt(message):
        return tokenizer.apply_chat_template(
            [{"role": "system", "content": SYSTEM_POLICY}, dict(message)],
            tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )
    def examples(split):
        # Explicit textual prompt/completion avoids training on internal
        # <think> tokens or instructing the model to disclose hidden reasoning.
        return Dataset.from_list([{
            "prompt": formatted_prompt(row["messages"][0]),
            "completion": row["messages"][1]["content"] + tokenizer.eos_token,
        } for row in bundle["samples"][split]])
    train, validation, test = examples("train"), examples("validation"), examples("test")
    steps_per_epoch = ceil(len(train) / 8)
    planned_steps = steps_per_epoch * args.epochs
    checkpoint_steps = max(1, min(10, ceil(steps_per_epoch / 2)))
    config = SFTConfig(
        output_dir=str(output_dir / "checkpoints"), num_train_epochs=args.epochs,
        learning_rate=8e-5, per_device_train_batch_size=1, gradient_accumulation_steps=8,
        max_length=1024, completion_only_loss=True, gradient_checkpointing=True,
        eos_token=tokenizer.eos_token,
        eval_strategy="steps", eval_steps=checkpoint_steps,
        save_strategy="steps", save_steps=checkpoint_steps, save_total_limit=3,
        load_best_model_at_end=True, metric_for_best_model="eval_loss",
        greater_is_better=False, report_to="none", logging_steps=1,
        bf16=torch.cuda.is_bf16_supported(), fp16=not torch.cuda.is_bf16_supported(),
    )
    trainer = SFTTrainer(
        model=model, args=config,
        train_dataset=train, eval_dataset=validation,
        processing_class=tokenizer,
    )

    class MeasuredProgress(TrainerCallback):
        def on_train_begin(self, args, state, control, **kwargs):
            reporter.emit("start", step=state.global_step,
                          total_steps=state.max_steps or planned_steps, **gpu_metrics())

        def on_log(self, args, state, control, logs=None, **kwargs):
            logs = logs or {}
            kind = "eval" if "eval_loss" in logs else "metric"
            values = {k: logs.get(k) for k in (
                "loss", "eval_loss", "learning_rate", "grad_norm",
                "train_samples_per_second")}
            reporter.emit(kind, step=state.global_step,
                          total_steps=state.max_steps or planned_steps,
                          epoch=state.epoch, **values, **gpu_metrics())

        def on_save(self, args, state, control, **kwargs):
            reporter.emit("checkpoint", step=state.global_step,
                          total_steps=state.max_steps or planned_steps,
                          epoch=state.epoch, **gpu_metrics())

    trainer.add_callback(MeasuredProgress())
    # Deterministic, human-referenced *held-out answer* checks, not self-grading.
    # Test examples never participate in training or validation selection.
    def checked_answers():
        trainer.model.eval()
        outcomes = []
        for example in bundle["samples"]["test"]:
            input_ids = tokenizer.apply_chat_template(
                [{"role": "system", "content": SYSTEM_POLICY}, example["messages"][0]],
                add_generation_prompt=True, enable_thinking=False,
                return_tensors="pt",
            ).to(trainer.model.device)
            with torch.inference_mode():
                generated = trainer.model.generate(
                    input_ids, max_new_tokens=160, do_sample=False,
                    pad_token_id=tokenizer.eos_token_id,
                )
            response = tokenizer.decode(generated[0, input_ids.shape[1]:],
                                        skip_special_tokens=True)
            if "</think>" in response:
                response = response.split("</think>")[-1].strip()
            outcomes.append(verified_match(
                response, example["reference_answer"], example["verifier"]))
        return outcomes

    if args.resume:
        if "baseline" not in metadata:
            raise SystemExit("No existe evaluación original intacta para reanudar el entrenamiento")
        before_loss = metadata["baseline"]["loss"]
        before_checks = metadata["baseline"]["checks"]
    else:
        before_loss = trainer.evaluate(eval_dataset=test, metric_key_prefix="test_before").get("test_before_loss")
        before_checks = checked_answers()
        metadata["baseline"] = {"loss": before_loss, "checks": before_checks}
        metadata_path.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
        metadata_path.chmod(0o600)
        reporter.emit("baseline", step=0, total_steps=planned_steps,
                      holdout_loss_before=before_loss, holdout_pass_before=sum(before_checks),
                      **gpu_metrics())
    try:
        trainer.train(resume_from_checkpoint=resume_checkpoint)  # Actual GPU gradients
    except Exception:
        # Keep signed dataset, local metrics and checkpoints for diagnosis.
        # Do not publish raw exception strings or any private training examples.
        reporter.emit("failed", step=trainer.state.global_step,
                      total_steps=trainer.state.max_steps or planned_steps,
                      **gpu_metrics())
        reporter.close()
        raise
    after_loss = trainer.evaluate(eval_dataset=test, metric_key_prefix="test_after").get("test_after_loss")
    after_checks = checked_answers()
    regressions = sum(x and not y for x, y in zip(before_checks, after_checks))
    recovered = sum(not x and y for x, y in zip(before_checks, after_checks))
    improved = (
        isinstance(before_loss, float) and isinstance(after_loss, float)
        and after_loss < before_loss and recovered >= 2 and regressions == 0
        and sum(after_checks) > sum(before_checks)
    )
    # The exact/contains verifier measures only documented reference checks.
    # Neither a lowered loss nor these checks establishes generalized reasoning.
    report = {
        "status": "candidate_held_for_review" if improved else "rejected_heldout_gate",
        "weights_trained": True, "production_promoted": False,
        "base_model": MODEL, "dataset_digest": bundle["dataset_digest"],
        "approval_key_fingerprint": attestation["key_fingerprint"],
        "approval_verified": True, "method": "QLoRA_4bit_NF4",
        "train_examples": bundle["sizes"]["train"],
        "validation_examples": bundle["sizes"]["validation"],
        "heldout_examples": bundle["sizes"]["test"],
        "heldout_loss_before": before_loss, "heldout_loss_after": after_loss,
        "heldout_verified_pass_before": sum(before_checks),
        "heldout_verified_pass_after": sum(after_checks),
        "heldout_recovered": recovered, "heldout_regressions": regressions,
        "reasoning_improvement_proven": False,
        "requires": "independent deterministic reasoning checks, safety regression, "
                    "latency, production canary approval and reversible deployment",
    }
    # Never put private texts in the report.
    (output_dir / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if improved:
        trainer.save_model(str(output_dir / "candidate-adapter"))
    else:
        # Never leave rejected LoRA checkpoints available for accidental rollout.
        from shutil import rmtree
        rmtree(output_dir / "checkpoints", ignore_errors=True)
    reporter.emit("finished", step=trainer.state.global_step,
                  total_steps=trainer.state.max_steps or planned_steps,
                  holdout_loss_before=before_loss, holdout_loss_after=after_loss,
                  holdout_pass_before=sum(before_checks), holdout_pass_after=sum(after_checks),
                  holdout_regressions=regressions,
                  weights_trained=True, candidate_accepted=improved, **gpu_metrics())
    reporter.close()
    print(json.dumps(report, ensure_ascii=False))
    return 0 if improved else 2


if __name__ == "__main__":
    raise SystemExit(main())
