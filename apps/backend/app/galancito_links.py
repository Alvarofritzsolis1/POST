"""Small local, explainable occupational matching with append-only trace.

These percentages compare *declared work requirements*, not people's quality,
eligibility, or probability of hiring. Missing optional facts are not failures.
No third-party AI call, automatic rejection, or unsolicited Messenger message.
"""
from __future__ import annotations

import re
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session

from .galancito_triage import TRADES, plain, private_data
from .models import utcnow
from .facebook_crm_models import FacebookLeadTrade, FacebookNeedAssociation, FacebookLeadTrace


def canonical_trade(value: str) -> str:
    normalized = plain(value or "")
    for trade, aliases in TRADES.items():
        if normalized in {plain(trade), *(plain(alias) for alias in aliases)}:
            return trade
    return (value or "").strip()[:120]


def trade_terms(value: str) -> list[str]:
    """Read occupational terms in a multi-trade sentence or requirement."""
    normalized = plain(value or "")
    found = []
    for trade, aliases in TRADES.items():
        for phrase in (trade, *aliases):
            token = plain(phrase)
            match = re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", normalized)
            if match:
                prefix = normalized[max(0, match.start() - 38):match.start()].strip()
                # Don't turn an explicit negative declaration into an active trade.
                if re.search(
                    r"(?:\bno soy|\bno hago|\bno trabajo(?: en)?|\bno me dedico a|"
                    r"\bsin experiencia en|\bno se)\s+(?:\w+\s+){0,2}$", prefix
                ):
                    continue
                found.append(trade)
                break
    return list(dict.fromkeys(found))


def extract_declared_trades(message: str, prior_prompt: str = "") -> list[str]:
    if not message or len(message) > 400 or private_data(message):
        return []
    value = plain(message)
    affirmative = bool(re.search(
        r"\b(?:soy|soi|trabajo|trabajamos|hago|hacemos|ofrezco|ofresco|"
        r"me dedico|me manejo|le pego|tengo experiencia|tambien hago|"
        r"tambien trabajo)\b", value
    ))
    direct_answer = (
        "?" not in message and "¿" not in message and len(value.split()) <= 3
        and ("oficio" in plain(prior_prompt) or "trabajo realizas" in plain(prior_prompt))
    )
    if not affirmative and not direct_answer:
        return []
    return trade_terms(message)


def audit_event(db: Session, lead, event: str, *, source: str = "system",
                trade: str | None = None, requirement_id: str | None = None,
                actor_id: str | None = None, remote_id: str | None = None) -> None:
    db.add(FacebookLeadTrace(
        org_id=lead.org_id, lead_id=lead.id, event=event[:32],
        source=source[:24], trade=trade, requirement_id=requirement_id,
        actor_id=actor_id, source_remote_id=remote_id,
    ))


def record_declared_trades(db: Session, lead, message: str, *,
                           remote_id: str | None = None, prior_prompt: str = "") -> list[str]:
    """Idempotent ingestion; no deletion of prior trades or manual edits."""
    detected = extract_declared_trades(message, prior_prompt)
    existing = list(db.scalars(select(FacebookLeadTrade).where(
        FacebookLeadTrade.org_id == lead.org_id,
        FacebookLeadTrade.lead_id == lead.id,
    )))
    by_trade = {plain(item.trade): item for item in existing}
    result = []
    for trade in detected:
        stored = by_trade.get(plain(trade))
        if stored is None and len(existing) < 12:
            stored = FacebookLeadTrade(
                org_id=lead.org_id, lead_id=lead.id, trade=trade,
                source="message", source_remote_id=remote_id,
            )
            db.add(stored)
            existing.append(stored)
            by_trade[plain(trade)] = stored
            audit_event(db, lead, "trade_added", trade=trade,
                        source="message", remote_id=remote_id)
        elif stored and not stored.active:
            stored.active, stored.updated_at = True, utcnow()
            stored.source_remote_id = remote_id
            audit_event(db, lead, "trade_reactivated", trade=trade,
                        source="message", remote_id=remote_id)
        if stored and stored.active:
            result.append(trade)
    return result


def record_manual_trade(db: Session, lead, trade: str, actor_id: str) -> None:
    normalized = canonical_trade(trade)
    if not normalized:
        return
    existing = db.scalar(select(FacebookLeadTrade).where(
        FacebookLeadTrade.org_id == lead.org_id,
        FacebookLeadTrade.lead_id == lead.id,
        FacebookLeadTrade.trade == normalized,
    ))
    if existing is None:
        db.add(FacebookLeadTrade(org_id=lead.org_id, lead_id=lead.id,
                                 trade=normalized, source="manual"))
        audit_event(db, lead, "trade_added", source="manual", trade=normalized, actor_id=actor_id)
    elif not existing.active:
        existing.active, existing.source, existing.updated_at = True, "manual", utcnow()
        audit_event(db, lead, "trade_reactivated", source="manual",
                    trade=normalized, actor_id=actor_id)


def link_requirement(db: Session, lead, requirement_id: str, actor_id: str) -> bool:
    existing = db.scalar(select(FacebookNeedAssociation).where(
        FacebookNeedAssociation.org_id == lead.org_id,
        FacebookNeedAssociation.lead_id == lead.id,
        FacebookNeedAssociation.requirement_id == requirement_id,
    ))
    if existing and existing.state == "linked":
        return False
    if existing:
        existing.state = "linked"
        existing.reviewed_by, existing.updated_at = actor_id, utcnow()
    else:
        db.add(FacebookNeedAssociation(
            org_id=lead.org_id, lead_id=lead.id, requirement_id=requirement_id,
            state="linked", reviewed_by=actor_id,
        ))
    if not lead.requirement_id:
        lead.requirement_id = requirement_id
    audit_event(db, lead, "need_linked", source="operator",
                requirement_id=requirement_id, actor_id=actor_id)
    return True


def unlink_requirement(db: Session, lead, requirement_id: str, actor_id: str) -> bool:
    existing = db.scalar(select(FacebookNeedAssociation).where(
        FacebookNeedAssociation.org_id == lead.org_id,
        FacebookNeedAssociation.lead_id == lead.id,
        FacebookNeedAssociation.requirement_id == requirement_id,
        FacebookNeedAssociation.state == "linked",
    ))
    if existing is None:
        return False
    existing.state, existing.updated_at = "unlinked", utcnow()
    audit_event(db, lead, "need_unlinked", source="operator",
                requirement_id=requirement_id, actor_id=actor_id)
    if lead.requirement_id == requirement_id:
        remaining = db.scalar(select(FacebookNeedAssociation).where(
            FacebookNeedAssociation.org_id == lead.org_id,
            FacebookNeedAssociation.lead_id == lead.id,
            FacebookNeedAssociation.state == "linked",
            FacebookNeedAssociation.requirement_id != requirement_id,
        ).order_by(FacebookNeedAssociation.created_at))
        lead.requirement_id = remaining.requirement_id if remaining else None
    return True


def suggest_requirements(lead, trades: list[str], requirements,
                         linked_ids: set[str] | None = None, *, limit: int = 5) -> list[dict]:
    """Explainable indication of matching occupational requirements, not candidate rank."""
    linked_ids = linked_ids or set()
    normalized = {plain(canonical_trade(t)) for t in trades if t}
    if lead.specialty:
        normalized.add(plain(canonical_trade(lead.specialty)))
    if not normalized:
        return []
    results = []
    for need in requirements:
        if need.org_id != lead.org_id or need.state != "published":
            continue
        if need.deadline and need.deadline < date.today():
            continue
        req_trades = trade_terms(need.specialty)
        if not req_trades:
            req_trades = [canonical_trade(need.specialty)]
        matching = [trade for trade in req_trades if plain(canonical_trade(trade)) in normalized]
        if not matching:
            continue
        # Trade = 65, explicitly declared team capacity = 20, date = 15.
        # Unknowns are omitted from denominator; coverage is displayed separately.
        earned, known, possible = 65, 65, 80 if lead.interest_type == "employment" else 100
        reasons = ["Coincide el oficio: " + ", ".join(matching[:3])]
        missing = []
        if lead.interest_type != "employment":
            if lead.workers is None:
                missing.append("Dotación sin informar")
            else:
                known += 20
                if lead.workers >= need.workers:
                    earned += 20
                    reasons.append("Dotación declarada suficiente")
                else:
                    reasons.append("Dotación por coordinar; no descarta a la persona")
        try:
            available = date.fromisoformat(lead.availability or "")
        except (ValueError, TypeError):
            available = None
        if available:
            known += 15
            if available <= need.start_date:
                earned += 15
                reasons.append("Fecha declarada compatible")
            else:
                reasons.append("Fecha a coordinar")
        else:
            missing.append("Disponibilidad por confirmar")
        results.append({
            "id": need.id, "title": need.title, "specialty": need.specialty,
            "matched_trades": matching,
            "coincidence_percent": round(100 * earned / known),
            "coverage_percent": round(100 * known / possible),
            "reasons": reasons, "missing": missing,
            "linked": need.id in linked_ids,
            "review_required": True,
        })
    return sorted(results, key=lambda row: (
        not row["linked"], -row["coverage_percent"],
        -row["coincidence_percent"], row["title"], row["id"],
    ))[:limit]
