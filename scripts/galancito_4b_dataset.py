"""Exact, signed, private 4B corpora; never mine live chats or invent approval."""
import hashlib
import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from galancito_finetune_dataset import load_approved, verified_training_manifest, verified_match
except ImportError:
    from app.galancito_finetune_dataset import load_approved, verified_training_manifest, verified_match

MODEL = "Qwen/Qwen3.5-4B"


def secure_bytes(path, maximum):
    path = Path(path)
    if path.parent.is_symlink():
        raise ValueError("Invalid private dataset directory")
    fd = os.open(path,os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or not 0 < info.st_size <= maximum:
            raise ValueError("Invalid private input permissions or size")
        data = stream.read(maximum+1)
        if len(data) != info.st_size or len(data) > maximum:
            raise ValueError("Private input changed while reading")
        return data


def approved_bundle(dataset, manifest, public_key):
    # Snapshot exact bytes before validating. Do not validate one version then
    # train another because a mounted source changed between reads.
    raw = secure_bytes(dataset,12_000_000)
    signature = secure_bytes(manifest,4096)
    digest = hashlib.sha256(raw).hexdigest()
    with TemporaryDirectory(prefix="galant-4b-approved-") as directory:
        root = Path(directory)
        data = root / "data.jsonl"
        approval = root / "approval.json"
        data.write_bytes(raw)
        approval.write_bytes(signature)
        data.chmod(0o600)
        approval.chmod(0o600)
        verified_training_manifest(data,approval,public_key,dataset_digest=digest,training_model=MODEL)
        bundle = load_approved(data)
    if bundle["dataset_digest"] != digest:
        raise ValueError("Dataset digest mismatch")
    return bundle


def select_distinct(cases, maximum):
    # Round-robin criteria, one independent case group per selected example.
    groups = {}
    for case in cases:
        groups.setdefault(case["criterion"],[]).append(case)
    for rows in groups.values():
        rows.sort(key=lambda row: (row["group"],row["messages"][0]["content"]))
    selected,seen = [],set()
    while groups and len(selected)<maximum:
        for key in sorted(list(groups)):
            rows = groups[key]
            while rows and rows[0]["group"] in seen:
                rows.pop(0)
            if not rows:
                del groups[key]
                continue
            case = rows.pop(0)
            selected.append(case)
            seen.add(case["group"])
            if len(selected)>=maximum:
                break
    if len(selected)<maximum:
        raise ValueError("Insufficient independent case groups")
    return selected
