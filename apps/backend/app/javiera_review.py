"""Revisión laboral/preventiva de JAVIERA: separación autor vs responsable.

Una revisión humana queda trazada; no equivale a certificación externa de la DT.
"""
from __future__ import annotations

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .javiera_models import JavieraReviewerAuthorization, JavieraSignoff
from .models import AuditEvent, User
from .network_models import NetworkMember
from .security import administrator, document_reviewer

router = APIRouter(prefix="/api/v1/javiera/admin/reviews", tags=["JAVIERA · Revisión"])

CHECKLISTS = {
    "laboral": (
        "identidad_y_empleador",
        "clausulas_y_naturaleza_servicios",
        "remuneraciones_y_jornada",
        "plazos_fechas_y_anexos",
        "coherencia_con_codigo_trabajo",
    ),
    "prevencion": (
        "riesgos_reales_de_la_actividad",
        "matriz_y_medidas_de_control",
        "puestos_sustancias_y_entorno",
        "eventos_capacitaciones_y_epp",
        "coherencia_con_ds44",
    ),
}
BASIS = {
    "laboral": "Código del Trabajo, artículos 9 y 10; https://www.bcn.cl/leychile/navegar?idNorma=207436",
    "prevencion": "D.S. 44, artículos 7 y 15; https://www.bcn.cl/leychile/navegar?idNorma=1205298",
}
KIND = {"template", "matrix", "excel_layout"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewerAssignment(Strict):
    user_id: str
    specialty: Literal["laboral", "prevencion"]
    designation: str = Field(min_length=12, max_length=240)
    active: bool = True


class ReviewInput(Strict):
    resource_kind: Literal["template", "matrix", "excel_layout"]
    resource_id: str
    specialty: Literal["laboral", "prevencion"]
    verdict: Literal["approved", "rejected"]
    checklist: dict[str, bool]
    comments: str = Field(min_length=40, max_length=4000)
    regulatory_basis: str = Field(min_length=12, max_length=250)


def audit(db: Session, user: User, action: str, resource_id: str):
    db.add(AuditEvent(org_id=user.org_id, user_id=user.id, action=action, resource_id=resource_id))


def valid_reviewer(db: Session, user: User, specialty: str):
    authority = db.scalar(select(JavieraReviewerAuthorization).where(
        JavieraReviewerAuthorization.org_id == user.org_id,
        JavieraReviewerAuthorization.user_id == user.id,
        JavieraReviewerAuthorization.specialty == specialty,
        JavieraReviewerAuthorization.active.is_(True)))
    if not authority:
        raise HTTPException(403, "Necesitas designación de revisor laboral o preventivo para esta organización")
    return authority


def require_signoff(db: Session, user: User, resource_kind: str, resource_id: str, specialty: str):
    valid_reviewer(db, user, specialty)
    record = db.scalar(select(JavieraSignoff).where(
        JavieraSignoff.org_id == user.org_id, JavieraSignoff.resource_kind == resource_kind,
        JavieraSignoff.resource_id == resource_id, JavieraSignoff.specialty == specialty,
        JavieraSignoff.verdict == "approved"))
    if not record:
        raise HTTPException(409, "Pendiente revisión humana documentada por responsable " + specialty)
    return record


def specialty_for_code(code: str) -> str:
    return ("laboral" if code in {
        "labor_contract", "transfer_addendum", "extension_addendum", "sworn_declaration"
    } else "prevencion")


@router.get("/checklists")
def checklists(user: User = Depends(document_reviewer)):
    return [{"specialty": key, "requirements": list(items), "legal_reference": BASIS[key]}
            for key, items in CHECKLISTS.items()]


@router.get("/reviewers")
def reviewers(user: User = Depends(administrator), db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(
        User.org_id == user.org_id, User.role.in_(("admin", "doc_reviewer")), User.enabled.is_(True))).all()
    grants = db.scalars(select(JavieraReviewerAuthorization).where(
        JavieraReviewerAuthorization.org_id == user.org_id)).all()
    allowed = {(g.user_id,g.specialty):g for g in grants}
    profiles = {p.user_id:p.name for p in db.scalars(select(NetworkMember).where(
        NetworkMember.user_id.in_([u.id for u in users]))).all()}
    return [{"user_id": u.id, "name": profiles.get(u.id) or "Administrador sin nombre registrado",
             "specialties": [{"specialty": scope, "active": allowed.get((u.id,scope)).active if (u.id,scope) in allowed else False,
                              "designation": allowed.get((u.id,scope)).designation if (u.id,scope) in allowed else ""}
                             for scope in CHECKLISTS]} for u in users]


@router.put("/reviewers")
def assign_reviewer(payload: ReviewerAssignment, user: User = Depends(administrator),
                    db: Session = Depends(get_db)):
    target = db.get(User, payload.user_id)
    if not target or target.org_id != user.org_id or target.role not in {"admin", "doc_reviewer"} or not target.enabled:
        raise HTTPException(404, "El responsable debe tener cuenta de revisor documental o administrador de la misma organización")
    if target.id == user.id:
        raise HTTPException(403, "Otro administrador debe acreditar la designación de revisor")
    grant = db.scalar(select(JavieraReviewerAuthorization).where(
        JavieraReviewerAuthorization.org_id == user.org_id,
        JavieraReviewerAuthorization.user_id == target.id,
        JavieraReviewerAuthorization.specialty == payload.specialty))
    if grant is None:
        grant = JavieraReviewerAuthorization(org_id=user.org_id, user_id=target.id,
            specialty=payload.specialty, delegated_by=user.id, designation=payload.designation)
        db.add(grant)
    else:
        grant.designation, grant.active, grant.delegated_by = (
            payload.designation, payload.active, user.id)
    db.flush()
    audit(db, user, "javiera.reviewer_assignment", grant.id)
    db.commit()
    return {"id":grant.id, "specialty":grant.specialty, "active":grant.active}


@router.post("/signoff")
def signoff(payload: ReviewInput, user: User = Depends(document_reviewer),
            db: Session = Depends(get_db)):
    from .javiera_models import JavieraExcelLayout, JavieraMatrix, JavieraRevision
    resources = {"template":JavieraRevision, "matrix":JavieraMatrix, "excel_layout":JavieraExcelLayout}
    obj = db.get(resources[payload.resource_kind], payload.resource_id)
    if not obj or obj.org_id != user.org_id:
        raise HTTPException(404, "Recurso fuera de la organización")
    if obj.author_id == user.id:
        raise HTTPException(403, "El autor no puede revisar ni aprobar su propio documento")
    valid_reviewer(db, user, payload.specialty)
    if payload.resource_kind == "matrix" and payload.specialty != "prevencion":
        raise HTTPException(422, "Las matrices preventivas requieren revisor de prevención")
    if payload.resource_kind in {"template","excel_layout"}:
        from .javiera_models import JavieraTemplate
        code = obj.code if payload.resource_kind == "excel_layout" else (
            db.get(JavieraTemplate, obj.template_id).code)
        if specialty_for_code(code) != payload.specialty:
            raise HTTPException(422, "La especialidad del revisor no corresponde al documento")
    expected = set(CHECKLISTS[payload.specialty])
    if set(payload.checklist) != expected or (
        payload.verdict == "approved" and not all(payload.checklist.values())
    ):
        raise HTTPException(422, "Debes completar los criterios de revisión de la especialidad")
    if payload.regulatory_basis.strip() != BASIS[payload.specialty]:
        raise HTTPException(422, "La referencia normativa debe coincidir con el catálogo vigente")
    previous = db.scalar(select(JavieraSignoff).where(
        JavieraSignoff.org_id == user.org_id, JavieraSignoff.resource_kind == payload.resource_kind,
        JavieraSignoff.resource_id == payload.resource_id,
        JavieraSignoff.specialty == payload.specialty))
    if previous is not None:
        raise HTTPException(409, "Esta revisión ya tiene un acta; crea una nueva versión si debe corregirse")
    row = JavieraSignoff(org_id=user.org_id, resource_kind=payload.resource_kind,
        resource_id=payload.resource_id, specialty=payload.specialty,
        verdict=payload.verdict, reviewer_id=user.id, checklist=payload.checklist,
        comments=payload.comments, regulatory_basis=payload.regulatory_basis)
    db.add(row)
    db.flush()
    audit(db, user, "javiera.review_" + row.verdict, row.id)
    db.commit()
    return {"id": row.id, "verdict": row.verdict, "resource_id": row.resource_id,
            "message": "Acta registrada; la validación profesional sigue siendo responsabilidad del revisor"}


@router.get("/signoff/{kind}/{resource_id}")
def get_signoff(kind: Literal["template", "matrix", "excel_layout"], resource_id: str,
                user: User = Depends(document_reviewer), db: Session = Depends(get_db)):
    rows = db.scalars(select(JavieraSignoff).where(
        JavieraSignoff.org_id == user.org_id, JavieraSignoff.resource_kind == kind,
        JavieraSignoff.resource_id == resource_id)).all()
    return [{"verdict": r.verdict, "specialty": r.specialty,
             "checklist":r.checklist, "comments":r.comments,
             "reviewer_id":r.reviewer_id, "created_at":r.created_at.isoformat(),
             "basis":r.regulatory_basis} for r in rows]
