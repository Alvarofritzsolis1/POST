"""GALANT 19.4.2: acceso autenticado a las imágenes del IRL original privado."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from .db import get_db
from .javiera_irl_original import load_original_for_user
from .models import User
from .security import administrator

router = APIRouter(prefix="/api/v1/javiera/v195", tags=["Javiera · IRL original A4"])


@router.get("/irl-original")
def irl_original(response: Response, user: User = Depends(administrator),
                 db: Session = Depends(get_db)):
    """La foto y el texto fijo se toman del XLSX de la organización; nunca del GitHub.

    La consulta no genera trabajadores ni modifica los otros módulos.
    """
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return load_original_for_user(db, user, approved_only=False)
