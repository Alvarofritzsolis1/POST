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


def new_session(user: User, db: Session | None = None) -> tuple[str, str]:
    secret = settings().app_secret
    if len(secret) < 48 or secret == "INSECURE_LOCAL_ONLY":
        raise RuntimeError("Configurar APP_SECRET fuerte antes de iniciar sesión")
    jti = secrets.token_hex(24)
    now = datetime.now(timezone.utc)
    from .network_models import NetworkMember
    member = db.get(NetworkMember, user.id) if db is not None else None
    data = {"sub": user.id, "org": user.org_id, "jti": jti,
            "ver": member.session_version if member else 0,
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
    from .network_models import NetworkMember
    member = db.get(NetworkMember, user.id)
    if payload.get("ver", 0) != (member.session_version if member else 0):
        raise HTTPException(401, "La sesión fue revocada. Inicia sesión nuevamente")
    db.info["network_auth"] = (user.id, payload.get("ver", 0))
    if user.role not in {"admin", "administrative", "resident"}:
        raise HTTPException(403, "Perfil anterior: un administrador debe asignarte uno de los tres perfiles vigentes")
    if user.role == "resident" and not (request.url.path.startswith("/api/v1/network/") or
            request.url.path in {"/api/v1/auth/me", "/api/v1/auth/logout"}):
        raise HTTPException(403, "El residente solo tiene acceso a Red de Obras")
    if user.role == "administrative":
        path = request.url.path
        allowed = (path.startswith("/api/v1/attendance/") or
                   path.startswith("/api/v1/attendance-v81/") or
                   path in {"/api/v1/ops/sites", "/api/v1/network/profile",
                            "/api/v1/labor/contract-alerts",
                            "/api/v1/auth/me", "/api/v1/auth/logout"} or
                   (request.method == "PATCH" and
                    path.startswith("/api/v1/labor/workers/") and path.endswith("/code")) or
                   (request.method == "POST" and path in {
                       "/api/v1/labor/workers", "/api/v1/labor/contracts",
                   }))
        if not allowed:
            raise HTTPException(403, "El administrativo solo tiene acceso a Control de Asistencia")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        expected = hmac.new(settings().app_secret.encode(), payload["jti"].encode(), hashlib.sha256).hexdigest()
        header = request.headers.get("X-CSRF-Token", "")
        cookie = request.cookies.get(CSRF, "")
        if not (header and hmac.compare_digest(header, expected) and hmac.compare_digest(cookie, expected)):
            raise HTTPException(403, "Token CSRF inválido")
    return user


def editor(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin"}:
        raise HTTPException(403, "Sin permiso de escritura")
    return user


def document_reviewer(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin"}:
        raise HTTPException(403, "Sin permiso de revisión documental")
    return user


def attendance_editor(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin", "administrative"}:
        raise HTTPException(403, "Sin permiso para registrar asistencia")
    return user


def contract_entry_editor(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin", "administrative"}:
        raise HTTPException(403, "Sin permiso para registrar contratos laborales")
    return user


def attendance_reviewer(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin"}:
        raise HTTPException(403, "Sin permiso para revisar asistencia")
    return user


def document_uploader(user: User = Depends(authorized_user)) -> User:
    if user.role not in {"admin"}:
        raise HTTPException(403, "Sin permiso para cargar documentos")
    return user


def administrator(user: User = Depends(authorized_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Solo el administrador puede realizar esta acción")
    return user
