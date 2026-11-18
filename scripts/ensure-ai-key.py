#!/usr/bin/env python3
"""Provision GALANT's encryption secret ON THE VPS only, never in GitHub Actions.

The host's existing .env.preview is the single persistent source of truth.
Safe on repeated deployments; never rotate an existing key or print its value.
"""
from __future__ import annotations

import base64
import fcntl
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile

NAME = "AI_CREDENTIAL_ENCRYPTION_KEY"
PATTERN = re.compile(r"^AI_CREDENTIAL_ENCRYPTION_KEY[ \t]*=[ \t]*(.*)$")


def valid_fernet_key(value: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}=", value):
        return False
    try:
        return len(base64.urlsafe_b64decode(value)) == 32
    except (ValueError, TypeError):
        return False


def ensure(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("No existe un archivo de entorno privado regular")
    if path.stat().st_mode & 0o077:
        # Do not store a master key where other host users can read it.
        path.chmod(0o600)
    lock_path = path.with_name(path.name + ".ai-key.lock")
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines()
            matched = [(i, m.group(1).strip()) for i, line in enumerate(lines)
                       if (m := PATTERN.match(line))]
            if len(matched) > 1:
                raise RuntimeError("Hay varias definiciones de la clave maestra. Revisar el entorno.")
            if matched:
                i, existing = matched[0]
                if existing.startswith(("'", '"')) and existing.endswith(existing[:1]):
                    existing = existing[1:-1]
                if existing:
                    if not valid_fernet_key(existing):
                        raise RuntimeError("La clave maestra actual no es válida; se conservó sin cambios.")
                    return "existing"
            # An explicitly supplied environment variable is never replaced silently.
            inherited = os.environ.get(NAME, "").strip()
            if inherited and not valid_fernet_key(inherited):
                raise RuntimeError("La clave maestra del proceso no es válida.")
            key = inherited or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
            if matched:
                lines[matched[0][0]] = NAME + "=" + key
            else:
                lines.append(NAME + "=" + key)
            new_content = "\n".join(lines) + "\n"
            # Atomic replacement prevents a truncated secret on power loss.
            target_fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".galant-ai-secret-")
            try:
                with os.fdopen(target_fd, "w", encoding="utf-8") as stream:
                    os.fchmod(stream.fileno(), stat.S_IRUSR | stat.S_IWUSR)
                    stream.write(new_content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, path)
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            return "generated"
    except OSError as exc:
        raise RuntimeError("No se pudo guardar la clave en el entorno privado.") from None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Uso: ensure-ai-key.py RUTA_ENV_PRIVADO", file=sys.stderr)
        return 64
    try:
        state = ensure(Path(argv[1]).resolve())
    except (RuntimeError, OSError, UnicodeError) as exc:
        print("Centro IA: " + str(exc), file=sys.stderr)
        return 1
    print("Centro IA: cifrado listo; clave " + ("conservada" if state == "existing" else "generada automáticamente") + ".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
