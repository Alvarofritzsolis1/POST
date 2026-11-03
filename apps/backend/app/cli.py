import argparse
from getpass import getpass
from sqlalchemy import select
from .db import Base, engine, SessionLocal
from .models import Organization, User
from . import platform_models
from . import ops_models  # register additive operational tables with Base.metadata
from .ops_api import ensure_sites
from .security import hash_password


def main():
    parser = argparse.ArgumentParser(description="Herramientas administrativas GALANT POST")
    cmds = parser.add_subparsers(dest="action", required=True)
    cmds.add_parser("init-db")
    admin = cmds.add_parser("create-admin")
    admin.add_argument("--email", required=True)
    admin.add_argument("--organization", default="Mi organización")
    for action in ("create-user", "link-user", "diagnose-user"):
        cmd = cmds.add_parser(action)
        cmd.add_argument("--email", required=True)
        if action != "diagnose-user":
            cmd.add_argument("--org-id", required=True)
            cmd.add_argument("--role", choices=["admin", "analyst", "viewer"], default="analyst")
        if action == "link-user":
            cmd.add_argument("--apply", action="store_true")
            cmd.add_argument("--backup", help="Ruta a un pg_dump de formato custom validado mediante pg_restore --list")
    args = parser.parse_args()
    if args.action in {"link-user", "diagnose-user"}:
        import json
        import hashlib
        import subprocess
        from pathlib import Path
        from sqlalchemy import func
        with SessionLocal.begin() as db:
            user = db.scalar(select(User).where(User.email == args.email.strip().lower()).with_for_update())
            if not user:
                raise SystemExit("Cuenta no encontrada")
            org = db.scalar(select(Organization).where(Organization.id == user.org_id).with_for_update())
            counts = {}
            for table in Base.metadata.sorted_tables:
                if "org_id" in table.c and table.name not in {"users", "audit_events", "ops_changes", "worksites", "audit_periods"}:
                    counts[table.name] = db.scalar(select(func.count()).select_from(table).where(table.c.org_id == org.id))
            print(json.dumps({"user_id": user.id, "org_id": org.id, "organization": org.name, "records": counts}, ensure_ascii=False))
            if args.action == "diagnose-user":
                return
            target = db.scalar(select(Organization).where(Organization.id == args.org_id).with_for_update())
            if not target:
                raise SystemExit("Organización destino no encontrada")
            if org.id == target.id:
                print("La cuenta ya pertenece a esa organización")
                return
            if any(counts.values()):
                raise SystemExit("BLOQUEADO: la organización origen contiene datos. Requiere plan de migración supervisado con mapeo, respaldo y validación. No se movió información.")
            if not args.apply:
                print("Plan válido para organización sin datos operativos. Repetir con --apply --backup RUTA tras revisar el diagnóstico.")
                return
            path = Path(args.backup or "")
            if not path.is_file() or path.stat().st_size == 0:
                raise SystemExit("Se requiere un respaldo pg_dump válido")
            subprocess.run(["pg_restore", "--list", str(path)], check=True, stdout=subprocess.DEVNULL)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            from .ops_api import audit_change
            old_org_id = user.org_id
            user.org_id, user.role = target.id, args.role
            audit_change(db, user, "user", user.id, {"organization_link": {"from": old_org_id, "to": target.id, "backup_sha256": digest}})
        print("Cuenta vinculada; sus sesiones anteriores quedan invalidadas")
        return
    if args.action == "create-user":
        pw = getpass("Contraseña (mínimo 12 caracteres): ")
        if pw != getpass("Confirmar contraseña: "):
            raise SystemExit("Las contraseñas son diferentes")
        with SessionLocal.begin() as db:
            if not db.get(Organization, args.org_id):
                raise SystemExit("Organización no encontrada")
            if db.scalar(select(User.id).where(User.email == args.email.strip().lower())):
                raise SystemExit("Ese correo ya existe; usa diagnose-user")
            db.add(User(email=args.email.strip().lower(), org_id=args.org_id, role=args.role, password_hash=hash_password(pw)))
        print("Usuario creado en la organización existente")
        return
    if args.action == "init-db":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            org_ids = db.scalars(select(Organization.id)).all()
        for org_id in org_ids:
            with SessionLocal() as db:
                ensure_sites(db, org_id)
        print("Tablas inicializadas")
        return
    pw = getpass("Contraseña (mínimo 12 caracteres): ")
    if pw != getpass("Confirmar contraseña: "):
        raise SystemExit("Las contraseñas son diferentes")
    with SessionLocal.begin() as db:
        email = args.email.strip().lower()
        if db.scalar(select(User.id).where(User.email == email)):
            raise SystemExit("Ese correo ya existe")
        if db.scalar(select(Organization.id).where(Organization.name == args.organization)):
            raise SystemExit("Ya existe una organización con ese nombre. Usa create-user --org-id para compartir sus datos")
        org = Organization(name=args.organization)
        db.add(org)
        db.flush()
        db.add(User(email=email, org_id=org.id, role="admin",
                    password_hash=hash_password(pw)))
        org_id = org.id
    with SessionLocal() as db:
        ensure_sites(db, org_id)
    print("Administrador creado")


if __name__ == "__main__":
    main()
