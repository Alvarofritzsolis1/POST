#!/usr/bin/env python3
"""Activar Galancito con Qwen3 1.7B SIN API de pago y SIN afectar otros módulos.

Ejecución manual desde el VPS DESPUÉS del despliegue:
  cd /opt/galant-post && sudo python3 scripts/setup-galancito-local.py

Solo asesora Red de Obras y (previa autorización) contesta Messenger.
"""
from __future__ import annotations

import os
import runpy
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env.preview"
COMPOSE = ROOT / "docker-compose.preview.yml"
MODEL = "qwen3:1.7b"

# Reutilizar el guardado atómico y el respaldo privado del instalador de Meta.
_previous = runpy.run_path(str(ROOT / "scripts" / "setup-galancito-messenger.py"))
env_values = _previous["env_values"]
write_env_atomically = _previous["write_env_atomically"]


def command(*args: str, timeout: int = 180) -> str:
    base = ["docker", "compose", "--profile", "local-ai",
            "--env-file", str(ENV), "-f", str(COMPOSE), *args]
    try:
        completed = subprocess.run(base, cwd=ROOT, check=True, text=True,
                                   capture_output=True, timeout=timeout)
        return completed.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # No revelar stderr de Docker que puede contener variables privadas.
        raise RuntimeError("El paso de Docker no se completó. No se activó ninguna IA.") from None


def preflight() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("Ejecuta este instalador con sudo en tu VPS")
    if not ENV.is_file() or not COMPOSE.is_file():
        raise RuntimeError("Falta .env.preview o Docker Compose de GALANT")
    if ENV.is_symlink() or stat.S_IMODE(ENV.stat().st_mode) & 0o077:
        raise RuntimeError("Archivo de configuración inseguro. Se requieren permisos 600")
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, _, amount = line.partition(":")
        if name == "MemAvailable":
            values[name] = int(amount.strip().split()[0]) * 1024
    available = values.get("MemAvailable", 0)
    if available < 6 * 1024**3:
        raise RuntimeError("No hay 6 GiB disponibles: GALANT debe tener prioridad")
    if (os.cpu_count() or 0) < 4:
        raise RuntimeError("Menos de 4 CPU detectadas; no se instalará el modelo")
    if shutil.disk_usage("/").free < 6 * 1024**3:
        raise RuntimeError("Necesitas al menos 6 GB libres para el modelo y las capas de Docker")
    print("✓ Memoria, CPU y disco suficientes para una prueba limitada")
    print("✓ Ollama tendrá un límite estricto de 3 GB RAM y 1,5 CPU")
    print("✓ Una conversación de IA a la vez. Modelo descargado tras 20 s de inactividad")


def install() -> None:
    preflight()
    print("\nGALANCITO LOCAL · Qwen3 1.7B (sin costo por mensaje)")
    print("Solo Facebook Messenger y asesor de Red de Obras. No toca otros módulos.")
    if input("¿Descargar y probar el modelo local en este VPS? [s/N]: ").strip().lower() not in {"s", "si", "sí"}:
        print("No se modificó ninguna configuración")
        return
    print("1/4. Descargando el servicio Ollama…")
    command("pull", "galancito-ollama", timeout=600)
    print("2/4. Iniciando servicio con límites de RAM y CPU…")
    command("up", "-d", "galancito-ollama", timeout=180)
    print("3/4. Descargando Qwen3 1.7B (~1,4 GB)…")
    try:
        command("exec", "-T", "galancito-ollama", "ollama", "pull", MODEL, timeout=900)
        # Se comprueba desde GALANT, no por un puerto expuesto en Internet.
        code = ("from app.galancito_local import generate_local_text; "
                "answer=generate_local_text('Responde español claro y breve', "
                "'¿Qué hace un carpintero?', 180); "
                "assert bool(answer.strip()); print('Modelo local probado')")
        output = command("exec", "-T", "api", "python", "-c", code, timeout=90)
        if "Modelo local probado" not in output:
            raise RuntimeError("La prueba de conexión local no confirmó una respuesta")
    except RuntimeError:
        # Nunca encender automáticamente una IA que no pasó la prueba.
        try:
            command("stop", "galancito-ollama", timeout=60)
        except RuntimeError:
            pass
        raise
    print("   ✓ Ollama responde desde el API privado de GALANT")

    fb = (input("¿Activar respuestas automáticas locales en Messenger? [s/N]: ")
          .strip().lower() in {"s", "si", "sí"})
    changes = {
        "GALANCITO_LOCAL_AI_ENABLED": "true",
        "GALANCITO_AI_PROVIDER": "ollama",
        "GALANCITO_AI_ENABLED": "true",
        "FACEBOOK_AI_PROVIDER": "ollama",
        "FACEBOOK_AI_ENABLED": "true" if fb else "false",
        "FACEBOOK_AI_AUTO_REPLY_ENABLED": "true" if fb else "false",
        "FACEBOOK_AI_AD_ENABLED": "false",
        # API keys previas, si existen, se conservan sin usarlas.
    }
    print("4/4. Guardando configuración privada y reiniciando solo API y Facebook…")
    backup = write_env_atomically(ENV, changes)
    print("   ✓ Respaldo de configuración: " + backup.name)
    try:
        command("up", "-d", "--no-deps", "--force-recreate",
                "api", "facebook-publisher", timeout=240)
    except RuntimeError:
        # Restaurar flags sin tocar base de datos ni perder tokens.
        write_env_atomically(ENV, {
            "GALANCITO_LOCAL_AI_ENABLED": "false",
            "GALANCITO_AI_ENABLED": "false",
            "FACEBOOK_AI_ENABLED": "false",
            "FACEBOOK_AI_AUTO_REPLY_ENABLED": "false",
        })
        raise
    print("\n✓ Galancito local habilitado solamente para Red de Obras" +
          (" y Messenger" if fb else ""))
    print("Sin costo por mensaje de API; sí usa los recursos de tu VPS.")
    print("Para detener Ollama sin detener GALANT:")
    print("  docker compose --profile local-ai --env-file .env.preview "
          "-f docker-compose.preview.yml stop galancito-ollama")
    print("Recuerda: Meta debe autorizar Messenger para contactos del público.")


if __name__ == "__main__":
    try:
        install()
    except (RuntimeError, KeyboardInterrupt, EOFError) as exc:
        if isinstance(exc, RuntimeError):
            print("No se pudo activar: " + str(exc), file=sys.stderr)
        else:
            print("Configuración cancelada", file=sys.stderr)
        sys.exit(1)
