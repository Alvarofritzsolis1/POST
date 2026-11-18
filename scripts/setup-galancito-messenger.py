#!/usr/bin/env python3
"""Asistente local de configuración Meta Messenger para GALANT.

Ejecutar SOLO en el VPS: sudo python3 scripts/setup-galancito-messenger.py
No transmite ni imprime credenciales. No modifica permisos de Meta ni crea
tokens de acceso a páginas (Meta exige autorización de su administrador).
"""
from __future__ import annotations

import getpass
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.preview"
COMPOSE_FILE = ROOT / "docker-compose.preview.yml"
GRAPH = "https://graph.facebook.com/v27.0"
DEFAULT_DOMAIN = "https://galant.dpdns.org"
KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
PAGE_PATTERN = re.compile(r"^[0-9]{5,30}$")
APP_PATTERN = re.compile(r"^[0-9]{5,30}$")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("Meta redirigió la solicitud")


opener = build_opener(NoRedirect)


class SetupError(Exception):
    pass


def env_values(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if match:
            result[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return result


def write_env_atomically(path: Path, changes: dict[str, str]) -> Path:
    if path.is_symlink():
        raise SetupError("Archivo .env.preview es enlace simbólico: revisión manual necesaria")
    source = path.read_text(encoding="utf-8")
    original = source.splitlines(keepends=True)
    keys_seen = set()
    edited = []
    for line in original:
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match and match.group(1) in changes:
            name = match.group(1)
            if name in keys_seen:
                continue  # evitar doble definición peligrosa en env
            edited.append(name + "=" + changes[name] + "\n")
            keys_seen.add(name)
        else:
            edited.append(line)
    for name, val in changes.items():
        if not KEY_PATTERN.fullmatch(name) or "\n" in val or "\r" in val:
            raise SetupError("Variable de entorno inválida")
        if name not in keys_seen:
            if edited and not edited[-1].endswith("\n"):
                edited.append("\n")
            edited.append(name + "=" + val + "\n")
    # Copia previa protegida, de la que se puede restaurar la configuración.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(path.name + ".backup-messenger-" + timestamp + "-" + secrets.token_hex(3))
    if backup.exists():
        raise SetupError("El respaldo de configuración ya existe; reintenta")
    shutil.copy2(path, backup)
    backup.chmod(0o600)
    fd, temp = tempfile.mkstemp(prefix=".env.preview.tmp.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("".join(edited))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return backup


def graph(method: str, path: str, token: str, fields: dict[str, str] | None = None) -> dict:
    if not re.fullmatch(r"/(?:me|[0-9]{5,30}(?:/subscriptions|/subscribed_apps)?)", path):
        raise SetupError("Ruta Meta no permitida")
    if path == "/me" and method != "GET":
        raise SetupError("La consulta de identidad de página debe ser de solo lectura")
    fields = fields or {}
    if method == "GET":
        uri = GRAPH + path + ("?" + urlencode(fields) if fields else "")
        body = None
    else:
        uri = GRAPH + path
        body = urlencode(fields).encode("utf-8")
    req = Request(uri, data=body, method=method, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with opener.open(req, timeout=18) as response:
            value = json.loads(response.read(65536).decode("utf-8"))
    except HTTPError as exc:
        raise SetupError(
            "Meta rechazó la acción (HTTP " + str(exc.code) +
            "). Verifica permisos, App Review y token de la página."
        ) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise SetupError("No se pudo contactar a Meta de manera segura") from None
    if not isinstance(value, dict) or "error" in value:
        raise SetupError("Meta no confirmó la operación")
    return value


def prompt_value(label: str, existing: str = "", *, secret: bool = False) -> str:
    if existing:
        return existing
    print("Escribe " + label + " (se guardará únicamente en el VPS):")
    return (getpass.getpass("Valor privado: ") if secret else input("Valor: ")).strip()


def compose(*args: str, capture: bool = False) -> str:
    command = ["docker", "compose", "--env-file", str(ENV_FILE),
               "-f", str(COMPOSE_FILE), *args]
    try:
        p = subprocess.run(command, cwd=ROOT, capture_output=True,
                           text=True, timeout=160, check=True)
        if not capture:
            print("   ✓ Contenedores procesados correctamente")
        return p.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # compose podría mencionar credenciales en errores: nunca imprimir stderr
        raise SetupError("Docker Compose falló. Revisa la configuración del VPS sin divulgar secretos.") from None


def detect_org_id() -> str:
    code = (
        "from app.db import SessionLocal; from app.models import Organization; "
        "from sqlalchemy import select; "
        "db=SessionLocal(); "
        "print('\\n'.join(o.id + ' | ' + o.name for o in "
        "db.scalars(select(Organization).order_by(Organization.name)).all())); "
        "db.close()"
    )
    rows = compose("exec", "-T", "api", "python", "-c", code, capture=True).splitlines()
    candidates = []
    for row in rows:
        match = re.match(r"^([0-9a-fA-F-]{36}) \| (.+)$", row)
        if match:
            candidates.append((match.group(1), match.group(2)))
    if not candidates:
        raise SetupError("No se pudo detectar la organización de GALANT; confirma que el API esté iniciado")
    if len(candidates) == 1:
        print("   ✓ Organización encontrada: " + candidates[0][1])
        return candidates[0][0]
    print("Se detectaron varias organizaciones. Selecciona la correcta:")
    for idx, (_, name) in enumerate(candidates, 1):
        print("  " + str(idx) + ". " + name)
    choice = input("Número: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(candidates)):
        raise SetupError("Selección de organización inválida")
    return candidates[int(choice) - 1][0]


def test_webhook(callback: str, verify_token: str) -> None:
    challenge = "galancito-" + secrets.token_hex(8)
    uri = callback + "?" + urlencode({
        "hub.mode": "subscribe", "hub.verify_token": verify_token,
        "hub.challenge": challenge,
    })
    req = Request(uri, method="GET")
    for attempt in range(20):
        try:
            with opener.open(req, timeout=12) as response:
                actual = response.read(2000).decode("utf-8")
            if actual == challenge:
                return
        except (URLError, HTTPError, TimeoutError, OSError, ValueError):
            pass  # Esperar el arranque del API después de recrear contenedores.
        if attempt < 19:
            time.sleep(2)
    raise SetupError(
        "El webhook no respondió correctamente en HTTPS. "
        "Comprueba el despliegue de GALANT, el dominio y el token de verificación.")


def yes(label: str, default: bool = False) -> bool:
    suffix = " [S/n]: " if default else " [s/N]: "
    answer = input(label + suffix).strip().casefold()
    return answer in {"s", "si", "sí"} or (default and answer == "")


def run() -> None:
    if os.geteuid() != 0:
        raise SetupError("Ejecuta con sudo en el VPS de GALANT")
    if not ENV_FILE.is_file() or not COMPOSE_FILE.is_file():
        raise SetupError("Se requiere /opt/galant-post con .env.preview y docker-compose.preview.yml")
    if stat.S_IMODE(ENV_FILE.stat().st_mode) & 0o077:
        raise SetupError(".env.preview tiene permisos demasiado abiertos (se requieren 600)")
    old = env_values(ENV_FILE)
    print("\nGALANCITO · Configuración automática de Facebook Messenger")
    print("Este asistente no obtiene permisos de Meta ni los inventa.")
    print("No mostrará ni enviará al chat tus tokens o claves.\n")

    app_id = prompt_value("el ID de la aplicación de Meta", old.get("FACEBOOK_APP_ID", ""))
    app_secret = prompt_value("el App Secret de Meta", old.get("FACEBOOK_APP_SECRET", ""), secret=True)
    page_token = prompt_value("el Page Access Token", old.get("FACEBOOK_PAGE_TOKEN", ""), secret=True)
    page_id = old.get("FACEBOOK_PAGE_ID", "")
    if not APP_PATTERN.fullmatch(app_id):
        raise SetupError("ID de aplicación de Meta inválido")
    if len(app_secret) < 12 or len(page_token) < 20:
        raise SetupError("App Secret o Page Token vacío/inválido")
    domain = old.get("PUBLIC_URL", "") or DEFAULT_DOMAIN
    domain = domain.rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{2,5})?", domain):
        raise SetupError("PUBLIC_URL debe ser un dominio HTTPS público válido")
    callback = domain + "/api/v1/network/facebook/webhook"
    verify_token = old.get("FACEBOOK_WEBHOOK_VERIFY_TOKEN", "")
    if len(verify_token) < 32:
        verify_token = secrets.token_urlsafe(40)

    print("\n1/5 Verificando que el token tiene acceso a la página…")
    page = graph("GET", "/me", page_token, {"fields": "id,name"})
    actual_page_id = str(page.get("id") or "")
    if not PAGE_PATTERN.fullmatch(actual_page_id):
        raise SetupError("El token no corresponde a una página de Facebook válida")
    if page_id and page_id != actual_page_id:
        raise SetupError("El token corresponde a una página distinta de la configurada")
    page_id = actual_page_id
    print("   ✓ Página confirmada: " + str(page.get("name") or "Página Meta")[:120])

    print("2/5 Detectando tu organización GALANT…")
    org_id = old.get("FACEBOOK_ORG_ID") or detect_org_id()
    print("3/5 Generando token y activando webhook local…")
    backup = write_env_atomically(ENV_FILE, {
        "FACEBOOK_APP_ID": app_id,
        "FACEBOOK_APP_SECRET": app_secret,
        "FACEBOOK_PAGE_ID": page_id,
        "FACEBOOK_PAGE_TOKEN": page_token,
        "FACEBOOK_ORG_ID": org_id,
        "FACEBOOK_WEBHOOK_VERIFY_TOKEN": verify_token,
        "FACEBOOK_MESSAGING_ENABLED": "true",
        # Never silently disable an existing, consent-gated Messenger assistant.
        # A verified external team also works; model choice is not tied to Ollama.
        "FACEBOOK_AI_AUTO_REPLY_ENABLED": old.get(
            "FACEBOOK_AI_AUTO_REPLY_ENABLED", "false"
        ),
    })
    print("   ✓ Copia privada anterior: " + backup.name)
    compose("up", "-d", "--no-deps", "--force-recreate", "api", "facebook-publisher")
    test_webhook(callback, verify_token)
    print("   ✓ GALANT respondió correctamente a la verificación HTTPS")

    print("4/5 Registrando el webhook en Meta…")
    subscription = graph("POST", "/" + app_id + "/subscriptions",
                         app_id + "|" + app_secret, {
        "object": "page", "callback_url": callback,
        "verify_token": verify_token, "fields": "messages",
    })
    if subscription.get("success") is not True:
        raise SetupError("Meta no confirmó el registro del webhook")
    print("   ✓ URL y campo 'messages' registrados")

    print("5/5 Suscribiendo la página a Messenger…")
    subscribed = graph("POST", "/" + page_id + "/subscribed_apps", page_token,
                       {"subscribed_fields": "messages"})
    if subscribed.get("success") is not True:
        raise SetupError("Meta no confirmó la suscripción de la página")
    print("   ✓ Suscripción de página aceptada por Meta")

    if yes("¿Publicar automáticamente en Facebook las NUEVAS necesidades seleccionadas?"):
        write_env_atomically(ENV_FILE, {"FACEBOOK_AUTOPUBLISH_ENABLED": "true"})
        compose("up", "-d", "--no-deps", "--force-recreate", "api", "facebook-publisher")
        print("   ✓ Nuevas necesidades seleccionadas se podrán difundir automáticamente.")

    print("\n✓ Meta está enlazado a GALANT para mensajes nuevos.")
    print("Para probar Galancito, escribe desde un usuario de prueba autorizado en Meta.")
    print("Para activar Galancito con IA gratuita en tu VPS, ejecuta:")
    print("  sudo python3 scripts/setup-galancito-local.py")
    print("No se requiere ninguna clave de OpenAI ni hay costo por mensaje de API.")
    print("\nLa autorización para el público general depende de los permisos y App Review de Meta.")
    print("Los contactos antiguos no se importan automáticamente.\n")


if __name__ == "__main__":
    try:
        run()
    except (SetupError, KeyboardInterrupt, EOFError) as exc:
        if isinstance(exc, SetupError):
            print("\nNo fue posible terminar: " + str(exc), file=sys.stderr)
        else:
            print("\nConfiguración interrumpida, sin continuar", file=sys.stderr)
        print("Revisa el estado actual; no repitas acciones si Meta devolvió una confirmación incierta.",
              file=sys.stderr)
        sys.exit(1)
