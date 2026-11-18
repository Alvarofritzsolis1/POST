"""Activate NVIDIA Nemotron Lightning for ALL GALANT users and organizations.

One private TTY key entry. No email, role selection or API key in arguments.
Verified key is encrypted once, then bound to each organization's Galancito.
New organizations are automatically covered by ai_global_lightning.sync_org.
"""
from __future__ import annotations

import getpass
import sys
from types import SimpleNamespace

from .ai_gateway import AIServiceError, encrypt_key, encryption_ready, invoke
from .ai_global_lightning import GLOBAL_ID, MODEL, sync_all
from .ai_models import AIGlobalCredential
from .db import SessionLocal
from .models import utcnow


def main() -> int:
    if not encryption_ready():
        print("ERROR: falta AI_CREDENTIAL_ENCRYPTION_KEY en el backend.")
        return 1
    key = getpass.getpass("Pega tu API Key NVIDIA (oculta): ").strip()
    if not key.startswith("nvapi-"):
        print("ERROR: se esperaba una clave NVIDIA que comienza con nvapi-.")
        return 1
    try:
        encrypted = encrypt_key(key)
    except AIServiceError as exc:
        print("ERROR al proteger la credencial:", str(exc))
        return 1
    del key

    print("Verificando Lightning con NVIDIA antes de activar usuarios...")
    try:
        answer, _, _ = invoke(
            SimpleNamespace(provider="nvidia", model=MODEL,
                            encrypted_key=encrypted),
            instructions="Responde brevemente en español.",
            prompt="Prueba del asistente GALANT. Responde OK.",
            max_output_tokens=256, timeout=35,
        )
    except AIServiceError as exc:
        print("ERROR:", str(exc))
        print("No se modificó ninguna conexión de GALANT.")
        return 1

    try:
        with SessionLocal.begin() as db:
            master = db.get(AIGlobalCredential, GLOBAL_ID)
            if master is None:
                master = AIGlobalCredential(id=GLOBAL_ID, provider="nvidia",
                                            model=MODEL, encrypted_key=encrypted)
                db.add(master)
            master.provider = "nvidia"
            master.model = MODEL
            master.encrypted_key = encrypted
            master.verified_at = utcnow()
            master.updated_at = utcnow()
            master.enabled = True
            count, total = sync_all(db, force=True)
    except Exception as exc:
        print("ERROR al guardar configuración:", type(exc).__name__)
        print("No se confirmaron cambios en la base de datos.")
        return 1

    print("OK: Nemotron Lightning verificado; respuesta:", answer[:60])
    print("Organizaciones vinculadas:", count, "de", total)
    if count < total:
        print("Las organizaciones sin usuarios activos se vincularán al habilitar una cuenta.")
    print("Todos los usuarios habilitados de esas organizaciones comparten la conexión.")
    print("Los datos y el consumo siguen separados por organización.")
    print("No se activaron respuestas automáticas de Messenger.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
