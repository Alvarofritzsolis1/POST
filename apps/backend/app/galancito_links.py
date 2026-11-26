"""Small local, explainable occupational matching with append-only trace.

These percentages compare *declared work requirements*, not people's quality,
eligibility, or probability of hiring. Missing optional facts are not failures.
No third-party AI call, automatic rejection, or unsolicited Messenger message.
"""
from __future__ import annotations

import re
from datetime import date, timezone
from functools import lru_cache
from sqlalchemy import select
from sqlalchemy.orm import Session

from .galancito_triage import TRADES, asks_about_application, declaration_text, plain, private_data
from .models import utcnow
from .network_service import today
from .facebook_crm_models import FacebookLeadTrade, FacebookNeedAssociation, FacebookLeadTrace


@lru_cache(maxsize=256)
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
                    r"\bsin experiencia en|\bno se|\bpero no|\bno)"
                    r"\s*(?:maestro(?: de)?\s*)?$", prefix
                ):
                    continue
                found.append(trade)
                break
    return list(dict.fromkeys(found))


_NOTICE_TRADE = re.compile(
    r"\b(?:aviso|publicaci[oó]n|anuncio|oferta|vacante)\s+(?:de|para)\s+([^,.!?;:\n]+)", re.I
)
_PERSONAL_TRADE = re.compile(r"\b(?:yo|soy|soi|hago|ofrezco|trabajo en)\b", re.I)


def advertised_trade(message: str) -> str | None:
    """Read a named trade from an advert reference without attributing it to the sender."""
    if not asks_about_application(message) or private_data(message) or not (notice := _NOTICE_TRADE.search(message)):
        return None
    trades = trade_terms(_PERSONAL_TRADE.split(notice[1], maxsplit=1)[0])
    return trades[0] if len(trades) == 1 else None


_OWN_TRADE = re.compile(
    r"\b(?:soy|soi|trabajo|trabajamos|hago|hacemos|ofrezco|ofresco|instalo|reparo|"
    r"me dedico|me manejo|le pego|tengo experiencia|trabajar en|quiero ofrecer|"
    r"mi (?:oficio|especialidad) (?:principal )?es|busco (?:pega|empleo|trabajo) (?:de|en|como))\b"
)
_TRADE_NEGATIVE = re.compile(r"\b(?:no|dej[eé] de) (?:soy|hago|trabajo|trabajamos|ofrezco|me dedico)?")
_TRADE_TOPIC = re.compile(r"\b(?:buscan|necesitan|necesito|buscamos|hay|tienen|"
                          r"mi (?:hermano|amigo|pap[aá]|jefe)|"
                          r"el (?:maestro|vecino)|mi (?:cuadrilla|equipo) (?:necesita|busca))\b")
_TRADE_FRAGMENTS = re.compile(
    r"[,;.!?¿¡\n]+|\b(?:pero|aunque|sino|y(?=\s+(?:no|mi|el|la|soy|soi|hago|ofrezco)\b))\b", re.I)


@lru_cache(maxsize=16)
def _trade_matcher(extra: tuple):
    by_alias = {plain(alias): trade for trade, aliases in TRADES.items()
                for alias in (trade, *aliases) if plain(alias)}
    for trade, aliases in extra:
        canonical = canonical_trade(trade)
        for alias in (trade, *aliases):
            if normalized := plain(alias):
                by_alias.setdefault(normalized, canonical)
    pattern = re.compile(r"\b(?:" + "|".join(
        re.escape(alias) for alias in sorted(by_alias, key=len, reverse=True)
    ) + r")\b")
    return by_alias, pattern


def trade_mentions(value: str, *, extra=()):
    """Return catalog spans, with attribution left to the caller."""
    _, matcher = _trade_matcher(extra)
    return matcher.finditer(value)


def trade_declarations(message: str, prior_prompt: str = "", *,
                       extra: dict | None = None, allow_bare: bool = False) -> dict[str, bool]:
    """True adds an explicitly stated trade; False corrects an earlier declaration."""
    if not message or len(message) > 3500 or private_data(message):
        return {}
    catalog, matcher = _trade_matcher(tuple((trade, tuple(aliases)) for trade, aliases in (extra or {}).items()))
    direct = any(p in plain(prior_prompt) for p in ("oficio", "trabajo realizas", "trabajo haces", "trabajos haces", "servicio ofreces", "a que te dedicas", "en que trabajas"))
    result = {}
    continuation = False
    for fragment in _TRADE_FRAGMENTS.split(declaration_text(message)):
        norm = plain(fragment)
        if not norm:
            continue
        if (asks_about_application(fragment) or _TRADE_TOPIC.search(norm)
                or re.match(r"^(?:como|cuanto|cuando|donde)\b", norm)):
            continuation = False
            continue
        mentions = list(dict.fromkeys(catalog[match[0]] for match in matcher.finditer(norm)))
        if len(mentions) > 1 and re.search(r"\b(?:o|tal vez|quizas)\b", norm):
            continuation = False
            continue
        own = bool(_OWN_TRADE.search(norm))
        bare = bool(mentions and len(norm.split()) <= 9 and not re.search(r"[?¿]", message)
                    and set(matcher.sub(" ", norm).split()) <= {"y", "e", "o", "de", "en", "tambien", "igual", "no"})
        negative = bool(_TRADE_NEGATIVE.search(norm))
        if not mentions:
            continuation = own and not negative
            continue
        if own or (bare and (direct or continuation or allow_bare or norm.startswith("tambien "))):
            for trade in mentions:
                result[trade] = not negative
        continuation = own and not negative or bare and continuation and not negative
    return result


def extract_declared_trades(message: str, prior_prompt: str = "") -> list[str]:
    return [trade for trade, present in trade_declarations(message, prior_prompt).items() if present]


def audit_event(db: Session, lead, event: str, *, source: str = "system",
                trade: str | None = None, requirement_id: str | None = None,
                actor_id: str | None = None, remote_id: str | None = None) -> None:
    db.add(FacebookLeadTrace(
        org_id=lead.org_id, lead_id=lead.id, event=event[:32],
        source=source[:24], trade=trade, requirement_id=requirement_id,
        actor_id=actor_id, source_remote_id=remote_id,
    ))


def record_declared_trades(db: Session, lead, message: str, *,
                           remote_id: str | None = None, prior_prompt: str = "",
                           declarations: dict[str, bool] | None = None,
                           historical: bool = False, at=None) -> tuple[list[str], bool]:
    """Keep additions and explicit corrections in the existing trade history."""
    detected = declarations if declarations is not None else trade_declarations(message, prior_prompt)
    if not detected:
        return [], False
    changed = False
    existing = list(db.scalars(select(FacebookLeadTrade).where(
        FacebookLeadTrade.org_id == lead.org_id,
        FacebookLeadTrade.lead_id == lead.id,
    ).order_by(FacebookLeadTrade.first_seen_at, FacebookLeadTrade.id)))
    by_trade = {plain(canonical_trade(item.trade)): item for item in existing}
    now = at or utcnow()
    for trade, present in detected.items():
        stored = by_trade.get(plain(trade))
        if stored and stored.updated_at and at:
            stamp = stored.updated_at
            stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
            if at < stamp:
                continue
        if stored is None and present and len(existing) < 40:
            stored = FacebookLeadTrade(
                org_id=lead.org_id, lead_id=lead.id, trade=trade,
                source="message", source_remote_id=remote_id, active=True,
                first_seen_at=now, updated_at=now,
            )
            db.add(stored)
            changed = True
            existing.append(stored)
            by_trade[plain(trade)] = stored
            audit_event(db, lead, "trade_added", trade=trade, source="message", remote_id=remote_id)
        elif stored and stored.source == "message" and stored.active != present and not historical:
            stored.active, stored.updated_at = present, now
            changed = True
            stored.source_remote_id = remote_id
            audit_event(db, lead, "trade_reactivated" if present else "trade_removed",
                        trade=trade, source="message", remote_id=remote_id)
    return [item.trade for item in existing if item.active], changed


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
        if need.deadline and need.deadline < today():
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
