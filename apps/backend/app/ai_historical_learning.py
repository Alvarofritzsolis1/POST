"""Read-only historical evidence, never raw conversations or inferred scores.

All available database metadata is aggregated without a 30-day cutoff.  This is
not permission to reuse message contents for fine-tuning: internal chats expire
and archived Messenger text has separate privacy requirements.
"""
from datetime import timedelta

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from .ai_quality_audit import CRITERIA
from .ai_quality_models import AIRealPracticeTrial, AIResponseReview
from .facebook_crm_models import FacebookChatMessage
from .galancito_knowledge_models import AssistantRun, InternalConversation
from .models import utcnow


def _scope(model, org_id, since=None, *, time_column=None):
    time_column = time_column if time_column is not None else model.created_at
    filters = [model.org_id == org_id]
    if since is not None:
        filters.append(time_column >= since)
    return filters


def _totals(db, model, org_id, since=None, *, clock=None):
    clock = clock if clock is not None else model.created_at
    total, earliest, latest = db.execute(
        select(func.count(), func.min(clock), func.max(clock))
        .where(*_scope(model, org_id, since, time_column=clock))
    ).one()
    return {"count": int(total or 0),
            "first_at": earliest.isoformat() if earliest else None,
            "last_at": latest.isoformat() if latest else None}


def _monthly(db, model, org_id, since=None, *, clock=None, channel=None):
    clock = clock if clock is not None else model.created_at
    year, month = extract("year", clock), extract("month", clock)
    dims = [year, month]
    if channel is not None:
        dims.append(channel)
    rows = db.execute(select(*dims, func.count()).where(
        *_scope(model, org_id, since, time_column=clock)
    ).group_by(*dims).order_by(year.desc(), month.desc())).all()
    result = []
    for row in rows:
        # Extract works in PostgreSQL and SQLAlchemy's SQLite test dialect.
        if row[0] is None or row[1] is None:
            continue
        data = {"month": f"{int(row[0]):04d}-{int(row[1]):02d}"}
        if channel is not None:
            data["channel"] = str(row[2])
        data["count"] = int(row[-1] or 0)
        result.append(data)
    return result


def historical_overview(db: Session, org_id: str, *, months: int = 0) -> dict:
    """Cross-version metadata inventory; 0 = all retained years, no content.

    SQL aggregation means this endpoint does not load private chat text or all
    AssistantRun objects into RAM. Review JSON labels are streamed in batches.
    """
    if not isinstance(months, int) or not 0 <= months <= 60:
        raise ValueError("La ventana histórica debe ser 0 o entre 1 y 60 meses")
    since = utcnow() - timedelta(days=months * 31) if months else None
    sources = {
        "runs": _totals(db, AssistantRun, org_id, since),
        "delivered_messenger": _totals(db, FacebookChatMessage, org_id, since),
        "reviews": _totals(db, AIResponseReview, org_id, since, clock=AIResponseReview.source_at),
        "practice_trials": _totals(db, AIRealPracticeTrial, org_id, since),
    }
    # Messenger count must be real delivered AI, never all stored messages.
    sent_filters = [
        FacebookChatMessage.org_id == org_id,
        FacebookChatMessage.ai_generated.is_(True),
        FacebookChatMessage.direction == "outbound",
        FacebookChatMessage.state == "sent",
    ]
    if since is not None:
        sent_filters.append(FacebookChatMessage.created_at >= since)
    delivered, first, last = db.execute(select(
        func.count(), func.min(FacebookChatMessage.created_at),
        func.max(FacebookChatMessage.created_at)
    ).where(*sent_filters)).one()
    sources["delivered_messenger"] = {
        "count": int(delivered or 0), "first_at": first.isoformat() if first else None,
        "last_at": last.isoformat() if last else None,
    }
    timeline = {
        "runs": _monthly(db, AssistantRun, org_id, since, channel=AssistantRun.channel),
        "reviews": _monthly(db, AIResponseReview, org_id, since,
                            clock=AIResponseReview.source_at, channel=AIResponseReview.channel),
        "practice_trials": _monthly(db, AIRealPracticeTrial, org_id, since,
                                   channel=AIRealPracticeTrial.channel),
    }

    by_channel = {}
    for channel, status, amount in db.execute(select(
        AssistantRun.channel, AssistantRun.feedback, func.count()
    ).where(*_scope(AssistantRun, org_id, since))
     .group_by(AssistantRun.channel, AssistantRun.feedback)):
        bucket = by_channel.setdefault(channel, {"recorded_runs": 0, "reported_incorrect": 0})
        bucket["recorded_runs"] += int(amount)
        if status == "incorrect":
            bucket["reported_incorrect"] += int(amount)

    # Human labels provide observed deficits, unlike complaint or latency counts.
    labels = {channel: {name: {"assessed": 0, "failed": 0} for name in fields}
              for channel, fields in CRITERIA.items()}
    scan = db.execute(select(AIResponseReview.channel, AIResponseReview.ratings).where(
        *_scope(AIResponseReview, org_id, since,
                time_column=AIResponseReview.source_at),
        AIResponseReview.rubric_version == 1,
    )).yield_per(500)
    for channel, ratings in scan:
        if channel not in labels or not isinstance(ratings, dict):
            continue
        for criterion, counts in labels[channel].items():
            value = ratings.get(criterion)
            if value is True or value is False:
                counts["assessed"] += 1
                if value is False:
                    counts["failed"] += 1
    for items in labels.values():
        for counts in items.values():
            counts["failure_percent"] = (
                round(100 * counts["failed"] / counts["assessed"], 1)
                if counts["assessed"] else None
            )

    trials = {}
    for channel, stage, result, amount in db.execute(select(
        AIRealPracticeTrial.channel, AIRealPracticeTrial.stage,
        AIRealPracticeTrial.outcome, func.count()
    ).where(*_scope(AIRealPracticeTrial, org_id, since))
     .group_by(AIRealPracticeTrial.channel, AIRealPracticeTrial.stage,
               AIRealPracticeTrial.outcome)):
        entry = trials.setdefault(channel, {})
        entry[f"{stage}:{result}"] = int(amount)

    # Strict privacy: even administrators cannot bulk-read another user's
    # saved internal conversation; only count retained rows and expired date.
    retained = db.scalar(select(func.count()).select_from(InternalConversation).where(
        InternalConversation.org_id == org_id,
        InternalConversation.expires_at >= utcnow(),
    ))
    return {
        "window": "all_retained" if not months else "last_months",
        "months": months,
        "sources": sources, "timeline": timeline,
        "runs_by_channel": by_channel, "audited_deficiencies": labels,
        "practice_outcomes": trials,
        "internal_opt_in_conversations_retained": int(retained or 0),
        "historical_quality_grade": None,
        "weights_updated": False,
        "training_dataset_approved": False,
        "limitations": [
            "Solo se analizan registros que todavía existen en la base de datos.",
            "Las respuestas anteriores a la telemetría pueden carecer de trazas del modelo.",
            "Los avisos de error y las muestras auditadas no representan toda la calidad histórica.",
            "Los chats privados del usuario no se exportan ni se leen de forma masiva.",
            "Los registros históricos no son ejemplos supervisados para entrenar pesos.",
        ],
    }
