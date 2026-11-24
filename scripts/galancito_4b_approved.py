"""Read an immutable, signed, consented 4B dataset snapshot."""
import hashlib
import os
import stat
import tempfile
from pathlib import Path
from galancito_finetune_dataset import load_approved,verified_training_manifest

def private_bytes(path,limit):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or not 0<info.st_size<=limit:
            raise ValueError("Dataset input must be a bounded private regular file")
        with os.fdopen(os.dup(fd),"rb") as stream:
            value=stream.read(limit+1)
        if not 0<len(value)<=limit:
            raise ValueError("Dataset input exceeds safe limit")
        return value
    finally:
        os.close(fd)

def approved_bundle(root,public_key):
    root=Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Approved organization directory unavailable")
    content=private_bytes(root/"approved.jsonl",12000000)
    signed=private_bytes(root/"approval.json",4096)
    # The exact bytes verified are the same bytes parsed. No mutable source
    # can be substituted between signature verification and model training.
    with tempfile.TemporaryDirectory(prefix="galant-approved-") as work:
        dataset=Path(work)/"approved.jsonl"
        manifest=Path(work)/"approval.json"
        dataset.write_bytes(content)
        manifest.write_bytes(signed)
        bundle=load_approved(dataset)
        verified_training_manifest(dataset,manifest,public_key,
            dataset_digest=bundle["dataset_digest"],training_model="Qwen/Qwen3.5-4B")
        if hashlib.sha256(content).hexdigest()!=bundle["dataset_digest"]:
            raise RuntimeError("Approved digest mismatch")
        return bundle

def select_groups(rows,count):
    chosen=[]
    seen=set()
    # The approved partition is fixed by case group. One sample per group,
    # deterministic order, cycling across criteria when possible.
    buckets={}
    for row in rows:
        buckets.setdefault(row["criterion"],[]).append(row)
    while len(chosen)<count and any(buckets.values()):
        for criterion in sorted(buckets):
            while buckets[criterion]:
                item=buckets[criterion].pop(0)
                if item["group"] not in seen:
                    chosen.append(item)
                    seen.add(item["group"])
                    break
            if len(chosen)==count:
                break
    if len(chosen)!=count:
        raise ValueError("Insufficient independent short approved case groups")
    return chosen
