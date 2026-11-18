"""Small offline topic classifier trained for 40 epochs on anonymized examples.

This is NOT Gemini/LLM fine tuning: only a local linear classifier is trained.
The approved FAQ bank is the actual source for Galancito's responses.
Uses Python standard library only and never sends requests to an AI provider.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata


CURRICULUM = Path(__file__).with_name("galancito_curriculum_2026.json")
EPOCHS = 40


def normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def features(value: str) -> dict[str, int]:
    words = normalize(value).split()
    stop = {"que", "como", "para", "una", "uno", "los", "las", "con",
            "por", "del", "esto", "esta", "quiero", "puedo", "hago",
            "hay", "debe", "soy", "mi", "me", "el", "en", "un", "a", "de"}
    words = [w for w in words if w not in stop and len(w) > 2][:36]
    out: dict[str, int] = {}
    for token in set(words):
        out["w:" + token] = 1
    for i in range(len(words) - 1):
        out["b:" + words[i] + "_" + words[i + 1]] = 1
    return out


def _score(weights: dict, category: str, values: dict[str, int]) -> float:
    w = weights[category]
    return sum(w.get(k, 0) * v for k, v in values.items())


def predict(weights: dict, value: str) -> tuple[str, float]:
    vals = features(value)
    if not vals:
        return "", 0
    scored = sorted((( _score(weights, cls, vals), cls) for cls in weights),
                    reverse=True)
    if not scored:
        return "", 0
    margin = scored[0][0] - (scored[1][0] if len(scored) > 1 else 0)
    return scored[0][1], round(margin, 2)


def train(epochs: int = EPOCHS) -> tuple[dict, dict]:
    if epochs != EPOCHS:
        raise ValueError("El programa está diseñado para 40 épocas verificables")
    corpus = json.loads(CURRICULUM.read_text(encoding="utf-8"))
    classes = sorted({case["category"] for case in corpus})
    examples = [(index, phrase, case["category"])
                for index, case in enumerate(corpus) for phrase in case["phrases"]]
    # Split by entire case, not by similar phrases, preventing answer leakage.
    training = [(text, group) for i, text, group in examples if i % 5 != 0]
    validation = [(text, group) for i, text, group in examples if i % 5 == 0]
    weights: dict[str, dict[str, int]] = {group: {} for group in classes}
    # Multiclass linear perceptron; deterministic and CPU-only.
    for epoch in range(epochs):
        order = training[epoch % len(training):] + training[:epoch % len(training)]
        for sample, expected in order:
            vals = features(sample)
            predicted, _ = predict(weights, sample)
            if predicted == expected:
                continue
            for key, value in vals.items():
                weights[expected][key] = weights[expected].get(key, 0) + value
                weights[predicted][key] = weights[predicted].get(key, 0) - value

    def accuracy(samples):
        return round(sum(predict(weights, sample)[0] == expected for sample, expected in samples)
                     / len(samples), 4) if samples else None

    report = {
        "kind": "offline-topic-perceptron",
        "model_is_generative": False,
        "epochs_completed": epochs,
        "curated_cases": len(corpus),
        "training_questions": len(training),
        "validation_questions": len(validation),
        "training_accuracy": accuracy(training),
        "holdout_accuracy": accuracy(validation),
        "categories": classes,
        "api_requests": 0,
        "provider_tokens_used": 0,
        "note": "Exactitud del clasificador temático, no de las respuestas de Galancito."
    }
    model = {"weights": weights, "report": report}
    return model, report


def save_model(destination: Path) -> dict:
    model, report = train()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise RuntimeError("No se puede escribir el modelo en un enlace simbólico")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                     dir=destination.parent, delete=False) as tmp:
        os.chmod(tmp.name, 0o600)
        json.dump(model, tmp, ensure_ascii=False, separators=(",", ":"))
        tmp.flush()
        os.fsync(tmp.fileno())
        path = tmp.name
    os.replace(path, destination)
    return report


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Aprendizaje local GALANT, sin API.")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--output", default="/data/private/galancito-topic-model.json")
    args = parser.parse_args()
    if args.epochs != EPOCHS:
        parser.error("Se admiten exactamente 40 épocas para este currículo.")
    report = save_model(Path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
