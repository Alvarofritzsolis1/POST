"""Install operator-curated Galancito knowledge and train the small local classifier.

Run inside GALANT API container:
    python -m app.galancito_seed_cli
Optional when several organizations use the same installation:
    python -m app.galancito_seed_cli --admin-email admin@empresa.cl

No API provider is invoked; employee documents and chat text are not read.
"""
from __future__ import annotations

import argparse
import json
from sqlalchemy import select
from .ai_models import AIConnection
from .db import SessionLocal
from .galancito_knowledge_api import install_curated_curriculum
from .models import User


def main() -> int:
    parser = argparse.ArgumentParser(description="Enseñar a Galancito gratis desde VPS")
    parser.add_argument("--admin-email", default="")
    args = parser.parse_args()
    with SessionLocal() as db:
        admin = None
        if args.admin_email:
            admin = db.scalar(select(User).where(
                User.email == args.admin_email,
                User.role == "admin",
                User.enabled.is_(True)))
            if admin is None:
                parser.error("El correo no corresponde a un administrador activo.")
        else:
            organizations = set(db.scalars(select(AIConnection.org_id).where(
                AIConnection.name == "Gemini VPS",
                AIConnection.provider == "gemini",
                AIConnection.encrypted_key.is_not(None))))
            if len(organizations) != 1:
                parser.error("No se identificó una sola organización de Gemini VPS; utiliza --admin-email.")
            admin = db.scalar(select(User).where(
                User.org_id == next(iter(organizations)),
                User.role == "admin",
                User.enabled.is_(True)).order_by(User.email))
            if admin is None:
                parser.error("La organización no tiene un administrador activo.")
        result = install_curated_curriculum(user=admin, db=db)
        print(json.dumps({
            "galancito": "aprendizaje local instalado",
            "casos_nuevos": result["created"],
            "casos_existentes": result["already_present"],
            "epocas_clasificador_local": result["training_epochs"],
            "acierto_evaluacion_clasificador": result["holdout_accuracy"],
            "tokens_api": 0,
            "organizacion": admin.org_id,
        }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
