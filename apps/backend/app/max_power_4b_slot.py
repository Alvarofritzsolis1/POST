"""Local process lock for mutually exclusive 4B practice and neural diagnostics.

The only shared mount contains control metadata, not models, chats or secrets.
The controller and the opt-in supervisor run under the same dedicated UID.
"""
import fcntl
import json
import os
from pathlib import Path
from time import time
from uuid import uuid4

CONTROL = Path("/4b-control")


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_name("." + path.name + "." + uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def acquire_slot(root=CONTROL):
    """Return open FD holding exclusive ownership, or None if unavailable."""
    try:
        fd = os.open(Path(root) / "engine.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def release_slot(fd):
    if fd is not None:
        os.close(fd)


def valid_intent(intent, *, now=None):
    now = time() if now is None else now
    stamp = intent.get("at")
    return (intent.get("enabled") is True and intent.get("quiet") is True
            and type(stamp) in (int, float) and 0 <= now - stamp <= 20
            and isinstance(intent.get("org"), str)
            and type(intent.get("generation")) is int and intent["generation"] > 0)
