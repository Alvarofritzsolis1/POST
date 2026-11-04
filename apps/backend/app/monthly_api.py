"""Vinculación y revisión manual de documentos por contratista, obra y mes."""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db
from .contractor_policy import inactive_for_period
from .models import Document, User, utcnow
from .ops_api import association_for, audit_change
from .ops_models import MonthlyDocument, ContractorWorksite
from .security import authorized_user, editor, document_reviewer

router = APIRouter(prefix="/api/v1/ops/monthly-documents", tags=["Documentación mensual"])

DocumentKind = Literal["cotizaciones", "f30_1", "asistencia", "liquidaciones",
                       "declaracion_jurada", "porteria", "anticipos", "otros"]
ReviewStatus = Literal["pending", "approved", "observed", "rejected", "not_applicable"]


def valid_period(value: str) -> str:
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", value):
        raise ValueError("El período debe tener formato AAAA-MM")
    return value


class MonthlyLinkInput(BaseModel):
    association_id: str
    period: str
    kind: DocumentKind
    document_id: str | None = None
    not_applicable: bool = False
    notes: str = Field(default="", max_length=2000)

    @field_validator("period")
    @classmethod
    def validate_period(cls, value: str) -> str:
        return valid_period(value)


class MonthlyReviewInput(BaseModel):
    review_status: ReviewStatus
    notes: str = Field(default="", max_length=2000)


def view(row: MonthlyDocument, document: Document | None) -> dict:
    return {
        "id": row.id,
        "association_id": row.association_id,
        "contractor_id": row.contractor_id,
        "period": row.period,
        "kind": row.kind,
        "document_id": row.document_id,
        "review_status": row.review_status,
        "review_source": "manual_without_pdf" if row.document_id is None else "with_document",
        "notes": row.notes,
        "created_by": row.created_by,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "original_name": document.original_name if document else None,
        "ocr_status": document.status if document else None,
        "payment_status": document.payment_status if document else None,
    }


@router.get("")
def list_monthly_documents(
    association_id: str, period: str | None = Query(default=None),
    user: User = Depends(authorized_user), db: Session = Depends(get_db),
):
    association_for(db, user.org_id, association_id)
    if period is not None:
        try:
            valid_period(period)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    query = select(MonthlyDocument, Document).outerjoin(
        Document, (Document.id == MonthlyDocument.document_id) &
                  (Document.org_id == MonthlyDocument.org_id),
    ).where(MonthlyDocument.org_id == user.org_id,
            MonthlyDocument.association_id == association_id)
    if period:
        query = query.where(MonthlyDocument.period == period)
    rows = db.execute(query.order_by(MonthlyDocument.created_at.desc(),
                                     MonthlyDocument.id.desc())).all()
    return [view(row, document) for row, document in rows]


@router.post("", status_code=201)
def link_monthly_document(
    payload: MonthlyLinkInput,
    user: User = Depends(document_reviewer), db: Session = Depends(get_db),
):
    association, contractor = association_for(db, user.org_id, payload.association_id)
    # Serialize against a concurrent offboarding on the same association.
    association = db.scalar(select(ContractorWorksite).where(
        ContractorWorksite.org_id == user.org_id,
        ContractorWorksite.id == association.id,
    ).execution_options(populate_existing=True).with_for_update())
    if inactive_for_period(association, payload.period) and not payload.not_applicable:
        raise HTTPException(422, "Contratista inactivo: no se admite documentación nueva para este período")
    if payload.not_applicable and payload.document_id:
        raise HTTPException(422, "No aplica no puede tener archivo adjunto")
    if not payload.not_applicable and not payload.document_id:
        raise HTTPException(422, "Selecciona un documento o marca No aplica")
    doc = None
    if payload.document_id:
        doc = db.scalar(select(Document).where(
            Document.id == payload.document_id, Document.org_id == user.org_id))
        if doc is None:
            raise HTTPException(404, "Documento no encontrado en esta organización")
        if db.scalar(select(MonthlyDocument.id).where(
            MonthlyDocument.org_id == user.org_id,
            MonthlyDocument.association_id == payload.association_id,
            MonthlyDocument.period == payload.period,
            MonthlyDocument.kind == payload.kind,
            MonthlyDocument.document_id == doc.id)):
            raise HTTPException(409, "Ese archivo ya está vinculado a este período y tipo")
    else:
        if db.scalar(select(MonthlyDocument.id).where(
            MonthlyDocument.org_id == user.org_id,
            MonthlyDocument.association_id == payload.association_id,
            MonthlyDocument.period == payload.period,
            MonthlyDocument.kind == payload.kind,
            MonthlyDocument.document_id.is_(None))):
            raise HTTPException(409, "Ya existe un registro No aplica para este requisito")
    record = MonthlyDocument(
        org_id=user.org_id, association_id=association.id,
        contractor_id=contractor.id, period=payload.period,
        kind=payload.kind, document_id=payload.document_id,
        review_status="not_applicable" if payload.not_applicable else "pending",
        notes=payload.notes, created_by=user.id,
        reviewed_by=user.id if payload.not_applicable else None,
        reviewed_at=utcnow() if payload.not_applicable else None,
    )
    db.add(record)
    db.flush()
    audit_change(db, user, "monthly_document", record.id, {
        "created": {"association_id": association.id, "period": payload.period,
                    "kind": payload.kind, "document_id": payload.document_id,
                    "review_status": record.review_status},
    })
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "El registro mensual ya existe") from None
    return view(record, doc)


@router.patch("/{record_id}")
def review_monthly_document(
    record_id: str, payload: MonthlyReviewInput,
    user: User = Depends(document_reviewer), db: Session = Depends(get_db),
):
    record = db.scalar(select(MonthlyDocument).where(
        MonthlyDocument.id == record_id, MonthlyDocument.org_id == user.org_id))
    if record is None:
        raise HTTPException(404, "Registro mensual no encontrado")
    association_for(db, user.org_id, record.association_id)
    if record.document_id is not None and payload.review_status == "not_applicable":
        raise HTTPException(422, "No aplica requiere registro sin documento")
    if payload.review_status in {"observed", "rejected", "not_applicable"} and not payload.notes.strip():
        raise HTTPException(422, "Se requiere una observación para rechazar u observar")
    old = {"review_status": record.review_status, "notes": record.notes}
    record.review_status = payload.review_status
    record.notes = payload.notes.strip()
    record.reviewed_by = user.id
    record.reviewed_at = utcnow()
    record.updated_at = utcnow()
    audit_change(db, user, "monthly_document", record.id, {
        "review": {"from": old, "to": {"review_status": record.review_status,
                                      "notes": record.notes}},
    })
    doc = db.get(Document, record.document_id) if record.document_id else None
    db.commit()
    return view(record, doc)
