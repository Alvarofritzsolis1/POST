"""Operational collaboration inside GALANT POST, backed by the shared database."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import User, utcnow
from .network_models import (
    NetworkAward,
    NetworkCapacity,
    NetworkConversation,
    NetworkCoordination,
    NetworkItem,
    NetworkMatch,
    NetworkMembership,
    NetworkMessage,
    NetworkNotification,
    NetworkParticipant,
    NetworkPendingItem,
    NetworkRequirement,
)
from .network_schemas import (
    AmendmentInput,
    AwardEdit,
    AwardInput,
    AwardRevision,
    CapacityInput,
    CoordinationEdit,
    InterestInput,
    MessageInput,
    ParticipantInput,
    RequirementInput,
    Renewal,
)
from .network_service import (
    actor_name,
    allocation,
    assigned_sites,
    award_view,
    capacity_for,
    capacity_view,
    check_version,
    clearance,
    committed_workers,
    key,
    coordination_records,
    coordination_view,
    event,
    lock_org,
    manages,
    match_score,
    notify,
    participant_for,
    rebuild_matches,
    record_for,
    require_awarder,
    require_site,
    requirement_for,
    requirement_view,
    site_users,
    today,
)
from .ops_models import Contractor, ContractorWorksite, OpsChange, Worksite
from .security import administrator, authorized_user

router = APIRouter(prefix="/api/v1/network", tags=["Red de Obras"])


def pagination(query, db, limit, offset):
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return list(db.scalars(query.limit(limit).offset(offset))), total


def scoped_requirements(db, user):
    query = select(NetworkRequirement).where(NetworkRequirement.org_id == user.org_id)
    if user.role == "resident":
        query = query.where(
            (NetworkRequirement.state != "draft")
            | NetworkRequirement.site_id.in_(assigned_sites(db, user))
        )
    elif user.role not in {"admin", "supervisor", "analyst"}:
        query = query.where(NetworkRequirement.state != "draft")
    return query


@router.get("/catalog")
def catalog(user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    sites = list(
        db.scalars(
            select(Worksite)
            .where(Worksite.org_id == user.org_id)
            .order_by(Worksite.name)
        )
    )
    links = list(
        db.scalars(
            select(ContractorWorksite).where(ContractorWorksite.org_id == user.org_id)
        )
    )
    return {
        "sites": [
            {"id": s.id, "name": s.name, "editable": manages(db, user, s.id)}
            for s in sites
        ],
        "contractors": [
            {
                "id": c.id,
                "name": c.name,
                "rut": c.rut,
                "site_ids": [
                    l.worksite_id
                    for l in links
                    if l.contractor_id == c.id and l.contract_status == "active"
                ],
            }
            for c in db.scalars(
                select(Contractor)
                .where(Contractor.org_id == user.org_id)
                .order_by(Contractor.name)
            )
        ],
        "specialties": sorted(
            {
                key(s): s
                for s in db.scalars(
                    select(NetworkCapacity.specialty)
                    .where(NetworkCapacity.org_id == user.org_id)
                    .union(
                        select(NetworkRequirement.specialty).where(
                            NetworkRequirement.org_id == user.org_id
                        )
                    )
                )
            }.values()
        ),
    }


@router.get("/contractors/{contractor_id}/clearance")
def contractor_clearance(
    contractor_id: str,
    site_id: str,
    period: str,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    from .monthly_api import valid_period

    try:
        valid_period(period)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    record_for(db, Contractor, user, contractor_id)
    require_site(db, user, site_id, write=True)
    return clearance(db, user, contractor_id, site_id, period)


@router.get("/requirements")
def requirements(
    site_id: str | None = None,
    specialty: str = "",
    q: str = "",
    priority: str = "",
    mine: bool = False,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    query = scoped_requirements(db, user)
    if site_id:
        require_site(db, user, site_id)
        query = query.where(NetworkRequirement.site_id == site_id)
    if mine and user.role == "resident":
        query = query.where(NetworkRequirement.site_id.in_(assigned_sites(db, user)))
    if specialty:
        query = query.where(NetworkRequirement.specialty_key == key(specialty))
    if q:
        query = query.where(NetworkRequirement.title.ilike("%" + q[:180] + "%"))
    if priority:
        query = query.where(
            NetworkRequirement.priority.in_(["high", "urgent"])
            if priority == "attention"
            else NetworkRequirement.priority == priority
        )
    rows, total = pagination(
        query.order_by(NetworkRequirement.created_at.desc(), NetworkRequirement.id),
        db,
        limit,
        offset,
    )
    return {"rows": [requirement_view(db, user, r) for r in rows], "total": total}


@router.get("/requirements/{record_id}")
def requirement(
    record_id: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)
):
    return requirement_view(
        db, user, requirement_for(db, user, record_id), detailed=True
    )


def save_items(db, user, row, body):
    existing = {
        i.id: i
        for i in db.scalars(
            select(NetworkItem).where(NetworkItem.requirement_id == row.id)
        )
    }
    seen = set()
    for pos, item in enumerate(body.items):
        if item.id:
            if item.id not in existing or item.id in seen:
                raise HTTPException(422, "Partida duplicada o ajena al requerimiento")
            stored = existing[item.id]
            seen.add(item.id)
            if db.scalar(
                select(NetworkAward.id)
                .where(NetworkAward.item_id == stored.id)
                .limit(1)
            ):
                if stored.quantity != item.quantity or stored.unit != item.unit:
                    raise HTTPException(
                        409,
                        "Una partida con historial requiere una ampliación formal; no cambies su unidad",
                    )
        else:
            stored = NetworkItem(org_id=user.org_id, requirement_id=row.id)
            db.add(stored)
        for field, value in item.model_dump(exclude={"id"}).items():
            setattr(stored, field, value)
        stored.position = pos
    for item_id, stored in existing.items():
        if item_id not in seen:
            if db.scalar(
                select(NetworkAward.id).where(NetworkAward.item_id == item_id).limit(1)
            ):
                raise HTTPException(
                    409,
                    "No se puede eliminar una partida con historial de adjudicación",
                )
            db.delete(stored)


@router.post("/requirements", status_code=201)
def create_requirement(
    body: RequirementInput,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    require_site(db, user, body.site_id, write=True)
    prior = db.scalar(
        select(NetworkRequirement).where(
            NetworkRequirement.org_id == user.org_id,
            NetworkRequirement.client_key == body.client_key,
        )
    )
    if prior:
        if (
            prior.created_by != user.id
            or prior.title != body.title
            or prior.site_id != body.site_id
        ):
            raise HTTPException(409, "La clave de publicación ya se utilizó")
        return requirement_view(db, user, prior, True)
    row = NetworkRequirement(
        org_id=user.org_id,
        created_by=user.id,
        specialty_key=key(body.specialty),
        **body.model_dump(exclude={"items", "version", "reason"}),
    )
    db.add(row)
    db.flush()
    save_items(db, user, row, body)
    event(db, user, "requirement", row.id, None, body.model_dump(mode="json"))
    if row.state == "published":
        residents = db.scalars(
            select(User.id).where(User.org_id == user.org_id, User.role == "resident")
        )
        notify(
            db,
            user,
            residents,
            "requirement:" + row.id,
            "Nueva necesidad: " + row.title,
            "requirement",
            row.id,
        )
    rebuild_matches(db, user)
    db.commit()
    return requirement_view(db, user, row, True)


@router.put("/requirements/{record_id}")
def update_requirement(
    record_id: str,
    body: RequirementInput,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    row = requirement_for(db, user, record_id, write=True)
    require_site(db, user, body.site_id, write=True)
    check_version(row, body.version)
    if row.state != "draft" and not body.reason:
        raise HTTPException(422, "Indica el motivo de la modificación")
    before = requirement_view(db, user, row)
    awards = db.scalars(
        select(NetworkAward)
        .join(NetworkItem, NetworkItem.id == NetworkAward.item_id)
        .where(NetworkItem.requirement_id == row.id)
    ).all()
    if row.site_id != body.site_id and (
        awards
        or db.scalar(
            select(NetworkMatch.id).where(NetworkMatch.requirement_id == row.id)
        )
    ):
        raise HTTPException(
            409, "La obra de un requerimiento vinculado no se puede cambiar"
        )
    if body.state != "published" and any(a.state != "revoked" for a in awards):
        raise HTTPException(
            409, "Revoca las adjudicaciones antes de cancelar o convertir en borrador"
        )
    for field, value in body.model_dump(
        exclude={"items", "client_key", "version", "reason"}
    ).items():
        setattr(row, field, value)
    row.version += 1
    row.specialty_key = key(body.specialty)
    row.updated_at = utcnow()
    save_items(db, user, row, body)
    event(
        db,
        user,
        "requirement",
        row.id,
        before,
        body.model_dump(mode="json"),
        body.reason,
    )
    rebuild_matches(db, user)
    notify(
        db,
        user,
        site_users(db, user, row.site_id),
        f"request:{row.id}:{row.version}",
        "Se actualizó la programación: " + row.title,
        "requirement",
        row.id,
    )
    db.commit()
    return requirement_view(db, user, row, True)


@router.get("/capacities")
def capacities(
    site_id: str | None = None,
    specialty: str = "",
    q: str = "",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
    contractor_id: str | None = None,
):
    query = select(NetworkCapacity).where(NetworkCapacity.org_id == user.org_id)
    if user.role == "resident":
        query = query.where(
            (NetworkCapacity.state != "draft")
            | NetworkCapacity.site_id.in_(assigned_sites(db, user))
        )
    elif user.role not in {"admin", "supervisor", "analyst"}:
        query = query.where(NetworkCapacity.state != "draft")
    if site_id:
        require_site(db, user, site_id)
        query = query.where(NetworkCapacity.site_id == site_id)
    if specialty:
        query = query.where(NetworkCapacity.specialty_key == key(specialty))
    if q:
        query = query.join(
            Contractor, Contractor.id == NetworkCapacity.contractor_id
        ).where(Contractor.name.ilike("%" + q[:180] + "%"))
    if contractor_id:
        record_for(db, Contractor, user, contractor_id)
        query = query.where(NetworkCapacity.contractor_id == contractor_id)
    rows, total = pagination(
        query.order_by(NetworkCapacity.updated_at.desc(), NetworkCapacity.id),
        db,
        limit,
        offset,
    )
    return {"rows": [capacity_view(db, user, r) for r in rows], "total": total}


@router.get("/capacities/{record_id}")
def capacity(
    record_id: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)
):
    return capacity_view(db, user, capacity_for(db, user, record_id))


def capacity_fields(db, user, row, body):
    require_site(db, user, body.site_id, write=True)
    company = record_for(db, Contractor, user, body.contractor_id)
    link = db.scalar(
        select(ContractorWorksite.id).where(
            ContractorWorksite.org_id == user.org_id,
            ContractorWorksite.contractor_id == company.id,
            ContractorWorksite.worksite_id == body.site_id,
            ContractorWorksite.contract_status == "active",
        )
    )
    if not link:
        raise HTTPException(
            422, "El contratista debe estar registrado y activo en la obra de origen"
        )
    for field, value in body.model_dump(
        exclude={"pending_items", "client_key", "version", "validity_days"}
    ).items():
        setattr(row, field, value)
    row.expires_on = today() + timedelta(days=body.validity_days)
    row.updated_at = utcnow()
    row.specialty_key = key(body.specialty)
    row.confirmed_at = utcnow() if body.availability == "confirmed" else None
    db.flush()
    db.execute(
        delete(NetworkPendingItem).where(NetworkPendingItem.capacity_id == row.id)
    )
    for item in body.pending_items:
        db.add(
            NetworkPendingItem(
                org_id=user.org_id, capacity_id=row.id, **item.model_dump()
            )
        )


@router.post("/capacities", status_code=201)
def create_capacity(
    body: CapacityInput,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    require_site(db, user, body.site_id, write=True)
    prior = db.scalar(
        select(NetworkCapacity).where(
            NetworkCapacity.org_id == user.org_id,
            NetworkCapacity.client_key == body.client_key,
        )
    )
    if prior:
        if prior.created_by != user.id or prior.contractor_id != body.contractor_id:
            raise HTTPException(409, "La clave de publicación ya se utilizó")
        return capacity_view(db, user, prior)
    # Fill required values before the first flush.
    row = NetworkCapacity(
        org_id=user.org_id,
        created_by=user.id,
        client_key=body.client_key,
        specialty_key=key(body.specialty),
        expires_on=today() + timedelta(days=body.validity_days),
        **body.model_dump(
            exclude={"pending_items", "client_key", "version", "validity_days"}
        ),
    )
    db.add(row)
    capacity_fields(db, user, row, body)
    event(db, user, "capacity", row.id, None, body.model_dump(mode="json"))
    rebuild_matches(db, user)
    db.commit()
    return capacity_view(db, user, row)


@router.put("/capacities/{record_id}")
def update_capacity(
    record_id: str,
    body: CapacityInput,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    row = capacity_for(db, user, record_id, write=True)
    check_version(row, body.version)
    if row.site_id != body.site_id or row.contractor_id != body.contractor_id:
        raise HTTPException(
            409, "Conserva la obra y contratista originales; crea una publicación nueva"
        )
    before = capacity_view(db, user, row)
    capacity_fields(db, user, row, body)
    row.version += 1
    event(db, user, "capacity", row.id, before, body.model_dump(mode="json"))
    rebuild_matches(db, user)
    db.commit()
    return capacity_view(db, user, row)


@router.post("/capacities/{record_id}/renew")
def renew_capacity(
    record_id: str,
    body: Renewal,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    row = capacity_for(db, user, record_id, write=True)
    check_version(row, body.version)
    before = {"expires_on": str(row.expires_on)}
    row.expires_on = today() + timedelta(days=body.validity_days)
    row.updated_at = utcnow()
    row.version += 1
    event(
        db,
        user,
        "capacity_renewal",
        row.id,
        before,
        {"expires_on": str(row.expires_on)},
    )
    rebuild_matches(db, user)
    db.commit()
    return capacity_view(db, user, row)


@router.get("/matches")
def matches(
    site_id: str | None = None,
    specialty: str = "",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
    capacity_id: str | None = None,
):
    query = (
        select(NetworkMatch)
        .join(NetworkRequirement, NetworkRequirement.id == NetworkMatch.requirement_id)
        .join(NetworkCapacity, NetworkCapacity.id == NetworkMatch.capacity_id)
        .where(
            NetworkMatch.org_id == user.org_id,
            NetworkMatch.active.is_(True),
            NetworkCapacity.expires_on >= today(),
        )
    )
    if site_id:
        require_site(db, user, site_id)
        query = query.where(
            (NetworkRequirement.site_id == site_id)
            | (NetworkCapacity.site_id == site_id)
        )
    if specialty:
        query = query.where(NetworkRequirement.specialty_key == key(specialty))
    if capacity_id:
        capacity_for(db, user, capacity_id)
        query = query.where(NetworkMatch.capacity_id == capacity_id)
    rows, total = pagination(
        query.order_by(NetworkMatch.score.desc(), NetworkMatch.id), db, limit, offset
    )
    return {
        "rows": [
            {
                "id": m.id,
                "score": m.score,
                "reasons": m.reasons,
                "requirement": requirement_view(
                    db, user, db.get(NetworkRequirement, m.requirement_id)
                ),
                "capacity": capacity_view(
                    db, user, db.get(NetworkCapacity, m.capacity_id)
                ),
            }
            for m in rows
        ],
        "total": total,
    }


@router.post("/coordinations", status_code=201)
def interest(
    body: InterestInput,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    match = record_for(db, NetworkMatch, user, body.match_id)
    req = requirement_for(db, user, match.requirement_id)
    cap = capacity_for(db, user, match.capacity_id)
    if not (manages(db, user, req.site_id) or manages(db, user, cap.site_id)):
        raise HTTPException(
            403, "Solo las obras involucradas pueden iniciar la coordinación"
        )
    coord = db.scalar(
        select(NetworkCoordination).where(NetworkCoordination.match_id == match.id)
    )
    if coord is None:
        if not match.active or match_score(db, req, cap) is None:
            raise HTTPException(
                409, "La oportunidad ya no está vigente; actualiza los datos"
            )
        coord = NetworkCoordination(
            org_id=user.org_id, match_id=match.id, created_by=user.id
        )
        db.add(coord)
        db.flush()
        conversation = NetworkConversation(org_id=user.org_id, coordination_id=coord.id)
        db.add(conversation)
        db.flush()
        for participant_id in {user.id, req.created_by, cap.created_by}:
            db.add(
                NetworkParticipant(
                    conversation_id=conversation.id, user_id=participant_id
                )
            )
        event(
            db,
            user,
            "coordination",
            coord.id,
            None,
            {"state": "interested", "match_id": match.id},
        )
        notify(
            db,
            user,
            site_users(db, user, req.site_id) + site_users(db, user, cap.site_id),
            "interest:" + coord.id,
            "Interés registrado: " + req.title,
            "coordination",
            coord.id,
        )
    else:
        conversation = db.scalar(
            select(NetworkConversation).where(
                NetworkConversation.coordination_id == coord.id
            )
        )
        if not db.get(NetworkParticipant, (conversation.id, user.id)):
            db.add(NetworkParticipant(conversation_id=conversation.id, user_id=user.id))
            event(db, user, "participant", conversation.id, None, {"joined": user.id})
    db.commit()
    return coordination_view(db, user, coord)


@router.get("/coordinations")
def coordinations(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
    requirement_id: str | None = None,
):
    query = (
        select(NetworkCoordination)
        .join(NetworkMatch, NetworkMatch.id == NetworkCoordination.match_id)
        .join(NetworkRequirement, NetworkRequirement.id == NetworkMatch.requirement_id)
        .join(NetworkCapacity, NetworkCapacity.id == NetworkMatch.capacity_id)
        .where(NetworkCoordination.org_id == user.org_id)
    )
    if requirement_id:
        requirement_for(db, user, requirement_id)
        query = query.where(NetworkRequirement.id == requirement_id)
    if user.role == "resident":
        ids = assigned_sites(db, user)
        query = query.where(
            NetworkRequirement.site_id.in_(ids) | NetworkCapacity.site_id.in_(ids)
        )
    elif user.role not in {"admin", "supervisor", "analyst"}:
        return {"rows": [], "total": 0}
    rows, total = pagination(
        query.order_by(NetworkCoordination.updated_at.desc(), NetworkCoordination.id),
        db,
        limit,
        offset,
    )
    return {"rows": [coordination_view(db, user, c) for c in rows], "total": total}


STEPS = [
    "interested",
    "contacted",
    "evaluating",
    "confirmed",
    "proposed",
    "approved",
    "documents_pending",
    "documents_complete",
    "finished",
]


@router.patch("/coordinations/{record_id}")
def edit_coordination(
    record_id: str,
    body: CoordinationEdit,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    coord = record_for(db, NetworkCoordination, user, record_id, lock=True)
    _, req, cap = coordination_records(db, user, coord)
    check_version(coord, body.version)
    if coord.state in {"cancelled", "rejected", "finished"}:
        raise HTTPException(409, "La coordinación ya está cerrada")
    terminal = body.state in {"cancelled", "rejected"}
    if terminal:
        if not body.reason:
            raise HTTPException(422, "Indica el motivo de rechazo o cancelación")
    elif body.state != STEPS[STEPS.index(coord.state) + 1]:
        raise HTTPException(409, "Transición de coordinación inválida")
    if body.state == "confirmed":
        require_site(db, user, cap.site_id, write=True)
        if cap.expires_on < today() or cap.availability != "confirmed":
            raise HTTPException(
                409,
                "El residente de origen debe confirmar y mantener vigente la capacidad",
            )
    if body.state in {"approved", "documents_complete", "finished"}:
        require_awarder(db, user, req.site_id)
    if body.state == "proposed":
        require_site(db, user, req.site_id, write=True)
    if (
        body.state == "documents_complete"
        and clearance(
            db, user, cap.contractor_id, req.site_id, req.start_date.strftime("%Y-%m")
        )["state"]
        != "enabled"
    ):
        raise HTTPException(
            409, "La habilitación documental de destino aún está pendiente"
        )
    if body.state == "finished" and not db.scalar(
        select(NetworkAward.id)
        .where(
            NetworkAward.coordination_id == coord.id, NetworkAward.state != "revoked"
        )
        .limit(1)
    ):
        raise HTTPException(
            409,
            "Registra una adjudicación vinculada antes de finalizar la coordinación",
        )
    previous = coord.state
    coord.state, coord.reason = body.state, body.reason
    coord.version += 1
    coord.updated_at = utcnow()
    event(
        db,
        user,
        "coordination",
        coord.id,
        {"state": previous},
        body.model_dump(),
        body.reason,
    )
    notify(
        db,
        user,
        site_users(db, user, req.site_id) + site_users(db, user, cap.site_id),
        f"coordination:{coord.id}:{coord.version}",
        "Coordinación actualizada: " + req.title,
        "coordination",
        coord.id,
    )
    db.commit()
    return coordination_view(db, user, coord)


@router.get("/conversations")
def conversations(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    query = (
        select(NetworkConversation)
        .join(
            NetworkParticipant,
            NetworkParticipant.conversation_id == NetworkConversation.id,
        )
        .where(
            NetworkConversation.org_id == user.org_id,
            NetworkParticipant.user_id == user.id,
        )
    )
    if user.role == "resident":
        ids = assigned_sites(db, user)
        query = (
            query.join(
                NetworkCoordination,
                NetworkCoordination.id == NetworkConversation.coordination_id,
            )
            .join(NetworkMatch, NetworkMatch.id == NetworkCoordination.match_id)
            .join(
                NetworkRequirement, NetworkRequirement.id == NetworkMatch.requirement_id
            )
            .join(NetworkCapacity, NetworkCapacity.id == NetworkMatch.capacity_id)
            .where(
                NetworkRequirement.site_id.in_(ids) | NetworkCapacity.site_id.in_(ids)
            )
        )
    rows, total = pagination(
        query.order_by(NetworkConversation.created_at.desc(), NetworkConversation.id),
        db,
        limit,
        offset,
    )
    result = []
    for row in rows:
        coord = db.get(NetworkCoordination, row.coordination_id)
        match = db.get(NetworkMatch, coord.match_id)
        req = db.get(NetworkRequirement, match.requirement_id)
        part = db.get(NetworkParticipant, (row.id, user.id))
        unread = select(func.count(NetworkMessage.id)).where(
            NetworkMessage.conversation_id == row.id,
            NetworkMessage.sender_id != user.id,
        )
        if part.read_at:
            unread = unread.where(NetworkMessage.created_at > part.read_at)
        result.append(
            {
                "id": row.id,
                "coordination_id": coord.id,
                "title": req.title,
                "site": db.get(Worksite, req.site_id).name,
                "unread": db.scalar(unread),
            }
        )
    return {"rows": result, "total": total}


@router.get("/conversations/{record_id}/messages")
def messages(
    record_id: str,
    before: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    participant_for(db, user, record_id)
    query = select(NetworkMessage).where(NetworkMessage.conversation_id == record_id)
    if before:
        cursor = record_for(db, NetworkMessage, user, before)
        if cursor.conversation_id != record_id:
            raise HTTPException(422, "Cursor de otra conversación")
        query = query.where(
            (NetworkMessage.created_at < cursor.created_at)
            | (
                (NetworkMessage.created_at == cursor.created_at)
                & (NetworkMessage.id < cursor.id)
            )
        )
    rows = list(
        db.scalars(
            query.order_by(
                NetworkMessage.created_at.desc(), NetworkMessage.id.desc()
            ).limit(limit + 1)
        )
    )
    more = len(rows) > limit
    rows = list(reversed(rows[:limit]))
    participants = []
    for person in db.scalars(
        select(NetworkParticipant).where(
            NetworkParticipant.conversation_id == record_id
        )
    ):
        participants.append(
            {
                "id": person.user_id,
                "name": actor_name(db, person.user_id),
                "sites": list(
                    db.scalars(
                        select(Worksite.name)
                        .join(
                            NetworkMembership, NetworkMembership.site_id == Worksite.id
                        )
                        .where(NetworkMembership.user_id == person.user_id)
                    )
                ),
                "read_at": person.read_at,
            }
        )
    return {
        "rows": [
            {
                "id": r.id,
                "body": r.body,
                "sender_id": r.sender_id,
                "sender": actor_name(db, r.sender_id),
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "next_before": rows[0].id if more else None,
        "participants": participants,
    }


@router.post("/conversations/{record_id}/messages", status_code=201)
def send_message(
    record_id: str,
    body: MessageInput,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    participant_for(db, user, record_id)
    old = db.scalar(
        select(NetworkMessage).where(
            NetworkMessage.conversation_id == record_id,
            NetworkMessage.sender_id == user.id,
            NetworkMessage.client_key == body.client_key,
        )
    )
    if old:
        if old.body != body.body:
            raise HTTPException(409, "La clave del mensaje ya se utilizó")
        return {"id": old.id}
    row = NetworkMessage(
        org_id=user.org_id,
        conversation_id=record_id,
        sender_id=user.id,
        **body.model_dump(),
    )
    db.add(row)
    db.flush()
    recipients = db.scalars(
        select(NetworkParticipant.user_id).where(
            NetworkParticipant.conversation_id == record_id
        )
    )
    notify(
        db,
        user,
        recipients,
        "message:" + row.id,
        "Nuevo mensaje de " + actor_name(db, user.id),
        "conversation",
        record_id,
    )
    db.commit()
    return {"id": row.id}


@router.post("/conversations/{record_id}/read")
def read_messages(
    record_id: str,
    last_message_id: str | None = None,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    part = participant_for(db, user, record_id)
    if last_message_id:
        message = record_for(db, NetworkMessage, user, last_message_id)
        if message.conversation_id != record_id:
            raise HTTPException(422, "Mensaje de otra conversación")
        if part.read_at is None or part.read_at.replace(
            tzinfo=None
        ) < message.created_at.replace(tzinfo=None):
            part.read_at = message.created_at
    else:
        # Mark only messages already delivered; do not consume concurrent future messages.
        raise HTTPException(422, "Indica el último mensaje visualizado")
    db.commit()
    return {"ok": True}


@router.post("/conversations/{record_id}/participants")
def add_coordinator(
    record_id: str,
    body: ParticipantInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    record_for(db, NetworkConversation, user, record_id)
    target = db.scalar(
        select(User).where(
            User.id == body.user_id, User.org_id == user.org_id, User.enabled.is_(True)
        )
    )
    if target is None or target.role != "admin":
        raise HTTPException(
            422, "El coordinador debe ser un administrador activo de esta organización"
        )
    if not db.get(NetworkParticipant, (record_id, target.id)):
        db.add(NetworkParticipant(conversation_id=record_id, user_id=target.id))
        event(
            db, user, "participant", record_id, None, {"added_coordinator": target.id}
        )
    db.commit()
    return {"ok": True}


@router.post("/awards", status_code=201)
def create_award(
    body: AwardInput,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    item = record_for(db, NetworkItem, user, body.item_id, lock=True)
    req = requirement_for(db, user, item.requirement_id)
    require_awarder(db, user, req.site_id)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    prior = db.scalar(
        select(NetworkAward).where(
            NetworkAward.org_id == user.org_id,
            NetworkAward.client_key == body.client_key,
        )
    )
    if prior:
        if prior.payload_hash != digest:
            raise HTTPException(
                409, "La clave de adjudicación ya se utilizó con otros datos"
            )
        return award_view(db, user, prior)
    if req.state != "published":
        raise HTTPException(409, "Solo se puede adjudicar un requerimiento publicado")
    record_for(db, Contractor, user, body.contractor_id)
    _, awarded, _, _, _ = allocation(db, item)
    if body.quantity > item.quantity - awarded:
        raise HTTPException(409, "La cantidad supera el saldo pendiente de la partida")
    if body.start_date < item.start_date or body.end_date > item.end_date:
        raise HTTPException(
            422, "Las fechas de ejecución deben estar dentro de la partida"
        )
    if body.coordination_id:
        coord = record_for(db, NetworkCoordination, user, body.coordination_id)
        match, target, cap = coordination_records(db, user, coord)
        if (
            target.id != req.id
            or cap.contractor_id != body.contractor_id
            or cap.id != body.capacity_id
        ):
            raise HTTPException(
                422,
                "La coordinación no corresponde a esta partida, contratista y capacidad",
            )
        if coord.state not in {
            "approved",
            "documents_pending",
            "documents_complete",
            "finished",
        }:
            raise HTTPException(409, "La propuesta de coordinación debe estar aprobada")
    if body.capacity_id:
        cap = capacity_for(db, user, body.capacity_id)
        if (
            cap.contractor_id != body.contractor_id
            or cap.state != "published"
            or cap.availability != "confirmed"
            or cap.expires_on < today()
        ):
            raise HTTPException(
                409,
                "Confirma la capacidad vigente del contratista antes de comprometerla",
            )
        if body.workers < 1:
            raise HTTPException(422, "Indica los trabajadores comprometidos")
        conflict = (
            committed_workers(db, cap, body.start_date, body.end_date) + body.workers
            > cap.workers
            or body.start_date < cap.available_date
        )
        if conflict and not (
            body.acknowledge_conflict and body.conflict_reason.strip()
        ):
            raise HTTPException(
                409,
                "Existe un conflicto de fecha o capacidad. Revisa las cuadrillas y confirma con motivo",
            )
    row = NetworkAward(
        org_id=user.org_id,
        awarded_by=user.id,
        payload_hash=digest,
        **body.model_dump(exclude={"acknowledge_conflict", "conflict_reason"}),
    )
    db.add(row)
    db.flush()
    event(
        db,
        user,
        "award",
        row.id,
        None,
        body.model_dump(mode="json"),
        body.conflict_reason,
    )
    notify(
        db,
        user,
        site_users(db, user, req.site_id),
        "award:" + row.id,
        "Partida adjudicada: " + item.name,
        "requirement",
        req.id,
    )
    if allocation(db, item)[1] == item.quantity:
        notify(
            db,
            user,
            site_users(db, user, req.site_id),
            "covered:" + row.id,
            "Partida completamente cubierta: " + item.name,
            "requirement",
            req.id,
        )
    if (
        clearance(
            db, user, row.contractor_id, req.site_id, row.start_date.strftime("%Y-%m")
        )["state"]
        != "enabled"
    ):
        notify(
            db,
            user,
            site_users(db, user, req.site_id),
            "clearance:" + row.id,
            "Adjudicación pendiente de habilitación documental: " + item.name,
            "requirement",
            req.id,
        )
    rebuild_matches(db, user)
    db.commit()
    return award_view(db, user, row)


@router.get("/awards")
def awards(
    site_id: str | None = None,
    specialty: str = "",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    query = (
        select(NetworkAward)
        .join(NetworkItem, NetworkItem.id == NetworkAward.item_id)
        .join(NetworkRequirement, NetworkRequirement.id == NetworkItem.requirement_id)
        .where(NetworkAward.org_id == user.org_id)
    )
    if user.role == "resident":
        query = query.where(NetworkRequirement.site_id.in_(assigned_sites(db, user)))
    if site_id:
        require_site(db, user, site_id)
        query = query.where(NetworkRequirement.site_id == site_id)
    if specialty:
        query = query.where(NetworkRequirement.specialty_key == key(specialty))
    rows, total = pagination(
        query.order_by(NetworkAward.created_at.desc(), NetworkAward.id),
        db,
        limit,
        offset,
    )
    return {"rows": [award_view(db, user, r) for r in rows], "total": total}


@router.patch("/awards/{record_id}")
def edit_award(
    record_id: str,
    body: AwardEdit,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    row = record_for(db, NetworkAward, user, record_id, lock=True)
    item = db.get(NetworkItem, row.item_id)
    req = requirement_for(db, user, item.requirement_id)
    require_awarder(db, user, req.site_id)
    check_version(row, body.version)
    allowed = {
        "assigned": {"ready", "revoked"},
        "ready": {"assigned", "in_progress", "revoked"},
        "in_progress": {"in_progress", "completed"},
        "completed": set(),
        "revoked": set(),
    }
    if body.state not in allowed[row.state]:
        raise HTTPException(
            409,
            "Transición de adjudicación inválida; conserva el historial de trabajos ejecutados",
        )
    if body.executed > row.quantity or body.executed < row.executed:
        raise HTTPException(
            422, "La cantidad ejecutada debe ser acumulativa y no superar la adjudicada"
        )
    if body.state in {"assigned", "ready", "revoked"} and body.executed:
        raise HTTPException(
            422, "La ejecución solo puede registrarse después del inicio"
        )
    if body.state == "completed" and body.executed != row.quantity:
        raise HTTPException(422, "Para finalizar, registra la totalidad ejecutada")
    if body.state in {"ready", "in_progress", "completed"}:
        if (
            clearance(
                db,
                user,
                row.contractor_id,
                req.site_id,
                row.start_date.strftime("%Y-%m"),
            )["state"]
            != "enabled"
        ):
            raise HTTPException(
                409,
                "No se puede autorizar la ejecución sin habilitación documental en destino",
            )
    before = award_view(db, user, row, False)
    row.state, row.executed = body.state, body.executed
    row.version += 1
    event(db, user, "award", row.id, before, body.model_dump(mode="json"), body.reason)
    notify(
        db,
        user,
        site_users(db, user, req.site_id),
        f"award:{row.id}:{row.version}",
        "Se actualizó la adjudicación: " + item.name,
        "requirement",
        req.id,
    )
    rebuild_matches(db, user)
    db.commit()
    return award_view(db, user, row)


@router.post("/items/{record_id}/amend")
def amend_item(
    record_id: str,
    body: AmendmentInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    row = record_for(db, NetworkItem, user, record_id, lock=True)
    if body.quantity <= row.quantity:
        raise HTTPException(422, "La ampliación debe aumentar la cantidad original")
    previous = str(row.quantity)
    row.quantity = body.quantity
    req = db.get(NetworkRequirement, row.requirement_id)
    req.version += 1
    event(
        db,
        user,
        "item_amendment",
        req.id,
        {"item_id": row.id, "quantity": previous},
        {"item_id": row.id, "quantity": str(body.quantity)},
        body.reason,
    )
    rebuild_matches(db, user)
    db.commit()
    return requirement_view(db, user, req, True)


@router.post("/awards/{record_id}/revise")
def revise_award(
    record_id: str,
    body: AwardRevision,
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    lock_org(db, user)
    row = record_for(db, NetworkAward, user, record_id, lock=True)
    item = db.get(NetworkItem, row.item_id)
    req = requirement_for(db, user, item.requirement_id)
    require_awarder(db, user, req.site_id)
    check_version(row, body.version)
    if row.state in {"revoked", "completed"}:
        raise HTTPException(409, "No se puede modificar una adjudicación cerrada")
    if (
        body.quantity < row.executed
        or body.quantity > item.quantity - allocation(db, item)[1] + row.quantity
    ):
        raise HTTPException(
            409,
            "La cantidad debe conservar lo ejecutado y respetar el saldo de la partida",
        )
    if body.start_date < item.start_date or body.end_date > item.end_date:
        raise HTTPException(
            422, "La programación debe estar dentro de las fechas de la partida"
        )
    if row.capacity_id:
        cap = capacity_for(db, user, row.capacity_id)
        reservations = db.scalar(
            select(func.coalesce(func.sum(NetworkAward.workers), 0)).where(
                NetworkAward.capacity_id == cap.id,
                NetworkAward.id != row.id,
                NetworkAward.state.notin_(["revoked", "completed"]),
                NetworkAward.start_date <= body.end_date,
                NetworkAward.end_date >= body.start_date,
            )
        )
        if (
            reservations + row.workers > cap.workers
            or body.start_date < cap.available_date
        ) and not (body.acknowledge_conflict and body.conflict_reason.strip()):
            raise HTTPException(
                409,
                "La reprogramación tiene conflictos de capacidad; confirma la excepción con motivo",
            )
    before = award_view(db, user, row, False)
    row.quantity, row.start_date, row.end_date = (
        body.quantity,
        body.start_date,
        body.end_date,
    )
    row.version += 1
    if row.executed == row.quantity:
        row.state = "completed"
    elif row.state == "ready":
        row.state = (
            "assigned"  # Recheck documentary clearance after changing the schedule.
        )
    event(
        db,
        user,
        "award_revision",
        row.id,
        before,
        body.model_dump(mode="json"),
        body.reason,
    )
    notify(
        db,
        user,
        site_users(db, user, req.site_id),
        f"award:{row.id}:{row.version}",
        "Se modificó una cantidad o programación: " + item.name,
        "requirement",
        req.id,
    )
    rebuild_matches(db, user)
    db.commit()
    return award_view(db, user, row)


@router.get("/history/{requirement_id}")
def history(
    requirement_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    req = requirement_for(db, user, requirement_id, detail=True)
    item_ids = select(NetworkItem.id).where(NetworkItem.requirement_id == req.id)
    award_ids = select(NetworkAward.id).where(NetworkAward.item_id.in_(item_ids))
    coord_ids = (
        select(NetworkCoordination.id)
        .join(NetworkMatch, NetworkMatch.id == NetworkCoordination.match_id)
        .where(NetworkMatch.requirement_id == req.id)
    )
    query = select(OpsChange).where(
        OpsChange.org_id == user.org_id,
        OpsChange.entity_type.like("network_%"),
        (OpsChange.entity_id == req.id)
        | OpsChange.entity_id.in_(item_ids)
        | OpsChange.entity_id.in_(award_ids)
        | OpsChange.entity_id.in_(coord_ids),
    )
    rows, total = pagination(
        query.order_by(OpsChange.created_at.desc(), OpsChange.id), db, limit, offset
    )
    return {
        "rows": [
            {
                "id": r.id,
                "kind": r.entity_type,
                "actor": actor_name(db, r.user_id),
                "at": r.created_at,
                "changes": r.changes,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/notifications")
def notifications(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    query = select(NetworkNotification).where(
        NetworkNotification.user_id == user.id,
        NetworkNotification.org_id == user.org_id,
    )
    unread = db.scalar(
        select(func.count()).select_from(
            query.where(NetworkNotification.read_at.is_(None)).subquery()
        )
    )
    rows, total = pagination(
        query.order_by(NetworkNotification.created_at.desc(), NetworkNotification.id),
        db,
        limit,
        offset,
    )
    return {
        "rows": [
            {
                "id": r.id,
                "title": r.title,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "created_at": r.created_at,
                "read": r.read_at is not None,
            }
            for r in rows
        ],
        "unread": unread,
        "total": total,
    }


@router.post("/notifications/{record_id}/read")
def read_notification(
    record_id: str, user: User = Depends(authorized_user), db: Session = Depends(get_db)
):
    query = select(NetworkNotification).where(
        NetworkNotification.org_id == user.org_id,
        NetworkNotification.user_id == user.id,
    )
    if record_id != "all":
        query = query.where(NetworkNotification.id == record_id)
    rows = list(db.scalars(query))
    if not rows and record_id != "all":
        raise HTTPException(404, "Notificación no encontrada")
    for row in rows:
        row.read_at = utcnow()
    db.commit()
    return {"ok": True}


@router.post("/sync")
def sync(user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    lock_org(db, user)
    for cap in db.scalars(
        select(NetworkCapacity).where(
            NetworkCapacity.org_id == user.org_id, NetworkCapacity.state == "published"
        )
    ):
        if cap.expires_on < today() or cap.updated_at.date() < today() - timedelta(
            days=7
        ):
            notify(
                db,
                user,
                site_users(db, user, cap.site_id),
                f"stale:{cap.id}:{cap.version}",
                "Revisar vigencia de capacidad",
                "capacity",
                cap.id,
                include_actor=True,
            )
    for req in db.scalars(
        scoped_requirements(db, user).where(
            NetworkRequirement.state == "published",
            NetworkRequirement.start_date >= today(),
            NetworkRequirement.start_date <= today() + timedelta(days=3),
        )
    ):
        if manages(db, user, req.site_id):
            notify(
                db,
                user,
                site_users(db, user, req.site_id),
                f"upcoming:{req.id}:{req.start_date}",
                "Inicio próximo: " + req.title,
                "requirement",
                req.id,
                include_actor=True,
            )
    rebuild_matches(db, user)
    db.commit()
    return {"ok": True}


@router.get("/overview")
def overview(
    site_id: str | None = None,
    specialty: str = "",
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    query = scoped_requirements(db, user)
    if user.role == "resident":
        query = query.where(NetworkRequirement.site_id.in_(assigned_sites(db, user)))
    if site_id:
        require_site(db, user, site_id)
        query = query.where(NetworkRequirement.site_id == site_id)
    if specialty:
        query = query.where(NetworkRequirement.specialty_key == key(specialty))
    reqs = list(db.scalars(query))
    views = [requirement_view(db, user, r) for r in reqs]
    active = [
        r
        for r in views
        if r["state"] == "published"
        and r["allocation_state"] not in {"completed", "cancelled"}
    ]
    parts = [i for r in active for i in r["items"]]
    relevant_awards = [a for i in parts for a in i["awards"]]
    capacities_q = select(NetworkCapacity).where(
        NetworkCapacity.org_id == user.org_id,
        NetworkCapacity.state == "published",
        NetworkCapacity.expires_on >= today(),
        NetworkCapacity.availability.notin_(["discarded", "committed"]),
    )
    if site_id:
        capacities_q = capacities_q.where(NetworkCapacity.site_id == site_id)
    if specialty:
        capacities_q = capacities_q.where(
            NetworkCapacity.specialty_key == key(specialty)
        )
    by_site, by_specialty = {}, {}
    for r in active:
        by_site[r["site"]] = by_site.get(r["site"], 0) + 1
        by_specialty[r["specialty"]] = by_specialty.get(r["specialty"], 0) + 1
    unread_q = (
        select(func.count(NetworkMessage.id))
        .join(
            NetworkParticipant,
            NetworkParticipant.conversation_id == NetworkMessage.conversation_id,
        )
        .where(
            NetworkMessage.org_id == user.org_id,
            NetworkParticipant.user_id == user.id,
            NetworkMessage.sender_id != user.id,
            (NetworkParticipant.read_at.is_(None))
            | (NetworkMessage.created_at > NetworkParticipant.read_at),
        )
    )
    coord_q = (
        select(func.count(NetworkCoordination.id))
        .join(NetworkMatch, NetworkMatch.id == NetworkCoordination.match_id)
        .join(NetworkRequirement, NetworkRequirement.id == NetworkMatch.requirement_id)
        .join(NetworkCapacity, NetworkCapacity.id == NetworkMatch.capacity_id)
        .where(
            NetworkCoordination.org_id == user.org_id,
            NetworkCoordination.state.notin_(["finished", "rejected", "cancelled"]),
        )
    )
    if user.role == "resident":
        allowed = assigned_sites(db, user)
        relevant_conversations = (
            select(NetworkConversation.id)
            .join(
                NetworkCoordination,
                NetworkCoordination.id == NetworkConversation.coordination_id,
            )
            .join(NetworkMatch, NetworkMatch.id == NetworkCoordination.match_id)
            .join(
                NetworkRequirement, NetworkRequirement.id == NetworkMatch.requirement_id
            )
            .join(NetworkCapacity, NetworkCapacity.id == NetworkMatch.capacity_id)
            .where(
                NetworkRequirement.site_id.in_(allowed)
                | NetworkCapacity.site_id.in_(allowed)
            )
        )
        unread_q = unread_q.where(
            NetworkMessage.conversation_id.in_(relevant_conversations)
        )
        coord_q = coord_q.where(
            NetworkRequirement.site_id.in_(allowed)
            | NetworkCapacity.site_id.in_(allowed)
        )
    elif user.role not in {"admin", "supervisor", "analyst"}:
        coord_q = coord_q.where(NetworkCoordination.created_by == user.id)
    if site_id:
        coord_q = coord_q.where(
            (NetworkRequirement.site_id == site_id)
            | (NetworkCapacity.site_id == site_id)
        )
    if specialty:
        coord_q = coord_q.where(NetworkRequirement.specialty_key == key(specialty))
    time_to_award = []
    for req in reqs:
        first = db.scalar(
            select(func.min(NetworkAward.created_at))
            .join(NetworkItem, NetworkItem.id == NetworkAward.item_id)
            .where(NetworkItem.requirement_id == req.id)
        )
        if first:
            time_to_award.append(
                max(0, (first - req.created_at).total_seconds() / 86400)
            )
    pending_clearance = sum(
        clearance(
            db,
            user,
            a["contractor_id"],
            a["site_id"],
            a["start_date"].strftime("%Y-%m"),
        )["state"]
        != "enabled"
        for a in relevant_awards
    )
    return {
        "requirements": len(active),
        "urgent": sum(r["priority"] in {"high", "urgent"} for r in active),
        "pending_items": sum(i["pending"] > 0 for i in parts),
        "partial_items": sum(i["state"] == "partial" for i in parts),
        "awarded_items": sum(i["state"] == "allocated" for i in parts),
        "capacities": db.scalar(
            select(func.count()).select_from(capacities_q.subquery())
        ),
        "matches": matches(site_id, specialty, 1, 0, user, db)["total"],
        "active_coordinations": db.scalar(coord_q),
        "awards": len(relevant_awards),
        "pending_clearance": pending_clearance,
        "enabled_awards": len(relevant_awards) - pending_clearance,
        "average_award_days": round(sum(time_to_award) / len(time_to_award), 1)
        if time_to_award
        else None,
        "unread_messages": db.scalar(unread_q),
        "by_site": by_site,
        "by_specialty": by_specialty,
    }


@router.get("/calendar")
def calendar(
    start: date,
    end: date,
    site_id: str | None = None,
    specialty: str = "",
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    if end < start or (end - start).days > 93:
        raise HTTPException(422, "Selecciona un rango de hasta 93 días")
    events = []
    query = scoped_requirements(db, user).where(
        NetworkRequirement.state == "published",
        NetworkRequirement.start_date <= end,
        NetworkRequirement.end_date >= start,
    )
    if site_id:
        require_site(db, user, site_id)
        query = query.where(NetworkRequirement.site_id == site_id)
    if specialty:
        query = query.where(NetworkRequirement.specialty_key == key(specialty))
    for req in db.scalars(query):
        events.append(
            {
                "id": req.id,
                "kind": "requirement",
                "title": req.title,
                "site_id": req.site_id,
                "date": req.start_date,
                "end_date": req.end_date,
                "overdue": req.deadline < today(),
            }
        )
        if manages(db, user, req.site_id):
            for award in db.scalars(
                select(NetworkAward)
                .join(NetworkItem, NetworkItem.id == NetworkAward.item_id)
                .where(
                    NetworkItem.requirement_id == req.id,
                    NetworkAward.state != "revoked",
                )
            ):
                events.append(
                    {
                        "id": award.id,
                        "kind": "award",
                        "requirement_id": req.id,
                        "title": db.get(Contractor, award.contractor_id).name,
                        "site_id": req.site_id,
                        "date": award.start_date,
                        "end_date": award.end_date,
                        "overdue": False,
                    }
                )
    cap_query = select(NetworkCapacity).where(
        NetworkCapacity.org_id == user.org_id,
        NetworkCapacity.state == "published",
        NetworkCapacity.available_date >= start,
        NetworkCapacity.available_date <= end,
    )
    if site_id:
        cap_query = cap_query.where(NetworkCapacity.site_id == site_id)
    if specialty:
        cap_query = cap_query.where(NetworkCapacity.specialty_key == key(specialty))
    for cap in db.scalars(cap_query):
        events.append(
            {
                "id": cap.id,
                "kind": "capacity",
                "title": db.get(Contractor, cap.contractor_id).name,
                "site_id": cap.site_id,
                "date": cap.available_date,
                "end_date": cap.available_date,
                "overdue": cap.expires_on < today(),
            }
        )
    return events


@router.get("/report")
def network_report(
    site_id: str | None = None,
    specialty: str = "",
    user: User = Depends(authorized_user),
    db: Session = Depends(get_db),
):
    import csv
    from io import StringIO

    query = scoped_requirements(db, user)
    if user.role == "resident":
        query = query.where(NetworkRequirement.site_id.in_(assigned_sites(db, user)))
    if site_id:
        require_site(db, user, site_id)
        query = query.where(NetworkRequirement.site_id == site_id)
    if specialty:
        query = query.where(NetworkRequirement.specialty_key == key(specialty))
    output = StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Obra",
            "Requerimiento",
            "Partida",
            "Total solicitado",
            "Unidad",
            "Adjudicado a",
            "RUT",
            "Cantidad adjudicada",
            "Saldo pendiente de la partida",
            "Cantidad ejecutada",
            "Estado adjudicación",
            "Inicio",
            "Término",
            "Responsable",
            "Habilitación en destino",
        ]
    )

    def safe(value):
        value = str(value or "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    for req in db.scalars(query.order_by(NetworkRequirement.created_at)):
        view = requirement_view(db, user, req, detailed=True)
        for item in view["items"]:
            for award in item["awards"] or [None]:
                writer.writerow(
                    [
                        safe(view["site"]),
                        safe(view["title"]),
                        safe(item["name"]),
                        item["quantity"],
                        safe(item["unit"]),
                        safe(award["contractor"] if award else "Sin asignar"),
                        safe(award["rut"] if award else ""),
                        award["quantity"] if award else 0,
                        item["pending"],
                        award["executed"] if award else 0,
                        safe(award["state"] if award else "pending"),
                        str(award["start_date"]) if award else "",
                        str(award["end_date"]) if award else "",
                        safe(award["awarded_by"] if award else ""),
                        safe(award["clearance"]["label"] if award else ""),
                    ]
                )
    event(
        db,
        user,
        "report",
        user.org_id,
        None,
        {"site_id": site_id, "specialty": specialty},
    )
    db.commit()
    return Response(
        "\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="red-de-obras.csv"',
            "Cache-Control": "no-store",
        },
    )
