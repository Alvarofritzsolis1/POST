"""One effective-rule evaluator shared by administrative and operational views."""
from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from copy import deepcopy

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from .config import settings
from .configuration_models import ConfigurationDocumentType as DocumentType, ConfigurationRule as Rule, ConfigurationSettings, GateMovement, ConfigurationObligationSnapshot
from .contractor_policy import inactive_for_period
from .control_models import ContributionControl, ContractAmendment, ContractRegister, ProcessCalendar, RequirementApplicability
from .models import Document, User, utcnow
from .network_models import NetworkMember
from .ops_api import contractor_classification
from .ops_models import AuditPeriod, Contractor, ContractorWorksite, MonthlyDocument, OpsChange, Worker, WorkerAssignment, Worksite
from .platform_models import DocumentReview, PaymentFinding, UserPreferences, WorkerTermination

TZ = ZoneInfo("America/Santiago")
EXEMPT = {"not_applicable", "exempt", "no_movements"}
DELIVERED = {"approved", "submitted", "incomplete", "rejected"}
SCOPES = {"general": 1, "category": 2, "site": 3, "association": 4, "exception": 5}
DEFAULTS = [
    ("f30", "F30", "contractor", "monthly"),
    ("f30_1", "F30-1", "contractor", "monthly"),
    ("cotizaciones", "Pago de cotizaciones previsionales", "contractor_workers", "monthly"),
    ("liquidaciones", "Liquidaciones firmadas", "contractor_workers", "monthly"),
    ("asistencia", "Libro de asistencia", "contractor_workers", "monthly"),
    ("porteria", "Informe de Portería", "contractor_site_period", "monthly"),
    ("contrato_trabajo", "Contrato de trabajo", "worker", "once"),
    ("anexos_contrato", "Anexos de contrato", "worker", "on_event"),
    ("finiquito", "Finiquito", "worker", "on_event"),
    ("declaracion_jurada", "Declaración jurada", "contractor", "monthly"),
    ("mutualidad", "Certificado de afiliación a mutualidad", "contractor", "annual"),
    ("accidentabilidad", "Certificado de accidentabilidad", "contractor", "annual"),
    ("siniestralidad", "Certificado de siniestralidad", "contractor", "annual"),
    ("anticipos", "Listado de anticipos", "contractor", "monthly"),
    ("otros", "Otros documentos personalizados", "contractor", "monthly"),
]


def today():
    return datetime.now(TZ).date()


def current_period():
    return today().strftime("%Y-%m")


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if c.isalnum() and not unicodedata.combining(c))


def period_number(period):
    year, month = map(int, period.split("-"))
    return year * 12 + month - 1


def add_months(period, count):
    value = period_number(period) + count
    return f"{value // 12:04d}-{value % 12 + 1:02d}"


def validate_period(value):
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", value):
        raise HTTPException(422, "El período debe tener formato AAAA-MM entre 2000 y 2099")
    return value


def parse_periods(value):
    periods = sorted(set(value.split(","))) if value else [current_period()]
    if not periods or len(periods) > 60:
        raise HTTPException(422, "Selecciona entre uno y sesenta períodos por consulta")
    return [validate_period(p) for p in periods]


def ensure_configuration(db, org_id):
    config = db.get(ConfigurationSettings, org_id)
    if config is None:
        config = ConfigurationSettings(org_id=org_id, porteria_start_period=current_period(), alert_days=7, repeated_periods=3, version=1)
        db.add(config)
    existing = {r.code for r in db.scalars(select(DocumentType).where(DocumentType.org_id == org_id))}
    for code, name, level, frequency in DEFAULTS:
        if code not in existing:
            db.add(DocumentType(org_id=org_id, code=code, name=name, normalized_name=normalized(name),
                                level=level, frequency=frequency, category="Control documental", system=True,
                                description="", conditions=""))
    db.flush()
    return config


def catalog_view(row):
    return {key: getattr(row, key) for key in ("id", "code", "name", "description", "category", "level", "frequency", "conditions", "system")}


def settings_view(row):
    return {key: getattr(row, key) for key in ("porteria_start_period", "alert_days", "repeated_periods", "version")}


def display_names(db, org_id):
    result = {}
    rows = db.execute(select(User, UserPreferences, NetworkMember)
                      .outerjoin(UserPreferences, UserPreferences.user_id == User.id)
                      .outerjoin(NetworkMember, NetworkMember.user_id == User.id)
                      .where(User.org_id == org_id)).all()
    for user, pref, member in rows:
        name = (pref.values.get("name", "") if pref else "") or (member.name if member else "")
        result[user.id] = name.strip() if name and "@" not in name else "Responsable sin nombre registrado"
    return result


def association_view(link, company, site):
    return {"association_id": link.id, "contractor_id": company.id, "name": company.name,
            "rut": company.rut, "site_id": site.id, "site": site.name,
            "category": canonical_category(contractor_classification(link, company)), "status": link.contract_status}


def canonical_category(value):
    return "CE" if value in {"CE", "ESP"} else value


def base_required(code, link, company, period, config, activation_start=None):
    category = canonical_category(contractor_classification(link, company))
    if code == "porteria":
        return period >= (activation_start or config.porteria_start_period) and category in {"CT", "CE", "CI"}
    if code == "anticipos" and category == "CI":
        return False
    if category == "CI":
        return code in {"cotizaciones", "declaracion_jurada"}
    if category == "CT":
        return code in {"cotizaciones", "f30_1", "liquidaciones", "asistencia"}
    return False


def resolve(document_type, link, company, period, config, rules, overrides=None):
    category = canonical_category(contractor_classification(link, company))
    activations = [rule for rule in rules if rule.scope == "activation" and rule.activation_from_period and rule.activation_from_period <= period]
    activation = max(activations, key=lambda rule: rule.revision) if activations else None
    activation_start = activation.period_start if activation else config.porteria_start_period
    result = {"applicable": base_required(document_type.code, link, company, period, config, activation_start),
              "rule_source": ("Inicio general configurado" if activation else "Regla general predeterminada") if document_type.code == "porteria" else "Plantilla de categoría existente",
              "rule_id": activation.id if activation and document_type.code == "porteria" else None, "frequency": document_type.frequency, "due_date": None,
              "period_start": activation_start if document_type.code == "porteria" else "2000-01", "exception_reason": ""}
    latest = {}
    for rule in rules:
        if rule.scope == "activation" or rule.document_type_id != document_type.id or not rule.period_start <= period or (rule.period_end and period > rule.period_end):
            continue
        matches = (rule.scope == "general" or (rule.scope == "category" and rule.category == category)
                   or (rule.scope == "site" and rule.site_id == link.worksite_id)
                   or (rule.scope in {"association", "exception"} and rule.association_id == link.id))
        if matches and (rule.scope not in latest or latest[rule.scope].revision < rule.revision):
            latest[rule.scope] = rule
    for scope in sorted(latest, key=SCOPES.get):
        rule = latest[scope]
        if rule.required is None:
            continue
        # Portería can only be exempted for a specific association and finite period.
        if document_type.code == "porteria" and not rule.required and scope != "exception":
            continue
        result.update(applicable=rule.required, rule_source={"general": "Regla general", "category": "Plantilla de categoría", "site": "Regla de obra", "association": "Regla individual", "exception": "Excepción temporal autorizada"}[scope],
                      rule_id=rule.id, frequency=rule.frequency, period_start=rule.period_start, exception_reason=rule.reason if scope == "exception" and rule.required is False else "")
        if rule.due_day:
            due_period = add_months(period, rule.due_month_offset)
            year, month = map(int, due_period.split("-"))
            result["due_date"] = date(year, month, min(rule.due_day, calendar.monthrange(year, month)[1])).isoformat()
        else:
            result["due_date"] = None
    if overrides and not result["rule_id"] and (document_type.code != "porteria" or period < config.porteria_start_period):
        override = overrides.get((link.id, period, document_type.code))
        if override is not None:
            result.update(applicable=override.applicable, rule_source="Excepción mensual existente")
    frequency = result["frequency"]
    delta = period_number(period) - period_number(result["period_start"])
    if (frequency == "quarterly" and delta % 3 or frequency == "annual" and delta % 12
            or document_type.level != "worker" and frequency in {"once", "on_event"} and delta != 0):
        result["applicable"] = False
    if inactive_for_period(link, period):
        result.update(applicable=False, rule_source="Contratista inactivo en período actual/futuro")
    return result


def legacy_requirements(db, org_id, association, company, period):
    config = db.get(ConfigurationSettings, org_id)
    if config is None:
        return {}
    documents = db.scalars(select(DocumentType).where(DocumentType.org_id == org_id)).all()
    rules = db.scalars(select(Rule).where(Rule.org_id == org_id)).all()
    overrides = {(r.association_id, r.period, r.kind): r for r in db.scalars(select(RequirementApplicability).where(RequirementApplicability.org_id == org_id, RequirementApplicability.association_id == association.id, RequirementApplicability.period == period))}
    return {document.code: resolve(document, association, company, period, config, rules, overrides) for document in documents}


def empty_counts():
    return {"required": 0, "approved": 0, "submitted": 0, "missing": 0, "incomplete": 0, "rejected": 0,
            "overdue": 0, "exempt": 0, "delivered": 0, "reviewed": 0, "porteria_pending": 0}


def count_obligation(counts, row):
    if row["state"] in EXEMPT and row["notes"].strip():
        counts["exempt"] += 1
    if not row["required"]:
        return
    counts["required"] += 1
    if row["state"] in counts:
        counts[row["state"]] += 1
    if row["delivered"]:
        counts["delivered"] += 1
    if row["state"] in {"approved", "incomplete", "rejected"}:
        counts["reviewed"] += 1
    if row["code"] == "porteria" and row["state"] != "approved":
        counts["porteria_pending"] += 1


def percentages(counts):
    counts["compliance"] = round(100 * counts["approved"] / counts["required"], 2) if counts["required"] else None
    counts["delivery"] = round(100 * counts["delivered"] / counts["required"], 2) if counts["required"] else None
    return counts


def evaluate(db, org_id, periods, site_id=None, category=None, q="", state=None, association_id=None, extra_rules=(), refresh_snapshot_codes=(), refresh_association_ids=None, persist_snapshots=False):
    config = ensure_configuration(db, org_id)
    types = db.scalars(select(DocumentType).where(DocumentType.org_id == org_id).order_by(DocumentType.name)).all()
    rules = list(db.scalars(select(Rule).where(Rule.org_id == org_id)).all()) + list(extra_rules)
    rules_by_type = defaultdict(list)
    for rule in rules:
        if not rule.period_end or rule.period_end >= min(periods):
            rules_by_type[rule.document_type_id].append(rule)
    query = select(ContractorWorksite, Contractor, Worksite).join(Contractor, Contractor.id == ContractorWorksite.contractor_id).join(Worksite, Worksite.id == ContractorWorksite.worksite_id).where(ContractorWorksite.org_id == org_id, Contractor.org_id == org_id, Worksite.org_id == org_id)
    if site_id:
        query = query.where(Worksite.id == site_id)
    if association_id:
        query = query.where(ContractorWorksite.id == association_id)
    all_links = db.execute(query.order_by(Contractor.name, Worksite.name)).all()
    all_links = [(link, company, site) for link, company, site in all_links if (not category or canonical_category(contractor_classification(link, company)) == canonical_category(category)) and (not q or normalized(q) in normalized(company.name + (company.rut or "")))]
    ids = [link.id for link, _, _ in all_links]
    links_by_pair = {(link.contractor_id, link.worksite_id): link.id for link, _, _ in all_links}
    if len(ids) * len(periods) * len(types) > 200000:
        raise HTTPException(422, "La consulta supera 200.000 requisitos. Acota obra, contratista o períodos")
    names = display_names(db, org_id)
    docs = db.scalars(select(MonthlyDocument).where(MonthlyDocument.org_id == org_id, MonthlyDocument.association_id.in_(ids), MonthlyDocument.period.in_(periods)).order_by(MonthlyDocument.updated_at.desc(), MonthlyDocument.id.desc())).all() if ids else []
    document_ids = {r.document_id for r in docs if r.document_id}
    originals = {r.id: r for r in db.scalars(select(Document).where(Document.org_id == org_id, Document.id.in_(document_ids)))} if document_ids else {}
    worker_reviews = db.scalars(select(DocumentReview).where(DocumentReview.org_id == org_id, DocumentReview.association_id.in_(ids), DocumentReview.period.in_(periods))).all() if ids else []
    review_aliases = {"Contrato": "contrato_trabajo", "Anexo": "anexos_contrato", "Finiquito": "finiquito", "Cotizaciones": "cotizaciones", "Liquidaciones": "liquidaciones", "Libro de asistencia": "asistencia"}
    by_review = {}
    for review in sorted(worker_reviews, key=lambda row: (str(row.reviewed_at), row.id), reverse=True):
        by_review.setdefault((review.association_id, review.period, review_aliases.get(review.requirement, review.requirement), review.subject), review)
    worker_document_ids = {r.document_id for r in worker_reviews if r.document_id}
    if worker_document_ids:
        originals.update({r.id: r for r in db.scalars(select(Document).where(Document.org_id == org_id, Document.id.in_(worker_document_ids)))})
    by_doc = {}
    for doc in docs:
        by_doc.setdefault((doc.association_id, doc.period, doc.kind), doc)
    overrides = {(r.association_id, r.period, r.kind): r for r in db.scalars(select(RequirementApplicability).where(RequirementApplicability.org_id == org_id, RequirementApplicability.association_id.in_(ids), RequirementApplicability.period.in_(periods)))} if ids else {}
    schedules = {(r.worksite_id, r.period, r.kind): r for r in db.scalars(select(ProcessCalendar).where(ProcessCalendar.org_id == org_id, ProcessCalendar.period.in_(periods)))}
    workers = db.execute(select(WorkerAssignment, Worker).join(Worker, Worker.id == WorkerAssignment.worker_id).where(WorkerAssignment.org_id == org_id, Worker.org_id == org_id)).all()
    worker_map = defaultdict(list)
    for assignment, worker in workers:
        link_id = links_by_pair.get((assignment.contractor_id, assignment.worksite_id))
        if link_id:
            worker_map[link_id].append((assignment, worker))
    contracts = db.scalars(select(ContractRegister).where(ContractRegister.org_id == org_id, ContractRegister.association_id.in_(ids))).all() if ids else []
    contracts_by_worker = defaultdict(list)
    for contract in contracts:
        contracts_by_worker[contract.worker_assignment_id].append(contract)
    contribution_controls = db.scalars(select(ContributionControl).where(ContributionControl.org_id == org_id, ContributionControl.association_id.in_(ids), ContributionControl.period.in_(periods))).all() if ids else []
    contribution_ids = [r.id for r in contribution_controls]
    findings = {r.control_id: r for r in db.scalars(select(PaymentFinding).where(PaymentFinding.org_id == org_id, PaymentFinding.control_id.in_(contribution_ids)))} if contribution_ids else {}
    differences = defaultdict(list)
    for control in contribution_controls:
        required_days = control.attendance_days if control.attendance_days is not None else control.required_days
        finding = findings.get(control.id)
        days_missing = max(0, required_days - control.paid_days) if required_days is not None and control.paid_days is not None else 0
        if control.payment_confirmed and days_missing and not control.justification.strip() or finding and finding.state == "insufficient":
            differences[(control.association_id, control.period)].append(control)
    contract_ids = [c.id for c in contracts]
    amendments = db.scalars(select(ContractAmendment).where(ContractAmendment.org_id == org_id, ContractAmendment.contract_id.in_(contract_ids))).all() if contract_ids else []
    terminations = db.scalars(select(WorkerTermination).where(WorkerTermination.org_id == org_id, WorkerTermination.contract_id.in_(contract_ids))).all() if contract_ids else []
    snapshots = {(r.association_id, r.period): r for r in db.scalars(select(ConfigurationObligationSnapshot).where(
        ConfigurationObligationSnapshot.org_id == org_id, ConfigurationObligationSnapshot.association_id.in_(ids),
        ConfigurationObligationSnapshot.period.in_(periods)))} if ids else {}
    proposal_codes = {r.document_type_id for r in extra_rules}
    totals = empty_counts()
    by_period = {p: dict(period=p, **empty_counts()) for p in periods}
    by_site, by_contractor = {}, {}
    obligations, alerts = [], []
    for link, company, site in all_links:
        info = association_view(link, company, site)
        contractor_counts = dict(info, **empty_counts())
        by_contractor[link.id] = contractor_counts
        by_site.setdefault(site.id, dict(site_id=site.id, site=site.name, **empty_counts()))
        for period in periods:
            snapshot = snapshots.get((link.id, period))
            frozen = snapshot.payload if snapshot and period < current_period() else None
            captured = deepcopy(frozen) if frozen else {"category": info["category"], "status": link.contract_status,
                "workers": [(a.id, w.name) for a, w in worker_map[link.id]], "entries": {}}
            historical_link = SimpleNamespace(**{column.name: getattr(link, column.name) for column in link.__table__.columns})
            if frozen:
                historical_link.historical_code = frozen["category"]
                historical_link.contract_status = frozen["status"]
            for doc_type in types:
                refresh = doc_type.code in refresh_snapshot_codes and (refresh_association_ids is None or link.id in refresh_association_ids)
                proposed = doc_type.id in proposal_codes
                saved = frozen.get("entries", {}).get(doc_type.code) if frozen else None
                use_saved = bool(saved and not proposed and not refresh)
                effective = deepcopy(saved["effective"]) if use_saved else resolve(doc_type, historical_link, company, period, config, rules_by_type[doc_type.id], overrides)
                if frozen and not saved and not proposed and not refresh:
                    effective["applicable"] = False
                subjects = [("contractor", None)]
                if doc_type.level == "worker":
                    subjects = []
                    month_start = date.fromisoformat(period + "-01")
                    month_end = date(month_start.year, month_start.month, calendar.monthrange(month_start.year, month_start.month)[1])
                    for assignment, worker in worker_map[link.id]:
                        relevant = contracts_by_worker.get(assignment.id, [])
                        active = any(c.start_date <= month_end and (c.end_date is None or c.end_date >= month_start) for c in relevant) if relevant else assignment.active
                        if active:
                            subjects.append((assignment.id, worker.name))
                if frozen and doc_type.level == "worker":
                    subjects = [(r["subject"], r["worker"]) for r in saved["subjects"]] if saved else [tuple(r) for r in frozen.get("workers", [])]
                captured_subjects = []
                for subject, worker_name in subjects:
                    review = by_review.get((link.id, period, doc_type.code, subject)) if subject != "contractor" else by_doc.get((link.id, period, doc_type.code))
                    status = (review.state if subject != "contractor" else review.review_status) if review else "missing"
                    status = {"pending": "submitted" if review and review.document_id else "missing", "observed": "incomplete"}.get(status, status)
                    if status not in EXEMPT | DELIVERED | {"missing", "overdue"}:
                        status = "missing"
                    notes = (review.observation if subject != "contractor" else review.notes) if review else ""
                    if effective["exception_reason"]:
                        status, notes = "exempt", effective["exception_reason"]
                    if doc_type.code == "cotizaciones" and differences.get((link.id, period)) and status not in EXEMPT:
                        status = "incomplete"
                        notes = (notes + "; " if notes else "") + "Diferencia previsional registrada pendiente de regularización o justificación"
                    required = effective["applicable"] is True
                    if subject != "contractor" and effective["frequency"] in {"once", "on_event"}:
                        worker_contracts = contracts_by_worker.get(subject, [])
                        worker_contract_ids = {c.id for c in worker_contracts}
                        event_periods = set()
                        if effective["frequency"] == "once":
                            event_periods = {max(effective["period_start"], c.start_date.strftime("%Y-%m")) for c in worker_contracts}
                            if not worker_contracts:
                                event_periods = {effective["period_start"]}
                        elif doc_type.code == "anexos_contrato":
                            event_periods = {a.amendment_date.strftime("%Y-%m") for a in amendments if a.contract_id in worker_contract_ids}
                        elif doc_type.code == "finiquito":
                            event_periods = {t.effective_date.strftime("%Y-%m") for t in terminations if t.contract_id in worker_contract_ids}
                        else:
                            event_periods = {effective["period_start"]}
                        required = required and period in event_periods
                    saved_subject = next((r for r in saved["subjects"] if r["subject"] == subject), None) if saved else None
                    if use_saved and saved_subject:
                        required = saved_subject["required"]
                    base_required_for_snapshot = required
                    if status in EXEMPT and not notes.strip():
                        status = "missing"
                    if status in EXEMPT:
                        required = False
                    due_date = effective["due_date"]
                    schedule = schedules.get((site.id, period, doc_type.code))
                    if period < config.porteria_start_period and not effective["rule_id"]:
                        # Historical denominator keeps the legacy evaluability rule.
                        required = required and bool(review or schedule and today() >= schedule.request_date)
                    if not effective["rule_id"] and schedule:
                        due_date = schedule.due_date.isoformat()
                    if use_saved and saved_subject:
                        due_date = saved_subject["due_date"]
                    captured_subjects.append({"subject": subject, "worker": worker_name,
                        "required": base_required_for_snapshot if period >= config.porteria_start_period or effective["rule_id"] else (base_required_for_snapshot and bool(review or schedule and today() >= schedule.request_date)),
                        "due_date": due_date})
                    delivered = bool((review and (status in DELIVERED or review.document_id)) or doc_type.code == "cotizaciones" and differences.get((link.id, period)))
                    if required and status == "missing" and due_date and due_date < today().isoformat():
                        status = "overdue"
                    if not required and status not in EXEMPT:
                        status = "not_required"
                    original = originals.get(review.document_id) if review else None
                    row = {"association_id": link.id, "contractor": company.name, "site_id": site.id, "site": site.name,
                           "category": frozen["category"] if frozen else info["category"], "period": period, "document_type_id": doc_type.id,
                           "code": doc_type.code, "document": doc_type.name, "subject": subject, "worker": worker_name,
                           "required": required, "state": status, "delivered": delivered,
                           "rule_source": effective["rule_source"], "rule_id": effective["rule_id"],
                           "frequency": effective["frequency"], "due_date": due_date, "notes": notes,
                           "reviewed_by": names.get(review.reviewed_by, "Responsable sin nombre registrado") if review and review.reviewed_by else None,
                           "reviewed_at": review.reviewed_at if review else None,
                           "document_id": review.document_id if review else None, "original_name": original.original_name if original else None}
                    if state and row["state"] != state:
                        continue
                    obligations.append(row)
                    if len(obligations) > 200000:
                        raise HTTPException(422, "La consulta supera 200.000 obligaciones personales; reduce los filtros")
                    for counts in (totals, by_period[period], by_site[site.id], contractor_counts):
                        count_obligation(counts, row)
                    if required and status in {"missing", "incomplete", "rejected", "overdue"}:
                        alerts.append({"key": f"document:{link.id}:{period}:{doc_type.code}:{subject}", "association_id": link.id,
                                       "contractor": company.name, "site": site.name, "period": period, "document": doc_type.name,
                                       "reason": {"missing": "Documento sin entrega registrada", "incomplete": "Documento entregado incompleto; requiere revisión", "rejected": "Documento rechazado", "overdue": "Fecha límite vencida"}[status],
                                       "priority": "high" if status in {"overdue", "rejected"} else "normal", "action": "Revisar antecedentes y registrar el resultado manual"})
                    elif required and due_date and 0 <= (date.fromisoformat(due_date) - today()).days <= config.alert_days and status != "approved":
                        alerts.append({"key": f"due:{link.id}:{period}:{doc_type.code}:{subject}", "association_id": link.id, "contractor": company.name, "site": site.name, "period": period, "document": doc_type.name, "reason": "Obligación próxima a vencer", "priority": "normal", "action": "Revisar antes de la fecha límite"})
                captured["entries"][doc_type.code] = {"effective": effective, "subjects": captured_subjects}
            if persist_snapshots and not extra_rules and period <= current_period():
                if snapshot is None:
                    snapshot = ConfigurationObligationSnapshot(org_id=org_id, association_id=link.id, period=period)
                    db.add(snapshot)
                    snapshots[(link.id, period)] = snapshot
                snapshot.payload = jsonable_encoder(captured)
                snapshot.updated_at = utcnow()
    totals.update(active=sum(link.contract_status == "active" for link, _, _ in all_links), inactive=sum(link.contract_status != "active" for link, _, _ in all_links), categories={c: sum(canonical_category(contractor_classification(l, company)) == c for l, company, _ in all_links) for c in ("CT", "CE", "CI")})
    links_info = {link.id: (company, site) for link, company, site in all_links}
    for contract in contracts:
        company, site = links_info[contract.association_id]
        if contract.end_date and contract.end_date.strftime("%Y-%m") in periods and 0 <= (contract.end_date - today()).days <= config.alert_days and contract.status == "active":
            alerts.append({"key": "contract:" + contract.id, "association_id": contract.association_id, "contractor": company.name, "site": site.name, "period": contract.end_date.strftime("%Y-%m"), "document": "Contrato de trabajo", "reason": "Contrato laboral próximo a terminar", "priority": "normal", "action": "Revisar fecha de término y antecedentes laborales"})
    contracts_by_id = {c.id: c for c in contracts}
    for termination in terminations:
        contract = contracts_by_id[termination.contract_id]
        if termination.effective_date.strftime("%Y-%m") in periods and termination.review_state != "approved":
            company, site = links_info[contract.association_id]
            alerts.append({"key": "termination:" + termination.id, "association_id": contract.association_id, "contractor": company.name, "site": site.name, "period": termination.effective_date.strftime("%Y-%m"), "document": "Finiquito", "reason": "Finiquito de término registrado pendiente de revisión", "priority": "normal", "action": "Revisar el finiquito en la ficha del trabajador"})
    alerts.extend(gate_alerts(db, org_id, ids, periods, all_links, worker_map, contracts_by_worker))
    problematic = defaultdict(set)
    for alert in alerts:
        if alert["priority"] == "high":
            problematic[alert["association_id"]].add(alert["period"])
    for association, months in problematic.items():
        if len(months) >= config.repeated_periods:
            info = by_contractor[association]
            alerts.append({"key": "repeated:" + association, "association_id": association, "contractor": info["name"], "site": info["site"], "period": ", ".join(sorted(months)), "document": "Varios documentos", "reason": "Observaciones reiteradas en múltiples períodos", "priority": "high", "action": "Revisar historial y acordar regularización"})
    return {"periods": periods, "summary": percentages(totals), "by_period": [percentages(r) for r in by_period.values()], "by_site": [percentages(r) for r in by_site.values()], "contractors": [percentages(r) for r in by_contractor.values()], "obligations": obligations, "alerts": alerts}


def gate_alerts(db, org_id, ids, periods, links, workers, contracts):
    from .v81_models import CalendarWeek, CalendarEntry
    info = {link.id: (company, site) for link, company, site in links}
    movements = db.scalars(select(GateMovement).where(GateMovement.org_id == org_id, GateMovement.association_id.in_(ids), GateMovement.period.in_(periods))).all() if ids else []
    weeks = db.scalars(select(CalendarWeek).where(CalendarWeek.org_id == org_id, CalendarWeek.association_id.in_(ids), CalendarWeek.period.in_(periods))).all() if ids else []
    week_map = {w.id: w for w in weeks}
    entries = db.scalars(select(CalendarEntry).where(CalendarEntry.org_id == org_id, CalendarEntry.week_id.in_(list(week_map)))).all() if week_map else []
    entry_map = {(e.week_id, e.worker_assignment_id): e for e in entries}
    result = []
    for move in movements:
        company, site = info[move.association_id]
        match = next(((a, w) for a, w in workers[move.association_id] if (move.worker_rut and w.rut == move.worker_rut) or (not move.worker_rut and normalized(w.name) == normalized(move.worker_name))), None)
        reason = None
        if match is None:
            reason = "Ingreso detectado sin registro de trabajador asociado"
        else:
            assignment, worker = match
            day = date.fromisoformat(move.movement_date)
            worker_contracts = contracts.get(assignment.id, [])
            if worker_contracts and not any(c.start_date <= day and (c.end_date is None or c.end_date >= day) for c in worker_contracts):
                reason = "Acceso fuera de fechas contractuales registradas — requiere revisión"
            else:
                covering = [w for w in weeks if w.association_id == move.association_id and w.start_date <= day <= w.end_date and w.state == "complete"]
                if covering and not any(move.movement_date in (entry_map[(w.id, assignment.id)].signed_dates or []) for w in covering if (w.id, assignment.id) in entry_map):
                    reason = "Posible diferencia entre portería y asistencia — requiere revisión"
        if reason:
            result.append({"key": "gate:" + move.id, "association_id": move.association_id, "contractor": company.name,
                           "site": site.name, "period": move.period, "document": "Informe de Portería", "reason": reason,
                           "priority": "normal", "action": "Contrastar el movimiento transcrito con registros y antecedentes; no es incumplimiento definitivo"})
    return result


def legacy_matrix(db, org_id, site_id, period):
    config = db.get(ConfigurationSettings, org_id)
    if config is None:
        return None
    has_rules = db.scalar(select(Rule.id).where(Rule.org_id == org_id, Rule.period_start <= period).limit(1))
    if period < config.porteria_start_period and not has_rules:
        return None
    result = evaluate(db, org_id, [period], site_id=site_id)
    grouped = defaultdict(list)
    for row in result["obligations"]:
        grouped[row["association_id"]].append(row)
    companies = db.execute(select(ContractorWorksite, Contractor).join(Contractor, Contractor.id == ContractorWorksite.contractor_id).where(ContractorWorksite.org_id == org_id, ContractorWorksite.worksite_id == site_id)).all()
    contractors = []
    for link, company in companies:
        requirements = []
        # Worker subjects are aggregated for legacy tables; the center keeps each subject.
        kinds = defaultdict(list)
        for row in grouped[link.id]:
            kinds[row["code"]].append(row)
        for kind, rows in kinds.items():
            row = next((r for r in rows if r["required"] and r["state"] != "approved"), rows[0])
            requirements.append({"kind": kind, "name": row["document"], "applicable": any(r["required"] for r in rows),
                                 "state": "approved" if all(r["state"] == "approved" for r in rows if r["required"]) and any(r["required"] for r in rows) else row["state"],
                                 "source": "document" if row["document_id"] else "manual_without_pdf" if row["reviewed_at"] else None,
                                 "document_id": row["document_id"], "reviewed_by": row["reviewed_by"], "reviewed_at": row["reviewed_at"],
                                 "notes": row["notes"], "request_date": period + "-01", "due_date": row["due_date"],
                                 "rule_source": row["rule_source"], "rule_id": row["rule_id"], "subjects": len(rows),
                                 "subject": row["subject"], "worker_level": row["subject"] != "contractor",
                                 "required_count": sum(r["required"] for r in rows),
                                 "approved_count": sum(r["required"] and r["state"] == "approved" for r in rows)})
        contractors.append({"association_id": link.id, "contractor_id": company.id, "name": company.name, "rut": company.rut,
                            "code": canonical_category(contractor_classification(link, company)), "historical_code": link.historical_code,
                            "nature": company.nature, "frequency": link.frequency, "status": link.contract_status,
                            "inactive_for_period": inactive_for_period(link, period), "requirements": requirements})
    counts = result["summary"]
    return {"period": period, "site_id": site_id, "contractors": contractors, "summary": {"applicable": counts["required"], "approved": counts["approved"], "reviewed": counts["reviewed"], "compliance": counts["compliance"], "progress": round(100 * counts["reviewed"] / counts["required"], 2) if counts["required"] else None, "delivery": counts["delivery"]}}


def rule_view(row, names=None):
    result = {key: getattr(row, key) for key in ("id", "document_type_id", "scope", "category", "site_id", "association_id", "required", "activation_from_period", "frequency", "period_start", "period_end", "due_day", "due_month_offset", "reason", "revision", "created_at")}
    result["created_by"] = (names or {}).get(row.created_by, "Responsable sin nombre registrado")
    return result


def preview_digest(org_id, user_id, payload, revision, targets, impact=()):
    value = json.dumps({"org_id": org_id, "user_id": user_id, "payload": payload, "revision": revision, "targets": sorted(targets), "impact": impact}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(settings().app_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def audit_rows(db, org_id, association_id=None, site_id=None, period=None, user_id=None, limit=100, offset=0):
    query = select(OpsChange).where(OpsChange.org_id == org_id, OpsChange.entity_type.in_(["configuration_rule", "configuration_catalog", "configuration_review", "configuration_alerts", "configuration_gate"]))
    if user_id:
        query = query.where(OpsChange.user_id == user_id)
    records = db.scalars(query.order_by(OpsChange.created_at.desc(), OpsChange.id.desc())).all()
    names = display_names(db, org_id)
    rows = []
    for record in records:
        data = record.changes
        if association_id and data.get("association_id") != association_id and association_id not in data.get("affected_association_ids", []):
            continue
        if site_id and data.get("site_id") != site_id and site_id not in data.get("affected_site_ids", []):
            continue
        if period and not (data.get("period") == period or (data.get("period_start", "9999-99") <= period <= (data.get("period_end") or "9999-99"))):
            continue
        rows.append({"id": record.id, "actor": names.get(record.user_id, "Responsable sin nombre registrado"), "user_id": record.user_id, "at": record.created_at,
                     "action": data.get("action", record.entity_type), "association_id": data.get("association_id"), "site_id": data.get("site_id"),
                     "period": data.get("period") or data.get("period_start"), "document": data.get("document"), "reason": data.get("reason", ""),
                     "before": data.get("before"), "after": data.get("after")})
    return {"rows": rows[offset:offset + limit], "total": len(rows)}


def refresh_confirmed_snapshots(db, org_id, association_ids, code, start, end=None):
    association_ids = sorted(set(association_ids))
    query = select(ConfigurationObligationSnapshot).where(ConfigurationObligationSnapshot.org_id == org_id,
        ConfigurationObligationSnapshot.association_id.in_(association_ids), ConfigurationObligationSnapshot.period >= start,
        ConfigurationObligationSnapshot.period < current_period())
    if end:
        query = query.where(ConfigurationObligationSnapshot.period <= end)
    periods = sorted({r.period for r in db.scalars(query)})
    for offset in range(0, len(periods), 60):
        evaluate(db, org_id, periods[offset:offset + 60], refresh_snapshot_codes={code}, refresh_association_ids=set(association_ids), persist_snapshots=True)
