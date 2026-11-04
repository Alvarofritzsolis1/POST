"""Organization-scoped administration. Cross-organization transfers are CLI-only."""

from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from .db import get_db
from .models import Organization, User
from .ops_api import audit_change, clean_name, site_for
from .ops_models import Worksite
from .platform_models import OrganizationSettings, RetentionRate, UserPreferences
from .security import administrator, authorized_user, hash_password, verify_password
from .version import VERSION

router = APIRouter(prefix="/api/v1/admin", tags=["Administración"])


class AccountCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "supervisor", "reviewer", "administrative", "viewer", "analyst"] = "supervisor"

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        value = value.strip().lower()
        if "@" not in value or any(c.isspace() for c in value):
            raise ValueError("Correo inválido")
        return value


class AccountPatch(BaseModel):
    role: Literal["admin", "supervisor", "reviewer", "administrative", "viewer", "analyst"]
    enabled: bool


class Preferences(BaseModel):
    name: str = Field(default="", max_length=180)
    appearance: Literal["light", "dark"] = "light"
    density: Literal["comfortable", "compact"] = "comfortable"
    notifications: bool = True
    default_site: str | None = None
    language: Literal["es"] = "es"
    date_format: Literal["dd/mm/yyyy"] = "dd/mm/yyyy"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)


class Catalogs(BaseModel):
    status_mapping: dict[str, Literal["active", "suspended", "offboarding", "inactive"]] = Field(
        default_factory=lambda: {
            "ACTIVO": "active",
            "SUSPENDIDO": "suspended",
            "INACTIVO": "inactive",
            "BAJA": "inactive",
        }
    )
    classification_mapping: dict[str, Literal["CT", "CI", "ESP"]] = Field(
        default_factory=dict
    )
    expiry_alert_days: list[int] = Field(default_factory=lambda: [30, 15, 7])
    termination_due_days: int | None = Field(default=None, ge=0, le=365)
    attendance_due_days: int = Field(default=2, ge=0, le=14)
    termination_causes: dict[str, str] = Field(default_factory=lambda: {
        "mutual_agreement": "Mutuo acuerdo (art. 159 N°1)",
        "resignation": "Renuncia voluntaria (art. 159 N°2)",
        "fixed_term_expiry": "Vencimiento del plazo (art. 159 N°4)",
        "work_completion": "Conclusión de obra o servicio (art. 159 N°5)",
        "business_needs": "Necesidades de la empresa (art. 161)",
        "notice": "Desahucio, cuando corresponda (art. 161)",
        "disciplinary": "Causal disciplinaria aplicable (art. 160)",
        "other_legal": "Otra causal legal",
    })
    extra_contract_types: dict[str, str] = Field(default_factory=dict)

    @field_validator("expiry_alert_days")
    @classmethod
    def validate_alert_days(cls, value):
        if not value or len(value) > 5 or len(value) != len(set(value)) or any(not 1 <= d <= 365 for d in value):
            raise ValueError("Configura entre uno y cinco plazos únicos de 1 a 365 días")
        return sorted(value, reverse=True)


class RateCreate(BaseModel):
    @field_validator("effective_from")
    @classmethod
    def monthly_rate(cls, value):
        if value.day != 1:
            raise ValueError("La vigencia debe comenzar el primer día del mes auditado")
        return value

    effective_from: date
    daily_clp: int = Field(ge=0, le=10000000)


def account_view(row):
    return {
        "id": row.id,
        "email": row.email,
        "role": row.role,
        "enabled": row.enabled,
        "org_id": row.org_id,
    }


def catalogs_for(db, org_id):
    row = db.get(OrganizationSettings, org_id)
    return Catalogs.model_validate(row.values if row else {}).model_dump()


@router.get("/profile")
def profile(user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    pref = db.get(UserPreferences, user.id)
    org = db.get(Organization, user.org_id)
    return {
        "user": account_view(user),
        "organization": org.name,
        "preferences": Preferences.model_validate(
            pref.values if pref else {}
        ).model_dump(),
        "version": VERSION,
    }


@router.put("/preferences")
def preferences(
    body: Preferences,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    if body.default_site:
        site_for(db, user.org_id, body.default_site)
    row = db.get(UserPreferences, user.id)
    if row is None:
        row = UserPreferences(user_id=user.id)
        db.add(row)
    row.values = body.model_dump()
    from .network_models import NetworkMember
    network_member = db.get(NetworkMember, user.id)
    if network_member is not None:
        network_member.name = body.name
    db.commit()
    return row.values


@router.post("/password")
def password(
    body: PasswordChange,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "Contraseña actual incorrecta")
    user.password_hash = hash_password(body.new_password)
    from .network_accounts import revoke_sessions
    revoke_sessions(db, user)
    audit_change(db, user, "user", user.id, {"password_changed": True})
    db.commit()
    return {"ok": True}


@router.get("/users")
def users(user: User = Depends(administrator), db: Session = Depends(get_db)):
    return [
        account_view(r)
        for r in db.scalars(
            select(User).where(User.org_id == user.org_id).order_by(User.email)
        )
    ]


@router.post("/users", status_code=201)
def create_user(
    body: AccountCreate,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    # Lock the organization to serialize administration and prevent removal of its last admin.
    from .network_service import lock_org
    lock_org(db, user)
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(
            409,
            "La cuenta ya existe. Si está en otra organización, requiere diagnóstico y vinculación supervisada desde el VPS",
        )
    row = User(
        org_id=user.org_id,
        email=body.email,
        role=body.role,
        password_hash=hash_password(body.password),
    )
    db.add(row)
    try:
        db.flush()
        audit_change(
            db,
            user,
            "user",
            row.id,
            {"created": {"email": row.email, "role": row.role}},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "La cuenta ya existe") from None
    return account_view(row)


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    body: AccountPatch,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    from .network_service import lock_org
    lock_org(db, user)
    row = db.scalar(select(User).where(User.id == user_id, User.org_id == user.org_id))
    if row is None:
        raise HTTPException(404, "Usuario no encontrado")
    if row.id == user.id and (not body.enabled or body.role != "admin"):
        raise HTTPException(409, "No puedes deshabilitar o degradar tu propia cuenta")
    before = account_view(row)
    row.role, row.enabled = body.role, body.enabled
    if before["role"] != row.role or before["enabled"] != row.enabled:
        from .network_accounts import revoke_sessions
        revoke_sessions(db, row)
    audit_change(db, user, "user", row.id, {"from": before, "to": account_view(row)})
    db.commit()
    return account_view(row)


@router.post("/sites", status_code=201)
def create_site(
    body: SiteCreate, user: User = Depends(administrator), db: Session = Depends(get_db)
):
    from .ops_import import _key

    name = clean_name(body.name)
    if any(
        _key(s.name) == _key(name)
        for s in db.scalars(select(Worksite).where(Worksite.org_id == user.org_id))
    ):
        raise HTTPException(409, "Ya existe una obra con ese nombre")
    row = Worksite(org_id=user.org_id, name=name)
    db.add(row)
    db.flush()
    audit_change(db, user, "worksite", row.id, {"created": {"name": name}})
    db.commit()
    return {"id": row.id, "name": row.name}


@router.get("/catalogs")
def catalogs(user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    return catalogs_for(db, user.org_id)


@router.put("/catalogs")
def update_catalogs(
    body: Catalogs, user: User = Depends(administrator), db: Session = Depends(get_db)
):
    row = db.get(OrganizationSettings, user.org_id)
    if row is None:
        row = OrganizationSettings(org_id=user.org_id)
        db.add(row)
    old = row.values or {}
    row.values = body.model_dump()
    audit_change(db, user, "catalogs", user.org_id, {"from": old, "to": row.values})
    db.commit()
    return row.values


@router.get("/rates")
def rates(user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    return [
        {
            "effective_from": r.effective_from,
            "daily_clp": r.daily_clp,
            "user_id": r.user_id,
        }
        for r in db.scalars(
            select(RetentionRate)
            .where(RetentionRate.org_id == user.org_id)
            .order_by(RetentionRate.effective_from.desc())
        )
    ]


@router.post("/rates", status_code=201)
def create_rate(
    body: RateCreate, user: User = Depends(administrator), db: Session = Depends(get_db)
):
    row = RetentionRate(org_id=user.org_id, user_id=user.id, **body.model_dump())
    db.add(row)
    try:
        db.flush()
        audit_change(
            db,
            user,
            "retention_rate",
            row.id,
            {"created": body.model_dump(mode="json")},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "Ya existe un valor para esa vigencia; se conserva su trazabilidad"
        ) from None
    return {"id": row.id}
