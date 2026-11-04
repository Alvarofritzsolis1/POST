"""Authorization, explainable matching and quantities shared by API and tests."""

from __future__ import annotations

import unicodedata
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select

from .models import Organization, User, utcnow
from .network_models import (
    NetworkAward,
    NetworkCapacity,
    NetworkConversation,
    NetworkCoordination,
    NetworkItem,
    NetworkMatch,
    NetworkMember,
    NetworkMembership,
    NetworkNotification,
    NetworkParticipant,
    NetworkPendingItem,
    NetworkRequirement,
)
from .ops_api import audit_change
from .ops_models import Contractor, ContractorWorksite, Worksite
from .platform_models import UserPreferences


def today():
    return utcnow().astimezone(ZoneInfo("America/Santiago")).date()


def key(value):
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", value.lower())
            if not unicodedata.combining(c)
        ).split()
    )


def lock_org(db, user):
    # One transaction lock also serializes match generation, invitations and retries.
    db.scalar(
        select(Organization).where(Organization.id == user.org_id).with_for_update()
    )
    auth = db.info.get("network_auth")
    if auth and auth[0] == user.id:
        db.refresh(user)
        member = db.scalar(
            select(NetworkMember)
            .where(NetworkMember.user_id == user.id)
            .execution_options(populate_existing=True)
        )
        if not user.enabled or (member.session_version if member else 0) != auth[1]:
            raise HTTPException(
                401,
                "Los permisos cambiaron mientras se procesaba la operación; inicia sesión nuevamente",
            )


def member_for(db, user):
    row = db.get(NetworkMember, user.id)
    if row is None:
        row = NetworkMember(user_id=user.id)
        db.add(row)
        db.flush()
    return row


def assigned_sites(db, user):
    return set(
        db.scalars(
            select(NetworkMembership.site_id)
            .join(Worksite, Worksite.id == NetworkMembership.site_id)
            .where(NetworkMembership.user_id == user.id, Worksite.org_id == user.org_id)
        )
    )


def manages(db, user, site_id):
    return user.role in {"admin", "supervisor", "analyst"} or (
        user.role == "resident" and site_id in assigned_sites(db, user)
    )


def require_site(db, user, site_id, write=False):
    row = db.scalar(
        select(Worksite).where(Worksite.id == site_id, Worksite.org_id == user.org_id)
    )
    if row is None:
        raise HTTPException(404, "Obra no encontrada")
    if write and not manages(db, user, site_id):
        raise HTTPException(403, "No tienes permiso para modificar esta obra")
    return row


def require_awarder(db, user, site_id):
    require_site(db, user, site_id, write=True)
    member = db.get(NetworkMember, user.id)
    if user.role != "admin" and not (member and member.can_award):
        raise HTTPException(403, "La adjudicación requiere autorización administrativa")


def record_for(db, model, user, record_id, lock=False):
    query = select(model).where(model.id == record_id, model.org_id == user.org_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if row is None:
        raise HTTPException(404, "Registro no encontrado")
    return row


def requirement_for(db, user, record_id, detail=False, write=False):
    row = record_for(db, NetworkRequirement, user, record_id, lock=write)
    own = manages(db, user, row.site_id)
    if row.state == "draft" and not own:
        raise HTTPException(404, "Requerimiento no encontrado")
    if (detail or write) and not own:
        raise HTTPException(
            403,
            "La vista colaborativa no permite acceder a detalles privados de otra obra",
        )
    return row


def capacity_for(db, user, record_id, write=False):
    row = record_for(db, NetworkCapacity, user, record_id, lock=write)
    if row.state == "draft" and not manages(db, user, row.site_id):
        raise HTTPException(404, "Publicación no encontrada")
    if write:
        require_site(db, user, row.site_id, write=True)
    return row


def participant_for(db, user, conversation_id):
    conversation = record_for(db, NetworkConversation, user, conversation_id)
    row = db.get(NetworkParticipant, (conversation_id, user.id))
    if row is None:
        raise HTTPException(403, "No eres participante de esta conversación")
    if user.role == "resident":
        coord = db.get(NetworkCoordination, conversation.coordination_id)
        coordination_records(db, user, coord)
    return row


def actor_name(db, user_id):
    row = db.get(NetworkMember, user_id)
    user = db.get(User, user_id)
    pref = db.get(UserPreferences, user_id)
    return (
        row.name if row and row.name else (pref.values.get("name") if pref else "")
    ) or user.email


def notify(
    db,
    user,
    recipients,
    event_key,
    title,
    resource_type,
    resource_id,
    include_actor=False,
):
    for user_id in set(recipients) - (set() if include_actor else {user.id}):
        recipient = db.get(User, user_id)
        if not recipient or not recipient.enabled or recipient.org_id != user.org_id:
            continue
        pref = db.get(UserPreferences, user_id)
        if pref and pref.values.get("notifications") is False:
            continue
        if db.scalar(
            select(NetworkNotification.id).where(
                NetworkNotification.user_id == user_id,
                NetworkNotification.event_key == event_key,
            )
        ):
            continue
        db.add(
            NetworkNotification(
                org_id=user.org_id,
                user_id=user_id,
                event_key=event_key,
                title=title,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )
    db.flush()


def site_users(db, user, site_id):
    assigned = select(NetworkMembership.user_id).where(
        NetworkMembership.site_id == site_id
    )
    return list(
        db.scalars(
            select(User.id).where(
                User.org_id == user.org_id,
                User.enabled.is_(True),
                (User.role.in_(["admin", "supervisor", "analyst"]))
                | User.id.in_(assigned),
            )
        )
    )


def event(db, user, kind, record_id, before=None, after=None, reason=""):
    audit_change(
        db,
        user,
        "network_" + kind,
        record_id,
        jsonable_encoder({"from": before, "to": after, "reason": reason}),
    )


def check_version(row, expected):
    if expected is None or expected != row.version:
        raise HTTPException(
            409, "Otra persona modificó el registro. Actualiza antes de guardar"
        )


def allocation(db, item):
    rows = list(
        db.scalars(
            select(NetworkAward).where(
                NetworkAward.item_id == item.id, NetworkAward.state != "revoked"
            )
        )
    )
    total = sum((r.quantity for r in rows), Decimal(0))
    executed = sum((r.executed for r in rows), Decimal(0))
    state = (
        "pending" if total == 0 else "partial" if total < item.quantity else "allocated"
    )
    execution = (
        "completed"
        if executed >= item.quantity
        else "in_progress"
        if any(r.state in {"in_progress", "completed"} for r in rows)
        else "pending"
    )
    return rows, total, executed, state, execution


def clearance(db, user, contractor_id, site_id, period):
    """Conservative, read-only bridge to the original document and labor controls."""
    from .compliance_api import document_matrix

    link = db.scalar(
        select(ContractorWorksite).where(
            ContractorWorksite.org_id == user.org_id,
            ContractorWorksite.contractor_id == contractor_id,
            ContractorWorksite.worksite_id == site_id,
        )
    )
    if not link or link.contract_status != "active":
        return {
            "state": "pending",
            "label": "Pendiente de habilitación en la obra de destino",
            "approved": 0,
            "required": 0,
        }
    cache = db.info.setdefault("network_document_matrix", {})
    cache_key = (user.org_id, site_id, period)
    if cache_key not in cache:
        cache[cache_key] = document_matrix(period, site_id, user, db)
    rows = [
        r
        for r in cache[cache_key]
        if r["association_id"] == link.id and r["state"] != "not_applicable"
    ]
    approved = sum(r["state"] == "approved" for r in rows)
    okay = bool(rows) and approved == len(rows)
    return {
        "state": "enabled" if okay else "pending",
        "label": "Habilitado documentalmente para la obra"
        if okay
        else "Pendiente de revisión documental",
        "approved": approved,
        "required": len(rows),
    }


def award_view(db, user, award, with_clearance=True):
    item = db.get(NetworkItem, award.item_id)
    req = db.get(NetworkRequirement, item.requirement_id)
    company = db.get(Contractor, award.contractor_id)
    result = {
        "id": award.id,
        "item_id": item.id,
        "item_name": item.name,
        "requirement_id": req.id,
        "requirement": req.title,
        "site_id": req.site_id,
        "site": db.get(Worksite, req.site_id).name,
        "contractor_id": company.id,
        "contractor": company.name,
        "rut": company.rut,
        "quantity": float(award.quantity),
        "unit": item.unit,
        "executed": float(award.executed),
        "state": award.state,
        "start_date": award.start_date,
        "end_date": award.end_date,
        "notes": award.notes,
        "awarded_by": actor_name(db, award.awarded_by),
        "created_at": award.created_at,
        "version": award.version,
        "capacity_id": award.capacity_id,
        "coordination_id": award.coordination_id,
        "workers": award.workers,
    }
    if with_clearance:
        result["clearance"] = clearance(
            db, user, company.id, req.site_id, award.start_date.strftime("%Y-%m")
        )
    return result


def requirement_view(db, user, req, detailed=False):
    own = manages(db, user, req.site_id)
    items = list(
        db.scalars(
            select(NetworkItem)
            .where(NetworkItem.requirement_id == req.id)
            .order_by(NetworkItem.position)
        )
    )
    parts = []
    for item in items:
        awards, total, executed, state, execution = allocation(db, item)
        parts.append(
            {
                "id": item.id,
                "name": item.name,
                "quantity": float(item.quantity),
                "unit": item.unit,
                "awarded": float(total),
                "pending": float(item.quantity - total),
                "executed": float(executed),
                "state": state,
                "execution": execution,
                "start_date": item.start_date,
                "end_date": item.end_date,
                "description": item.description if own else "",
                "notes": item.notes if own else "",
                "awards": [
                    award_view(db, user, a, with_clearance=detailed) for a in awards
                ]
                if own
                else [],
            }
        )
    covered = sum(p["state"] == "allocated" for p in parts)
    state = (
        "none"
        if all(p["state"] == "pending" for p in parts)
        else "full"
        if covered == len(parts)
        else "partial"
    )
    if parts and all(p["execution"] == "completed" for p in parts):
        state = "completed"
    elif any(p["execution"] == "in_progress" for p in parts):
        state = "in_progress"
    if req.state == "cancelled":
        state = "cancelled"
    return {
        "id": req.id,
        "site_id": req.site_id,
        "site": db.get(Worksite, req.site_id).name,
        "title": req.title,
        "specialty": req.specialty,
        "priority": req.priority,
        "workers": req.workers,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "deadline": req.deadline,
        "state": req.state,
        "allocation_state": state,
        "description": req.description if own else "",
        "resident": actor_name(db, req.created_by),
        "created_by": req.created_by,
        "created_at": req.created_at,
        "updated_at": req.updated_at,
        "editable": own,
        "can_award": own
        and (
            user.role == "admin"
            or bool((m := db.get(NetworkMember, user.id)) and m.can_award)
        ),
        "version": req.version,
        "items": parts,
        "item_count": len(parts),
        "covered_items": covered,
        "coverage": round(
            sum(min(p["awarded"] / p["quantity"], 1) for p in parts)
            / max(len(parts), 1)
            * 100
        ),
    }


def capacity_view(db, user, cap):
    company = db.get(Contractor, cap.contractor_id)
    stale = cap.updated_at.date() < today() - timedelta(days=7)
    return {
        "id": cap.id,
        "site_id": cap.site_id,
        "site": db.get(Worksite, cap.site_id).name,
        "contractor_id": company.id,
        "contractor": company.name,
        "rut": company.rut,
        "specialty": cap.specialty,
        "resident": actor_name(db, cap.created_by),
        "created_by": cap.created_by,
        "situation": cap.situation,
        "workers": cap.workers,
        "mode": cap.mode,
        "available_date": cap.available_date,
        "availability": cap.availability,
        "can_transfer": cap.can_transfer,
        "notes": cap.notes,
        "state": cap.state,
        "confirmed_at": cap.confirmed_at,
        "expires_on": cap.expires_on,
        "expired": cap.expires_on < today(),
        "stale": stale,
        "updated_at": cap.updated_at,
        "editable": manages(db, user, cap.site_id),
        "version": cap.version,
        "pending_items": [
            {
                "name": i.name,
                "quantity": float(i.quantity),
                "unit": i.unit,
                "end_date": i.end_date,
            }
            for i in db.scalars(
                select(NetworkPendingItem).where(
                    NetworkPendingItem.capacity_id == cap.id
                )
            )
        ],
    }


def committed_workers(db, cap, start, end):
    return (
        db.scalar(
            select(func.coalesce(func.sum(NetworkAward.workers), 0)).where(
                NetworkAward.capacity_id == cap.id,
                NetworkAward.state.notin_(["revoked", "completed"]),
                NetworkAward.start_date <= end,
                NetworkAward.end_date >= start,
            )
        )
        or 0
    )


def match_score(db, req, cap):
    if (
        req.state != "published"
        or cap.state != "published"
        or req.site_id == cap.site_id
        or key(req.specialty) != key(cap.specialty)
        or not cap.can_transfer
        or cap.availability in {"discarded", "committed"}
        or cap.expires_on < today()
        or cap.available_date > req.deadline
    ):
        return None
    items = list(
        db.scalars(select(NetworkItem).where(NetworkItem.requirement_id == req.id))
    )
    if items and all(allocation(db, i)[1] >= i.quantity for i in items):
        return None
    remaining = max(
        0, cap.workers - committed_workers(db, cap, req.start_date, req.end_date)
    )
    if remaining == 0:
        return None
    score = 40
    reasons = ["Coincide la especialidad: " + req.specialty]
    if cap.available_date <= req.start_date:
        score += 25
        reasons.append("Fecha prevista compatible con el inicio solicitado")
    else:
        score += 10
        reasons.append("Disponibilidad posterior al inicio, dentro del plazo límite")
    score += round(min(remaining / req.workers, 1) * 25)
    reasons.append(
        f"Capacidad estimada libre: {remaining} de {req.workers} trabajadores requeridos"
    )
    pending = " ".join(
        db.scalars(
            select(NetworkPendingItem.name).where(
                NetworkPendingItem.capacity_id == cap.id
            )
        )
    )
    if set(key(" ".join(i.name for i in items)).split()) & set(key(pending).split()):
        score += 10
        reasons.append("Hay tipos de partidas relacionados")
    reasons.append(
        "La oportunidad requiere coordinación; no asigna contratistas ni trabajadores"
    )
    return score, reasons


def rebuild_matches(db, user):
    db.flush()
    existing = {
        (m.requirement_id, m.capacity_id): m
        for m in db.scalars(
            select(NetworkMatch).where(NetworkMatch.org_id == user.org_id)
        )
    }
    for match in existing.values():
        match.active = False
    reqs = list(
        db.scalars(
            select(NetworkRequirement).where(
                NetworkRequirement.org_id == user.org_id,
                NetworkRequirement.state == "published",
            )
        )
    )
    caps = list(
        db.scalars(
            select(NetworkCapacity).where(
                NetworkCapacity.org_id == user.org_id,
                NetworkCapacity.state == "published",
            )
        )
    )
    for req in reqs:
        for cap in caps:
            result = match_score(db, req, cap)
            if result is None:
                continue
            pair = (req.id, cap.id)
            match = existing.get(pair)
            new = match is None
            if new:
                match = NetworkMatch(
                    org_id=user.org_id, requirement_id=req.id, capacity_id=cap.id
                )
                db.add(match)
            match.score, match.reasons, match.active = *result, True
            db.flush()
            if new:
                notify(
                    db,
                    user,
                    site_users(db, user, req.site_id),
                    "match:" + match.id,
                    "Posible contratista para: " + req.title,
                    "match",
                    match.id,
                )


def coordination_records(db, user, coord):
    match = record_for(db, NetworkMatch, user, coord.match_id)
    req = requirement_for(db, user, match.requirement_id)
    cap = capacity_for(db, user, match.capacity_id)
    if not (manages(db, user, req.site_id) or manages(db, user, cap.site_id)):
        raise HTTPException(403, "No tienes acceso a esta coordinación")
    return match, req, cap


def coordination_view(db, user, coord):
    match, req, cap = coordination_records(db, user, coord)
    conversation = db.scalar(
        select(NetworkConversation).where(
            NetworkConversation.coordination_id == coord.id
        )
    )
    return {
        "id": coord.id,
        "match_id": match.id,
        "requirement_id": req.id,
        "requirement": req.title,
        "site": db.get(Worksite, req.site_id).name,
        "origin": db.get(Worksite, cap.site_id).name,
        "contractor": db.get(Contractor, cap.contractor_id).name,
        "state": coord.state,
        "reason": coord.reason,
        "version": coord.version,
        "conversation_id": conversation.id
        if conversation and db.get(NetworkParticipant, (conversation.id, user.id))
        else None,
        "updated_at": coord.updated_at,
        "capacity_id": cap.id,
    }
