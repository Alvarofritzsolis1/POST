#!/usr/bin/env python3
"""Copy only the AI encryption key into the already-protected backup directory."""
import os
from pathlib import Path
import re
import sys

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader

SOURCE = Path(".env.preview")
LABEL = "AI_CREDENTIAL_ENCRYPTION_KEY"


def backup(directory: Path) -> bool:
    if SOURCE.is_symlink() or not SOURCE.is_file():
        raise RuntimeError("No existe el archivo de entorno privado")
    keys = re.findall(r"^AI_CREDENTIAL_ENCRYPTION_KEY[ \t]*=[ \t]*(.*)$",
                      SOURCE.read_text(encoding="utf-8"), re.MULTILINE)
    if len(keys) > 1:
        raise RuntimeError("Hay claves maestras duplicadas; respaldo cancelado")
    if not keys or not keys[0].strip():
        return False
    loader = SourceFileLoader("ai_key_validator", "scripts/ensure-ai-key.py")
    spec = spec_from_loader(loader.name, loader)
    mod = module_from_spec(spec)
    loader.exec_module(mod)
    value = keys[0].strip()
    if value.startswith(("'", '"')) and value.endswith(value[:1]):
        value = value[1:-1]
    if not mod.valid_fernet_key(value):
        raise RuntimeError("La clave maestra es inválida; respaldo cancelado")
    target = directory / "ai-key.env"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(LABEL + "=" + value + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Uso: backup-ai-key.py DIRECTORIO_PRIVADO", file=sys.stderr)
        return 64
    try:
        ready = backup(Path(argv[1]))
    except (RuntimeError, OSError, UnicodeError) as exc:
        print("Respaldo de IA cancelado: " + str(exc), file=sys.stderr)
        return 1
    print("Copia cifrado IA: " + ("incluida" if ready else "sin clave previa"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
