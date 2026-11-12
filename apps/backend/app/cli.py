"""Administración local de cuentas en una organización compartida."""
import argparse
from getpass import getpass

from sqlalchemy import func, select

from .db import Base, SessionLocal, engine
from .models import AuditEvent, Document, Organization, User
from . import platform_models
from . import ops_models, control_models, network_models  # registrar tablas antes de crear esquema
from .ops_models import AuditPeriod, Contractor, ContractorWorksite, MonthlyDocument, OpsChange, Worker, WorkerAssignment, Worksite
from .control_models import ContributionControl, MonthlyActivity, ContractRegister, ContractAmendment, ProcessCalendar, WorkTask, OffboardingCase, RequirementApplicability
from .ops_api import DEFAULT_SITES, INITIAL_PERIOD, ensure_sites
from .security import hash_password
from .platform_models import BackupCheckpoint, SchemaVersion
from .version import VERSION
from .migrations import v0_6_0, v0_7_0, v8_1_0, v13_1_0, v16_0_0, v16_0_1, v16_6_0, v20_0_0
from . import v81_models, configuration_models, javiera_models, javiera_v166_models, javiera_workbook_models  # register additive tables


def record_verified_backup(db, sha256: str):
    import re
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise SystemExit("Se requiere SHA256 del respaldo tras verificar su restauración aislada")
    for org_id in db.scalars(select(Organization.id)).all():
        db.add(BackupCheckpoint(org_id=org_id, sha256=sha256))


def migrate(db):
    """Versioned, additive 0.6 migration; leaves all historical tables intact."""
    SchemaVersion.__table__.create(bind=db.connection(), checkfirst=True)
    if not db.get(SchemaVersion, v0_6_0.MIGRATION_ID):
        v0_6_0.upgrade(db.connection())
        db.add(SchemaVersion(version=v0_6_0.MIGRATION_ID))
    if not db.get(SchemaVersion, v0_7_0.MIGRATION_ID):
        v0_7_0.upgrade(db.connection())
        db.add(SchemaVersion(version=v0_7_0.MIGRATION_ID))
    if not db.get(SchemaVersion, v8_1_0.MIGRATION_ID):
        v8_1_0.upgrade(db)
        db.add(SchemaVersion(version=v8_1_0.MIGRATION_ID))

    if not db.get(SchemaVersion, v13_1_0.MIGRATION_ID):
        v13_1_0.upgrade(db)
        db.add(SchemaVersion(version=v13_1_0.MIGRATION_ID))

    if not db.get(SchemaVersion, v16_0_0.MIGRATION_ID):
        v16_0_0.upgrade(db.connection())
        db.add(SchemaVersion(version=v16_0_0.MIGRATION_ID))

    if not db.get(SchemaVersion, v16_0_1.MIGRATION_ID):
        v16_0_1.upgrade(db.connection())
        db.add(SchemaVersion(version=v16_0_1.MIGRATION_ID))

    if not db.get(SchemaVersion, v16_6_0.MIGRATION_ID):
        v16_6_0.upgrade(db.connection())
        db.add(SchemaVersion(version=v16_6_0.MIGRATION_ID))

    if not db.get(SchemaVersion, v20_0_0.MIGRATION_ID):
        v20_0_0.upgrade(db.connection())
        db.add(SchemaVersion(version=v20_0_0.MIGRATION_ID))


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
    for model in (Document, Contractor, ContractorWorksite, Worker, WorkerAssignment, OpsChange, MonthlyDocument, ContributionControl, MonthlyActivity, ContractRegister, ContractAmendment, ProcessCalendar, WorkTask, OffboardingCase, RequirementApplicability):
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
    upgrade = cmds.add_parser("migrate-db", help="Migración aditiva tras restauración de prueba")
    upgrade.add_argument("--verified-backup-sha256", required=True)
    verified = cmds.add_parser("register-verified-backup", help="Habilitar reconciliación tras verificar restauración")
    verified.add_argument("--verified-backup-sha256", required=True)
    admin = cmds.add_parser("create-admin", help="Crear empresa NUEVA y su administrador inicial")
    admin.add_argument("--email", required=True)
    admin.add_argument("--organization", default="Mi organización")
    for command in ("create-user", "link-user"):
        cmd = cmds.add_parser(command, help="Crear o vincular usuario a empresa EXISTENTE")
        cmd.add_argument("--email", required=True)
        cmd.add_argument("--admin-email", required=True, help="Administrador de la empresa que compartirá sus contratistas")
        cmd.add_argument("--role", choices=("admin", "administrative", "resident", "doc_reviewer"), default="administrative")
        if command == "link-user":
            cmd.add_argument("--apply", action="store_true")
            cmd.add_argument("--backup", help="pg_dump custom validado con pg_restore --list")
    diag = cmds.add_parser("diagnose-user")
    diag.add_argument("--email", required=True)
    args = parser.parse_args()
    if args.action == "register-verified-backup":
        with SessionLocal.begin() as db:
            record_verified_backup(db, args.verified_backup_sha256)
        print("Respaldo verificado registrado para las organizaciones")
        return
    if args.action == "migrate-db":
        with SessionLocal.begin() as db:
            migrate(db)
            record_verified_backup(db, args.verified_backup_sha256)
        with SessionLocal() as db:
            org_ids = db.scalars(select(Organization.id)).all()
        for org_id in org_ids:
            with SessionLocal() as db:
                ensure_sites(db, org_id)
        print(f"Esquema {VERSION} migrado sin eliminar datos")
        return
    if args.action == "diagnose-user":
        import json
        with SessionLocal() as db:
            target = db.scalar(select(User).where(User.email == args.email.strip().lower()))
            if target is None:
                raise SystemExit("Cuenta no encontrada")
            org = db.get(Organization, target.org_id)
            records = {}
            for table in Base.metadata.sorted_tables:
                if "org_id" in table.c:
                    records[table.name] = db.scalar(select(func.count()).select_from(table).where(table.c.org_id == org.id))
            print(json.dumps({"email": target.email, "user_id": target.id, "org_id": org.id, "organization": org.name, "records": records}, ensure_ascii=False))
        return

    if args.action == "init-db":
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            org_ids = db.scalars(select(Organization.id)).all()
        for org_id in org_ids:
            with SessionLocal() as db:
                ensure_sites(db, org_id)
        with SessionLocal.begin() as db:
            migrate(db)
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
            old_access = (target.org_id, target.role)
            if target.org_id != admin.org_id:
                db.scalar(select(Organization).where(Organization.id == target.org_id).with_for_update())
                check_empty_organization(db, target.org_id, target.id)
                for table in Base.metadata.sorted_tables:
                    if "org_id" in table.c and table.name not in {"users", "worksites", "audit_periods", "audit_events"}:
                        if db.scalar(select(func.count()).select_from(table).where(table.c.org_id == target.org_id)):
                            raise SystemExit("La organización contiene datos; requiere migración supervisada")
                if not args.apply:
                    print("Plan: vincular cuenta vacía. Repetir con --apply --backup RUTA tras verificar restauración")
                    return
                import hashlib
                import subprocess
                from pathlib import Path
                path = Path(args.backup or "")
                if not path.is_file() or path.stat().st_size == 0:
                    raise SystemExit("Se requiere respaldo pg_dump custom no vacío")
                subprocess.run(["pg_restore", "--list", str(path)], check=True, stdout=subprocess.DEVNULL)
                with path.open("rb") as backup_stream:
                    backup_hash = hashlib.file_digest(backup_stream, "sha256").hexdigest()
                old_org = target.org_id
                target.org_id = admin.org_id
                from .ops_api import audit_change
                audit_change(db, admin, "user", target.id, {"organization_link": {"from": old_org, "to": admin.org_id, "backup_sha256": backup_hash}})
            target.role = args.role
            if old_access != (target.org_id, target.role):
                from .network_accounts import revoke_sessions
                revoke_sessions(db, target)
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
            if db.scalar(select(Organization.id).where(Organization.name == args.organization)):
                raise SystemExit("Ya existe esa organización; usa create-user --admin-email para compartir datos")
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
