"""Curated, entirely invented GALANT intake examples for a PRIVATE CPU LoRA lab.

Never use real chats, contractor records, fabricated approval or personal data.
A deterministic code-derived digest protects the private lab input against edits.
This is a development exercise, NOT production learning evidence or consent.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

SPECIALTIES = (
    "carpintería", "albañilería", "electricidad", "gasfitería",
    "pintura", "cerámica", "yesería", "soldadura", "enfierradura",
    "techumbre",
)
VERSION = "galant-curated-synthetic-intake-1"

def examples():
    for specialty in SPECIALTIES:
        tasks = (
            ("profile", f"Hola, soy de {specialty} y busco pega.",
             f"Hola, gracias por escribir. ¿En qué comuna buscas trabajo en {specialty}?"),
            ("profile", f"Trabajo en {specialty} hace cinco años, me interesa postular.",
             "Perfecto, anoté tus cinco años de experiencia. ¿En qué comuna estás disponible?"),
            ("accuracy", f"Tengo dos ayudantes y trabajamos en {specialty}. ¿Podemos ir los tres?",
             "Entiendo, son tres personas incluyéndote. ¿En qué comuna pueden trabajar?"),
            ("grounding", f"Vi un aviso para {specialty}. ¿Cuánto están pagando?",
             "Para confirmar el pago, ¿me indicas cuál aviso u obra viste? No tengo un monto confirmado."),
            ("understanding", f"Me dedico a {specialty} por mi cuenta y quiero ofrecer servicios.",
             f"Entiendo, ofreces servicios de {specialty} como independiente. ¿En qué comunas trabajas?"),
            ("grounding", f"¿Quedan cupos para {specialty} en la obra que publicaron?",
             "¿Qué obra o aviso viste? Así puedo orientarte sin confirmarte cupos que no he verificado."),
            ("context", f"Soy de {specialty} y puedo empezar el próximo lunes.",
             "Perfecto, anoté que tienes disponibilidad desde el próximo lunes. ¿En qué comuna estás?"),
            ("naturalness", f"Buenas, ¿con quién hablo? Quería consultar por {specialty}.",
             f"¡Hola! Te puedo orientar con tu consulta de {specialty}. ¿Qué necesitas saber?"),
            ("safety", f"Trabajo en {specialty}, pero no quiero compartir mi teléfono todavía.",
             "Está bien, podemos seguir conversando por aquí. ¿En qué comuna estás disponible?"),
            ("understanding", f"Ofrezco {specialty} y además estoy buscando trabajo dependiente.",
             f"Entendido, buscas trabajo y también ofreces servicios de {specialty}. ¿En qué comuna te interesa?"),
        )
        for index, (criterion, question, answer) in enumerate(tasks):
            group = sha256(f"{VERSION}:{specialty}:{index}".encode()).hexdigest()
            yield {
                "source": "curated_synthetic", "case_group": group,
                "criterion": criterion, "verifier": "exact",
                "messages": [{"role": "user", "content": question},
                             {"role": "assistant", "content": answer}],
                "reference_answer": answer,
            }

def dataset_bytes():
    return "".join(json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                   for case in examples()).encode("utf-8")

def verify_dataset(path):
    """Accept only the exact public, versioned, synthetic corpus from code."""
    from app.galancito_finetune_dataset import bucket, MINIMUM, PROHIBITED, ALLOWED_CRITERIA
    blob = Path(path).read_bytes()
    expected = dataset_bytes()
    if blob != expected:
        raise ValueError("El corpus sintético fue modificado; no entrenar")
    splits = {"train": [], "validation": [], "test": []}
    for case in examples():
        assert case["criterion"] in ALLOWED_CRITERIA
        assert all(not PROHIBITED.search(part["content"]) for part in case["messages"])
        assert not PROHIBITED.search(case["reference_answer"])
        splits[bucket(case["case_group"])].append(case)
    sizes = {key: len(value) for key, value in splits.items()}
    if any(sizes[key] < minimum for key, minimum in MINIMUM.items()):
        raise ValueError("El corpus sintético no satisface particiones independientes")
    return {
        "samples": splits, "sizes": sizes,
        "dataset_digest": sha256(blob).hexdigest(),
        "data_kind": "curated_synthetic",
        "human_approval_independently_verified": False,
        "attestations_present": False,
    }

def prepare_lab(org_root):
    """Materialize code-owned examples without touching approved real datasets."""
    root = Path(org_root)
    if root.is_symlink():
        raise ValueError("Directorio privado simbólico no permitido")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lab = root / "synthetic-lab"
    if lab.is_symlink():
        raise ValueError("Directorio de laboratorio simbólico no permitido")
    lab.mkdir(mode=0o700, exist_ok=True)
    lab.chmod(0o700)
    path = lab / "synthetic.jsonl"
    if path.is_symlink():
        raise ValueError("Corpus de laboratorio simbólico no permitido")
    if not path.exists():
        path.write_bytes(dataset_bytes())
        path.chmod(0o600)
    if path.stat().st_mode & 0o077:
        raise ValueError("Corpus sintético requiere permisos 0600")
    bundle = verify_dataset(path)
    return lab, bundle
