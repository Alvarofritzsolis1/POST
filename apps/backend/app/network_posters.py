"""Bounded, private image storage for approved social recruitment posters.

The browser composes the exact preview image. No AI-generated copy, remote URL,
site name, or unapproved media is accepted by the publisher from this module.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from .config import settings

MAX_JPEG_BYTES = 2_500_000
MAX_DATA_LENGTH = 3_400_000
POSTER_SIZE = (1080, 1350)
_DATA_URI = re.compile(r"^data:image/jpeg;base64,([A-Za-z0-9+/]+={0,2})$")


def poster_directory(org_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", org_id):
        raise HTTPException(422, "Identificador de organización inválido")
    return settings().document_dir / org_id / "network" / "posters"


def store_poster(data: str, org_id: str, requirement_id: str) -> str:
    """Validate and normalize user preview to one private, stable JPG.

    Reject SVG, scripts, remote URLs, huge images and image decompression bombs.
    The exact exported design becomes the attachment sent to Meta.
    """
    if not data or len(data) > MAX_DATA_LENGTH:
        raise HTTPException(422, "Se requiere la imagen JPG de la convocatoria (máximo 2,5 MB)")
    match = _DATA_URI.fullmatch(data)
    if not match:
        raise HTTPException(422, "La imagen debe ser JPG generada desde la vista previa")
    try:
        raw = base64.b64decode(match.group(1), validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "La imagen contiene datos inválidos") from None
    if not raw or len(raw) > MAX_JPEG_BYTES:
        raise HTTPException(422, "La imagen supera el máximo permitido de 2,5 MB")
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format != "JPEG" or image.size != POSTER_SIZE:
                raise HTTPException(422, "La imagen debe ser JPG de 1080 × 1350 píxeles")
            result = image.convert("RGB")
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(422, "Archivo de imagen dañado o no compatible") from None
    if not re.fullmatch(r"[a-f0-9-]{36}", requirement_id):
        raise HTTPException(422, "Identificador de convocatoria inválido")
    folder = poster_directory(org_id)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = folder / (requirement_id + ".jpg")
    temp = folder / ("." + uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as stream:
            os.chmod(temp, 0o600)
            result.save(stream, format="JPEG", quality=87, optimize=True)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return str(destination)


def verified_poster_path(value: str, org_id: str) -> Path:
    """Never let a database value turn into an arbitrary filesystem read."""
    base = poster_directory(org_id).resolve()
    path = Path(value).resolve()
    if path.parent != base or path.suffix != ".jpg" or not path.is_file():
        raise FileNotFoundError("No existe una imagen aprobada para esta publicación")
    if path.stat().st_size > MAX_JPEG_BYTES:
        raise ValueError("La imagen excede el tamaño permitido")
    return path
