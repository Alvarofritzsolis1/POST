#!/usr/bin/env python3
"""Opt-in local Qwen upgrade; run only after this code is deployed.

Default is read-only preflight. --activate requires a freshly verified backup,
a maintenance window, and prior approval of comparative quality results.
Never sends Messenger messages, removes models/volumes or restores an old DB.
"""
import argparse
import fcntl
import json
import os
import re
from pathlib import Path
import runpy
import shutil
import stat
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env.preview"
MODEL = "qwen3.5:4b-q4_K_M"
OLD = "qwen3:1.7b"
COMPOSE = ["docker", "compose", "--profile", "local-ai", "--profile", "training",
           "--env-file", str(ENV), "-f", str(ROOT / "docker-compose.preview.yml")]
JAVIERA_OVERRIDE = ROOT / "docker-compose.javiera20.yml"
if JAVIERA_OVERRIDE.is_file():
    COMPOSE += ["--env-file", str(ROOT / ".env.javiera20"), "-f", str(JAVIERA_OVERRIDE)]
SERVICES = ("api", "worker", "facebook-publisher")
CHANGES = {"GALANCITO_LOCAL_MODEL": MODEL, "GALANCITO_OLLAMA_MEM_LIMIT": "5g",
           "GALANCITO_OLLAMA_CPUS": "2", "GALANCITO_NUM_THREAD": "2",
           "GALANCITO_TIMEOUT_SECONDS": "45", "GALANCITO_MEMORY_RESERVE_MB": "2048",
           "GALANCITO_KEEP_ALIVE": "5m",
           "GALANCITO_AI_PROVIDER": "ollama", "FACEBOOK_AI_PROVIDER": "ollama",
           "GALANCITO_LOCAL_AI_ENABLED": "true"}
SMOKE = """import json
import sys
import time
import urllib.request
from urllib.error import HTTPError, URLError

model = MODEL_TOKEN
url = 'http://galancito-ollama:11434/api/chat'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# Cold model loading is different from response latency after warmup.
# These are synthetic prompts only; never print Messenger content or secrets.
stages = [
    ('carga_inicial', 'Saluda brevemente en español.', 180),
    ('respuesta_caliente', 'Un maestro trabaja en carpintería. Dale un saludo corto.', 45),
]
for stage, prompt, timeout_seconds in stages:
    payload = {
        'model': model,
        'messages': [{'role': 'system', 'content': 'Responde brevemente en español, sin explicaciones adicionales.'},
                     {'role': 'user', 'content': prompt}],
        'think': False, 'stream': False, 'keep_alive': '2m',
        'options': {'num_ctx': 2048, 'num_thread': 2, 'num_predict': 64, 'temperature': 0},
    }
    started = time.monotonic()
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            result = json.load(response)
    except HTTPError as error:
        print('SMOKE_ERROR stage=%s http=%d' % (stage, error.code), file=sys.stderr)
        sys.exit(21)
    except (URLError, TimeoutError, OSError) as error:
        print('SMOKE_ERROR stage=%s transport=%s' % (stage, type(error).__name__), file=sys.stderr)
        sys.exit(22)
    except (ValueError, TypeError):
        print('SMOKE_ERROR stage=%s invalid_json' % stage, file=sys.stderr)
        sys.exit(23)
    elapsed = time.monotonic() - started
    message = result.get('message')
    content = message.get('content', '') if isinstance(message, dict) else ''
    if not isinstance(content, str) or len(content.strip()) < 3 or '<think>' in content.casefold():
        print('SMOKE_ERROR stage=%s invalid_response' % stage, file=sys.stderr)
        sys.exit(24)
    if stage == 'respuesta_caliente' and elapsed >= 45:
        print('SMOKE_ERROR stage=%s latency_gate' % stage, file=sys.stderr)
        sys.exit(25)
    print('SMOKE_OK stage=%s seconds=%.2f tokens=%s' %
          (stage, elapsed, result.get('eval_count', 'unknown')), flush=True)
"""
HEALTH = "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=5).status == 200"


def run(args, timeout=180):
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Tiempo de ejecución agotado; operación detenida sin activar el modelo.") from None
    except subprocess.CalledProcessError as error:
        # Only explicitly marked diagnostics from the synthetic Ollama smoke test.
        allowed = re.compile(
            r"SMOKE_ERROR stage=(?:carga_inicial|respuesta_caliente) "
            r"(?:http=[0-9]{3}|transport=[A-Za-z]{1,40}|invalid_json|invalid_response|latency_gate)"
        )
        safe = [line.strip() for line in (error.stderr or "").splitlines()
                if allowed.fullmatch(line.strip())][:2]
        detail = (" " + "; ".join(safe)) if safe else (" exit_code=" + str(error.returncode))
        raise RuntimeError("Falló un paso de verificación/ejecución." + detail) from None
    except OSError:
        raise RuntimeError("No se pudo ejecutar el comando de verificación.") from None
    return result.stdout


def compose(*args, timeout=180):
    return run([*COMPOSE, *args], timeout)


def memory_mb():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    raise RuntimeError("No se pudo comprobar la memoria disponible")


def preflight():
    if os.geteuid() != 0 or not ENV.is_file() or ENV.is_symlink() or stat.S_IMODE(ENV.stat().st_mode) & 0o077:
        raise RuntimeError("Ejecutar como root en GALANT con .env.preview privado (600)")
    if JAVIERA_OVERRIDE.is_file() and not (ROOT / ".env.javiera20").is_file():
        raise RuntimeError("Falta el entorno de Javiera; no se recreará el API con una configuración incompleta")
    compose("config", "--quiet")
    if memory_mb() < 7168 or (os.cpu_count() or 0) < 4:
        raise RuntimeError("Se requieren 7 GiB disponibles y 4 CPU antes de probar; no se modifica nada")
    if shutil.disk_usage(ROOT).free < 8 * 1024**3 or shutil.disk_usage("/var/lib/docker" if Path("/var/lib/docker").exists() else "/").free < 8 * 1024**3:
        raise RuntimeError("Se requieren 8 GiB libres en proyecto y almacenamiento Docker")
    running = set(compose("ps", "--status", "running", "--services").split())
    if {"galancito-trainer", "galancito-training-ollama"} & running:
        raise RuntimeError("Entrenamiento activo o disponible. Finalizar la ronda y detener sus servicios, sin borrar volúmenes.")
    if not {"api", "db", "galancito-ollama", *SERVICES} <= running:
        raise RuntimeError("El stack activo está incompleto; revisar antes de cambiar el modelo")
    compose("exec", "-T", "api", "python", "-c", HEALTH)
    if JAVIERA_OVERRIDE.is_file() and "javiera-calc" not in running:
        raise RuntimeError("Javiera no está operativo; no se modificará el API")
    compose("exec", "-T", "api", "python", "-c",
            "from app.config import Settings; assert Settings(galancito_local_model=" + repr(MODEL) + ").galancito_local_model == " + repr(MODEL))
    models = compose("exec", "-T", "galancito-ollama", "ollama", "list")
    if OLD not in {line.split()[0] for line in models.splitlines() if line.split()}:
        raise RuntimeError("No se encontró el modelo original: no se activará el candidato")


def wait_health():
    for attempt in range(24):
        try:
            compose("exec", "-T", "api", "python", "-c", HEALTH, timeout=12)
            running = set(compose("ps", "--status", "running", "--services").split())
            if {*SERVICES, "galancito-ollama", "db"} <= running:
                return
        except RuntimeError:
            pass
        time.sleep(5)
    raise RuntimeError("GALANT no confirmó el estado saludable")


def smoke():
    result = compose("exec", "-T", "api", "python", "-c", SMOKE.replace("MODEL_TOKEN", repr(MODEL)), timeout=260)
    if result.count("SMOKE_OK stage=") != 2:
        raise RuntimeError("No se confirmaron las dos pruebas sintéticas")
    print(result.strip())
    if memory_mb() < 2048:
        raise RuntimeError("Reserva de memoria insuficiente, se aborta")
    cid = compose("ps", "-q", "galancito-ollama").strip()
    if not cid:
        raise RuntimeError("Ollama no está activo")
    state = json.loads(run(["docker", "inspect", "--format", "{{json .State}}", cid]))
    if state.get("OOMKilled") or not state.get("Running"):
        raise RuntimeError("Ollama no está estable")


def restore_env(original):
    fd, path = tempfile.mkstemp(prefix=".env.preview.qwen-rollback-", dir=ROOT)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(original)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(path, 0o600)
        os.replace(path, ENV)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def activate():
    helper = runpy.run_path(str(ROOT / "scripts/setup-galancito-messenger.py"))
    write = helper["write_env_atomically"]
    backup_out = run(["bash", str(ROOT / "scripts/backup-preview.sh")], timeout=3600)
    paths = [line.removeprefix("BACKUP_PATH=") for line in backup_out.splitlines() if line.startswith("BACKUP_PATH=")]
    if len(paths) != 1:
        raise RuntimeError("No se confirmó el respaldo")
    backup = Path(paths[0])
    run(["bash", str(ROOT / "scripts/verify-restore-preview.sh"), str(backup)], timeout=3600)
    original = ENV.read_bytes()
    config_backup = backup / "env-preview-before-qwen"
    with config_backup.open("xb") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(original)
    print("Respaldo y restauración aislada verificados.")
    preflight()
    # Pull alongside the original without deleting or replacing its tag.
    compose("exec", "-T", "galancito-ollama", "ollama", "pull", MODEL, timeout=3600)
    try:
        write(ENV, {k: CHANGES[k] for k in ("GALANCITO_OLLAMA_MEM_LIMIT", "GALANCITO_OLLAMA_CPUS")})
        compose("up", "-d", "--no-deps", "galancito-ollama", timeout=240)
        wait_health()
        smoke()
        write(ENV, CHANGES)
        compose("up", "-d", "--no-deps", "--force-recreate", *SERVICES, timeout=300)
        wait_health()
        for service in SERVICES:
            compose("exec", "-T", service, "python", "-c",
                    "from app.config import settings; s=settings(); assert s.galancito_local_model==" + repr(MODEL) +
                    " and s.galancito_local_ai_enabled and s.galancito_ai_provider=='ollama' and s.facebook_ai_provider=='ollama'")
        smoke()
    except BaseException:
        print("Activación no validada. Reponiendo la configuración anterior sin restaurar la BD.")
        restore_env(original)
        compose("up", "-d", "--no-deps", "--force-recreate", "galancito-ollama", *SERVICES, timeout=300)
        wait_health()
        print("Configuración anterior recuperada. Revisar la calidad antes de reintentar.")
        raise
    print("Modelo configurado y pruebas sintéticas aprobadas. Verificar Messenger con un contacto de prueba autorizado.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate", action="store_true", help="Tras QA comparativa aprobada, activar con respaldo y reversión")
    args = parser.parse_args()
    if not args.activate:
        preflight()
        print("Preflight aprobado. No se modificó configuración ni base de datos.")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Se requiere root")
    with open("/run/lock/galant-qwen-upgrade.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight()
        activate()


if __name__ == "__main__":
    main()
