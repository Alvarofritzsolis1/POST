"""Administración local de cuentas en una organización compartida."""
import argparse
from getpass import getpass

from sqlalchemy import func, select

from .db import Base, SessionLocal, engine
from .models import AuditEvent, Document, Organization, User
from . import ops_models, control_models  # registrar tablas antes de crear esquema
from .ops_models import AuditPeriod, Contractor, ContractorWorksite, MonthlyDocument, OpsChange, Worker, WorkerAssignment, Worksite
from .control_models import ContributionControl, MonthlyActivity, ContractRegister, ProcessCalendar, WorkTask, OffboardingCase, RequirementApplicability
from .ops_api import DEFAULT_SITES, INITIAL_PERIOD, ensure_sites
from .security import hash_password


def find_admin(db, email: str) -> User:
    admin = db.scalar(select(User).where(User.email == email.strip().lower()))
    if admin is None or not admin.enabled or admin.role != "admin":
        raise SystemExit("El correo de referencia no corresponde a un administrador habilitado")
    return admin


def check_empty_organization(db, org_id: str, user_id: str) -> None:
    """No transferir silenciosamente información entre organizaciones."""
    others = db.scalar(select(func.count(User.id)).where(User.org_id == org_id, User.id != user_id))
    if others:
        raise SystemExit("Organización de origen con otros usuarios: requiere migración administrada")
    for model in (Document, Contractor, ContractorWorksite, Worker, WorkerAssignment, OpsChange, MonthlyDocument, ContributionControl, MonthlyActivity, ContractRegister, ProcessCalendar, WorkTask, OffboardingCase, RequirementApplicability):
        if db.scalar(select(model.id).where(model.org_id == org_id).limit(1)):
            raise SystemExit("La organización de origen tiene registros: no se moverán ni perderán datos. Requiere migración supervisada")
    # Se permiten únicamente las tres obras y períodos iniciales creados por init-db.
    sites = db.scalars(select(Worksite).where(Worksite.org_id == org_id)).all()
    if any(site.name not in DEFAULT_SITES for site in sites):
        raise SystemExit("La organización de origen tiene obras personalizadas; requiere migración supervisada")
    periods = db.scalars(select(AuditPeriod).where(AuditPeriod.org_id == org_id)).all()
    if any(p.period != INITIAL_PERIOD for p in periods):
        raise SystemExit("La organización de origen tiene períodos personalizados; requiere migración supervisada")


def main():
    parser = argparse.ArgumentParser(description="Herramientas administrativas GALANT POST")
    cmds = parser.add_subparsers(dest="action", required=True)
    cmds.add_parser("init-db")
    admin = cmds.add_parser("create-admin", help="Crear empresa NUEVA y su administrador inicial")
    admin.add_argument("--email", required=True)
    admin.add_argument("--organization", default="Mi organización")
    for command in ("create-user", "link-user"):
        cmd = cmds.add_parser(command, help="Crear o vincular usuario a empresa EXISTENTE")
        cmd.add_argument("--email", required=True)
        cmd.add_argument("--admin-email", required=True, help="Administrador de la empresa que compartirá sus contratistas")
        cmd.add_argument("--role", choices=("admin", "analyst", "viewer"), default="analyst")
    args = parser.parse_args()

    if args.action == "init-db":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            org_ids = db.scalars(select(Organization.id)).all()
        for org_id in org_ids:
            with SessionLocal() as db:
                ensure_sites(db, org_id)
        print("Tablas inicializadas (sin borrar datos)")
        return

    email = args.email.strip().lower()
    if args.action == "link-user":
        with SessionLocal.begin() as db:
            admin = find_admin(db, args.admin_email)
            target = db.scalar(select(User).where(User.email == email))
            if target is None:
                raise SystemExit("La cuenta no existe. Usa create-user para crearla")
            if target.id == admin.id:
                raise SystemExit("No puedes reasignar la cuenta del administrador de referencia")
            if target.org_id != admin.org_id:
                check_empty_organization(db, target.org_id, target.id)
                target.org_id = admin.org_id
            target.role = args.role
        print("Usuario vinculado a la misma organización. Debe cerrar sesión y volver a ingresar")
        return

    pw = getpass("Contraseña (mínimo 12 caracteres): ")
    if pw != getpass("Confirmar contraseña: "):
        raise SystemExit("Las contraseñas son diferentes")
    hashed = hash_password(pw)
    with SessionLocal.begin() as db:
        if db.scalar(select(User.id).where(User.email == email)):
            raise SystemExit("Ese correo ya existe. Para una cuenta vacía usa link-user")
        if args.action == "create-admin":
            org = Organization(name=args.organization)
            db.add(org)
            db.flush()
            db.add(User(email=email, org_id=org.id, role="admin", password_hash=hashed))
            org_id = org.id
        else:
            existing_admin = find_admin(db, args.admin_email)
            org_id = existing_admin.org_id
            db.add(User(email=email, org_id=org_id, role=args.role, password_hash=hashed))
    with SessionLocal() as db:
        ensure_sites(db, org_id)
    print("Cuenta creada dentro de empresa existente" if args.action == "create-user"
          else "Empresa y administrador inicial creados. Usa create-user para agregar colaboradores")


if __name__ == "__main__":
    main()
