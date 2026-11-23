#!/usr/bin/env python3
"""Idempotent server-only secret for signed LoRA telemetry.

Does not enable training, access private examples, start Docker or print key.
The host's .env.preview remains the single persistent source of truth.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile

NAME = "GALANT_FINETUNE_METRICS_SECRET"
PATTERN = re.compile(r"^GALANT_FINETUNE_METRICS_SECRET[ \t]*=[ \t]*(.*)$")


def ensure(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Archivo de entorno privado ausente o enlazado")
    if path.stat().st_mode & 0o077:
        path.chmod(0o600)
    lock_file = path.with_name(path.name + ".finetune-metrics.lock")
    fd = os.open(lock_file, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            original = path.read_text(encoding="utf-8")
            rows = original.splitlines()
            matched = [(i, match.group(1).strip()) for i, row in enumerate(rows)
                       if (match := PATTERN.match(row))]
            if len(matched) > 1:
                raise RuntimeError("Hay definiciones duplicadas para la clave de telemetría")
            if matched:
                old = matched[0][1]
                if old.startswith(("'", '"')) and old.endswith(old[:1]):
                    old = old[1:-1]
                if old:
                    if len(old) < 48:
                        raise RuntimeError("La clave existente es demasiado corta; se conserva sin cambios")
                    return "existing"
            inherited = os.environ.get(NAME, "").strip()
            if inherited and len(inherited) < 48:
                raise RuntimeError("Clave de telemetría heredada demasiado corta")
            value = inherited or secrets.token_urlsafe(48)
            if matched:
                rows[matched[0][0]] = NAME + "=" + value
            else:
                rows.append(NAME + "=" + value)
            tmp_fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".galant-finetune-key-")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as stream:
                    os.fchmod(stream.fileno(), stat.S_IRUSR | stat.S_IWUSR)
                    stream.write("\n".join(rows) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp_name, path)
                dir_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            return "generated"
    except OSError:
        raise RuntimeError("No se pudo conservar la clave privada de métricas") from None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Uso: ensure-finetune-metrics-key.py RUTA_ENV_PRIVADO", file=sys.stderr)
        return 64
    try:
        state = ensure(Path(argv[1]))
    except (RuntimeError, OSError, UnicodeError) as exc:
        print("MAX POWER: " + str(exc), file=sys.stderr)
        return 1
    print("MAX POWER: firma de métricas lista; clave "
          + ("conservada" if state == "existing" else "generada en el servidor") + ".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
