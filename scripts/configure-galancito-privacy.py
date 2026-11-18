#!/usr/bin/env python3
"""Safely configure confidential employer names on VPS only, never in GitHub."""
from __future__ import annotations

from getpass import getpass
from pathlib import Path
import os
import re
import stat
import sys
import tempfile

KEY = "GALANCITO_PRIVATE_COMPANY_NAMES"


def configure(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("No se encontró un archivo de entorno privado seguro")
    if path.stat().st_mode & 0o077:
        path.chmod(0o600)
    supplied = getpass("Nombres confidenciales, separados por coma (ocultos): ").strip()
    names = [name.strip() for name in supplied.split(",") if name.strip()]
    if not 1 <= len(names) <= 20:
        raise RuntimeError("Ingresa entre 1 y 20 nombres")
    if any(not 3 <= len(name) <= 80 or re.search(r'[\r\n"\\#$]', name) for name in names):
        raise RuntimeError("Hay un nombre inválido: evita caracteres especiales de entorno")
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    indexes = [i for i, line in enumerate(lines) if line.startswith(KEY + "=")]
    if len(indexes) > 1:
        raise RuntimeError("Existen definiciones duplicadas")
    line = KEY + '="' + ",".join(names) + '"'
    if indexes:
        lines[indexes[0]] = line
    else:
        lines.append(line)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".galant-privacy-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            os.fchmod(file.fileno(), stat.S_IRUSR | stat.S_IWUSR)
            file.write("\n".join(lines) + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("Protección configurada en el VPS. El nombre no se muestra ni se sube a GitHub.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: configure-galancito-privacy.py ARCHIVO_ENV_PRIVADO")
    try:
        configure(Path(sys.argv[1]).resolve())
    except (ValueError, UnicodeError, OSError, RuntimeError) as error:
        sys.exit("Error: " + str(error))
