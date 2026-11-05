#!/usr/bin/env python3
"""Determina si un push a main aprueba una *nueva* versión para el VPS.

El único indicador de una versión autorizada es un incremento coherente
de versión backend + frontend + lockfile, confirmado tras merge a main.
Un push que solo cambie documentación, código o tests no activa despliegue.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

FILES = ("apps/backend/app/version.py", "apps/frontend/package.json", "apps/frontend/package-lock.json")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)(?:-rc([1-9][0-9]*))?$")
API_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.MULTILINE)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.PIPE).strip()


def api_version(text: str) -> str:
    match = API_RE.search(text)
    if not match:
        raise ValueError("No se encontró VERSION en backend")
    return match.group(1)


def release_tuple(version: str) -> tuple[int, int, int, int]:
    match = VERSION_RE.fullmatch(version)
    if not match:
        raise ValueError(f"Versión inválida: {version!r}")
    major, minor, patch = (int(x) for x in match.groups()[:3])
    # -rcN es anterior a versión final; no permitir rebajar una versión final.
    rc = int(match.group(4)) if match.group(4) else 100_000
    return major, minor, patch, rc


def release_versions(source):
    backend = api_version(source(FILES[0]))
    frontend = json.loads(source(FILES[1]))["version"]
    lock = json.loads(source(FILES[2]))
    if frontend != backend or lock["version"] != backend or lock["packages"][""]["version"] != backend:
        raise ValueError("Las versiones backend, frontend y lockfile no coinciden")
    release_tuple(backend)
    return backend


def check(base: str, head: str) -> tuple[bool, str]:
    if not SHA_RE.fullmatch(base) or not SHA_RE.fullmatch(head):
        raise ValueError("La comprobación requiere 2 SHA de 40 caracteres")
    if base == head:
        return False, "mismo commit"
    if git("rev-parse", "HEAD") != head:
        raise ValueError("HEAD no coincide con el commit autorizado")
    if git("merge-base", "--is-ancestor", base, head) != "":
        raise ValueError("La comparación de commits no es válida")
    changed = set(git("diff", "--name-only", base, head).splitlines())
    edited = changed.intersection(FILES)
    if not edited:
        return False, "sin cambio de versión (no se actualiza el VPS)"
    if edited != set(FILES):
        raise ValueError("Versión incompleta: deben modificarse backend, frontend y lockfile juntos")
    old = release_versions(lambda path: git("show", f"{base}:{path}"))
    new = release_versions(lambda path: Path(path).read_text(encoding="utf-8"))
    if release_tuple(new) <= release_tuple(old):
        raise ValueError(f"Versión no creciente: {old} -> {new}")
    return True, f"{old} -> {new}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        deploy, reason = check(args.base, args.head)
    except (ValueError, subprocess.CalledProcessError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"RELEASE RECHAZADA: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Auto-despliegue: {'APROBADO' if deploy else 'OMITIDO'} · {reason}")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"deploy={'true' if deploy else 'false'}\n")
            stream.write(f"detail={reason}\n")


if __name__ == "__main__":
    main()
