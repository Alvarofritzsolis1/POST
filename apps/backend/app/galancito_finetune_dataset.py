"""Validation gate for *real*, explicitly approved supervised Qwen examples.

Never bulk-copy GALANT/Messenger chats into a model dataset.  The operator
supplies an independently reviewed, consented, anonymized JSONL.  These
checks reject obvious personal data, duplicate prompts and data leakage; they
do NOT replace a human privacy review.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

MODEL = "Qwen/Qwen3.5-4B"
ALLOWED_CRITERIA = frozenset({
    "reasoning", "accuracy", "grounding", "context", "understanding",
    "profile", "naturalness", "helpfulness", "safety",
})
REQUIRED = frozenset({
    "source", "approved_by", "usage_authorized", "privacy_reviewed",
    "case_group", "criterion", "messages", "reference_answer",
    "verifier",
})
MINIMUM = {"train": 30, "validation": 10, "test": 10}
SPLITS = ("train", "validation", "test")
PROHIBITED = re.compile(
    r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|"
    r"(?<!\d)(?:\+?56[\s.-]?)?9[\s.-]?\d{4}[\s.-]?\d{4}(?!\d)|"
    r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[0-9kK]\b|"
    r"(?i:(?:api[_ ]?key|password|contraseña|claveúnica|bearer\s+)[\s:=]+\S+)|"
    r"(?i:(?:sk-|gsk_|nvapi-|AIza)[A-Za-z0-9_\-]{8,})"
)


def bucket(group: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", group):
        raise ValueError("case_group debe ser un hash SHA256 sin identificadores personales")
    number = int(sha256(("galant-22-split-" + group).encode()).hexdigest()[:12], 16) % 100
    return "train" if number < 70 else "validation" if number < 85 else "test"


def _checked(item: dict, line: int) -> dict:
    if not isinstance(item, dict) or not REQUIRED <= item.keys():
        raise ValueError(f"Línea {line}: faltan campos de procedencia o de verificación")
    if (item["source"] != "human_reviewed_real" or
            item["usage_authorized"] is not True or item["privacy_reviewed"] is not True):
        raise ValueError(f"Línea {line}: no autorizado como dato de entrenamiento real")
    if not isinstance(item["approved_by"], str) or not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", item["approved_by"]):
        raise ValueError(f"Línea {line}: aprobación humana individual no verificable")
    if item["criterion"] not in ALLOWED_CRITERIA:
        raise ValueError(f"Línea {line}: competencia no permitida")
    if item["verifier"] not in {"exact", "contains"}:
        raise ValueError(f"Línea {line}: falta verificador objetivo del resultado")
    messages = item["messages"]
    if (not isinstance(messages, list) or len(messages) != 2 or
            [part.get("role") for part in messages if isinstance(part, dict)] !=
            ["user", "assistant"]):
        raise ValueError(f"Línea {line}: deben existir pregunta y respuesta humana corregida")
    raw = []
    for msg in messages:
        if set(msg) != {"role", "content"} or not isinstance(msg["content"], str):
            raise ValueError(f"Línea {line}: formato del ejemplo inválido")
        value = msg["content"].strip()
        if len(value) < 5 or len(value) > 1100:
            raise ValueError(f"Línea {line}: largo de ejemplo inadecuado")
        raw.append(value)
    expected = item["reference_answer"]
    if not isinstance(expected, str) or not 2 <= len(expected.strip()) <= 400:
        raise ValueError(f"Línea {line}: respuesta de referencia ausente")
    if any(PROHIBITED.search(value) for value in (*raw, expected)):
        raise ValueError(f"Línea {line}: contiene dato personal o credencial; no se entrena")
    if not verified_match(raw[1], expected, item["verifier"]):
        raise ValueError(f"Línea {line}: la respuesta corregida no coincide con la referencia verificada")
    split = bucket(item["case_group"])
    return {
        "split": split, "group": item["case_group"], "criterion": item["criterion"],
        "messages": [{"role": "user", "content": raw[0]},
                     {"role": "assistant", "content": raw[1]}],
        "reference_answer": expected.strip(),
        "verifier": item["verifier"],
    }


def load_approved(path: str | Path, *, enforce_minimum: bool = True) -> dict:
    dataset_path = Path(path)
    if not dataset_path.is_file() or dataset_path.stat().st_size > 12_000_000:
        raise ValueError("Datos no disponibles o demasiado grandes para esta versión")
    partitions = {name: [] for name in SPLITS}
    seen_questions: set[str] = set()
    seen_groups: dict[str, str] = {}
    counts = Counter()
    with dataset_path.open(encoding="utf-8") as stream:
        for index, row in enumerate(stream, 1):
            if index > 50_000:
                raise ValueError("Supera 50.000 ejemplos; divide el proceso")
            if not row.strip():
                continue
            try:
                item = _checked(json.loads(row), index)
            except (TypeError, json.JSONDecodeError, AttributeError) as exc:
                raise ValueError(f"Línea {index}: JSON o campos no válidos") from exc
            question = " ".join(item["messages"][0]["content"].casefold().split())
            fingerprint = sha256(question.encode()).hexdigest()
            if fingerprint in seen_questions:
                raise ValueError(f"Línea {index}: pregunta repetida; evita sobreajuste o filtración")
            seen_questions.add(fingerprint)
            group = item["group"]
            if group in seen_groups and seen_groups[group] != item["split"]:
                raise ValueError(f"Línea {index}: mismo caso compartido entre particiones")
            seen_groups[group] = item["split"]
            partitions[item["split"]].append(item)
            counts[item["criterion"]] += 1
    sizes = {name: len(rows) for name, rows in partitions.items()}
    if enforce_minimum and any(sizes[k] < n for k, n in MINIMUM.items()):
        raise ValueError(
            "Datos reales insuficientes: se requieren al menos " +
            ", ".join(f"{n} en {k}" for k, n in MINIMUM.items()) +
            f"; disponible: {sizes}"
        )
    return {"samples": partitions, "sizes": sizes, "criteria": dict(counts),
            "dataset_digest": sha256(dataset_path.read_bytes()).hexdigest(),
            "attestations_present": True,
            "human_approval_independently_verified": False}



def verified_training_manifest(dataset_file: str | Path, manifest_file: str | Path,
                               public_key_hex: str, *, dataset_digest: str | None = None) -> dict:
    """Verify a separate administrator signature over the exact approved data.

    Ed25519 authenticates the *signer's assertion* (not the truth of a
    conversation). The signing key and approval evidence never enter GALANT.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not isinstance(public_key_hex, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", public_key_hex):
        raise ValueError("Falta clave pública Ed25519 válida, de 32 bytes")
    path = Path(manifest_file)
    if not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("Manifest de autorización no disponible o demasiado grande")
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Manifest de autorización corrupto") from exc
    expected_fields = {
        "dataset_sha256", "approved_by", "approved_at", "privacy_reviewed",
        "usage_authorized", "training_model", "purpose", "signature_ed25519",
    }
    if not isinstance(wrapper, dict) or set(wrapper) != expected_fields:
        raise ValueError("Manifest de autorización incompleto o no permitido")
    signature = wrapper.pop("signature_ed25519")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-fA-F]{128}", signature):
        raise ValueError("Firma Ed25519 no válida")
    statement = json.dumps(wrapper, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(
            bytes.fromhex(signature), statement,
        )
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("Firma del conjunto de datos inválida o no autorizada") from exc
    digest = dataset_digest or sha256(Path(dataset_file).read_bytes()).hexdigest()
    if (wrapper["dataset_sha256"] != digest or wrapper["training_model"] != MODEL
            or wrapper["usage_authorized"] is not True
            or wrapper["privacy_reviewed"] is not True
            or wrapper["purpose"] != "offline_galant_finetune_qwen"):
        raise ValueError("El manifiesto no aprueba exactamente estos datos y este modelo")
    if not isinstance(wrapper["approved_by"], str) or not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            wrapper["approved_by"]):
        raise ValueError("Identificador del aprobador no válido")
    if not isinstance(wrapper["approved_at"], str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", wrapper["approved_at"]):
        raise ValueError("Fecha de autorización en UTC no válida")
    return {
        "signed": True, "dataset_digest": digest,
        "approved_by": wrapper["approved_by"],
        "approved_at": wrapper["approved_at"],
        "key_fingerprint": sha256(bytes.fromhex(public_key_hex)).hexdigest()[:16],
    }


def verified_match(answer: str, expected: str, verifier: str) -> bool:
    """Deterministic *limited* check; not a judge of general reasoning."""
    norm = lambda x: " ".join(str(x).strip().casefold().split())
    a, e = norm(answer), norm(expected)
    return a == e if verifier == "exact" else e in a
