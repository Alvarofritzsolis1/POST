"""Pruebas MANUALES de Facebook Pages, independientes de publicación automática.

El token existe SOLO en el worker; la API guarda un trabajo transaccional.
La conexión verifica identidad/validez básica, NO garantiza permiso de publicar.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User, utcnow
from .network_models import NetworkFacebookManual
from .network_schemas import Input
from .ops_models import Worksite
from .security import administrator
from .network_service import lock_org

router = APIRouter(prefix="/api/v1/network/facebook", tags=["Facebook · pruebas"])


class ManualAd(Input):
    site_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=5, max_length=140)
    specialty: str = Field(min_length=2, max_length=100)
    city: str = Field(min_length=2, max_length=90)
    region: str = Field(min_length=2, max_length=90)
    workers: int = Field(ge=1, le=1000)
    start_date: date
    end_date: date
    deadline: date
    items: list[str] = Field(min_length=1, max_length=10)
    requirements: str = Field(default="", max_length=800)
    contact_mode: Literal["messenger", "email", "whatsapp"] = "messenger"
    contact_value: str = Field(default="", max_length=140)

    @model_validator(mode="after")
    def validate_ad(self):
        if self.end_date < self.start_date or self.deadline > self.end_date:
            raise ValueError("Verifica fechas de inicio, término y plazo de recepción")
        if self.deadline < date.today():
            raise ValueError("El plazo de postulación no puede estar en el pasado")
        if any(not 2 <= len(part.strip()) <= 120 for part in self.items):
            raise ValueError("Cada partida debe contener entre 2 y 120 caracteres")
        if len(set(part.strip().casefold() for part in self.items)) != len(self.items):
            raise ValueError("Las partidas no deben repetirse")
        if self.contact_mode == "email":
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.contact_value):
                raise ValueError("Ingresa un correo válido de contacto comercial")
        elif self.contact_mode == "whatsapp":
            if not re.fullmatch(r"\+?[0-9 ]{9,18}", self.contact_value):
                raise ValueError("Ingresa un WhatsApp válido con código de país")
        elif self.contact_value.strip():
            raise ValueError("Messenger no requiere información de contacto adicional")
        return self


class ManualPublish(Input):
    ad: ManualAd
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation: Literal["PUBLICAR PRUEBA"]
    client_key: str = Field(min_length=8, max_length=80)


class ManualRemove(Input):
    confirmation: Literal["RETIRAR PRUEBA"]


def _site(db: Session, user: User, site_id: str) -> Worksite:
    site = db.scalar(select(Worksite).where(Worksite.id == site_id, Worksite.org_id == user.org_id))
    if site is None:
        raise HTTPException(422, "Selecciona una obra registrada en GALANT")
    return site


def _format(db: Session, user: User, ad: ManualAd) -> tuple[str, str]:
    site = _site(db, user, ad.site_id)
    values = [
        "🧪 PUBLICACIÓN DE PRUEBA — NO ES UNA CONVOCATORIA REAL", "",
        "EMPRESAS CONTRATISTAS DE CONSTRUCCIÓN", "",
        ad.title, "",
        "📍 Obra: " + site.name,
        "Ubicación: " + ad.city + ", " + ad.region,
        "Especialidad: " + ad.specialty,
        "Dotación estimada: " + str(ad.workers) + " personas",
        "Inicio previsto: " + ad.start_date.strftime("%d/%m/%Y"),
        "Término estimado: " + ad.end_date.strftime("%d/%m/%Y"),
        "Fecha límite de contacto: " + ad.deadline.strftime("%d/%m/%Y"), "",
        "PARTIDAS CONSIDERADAS:",
        *("• " + part.strip() for part in ad.items), "",
    ]
    if ad.requirements.strip():
        values.extend(["REQUISITOS PARA EMPRESAS:", ad.requirements.strip(), ""])
    values.append("CONTACTO:")
    if ad.contact_mode == "messenger":
        values.append("Escríbenos por mensaje privado a esta página.")
    elif ad.contact_mode == "email":
        values.append("Correo comercial: " + ad.contact_value.strip())
    else:
        values.append("WhatsApp comercial: " + ad.contact_value.strip())
    values.extend(["", "Publicación de ensayo técnico. No se recibirán postulaciones ni se adjudicarán partidas con esta prueba."])
    message = "\n".join(values)
    if len(message) > 4000:
        raise HTTPException(422, "El anuncio supera 4.000 caracteres; resume las partidas o requisitos")
    cfg = settings()
    digest = hashlib.sha256((cfg.facebook_page_id + "\n" + message).encode("utf-8")).hexdigest()
    return message, digest


def _view(row: NetworkFacebookManual) -> dict:
    return {
        "id": row.id, "kind": row.action, "state": row.state,
        "title": row.title, "page_name": row.page_name,
        "post_url": (
            "https://www.facebook.com/" + row.post_id
            if row.post_id and re.fullmatch(r"[0-9]+_[0-9]+", row.post_id) else None
        ),
        "error": row.last_error, "created_at": row.created_at.isoformat(),
    }


def _assert_enabled():
    cfg = settings()
    if not cfg.facebook_manual_testing_enabled:
        raise HTTPException(409, "El modo de prueba está desactivado. No se publicó nada.")
    if not re.fullmatch(r"[0-9]{5,30}", cfg.facebook_page_id):
        raise HTTPException(409, "Falta configurar el ID de la página")
    return cfg


@router.get("/tests")
def list_manual_tests(user: User = Depends(administrator), db: Session = Depends(get_db)):
    cfg = settings()
    rows = list(db.scalars(select(NetworkFacebookManual).where(
        NetworkFacebookManual.org_id == user.org_id,
    ).order_by(NetworkFacebookManual.created_at.desc(), NetworkFacebookManual.id.desc()).limit(30)))
    verified = next((r for r in rows if r.action == "verify" and r.state == "verified"), None)
    return {
        "manual_enabled": cfg.facebook_manual_testing_enabled,
        "automatic_enabled": cfg.facebook_autopublish_enabled,
        "page_id": cfg.facebook_page_id,
        "verified_page_name": verified.page_name if verified else None,
        "history": [_view(r) for r in rows],
    }


@router.post("/tests/preview")
def preview_manual_test(ad: ManualAd, user: User = Depends(administrator), db: Session = Depends(get_db)):
    message, digest = _format(db, user, ad)
    return {"message": message, "preview_hash": digest, "character_count": len(message)}


@router.post("/tests/verify", status_code=202)
def verify_page(user: User = Depends(administrator), db: Session = Depends(get_db)):
    cfg = _assert_enabled()
    lock_org(db, user)
    running = db.scalar(select(NetworkFacebookManual).where(
        NetworkFacebookManual.org_id == user.org_id,
        NetworkFacebookManual.page_id == cfg.facebook_page_id,
        NetworkFacebookManual.action == "verify",
        NetworkFacebookManual.state.in_(["pending", "sending"]),
    ))
    if running:
        return _view(running)
    row = NetworkFacebookManual(
        org_id=user.org_id, created_by=user.id,
        page_id=cfg.facebook_page_id, client_key=str(uuid4()),
        action="verify", state="pending", title="Comprobación de identidad y token",
    )
    db.add(row)
    db.commit()
    return _view(row)


@router.post("/tests/publish", status_code=202)
def publish_manual_test(body: ManualPublish, user: User = Depends(administrator), db: Session = Depends(get_db)):
    cfg = _assert_enabled()
    lock_org(db, user)
    message, digest = _format(db, user, body.ad)
    if digest != body.preview_hash:
        raise HTTPException(409, "Cambió el formulario desde la vista previa. Previsualiza otra vez.")
    previous = db.scalar(select(NetworkFacebookManual).where(
        NetworkFacebookManual.org_id == user.org_id,
        NetworkFacebookManual.client_key == body.client_key,
    ))
    if previous:
        if previous.message != message or previous.action not in ("publish", "delete"):
            raise HTTPException(409, "Esa solicitud ya fue usada para otro contenido")
        return _view(previous)
    row = NetworkFacebookManual(
        org_id=user.org_id, created_by=user.id, page_id=cfg.facebook_page_id,
        client_key=body.client_key, action="publish", state="pending",
        title=body.ad.title, message=message,
    )
    db.add(row)
    db.commit()
    return _view(row)


@router.post("/tests/{test_id}/remove", status_code=202)
def remove_manual_test(test_id: str, body: ManualRemove, user: User = Depends(administrator), db: Session = Depends(get_db)):
    cfg = _assert_enabled()
    lock_org(db, user)
    row = db.scalar(select(NetworkFacebookManual).where(
        NetworkFacebookManual.org_id == user.org_id,
        NetworkFacebookManual.id == test_id,
        NetworkFacebookManual.page_id == cfg.facebook_page_id,
    ))
    if not row:
        raise HTTPException(404, "No se encontró la publicación de prueba")
    if row.action == "delete" and row.state in ("pending", "sending", "deleted"):
        return _view(row)
    if row.action != "publish" or row.state != "published" or not row.post_id:
        raise HTTPException(409, "Solo se pueden retirar publicaciones de prueba confirmadas")
    row.action, row.state, row.updated_at = "delete", "pending", utcnow()
    row.last_error = None
    db.commit()
    return _view(row)
