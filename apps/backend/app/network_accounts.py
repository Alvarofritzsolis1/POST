"""Single-use invitations and account scopes. Tokens are never stored in plaintext."""

import hashlib
import logging
import secrets
import smtplib
import ssl
import time
from collections import defaultdict, deque
from datetime import timedelta
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User, utcnow
from .network_models import NetworkMember, NetworkMembership, NetworkToken
from .network_schemas import (
    AccountEdit,
    AccountInput,
    ForgotPassword,
    NetworkProfile,
    SetPassword,
)
from .network_service import (
    actor_name,
    assigned_sites,
    event,
    lock_org,
    member_for,
    require_site,
)
from .platform_models import UserPreferences
from .security import administrator, authorized_user, hash_password

router = APIRouter(prefix="/api/v1", tags=["Cuentas Red de Obras"])
attempts = defaultdict(deque)


def throttle(request, label):
    # Bounded IP/purpose buckets; no account discovery through response differences.
    identifier = (request.client.host if request.client else "unknown", label)
    now = time.monotonic()
    if len(attempts) > 5000:
        for k in list(attempts):
            if not attempts[k] or now - attempts[k][-1] > 600:
                attempts.pop(k, None)
    tries = attempts[identifier]
    while tries and now - tries[0] > 600:
        tries.popleft()
    if len(tries) >= 8:
        raise HTTPException(429, "Demasiados intentos. Intenta más tarde")
    tries.append(now)


def revoke_sessions(db, user):
    member = member_for(db, user)
    member.session_version += 1


def issue_token(db, target, purpose):
    for old in db.scalars(
        select(NetworkToken)
        .where(NetworkToken.user_id == target.id, NetworkToken.used_at.is_(None))
        .with_for_update()
    ):
        old.used_at = utcnow()
    raw = secrets.token_urlsafe(48)
    expiry = utcnow() + timedelta(hours=48 if purpose == "invite" else 1)
    db.add(
        NetworkToken(
            user_id=target.id,
            digest=hashlib.sha256(raw.encode()).hexdigest(),
            purpose=purpose,
            expires_at=expiry,
        )
    )
    return {"activation_path": "/#establecer-clave=" + raw, "expires_at": expiry}


def deliver_link(email, path):
    cfg = settings()
    if not cfg.smtp_host or not cfg.smtp_from or not cfg.public_url:
        return False
    message = EmailMessage()
    message["Subject"] = "GALANT POST · Establece tu contraseña"
    message["From"], message["To"] = cfg.smtp_from, email
    message.set_content(
        "Abre este enlace de un solo uso para establecer tu contraseña:\n\n"
        + cfg.public_url.rstrip("/")
        + path
        + "\n\nSi no lo solicitaste, ignora este mensaje."
    )
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if cfg.smtp_user:
                smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        logging.getLogger(__name__).warning(
            "No se pudo entregar el enlace de acceso por SMTP"
        )
        return False


def account_view(db, target):
    member = db.get(NetworkMember, target.id)
    return {
        "id": target.id,
        "email": target.email,
        "name": actor_name(db, target.id),
        "title": member.title if member else "",
        "role": target.role,
        "enabled": target.enabled,
        "site_ids": sorted(assigned_sites(db, target)),
        "can_award": bool(member and member.can_award),
    }


def assign(db, actor, target, body):
    if body.role in {"resident", "administrative"} and not body.site_ids:
        raise HTTPException(422, "Asigna al menos una obra al residente o administrativo")
    if len(body.site_ids) != len(set(body.site_ids)):
        raise HTTPException(422, "Obras repetidas")
    for site_id in body.site_ids:
        require_site(db, actor, site_id)
    db.execute(delete(NetworkMembership).where(NetworkMembership.user_id == target.id))
    for site_id in body.site_ids:
        db.add(
            NetworkMembership(user_id=target.id, site_id=site_id, assigned_by=actor.id)
        )
    member = member_for(db, target)
    member.name, member.title, member.can_award = (
        body.name, body.title, body.can_award if body.role == "resident" else False
    )
    preferences = db.get(UserPreferences, target.id)
    if preferences is None:
        preferences = UserPreferences(user_id=target.id, values={})
        db.add(preferences)
    preferences.values = {**(preferences.values or {}), "name": body.name}
    target.role, target.enabled = body.role, body.enabled


@router.get("/network/profile")
def profile(user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    pref = db.get(UserPreferences, user.id)
    return {
        **account_view(db, user),
        "notifications": (pref.values or {}).get("notifications", True)
        if pref
        else True,
    }


@router.put("/network/profile")
def edit_profile(
    body: NetworkProfile,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    member = member_for(db, user)
    before = {"name": member.name, "title": member.title}
    member.name, member.title = body.name, body.title
    pref = db.get(UserPreferences, user.id)
    if pref is None:
        pref = UserPreferences(user_id=user.id, values={})
        db.add(pref)
    pref.values = {
        **(pref.values or {}),
        "name": body.name,
        "notifications": body.notifications,
    }
    event(db, user, "profile", user.id, before, body.model_dump())
    db.commit()
    return profile(user, db)


@router.get("/network/users")
def accounts(user: User = Depends(administrator), db: Session = Depends(get_db)):
    return [
        account_view(db, row)
        for row in db.scalars(
            select(User).where(User.org_id == user.org_id).order_by(User.email)
        )
    ]


@router.post("/network/users", status_code=201)
def invite(
    body: AccountInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    from sqlalchemy.exc import IntegrityError

    lock_org(db, user)
    if db.scalar(
        select(User.id).where(func.lower(User.email) == str(body.email).lower())
    ):
        raise HTTPException(409, "Ya existe una cuenta con ese correo")
    target = User(
        org_id=user.org_id,
        email=str(body.email),
        role=body.role,
        password_hash=hash_password(secrets.token_urlsafe(48)),
        enabled=body.enabled,
    )
    db.add(target)
    try:
        db.flush()
        assign(db, user, target, body)
        link = issue_token(db, target, "invite")
        event(db, user, "account", target.id, None, account_view(db, target))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe una cuenta con ese correo") from None
    delivered = deliver_link(target.email, link["activation_path"])
    return {"user": account_view(db, target), **link, "email_delivered": delivered}


@router.patch("/network/users/{target_id}")
def edit_account(
    target_id: str,
    body: AccountEdit,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    target = db.scalar(
        select(User)
        .where(User.id == target_id, User.org_id == user.org_id)
        .with_for_update()
    )
    if target is None:
        raise HTTPException(404, "Cuenta no encontrada")
    if target.id == user.id and (not body.enabled or body.role != "admin"):
        raise HTTPException(409, "No puedes suspender o degradar tu propia cuenta")
    if (
        target.role == "admin"
        and target.enabled
        and (not body.enabled or body.role != "admin")
    ):
        count = db.scalar(
            select(func.count(User.id)).where(
                User.org_id == user.org_id, User.enabled.is_(True), User.role == "admin"
            )
        )
        if count <= 1:
            raise HTTPException(
                409, "No se puede suspender al último administrador activo"
            )
    before = account_view(db, target)
    assign(db, user, target, body)
    after = account_view(db, target)
    if any(before[k] != after[k] for k in ("role", "enabled", "site_ids", "can_award")):
        revoke_sessions(db, target)
    event(db, user, "account", target.id, before, after)
    db.commit()
    return after


@router.post("/network/users/{target_id}/access-link")
def access_link(
    target_id: str, user: User = Depends(administrator), db: Session = Depends(get_db)
):
    lock_org(db, user)
    target = db.scalar(
        select(User).where(User.id == target_id, User.org_id == user.org_id)
    )
    if target is None or not target.enabled:
        raise HTTPException(404, "Cuenta activa no encontrada")
    link = issue_token(db, target, "reset")
    event(db, user, "account_access", target.id, None, {"reset_link_issued": True})
    db.commit()
    return {
        **link,
        "email_delivered": deliver_link(target.email, link["activation_path"]),
    }


@router.post("/auth/forgot-password")
def forgot(body: ForgotPassword, request: Request, db: Session = Depends(get_db)):
    throttle(request, "forgot")
    target = db.scalar(
        select(User).where(
            User.email == str(body.email).lower(), User.enabled.is_(True)
        )
    )
    cfg = settings()
    if target and cfg.smtp_host and cfg.public_url and cfg.smtp_from:
        lock_org(db, target)
        link = issue_token(db, target, "reset")
        db.commit()
        deliver_link(target.email, link["activation_path"])
    return {
        "message": "Si la cuenta existe y el correo está configurado, recibirás un enlace. También puedes pedirlo a tu administrador."
    }


@router.post("/auth/network-password")
def set_password(body: SetPassword, request: Request, db: Session = Depends(get_db)):
    throttle(request, "password")
    digest = hashlib.sha256(body.token.encode()).hexdigest()
    token = db.scalar(select(NetworkToken).where(NetworkToken.digest == digest))
    if token is None:
        raise HTTPException(400, "Enlace inválido o caducado")
    target = db.get(User, token.user_id)
    lock_org(db, target)
    db.refresh(token, with_for_update=True)
    expiry = (
        token.expires_at.replace(tzinfo=utcnow().tzinfo)
        if token.expires_at.tzinfo is None
        else token.expires_at
    )
    if token.used_at or expiry < utcnow() or not target.enabled:
        raise HTTPException(400, "Enlace inválido o caducado")
    target.password_hash = hash_password(body.password)
    token.used_at = utcnow()
    revoke_sessions(db, target)
    event(db, target, "password", target.id, None, {"password_established": True})
    db.commit()
    return {"ok": True}
