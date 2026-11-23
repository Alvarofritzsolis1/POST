#!/usr/bin/env python3
"""Optional OFFLINE LoRA fine-tuning of Qwen3.5-4B on human-approved examples.

Never run on the live Ollama service. No model is automatically promoted.
Dry-run validates the real dataset without installing Torch/TRL or reading
production chats. --execute requires a dedicated CUDA GPU and explicit action.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "backend"))
from app.galancito_finetune_dataset import MODEL, load_approved, verified_match


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="GALANT · entrenamiento neuronal supervisado aislado")
    p.add_argument("--dataset", required=True, help="JSONL privado, curado, con permisos explícitos")
    p.add_argument("--output", help="Directorio privado de resultados (obligatorio para --execute)")
    p.add_argument("--execute", action="store_true",
                   help="Ejecuta gradientes LoRA con GPU, sin afectar el modelo de producción")
    p.add_argument("--epochs", type=int, default=1, choices=[1, 2, 3])
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
        from peft import LoraConfig
        from transformers import AutoTokenizer, Qwen3_5ForCausalLM
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise SystemExit("Instala PyTorch CUDA, Transformers 5+, datasets, peft y trl "
                         "en una máquina de entrenamiento aislada") from exc
    if not torch.cuda.is_available():
        raise SystemExit("Sin GPU CUDA: no se entrena en el VPS de atención")
    free, _ = torch.cuda.mem_get_info()
    if free < 9 * 1024 ** 3:
        raise SystemExit("Menos de 9 GiB libres de GPU; no se arriesga un proceso incompleto")
    output_dir = Path(args.output).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit("El directorio de salida debe estar vacío para evitar mezclas de versiones")
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=False)
    model = Qwen3_5ForCausalLM.from_pretrained(
        MODEL, dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
        device_map="auto", trust_remote_code=False,
    )
    def examples(split):
        return Dataset.from_list([{
            "prompt": [{"role": "system", "content": "Responde en español. Razona con evidencias sin inventar hechos."},
                       dict(row["messages"][0])],
            "completion": [dict(row["messages"][1])],
        } for row in bundle["samples"][split]])
    train, validation, test = examples("train"), examples("validation"), examples("test")
    config = SFTConfig(
        output_dir=str(output_dir / "checkpoints"), num_train_epochs=args.epochs,
        learning_rate=8e-5, per_device_train_batch_size=1, gradient_accumulation_steps=8,
        max_length=1024, completion_only_loss=True,
        eval_strategy="epoch", save_strategy="epoch",
        load_best_model_at_end=True, metric_for_best_model="eval_loss",
        greater_is_better=False, report_to="none", logging_steps=10,
        bf16=torch.cuda.is_bf16_supported(), fp16=not torch.cuda.is_bf16_supported(),
    )
    trainer = SFTTrainer(
        model=model, args=config,
        train_dataset=train, eval_dataset=validation,
        peft_config=LoraConfig(
            r=16, lora_alpha=32, lora_dropout=0.05,
            target_modules="all-linear", bias="none", task_type="CAUSAL_LM",
        ),
        processing_class=tokenizer,
    )
    # Deterministic, human-referenced *held-out answer* checks, not self-grading.
    # Test examples never participate in training or validation selection.
    def checked_answers():
        trainer.model.eval()
        outcomes = []
        for example in bundle["samples"]["test"]:
            prompt = [
                {"role": "system", "content": "Responde en español. Razona con evidencias sin inventar hechos."},
                example["messages"][0],
            ]
            input_ids = tokenizer.apply_chat_template(
                prompt, add_generation_prompt=True, return_tensors="pt"
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

    before_loss = trainer.evaluate(eval_dataset=test, metric_key_prefix="test_before").get("test_before_loss")
    before_checks = checked_answers()
    trainer.train()  # Real LoRA gradient updates in isolated GPU, NOT Ollama.
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
        "status": "candidate_held_for_review" if improved else "rejected_no_heldout_loss_gain",
        "weights_trained": True, "production_promoted": False,
        "base_model": MODEL, "dataset_digest": bundle["dataset_digest"],
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
    print(json.dumps(report, ensure_ascii=False))
    return 0 if improved else 2


if __name__ == "__main__":
    raise SystemExit(main())
