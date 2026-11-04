import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import User

hasher = PasswordHasher()
SESSION = "galant_post_session"
CSRF = "galant_post_csrf"


def hash_password(value: str) -> str:
    if len(value) < 12:
        raise ValueError("La contraseña requiere al menos 12 caracteres")
    return hasher.hash(value)


def verify_password(value: str, digest: str) -> bool:
    try:
        return hasher.verify(digest, value)
    except Exception:
        return False


def new_session(user: User) -> tuple[str, str]:
    secret = settings().app_secret
    if len(secret) < 48 or secret == "INSECURE_LOCAL_ONLY":
        raise RuntimeError("Configurar APP_SECRET fuerte antes de iniciar sesión")
    jti = secrets.token_hex(24)
    now = datetime.now(timezone.utc)
    data = {"sub": user.id, "org": user.org_id, "jti": jti,
            "iat": now, "exp": now + timedelta(hours=settings().session_hours)}
    token = jwt.encode(data, secret, algorithm="HS256")
    csrf = hmac.new(secret.encode(), jti.encode(), hashlib.sha256).hexdigest()
    return token, csrf


def authorized_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw = request.cookies.get(SESSION)
    if not raw:
        raise HTTPException(401, "Inicia sesión")
    try:
        payload = jwt.decode(raw, settings().app_secret, algorithms=["HS256"])
        user = db.get(User, payload["sub"])
    except (jwt.PyJWTError, KeyError):
        raise HTTPException(401, "Sesión inválida") from None
    if not user or not user.enabled or payload.get("org") != user.org_id:
        raise HTTPException(401, "Sesión no autorizada")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        expected = hmac.new(settings().app_secret.encode(), payload["jti"].encode(), hashlib.sha256).hexdigest()
        header = request.headers.get("X-CSRF-Token", "")
        cookie = request.cookies.get(CSRF, "")
        if not (header and hmac.compare_digest(header, expected) and hmac.compare_digest(cookie, expected)):
            raise HTTPException(403, "Token CSRF inválido")
    return user


def editor(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin", "analyst", "supervisor"}:
        raise HTTPException(403, "Sin permiso de escritura")
    return user


def document_reviewer(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin", "analyst", "supervisor", "reviewer"}:
        raise HTTPException(403, "Sin permiso de revisión documental")
    return user


def attendance_editor(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin", "supervisor", "analyst", "administrative"}:
        raise HTTPException(403, "Sin permiso para registrar asistencia")
    return user


def attendance_reviewer(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin", "supervisor", "analyst"}:
        raise HTTPException(403, "Sin permiso para revisar asistencia")
    return user


def document_uploader(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin", "supervisor", "analyst", "reviewer", "administrative"}:
        raise HTTPException(403, "Sin permiso para cargar documentos")
    return user


def administrator(user: User = Depends(authorized_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Solo el administrador puede realizar esta acción")
    return user
