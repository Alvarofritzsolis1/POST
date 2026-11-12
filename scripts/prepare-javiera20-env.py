"""Create the VPS-only Calc credential atomically; never print its value."""
import os
from pathlib import Path
import re
import secrets
import stat
import sys


def prepare(path: Path):
    if path.is_symlink():
        raise SystemExit("El archivo privado Calc no puede ser un enlace simbólico")
    if not path.exists():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as stream:
                stream.write("JAVIERA_CALC_SECRET=" + secrets.token_urlsafe(48) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
    if not path.is_file() or not re.fullmatch(
        r"JAVIERA_CALC_SECRET=[A-Za-z0-9_-]{32,256}\n?", path.read_text()
    ):
        raise SystemExit("La configuración privada Calc no es válida; despliegue cancelado")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
