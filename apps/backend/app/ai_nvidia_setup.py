"""Provision NVIDIA Nemotron Lightning for a GALANT organization from a private VPS TTY.

Run from the API container, where DB and encryption key are already configured.
Never accepts a key as a CLI argument, puts one in Git, or prints credentials.
"""
from __future__ import annotations

import argparse
import getpass
import sys
import time
from types import SimpleNamespace

from sqlalchemy import select

from .ai_gateway import AIServiceError, encryption_ready, encrypt_key, invoke, record_usage
from .ai_models import AIConnection, AIOrchestration
from .db import SessionLocal
from .models import AuditEvent, User, utcnow

MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
CONNECTION_NAME = "NVIDIA Nemotron Lightning"


def select_admin(db, email: str | None) -> User:
    admins = list(db.scalars(
        select(User).where(User.enabled.is_(True), User.role == "admin").order_by(User.email)
    ))
    if email:
        found = [u for u in admins if u.email.casefold() == email.casefold()]
        if len(found) != 1:
            raise RuntimeError("No existe un administrador activo con ese correo.")
        return found[0]
    orgs = {user.org_id for user in admins}
    if len(orgs) != 1:
        raise RuntimeError(
            "Hay varias organizaciones (o no hay administrador activo). "
            "Vuelve a ejecutar con --admin-email CORREO_DEL_ADMIN."
        )
    return admins[0]


def provision(db, admin: User, encrypted_key: str, usage: tuple[int, int], elapsed: int) -> None:
    """Reuses only the *same* NVIDIA Lightning connection; preserves other AI."""
    conn = db.scalars(select(AIConnection).where(
        AIConnection.org_id == admin.org_id,
        AIConnection.provider == "nvidia",
        AIConnection.model == MODEL,
    )).first()
    if conn is None:
        existing_names = set(db.scalars(
            select(AIConnection.name).where(AIConnection.org_id == admin.org_id)
        ))
        name = CONNECTION_NAME
        count = 2
        while name in existing_names:
            name = CONNECTION_NAME + " #" + str(count)
            count += 1
        conn = AIConnection(
            org_id=admin.org_id, updated_by=admin.id,
            name=name, provider="nvidia", model=MODEL,
        )
        db.add(conn)
        db.flush()
    conn.encrypted_key = encrypted_key
    conn.enabled = True
    conn.last_status = "verified"
    conn.last_checked_at = utcnow()
    conn.updated_by = admin.id
    conn.updated_at = utcnow()
    policy = db.get(AIOrchestration, admin.org_id)
    if policy is None:
        policy = AIOrchestration(
            org_id=admin.org_id, updated_by=admin.id,
            monthly_token_limit=100000,
        )
        db.add(policy)
    routes = dict(policy.task_routes or {})
    if policy.review_enabled and routes.get("review") == conn.id:
        raise RuntimeError("Lightning ya figura como revisor; cambia esa ruta en Configuración > IA.")
    routes["red_obras"] = conn.id
    policy.task_routes = routes
    policy.enabled = True
    policy.updated_by = admin.id
    policy.updated_at = utcnow()
    record_usage(db, conn, "connection_test", status="success",
                 input_tokens=usage[0], output_tokens=usage[1], duration_ms=elapsed)
    db.add(AuditEvent(
        org_id=admin.org_id, user_id=admin.id,
        action="ai.connection.setup_vps", resource_id=conn.id,
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description="Conectar NVIDIA Lightning a GALANT")
    parser.add_argument("--admin-email", help="Obligatorio solo si hay varias organizaciones")
    args = parser.parse_args()
    if not encryption_ready():
        print("ERROR: configura primero AI_CREDENTIAL_ENCRYPTION_KEY en el servidor.")
        return 1
    try:
        with SessionLocal() as db:
            admin = select_admin(db, args.admin_email)
            admin_id = admin.id
            org_id = admin.org_id
    except Exception as exc:
        print("ERROR al seleccionar organización:", str(exc))
        return 1

    key = getpass.getpass("Pega tu NVIDIA API Key (no se muestra): ").strip()
    if not key.startswith("nvapi-"):
        print("ERROR: la clave debe comenzar con nvapi-. No se guardó nada.")
        return 1
    try:
        encrypted = encrypt_key(key)
    except AIServiceError as exc:
        print("ERROR de cifrado:", str(exc))
        return 1
    # Clear our direct variable: the encrypted form is the only persistent value.
    del key
    started = time.monotonic()
    print("Probando Nemotron Lightning en la API de NVIDIA...")
    try:
        answer, in_tokens, out_tokens = invoke(
            SimpleNamespace(provider="nvidia", model=MODEL, encrypted_key=encrypted),
            instructions="Responde de forma concisa en español.",
            prompt="Prueba de conexión de GALANT. Responde OK.",
            max_output_tokens=256,
            timeout=35,
        )
    except AIServiceError as exc:
        print("ERROR de conexión:", str(exc))
        print("La API Key no se guardó ni se cambió el agente.")
        return 1
    elapsed = round((time.monotonic() - started) * 1000)
    try:
        with SessionLocal.begin() as db:
            admin = db.get(User, admin_id)
            if not admin or not admin.enabled or admin.role != "admin" or admin.org_id != org_id:
                raise RuntimeError("La cuenta administradora dejó de estar habilitada.")
            provision(db, admin, encrypted, (in_tokens, out_tokens), elapsed)
    except Exception as exc:
        print("ERROR al guardar en GALANT:", type(exc).__name__, str(exc))
        return 1
    print("OK: NVIDIA Nemotron Lightning verificado y enlazado con Red de Obras.")
    print("Responde:", answer[:80])
    print("Configuración compartida por la organización; no requiere una clave por usuario.")
    print("Messenger se conserva SIN cambios para evitar respuestas automáticas accidentales.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
