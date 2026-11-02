import argparse
from getpass import getpass
from sqlalchemy import select
from .db import Base, engine, SessionLocal
from .models import Organization, User
from .security import hash_password


def main():
    parser = argparse.ArgumentParser(description="Herramientas administrativas GALANT POST")
    cmds = parser.add_subparsers(dest="action", required=True)
    cmds.add_parser("init-db")
    admin = cmds.add_parser("create-admin")
    admin.add_argument("--email", required=True)
    admin.add_argument("--organization", default="Mi organización")
    args = parser.parse_args()
    if args.action == "init-db":
        Base.metadata.create_all(bind=engine)
        print("Tablas inicializadas")
        return
    pw = getpass("Contraseña (mínimo 12 caracteres): ")
    if pw != getpass("Confirmar contraseña: "):
        raise SystemExit("Las contraseñas son diferentes")
    with SessionLocal.begin() as db:
        email = args.email.strip().lower()
        if db.scalar(select(User.id).where(User.email == email)):
            raise SystemExit("Ese correo ya existe")
        org = Organization(name=args.organization)
        db.add(org)
        db.flush()
        db.add(User(email=email, org_id=org.id, role="admin",
                    password_hash=hash_password(pw)))
    print("Administrador creado")


if __name__ == "__main__":
    main()
