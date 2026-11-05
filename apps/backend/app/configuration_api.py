"""Administrator-only documentary configuration; all evidence is registered manually."""
from __future__ import annotations

import hmac
from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .configuration_models import ConfigurationDocumentType as DocumentType, ConfigurationRule as Rule, ConfigurationSettings, GateMovement, ConfigurationObligationSnapshot
from . import configuration_service as service
from .db import get_db
from .models import User, utcnow
from .network_service import lock_org
from .ops_api import association_for, audit_change, ensure_sites, normalize_rut, site_for
from .ops_models import AuditPeriod, Contractor, ContractorWorksite, MonthlyDocument, Worker, WorkerAssignment, Worksite
from .platform_models import DocumentReview
from .control_models import ContractRegister
from .security import administrator

router = APIRouter(prefix="/api/v1/admin/configuration", tags=["Configuración General"])
Frequency = Literal["monthly", "quarterly", "annual", "once", "on_event"]
State = Literal["approved", "submitted", "missing", "incomplete", "rejected", "overdue", "not_applicable", "exempt", "no_movements"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogInput(StrictModel):
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4000)
    category: str = Field(default="Personalizado", min_length=1, max_length=80)
    level: Literal["contractor", "worker", "contractor_site_period", "contractor_workers"] = "contractor"
    frequency: Frequency = "monthly"
    conditions: str = Field(default="", max_length=4000)

    @field_validator("name", "category")
    @classmethod
    def clean_text(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("El nombre no puede quedar vacío")
        return value


class RuleInput(StrictModel):
    document_type_id: str
    scope: Literal["general", "category", "site", "association", "exception"] = "general"
    category: Literal["CT", "CE", "CI", "ESP"] | None = None
    site_id: str | None = None
    association_ids: list[str] = Field(default_factory=list, max_length=2000)
    required: bool | None = True
    frequency: Frequency = "monthly"
    period_start: str
    period_end: str | None = None
    due_day: int | None = Field(default=None, ge=1, le=31)
    due_month_offset: Literal[0, 1] = 1
    reason: str = Field(min_length=3, max_length=4000)
    retroactive: bool = False

    @field_validator("period_start", "period_end")
    @classmethod
    def validate_period(cls, value):
        return service.validate_period(value) if value is not None else None

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Indica un motivo de al menos tres caracteres")
        return value.strip()

    @model_validator(mode="after")
    def valid_scope(self):
        if self.period_end and self.period_end < self.period_start:
            raise ValueError("El período final no puede ser anterior al inicial")
        if self.scope == "category" and not self.category:
            raise ValueError("Selecciona una categoría")
        if self.scope == "site" and not self.site_id:
            raise ValueError("Selecciona una obra")
        if self.scope in {"association", "exception"} and not self.association_ids:
            raise ValueError("Selecciona al menos un contratista")
        if len(set(self.association_ids)) != len(self.association_ids):
            raise ValueError("No se pueden repetir contratistas")
        if self.scope == "exception" and not self.period_end:
            raise ValueError("La excepción debe tener un período final")
        if self.period_start < service.current_period() and not self.retroactive:
            raise ValueError("Una corrección histórica requiere activar la opción retroactiva y revisar su impacto")
        return self


class RuleApplyInput(RuleInput):
    preview_token: str = Field(min_length=1, max_length=100)
    confirm: bool


class PorteriaStartInput(StrictModel):
    period_start: str
    reason: str = Field(min_length=3, max_length=4000)
    retroactive: bool = False

    @field_validator("period_start")
    @classmethod
    def valid_start(cls, value):
        return service.validate_period(value)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Justifica el cambio de período inicial")
        return value.strip()

    @model_validator(mode="after")
    def explicit_history(self):
        if self.period_start < service.current_period() and not self.retroactive:
            raise ValueError("Una activación anterior al mes actual requiere corrección retroactiva explícita")
        return self


class PorteriaStartApply(PorteriaStartInput):
    preview_token: str = Field(min_length=1, max_length=100)
    confirm: bool


class ReviewInput(StrictModel):
    association_id: str
    period: str
    document_type_id: str
    state: State
    notes: str = Field(default="", max_length=4000)
    subject: str = Field(default="contractor", max_length=36)

    @field_validator("period")
    @classmethod
    def valid_period(cls, value):
        return service.validate_period(value)

    @model_validator(mode="after")
    def reason_required(self):
        self.notes = self.notes.strip()
        if self.state in service.EXEMPT | {"incomplete", "rejected", "overdue"} and len(self.notes) < 3:
            raise ValueError("Registra una justificación verificable para este estado")
        return self


class AlertsInput(StrictModel):
    alert_days: int = Field(ge=0, le=365)
    repeated_periods: int = Field(ge=2, le=60)
    reason: str = Field(min_length=3, max_length=4000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Registra el motivo del cambio")
        return value.strip()


class GateInput(StrictModel):
    association_id: str
    period: str
    worker_name: str = Field(min_length=2, max_length=180)
    worker_rut: str | None = None
    movement_date: date
    notes: str = Field(min_length=3, max_length=4000)

    @field_validator("period")
    @classmethod
    def valid_period(cls, value):
        return service.validate_period(value)

    @field_validator("worker_rut")
    @classmethod
    def valid_rut(cls, value):
        return normalize_rut(value)

    @field_validator("worker_name", "notes")
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("Completa la identificación y respaldo del movimiento")
        return " ".join(value.split())

    @model_validator(mode="after")
    def matching_period(self):
        if self.movement_date.strftime("%Y-%m") != self.period:
            raise ValueError("La fecha de movimiento debe pertenecer al período indicado")
        if self.movement_date > service.today():
            raise ValueError("No se pueden registrar accesos futuros como evidencia")
        return self


def lock_admin(db, user):
    lock_org(db, user)
    db.refresh(user)
    if not user.enabled or user.role != "admin":
        raise HTTPException(403, "Los permisos cambiaron; esta acción requiere un administrador habilitado")
    return service.ensure_configuration(db, user.org_id)


def type_for(db, user, type_id):
    row = db.scalar(select(DocumentType).where(DocumentType.id == type_id, DocumentType.org_id == user.org_id))
    if row is None:
        raise HTTPException(404, "Tipo documental no encontrado")
    return row


@router.get("/bootstrap")
def bootstrap(user: User = Depends(administrator), db: Session = Depends(get_db)):
    # Persist the first-use activation month once, rather than deriving a moving date.
    config = lock_admin(db, user)
    db.commit()
    sites = ensure_sites(db, user.org_id)
    companies = db.execute(select(ContractorWorksite, Contractor, Worksite).join(Contractor, Contractor.id == ContractorWorksite.contractor_id).join(Worksite, Worksite.id == ContractorWorksite.worksite_id).where(ContractorWorksite.org_id == user.org_id, Contractor.org_id == user.org_id, Worksite.org_id == user.org_id).order_by(Contractor.name, Worksite.name)).all()
    periods = set(db.scalars(select(AuditPeriod.period).where(AuditPeriod.org_id == user.org_id)))
    periods.update(db.scalars(select(MonthlyDocument.period).where(MonthlyDocument.org_id == user.org_id)))
    rules = db.scalars(select(Rule).where(Rule.org_id == user.org_id)).all()
    periods.update(r.period_start for r in rules)
    periods.update(r.period_end for r in rules if r.period_end)
    periods.update([service.current_period(), config.porteria_start_period])
    return {"catalog": [service.catalog_view(r) for r in db.scalars(select(DocumentType).where(DocumentType.org_id == user.org_id).order_by(DocumentType.name))],
            "sites": [{"id": s.id, "name": s.name} for s in sites],
            "contractors": [service.association_view(*rows) for rows in companies], "periods": sorted(periods), "settings": {**service.settings_view(config), "porteria_start_period": next((r.period_start for r in sorted(rules, key=lambda row: row.revision, reverse=True) if r.scope == "activation"), config.porteria_start_period)}}


@router.post("/catalog", status_code=201)
def create_catalog(body: CatalogInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    config = lock_admin(db, user)
    key = service.normalized(body.name)
    if not key:
        raise HTTPException(422, "El nombre debe incluir letras o números")
    aliases = {service.normalized(code): service.normalized(name) for code, name, _, _ in service.DEFAULTS}
    key = aliases.get(key, key)
    if db.scalar(select(DocumentType.id).where(DocumentType.org_id == user.org_id, DocumentType.normalized_name == key)):
        raise HTTPException(409, "Ya existe un documento con ese nombre o formato equivalente")
    record = DocumentType(org_id=user.org_id, code="custom_" + uuid4().hex[:24], normalized_name=key, system=False, **body.model_dump())
    db.add(record)
    db.flush()
    config.version += 1
    audit_change(db, user, "configuration_catalog", record.id, {"action": "Documento agregado al catálogo", "document": record.name, "reason": "Alta administrativa de tipo documental", "before": None, "after": service.catalog_view(record)})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "El documento ya fue registrado por otro administrador") from None
    return service.catalog_view(record)


def validate_filters(db, user, site_id=None, association_id=None):
    if site_id:
        site_for(db, user.org_id, site_id)
    if association_id:
        link, _ = association_for(db, user.org_id, association_id)
        if site_id and link.worksite_id != site_id:
            raise HTTPException(422, "El contratista no pertenece a la obra indicada")


@router.get("/summary")
def summary(periods: str | None = None, site_id: str | None = None, category: Literal["CT", "CE", "CI", "ESP"] | None = None,
            q: str = Query(default="", max_length=180), state: str | None = None, association_id: str | None = None,
            user: User = Depends(administrator), db: Session = Depends(get_db)):
    validate_filters(db, user, site_id, association_id)
    selected = service.parse_periods(periods)
    lock_admin(db, user)
    result = service.evaluate(db, user.org_id, selected, site_id, category, q, state, association_id, persist_snapshots=True)
    db.commit()
    return result


@router.get("/contractors/{association_id}")
def contractor(association_id: str, periods: str | None = None, user: User = Depends(administrator), db: Session = Depends(get_db)):
    link, company = association_for(db, user.org_id, association_id)
    selected = service.parse_periods(periods)
    lock_admin(db, user)
    result = service.evaluate(db, user.org_id, selected, association_id=association_id, persist_snapshots=True)
    site = site_for(db, user.org_id, link.worksite_id)
    result["contractor"] = service.association_view(link, company, site)
    workers = db.execute(select(WorkerAssignment, Worker).join(Worker, Worker.id == WorkerAssignment.worker_id).where(WorkerAssignment.org_id == user.org_id, Worker.org_id == user.org_id, WorkerAssignment.contractor_id == company.id, WorkerAssignment.worksite_id == site.id)).all()
    contracts = db.scalars(select(ContractRegister).where(ContractRegister.org_id == user.org_id, ContractRegister.association_id == association_id)).all()
    result["workers"] = [{"id": a.id, "name": w.name, "rut": w.rut, "active": a.active, "contracts": [{"id": c.id, "contract_type": c.contract_type, "start_date": c.start_date, "end_date": c.end_date, "status": c.status} for c in contracts if c.worker_assignment_id == a.id]} for a, w in workers]
    names = service.display_names(db, user.org_id)
    result["rules"] = [service.rule_view(r, names) for r in db.scalars(select(Rule).where(Rule.org_id == user.org_id).order_by(Rule.revision.desc())) if r.scope == "general" or r.scope == "category" and r.category == result["contractor"]["category"] or r.scope == "site" and r.site_id == site.id or r.association_id == association_id]
    result["audit"] = service.audit_rows(db, user.org_id, association_id=association_id)["rows"]
    result["gate_movements"] = [gate_view(r, names) for r in db.scalars(select(GateMovement).where(GateMovement.org_id == user.org_id, GateMovement.association_id == association_id, GateMovement.period.in_(selected)).order_by(GateMovement.movement_date.desc()))]
    db.commit()
    return result


def rule_targets(db, user, body):
    document = type_for(db, user, body.document_type_id)
    if body.category:
        body.category = service.canonical_category(body.category)
    # Validate all supplied IDs, including fields not selected by the scope.
    if body.site_id:
        site_for(db, user.org_id, body.site_id)
    for association_id in body.association_ids:
        association_for(db, user.org_id, association_id)
    if document.code == "porteria":
        if body.required is False and body.scope != "exception":
            raise HTTPException(422, "Portería es obligatoria para CT, CE y CI; utiliza una excepción individual temporal justificada")
        if body.frequency != "monthly":
            raise HTTPException(422, "El Informe de Portería mantiene frecuencia mensual")
    query = select(ContractorWorksite, Contractor).join(Contractor, Contractor.id == ContractorWorksite.contractor_id).where(ContractorWorksite.org_id == user.org_id, Contractor.org_id == user.org_id)
    if body.scope == "site":
        query = query.where(ContractorWorksite.worksite_id == body.site_id)
    if body.scope in {"association", "exception"}:
        query = query.where(ContractorWorksite.id.in_(body.association_ids))
    historical_targets = set()
    if body.scope == "category" and body.retroactive:
        snapshots = db.scalars(select(ConfigurationObligationSnapshot).where(
            ConfigurationObligationSnapshot.org_id == user.org_id,
            ConfigurationObligationSnapshot.period >= body.period_start,
            ConfigurationObligationSnapshot.period <= (body.period_end or "2099-12")))
        historical_targets = {r.association_id for r in snapshots if r.payload.get("category") == body.category}
    targets = [(link, company) for link, company in db.execute(query) if body.scope != "category" or service.canonical_category(service.contractor_classification(link, company)) == body.category or link.id in historical_targets]
    return document, targets


def prepared_rules(db, user, body, config):
    document, targets = rule_targets(db, user, body)
    base = body.model_dump(exclude={"association_ids", "retroactive", "preview_token", "confirm"})
    base.update(org_id=user.org_id, created_by=user.id, revision=config.version + 1)
    base["category"] = service.canonical_category(base["category"]) if base["category"] else None
    rules = [Rule(id=str(uuid4()), association_id=association_id, **base) for association_id in body.association_ids] if body.scope in {"association", "exception"} else [Rule(id=str(uuid4()), **base)]
    return document, targets, rules


def preview_for(db, user, body, config):
    document, targets, rules = prepared_rules(db, user, body, config)
    end = body.period_end or service.add_months(body.period_start, 11)
    count = service.period_number(end) - service.period_number(body.period_start) + 1
    selected = [service.add_months(body.period_start, number) for number in range(min(60, count))]
    before = service.evaluate(db, user.org_id, selected, persist_snapshots=True)
    after = service.evaluate(db, user.org_id, selected, extra_rules=rules)
    target_ids = {link.id for link, _ in targets}
    previous = {(r["association_id"], r["period"], r["subject"]): r for r in before["obligations"] if r["document_type_id"] == document.id and r["association_id"] in target_ids}
    changes = []
    info = {r["association_id"]: r for r in after["contractors"]}
    for row in after["obligations"]:
        if row["association_id"] not in target_ids or row["document_type_id"] != document.id:
            continue
        old = previous.get((row["association_id"], row["period"], row["subject"]))
        changes.append({"association_id": row["association_id"], "name": row["contractor"], "site": row["site"], "period": row["period"], "subject": row["subject"], "from_required": old["required"] if old else False, "to_required": row["required"]})
    payload = body.model_dump(exclude={"preview_token", "confirm"})
    token = service.preview_digest(user.org_id, user.id, payload, config.version, target_ids, sorted(changes, key=lambda row: (row["association_id"], row["period"], row["subject"])))
    conflicts = [service.rule_view(r) for r in db.scalars(select(Rule).where(Rule.org_id == user.org_id, Rule.document_type_id == document.id, Rule.scope == body.scope, Rule.period_start <= end)) if (not r.period_end or r.period_end >= body.period_start) and (body.scope == "general" or body.scope == "category" and r.category == body.category or body.scope == "site" and r.site_id == body.site_id or r.association_id in body.association_ids)]
    return {"preview_token": token, "affected": len(target_ids), "conflicts": conflicts,
            "changes": changes, "historical": body.period_start < service.current_period(),
            "periods_previewed": selected, "continues_after_preview": count > 60 or body.period_end is None}, rules, targets, document


@router.post("/rules/preview")
def preview(body: RuleInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    config = lock_admin(db, user)
    result, _, _, _ = preview_for(db, user, body, config)
    db.commit()  # only lazy catalog initialization, never applies the proposed rule
    return result


@router.post("/rules/apply")
def apply_rules(body: RuleApplyInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    if not body.confirm:
        raise HTTPException(422, "Confirma expresamente los cambios después de revisar la vista previa")
    config = lock_admin(db, user)
    result, rules, targets, document = preview_for(db, user, body, config)
    if not hmac.compare_digest(result["preview_token"], body.preview_token):
        raise HTTPException(409, "La configuración, los destinatarios o la propuesta cambiaron; genera una nueva vista previa")
    config.version += 1
    for rule in rules:
        db.add(rule)
        db.flush()
        affected = [link for link, _ in targets if not rule.association_id or link.id == rule.association_id]
        audit_change(db, user, "configuration_rule", rule.id, {"action": "Exigencia documental configurada", "association_id": rule.association_id,
            "site_id": rule.site_id or (affected[0].worksite_id if rule.association_id and affected else None), "affected_association_ids": [a.id for a in affected],
            "affected_site_ids": sorted({a.worksite_id for a in affected}), "period_start": rule.period_start, "period_end": rule.period_end,
            "document": document.name, "reason": rule.reason, "before": jsonable_encoder(result["conflicts"]), "after": jsonable_encoder(service.rule_view(rule, service.display_names(db, user.org_id)))})
    service.refresh_confirmed_snapshots(db, user.org_id, [link.id for link, _ in targets], document.code, body.period_start, body.period_end)
    db.commit()
    return {"created": len(rules), "version": config.version}


def porteria_start_preview(db, user, body, config):
    document = db.scalar(select(DocumentType).where(DocumentType.org_id == user.org_id, DocumentType.code == "porteria"))
    effective_from = min(service.current_period(), body.period_start) if body.retroactive else service.current_period()
    candidate = Rule(id=str(uuid4()), org_id=user.org_id, document_type_id=document.id, scope="activation", required=True,
                     frequency="monthly", activation_from_period=effective_from, period_start=body.period_start,
                     period_end=None, due_day=None, due_month_offset=1, reason=body.reason,
                     revision=config.version + 1, created_by=user.id)
    end = max(service.add_months(service.current_period(), 11), body.period_start)
    span = service.period_number(end) - service.period_number(effective_from) + 1
    if span > 60:
        raise HTTPException(422, "El cambio de inicio debe caber en una vista previa de hasta sesenta meses")
    periods = [service.add_months(effective_from, n) for n in range(span)]
    before = service.evaluate(db, user.org_id, periods, persist_snapshots=True)
    after = service.evaluate(db, user.org_id, periods, extra_rules=[candidate])
    previous = {(r["association_id"], r["period"]): r for r in before["obligations"] if r["code"] == "porteria"}
    changes = [{"association_id": r["association_id"], "name": r["contractor"], "site": r["site"], "period": r["period"],
                "from_required": previous[(r["association_id"], r["period"])]["required"], "to_required": r["required"]}
               for r in after["obligations"] if r["code"] == "porteria"]
    targets = {r["association_id"] for r in changes}
    token = service.preview_digest(user.org_id, user.id, body.model_dump(exclude={"confirm", "preview_token"}), config.version,
                                   targets, sorted(changes, key=lambda row: (row["association_id"], row["period"])))
    return {"preview_token": token, "affected": len(targets), "changes": changes, "conflicts": [],
            "historical": effective_from < service.current_period(), "effective_from_period": effective_from,
            "periods_previewed": periods, "continues_after_preview": True}, candidate


@router.post("/porteria-start/preview")
def preview_porteria_start(body: PorteriaStartInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    config = lock_admin(db, user)
    result, _ = porteria_start_preview(db, user, body, config)
    db.commit()
    return result


@router.post("/porteria-start/apply")
def apply_porteria_start(body: PorteriaStartApply, user: User = Depends(administrator), db: Session = Depends(get_db)):
    if not body.confirm:
        raise HTTPException(422, "Confirma el cambio de inicio después de revisar su impacto")
    config = lock_admin(db, user)
    result, rule = porteria_start_preview(db, user, body, config)
    if not hmac.compare_digest(result["preview_token"], body.preview_token):
        raise HTTPException(409, "El impacto cambió; genera una nueva vista previa")
    prior = db.scalar(select(Rule).where(Rule.org_id == user.org_id, Rule.scope == "activation").order_by(Rule.revision.desc()).limit(1))
    db.add(rule)
    db.flush()
    config.version += 1
    audit_change(db, user, "configuration_rule", rule.id, {"action": "Período inicial de Portería configurado", "document": "Informe de Portería",
        "period_start": rule.activation_from_period, "reason": body.reason,
        "affected_association_ids": sorted({r["association_id"] for r in result["changes"]}),
        "before": {"porteria_start_period": prior.period_start if prior else config.porteria_start_period},
        "after": {"porteria_start_period": rule.period_start, "effective_from_period": rule.activation_from_period}})
    service.refresh_confirmed_snapshots(db, user.org_id, [r["association_id"] for r in result["changes"]], "porteria", rule.activation_from_period)
    db.commit()
    return {"created": 1, "version": config.version, "porteria_start_period": rule.period_start}


def save_review_record(db, user, association_id, period, kind, state, notes, subject="contractor"):
    """Shared write path for legacy review endpoints; caller owns commit."""
    config = lock_admin(db, user)
    link, company = association_for(db, user.org_id, association_id)
    db.scalar(select(ContractorWorksite).where(ContractorWorksite.id == link.id, ContractorWorksite.org_id == user.org_id).with_for_update())
    document_type = db.scalar(select(DocumentType).where(DocumentType.org_id == user.org_id, DocumentType.code == kind))
    if document_type is None:
        raise HTTPException(404, "Tipo documental no encontrado")
    state = {"observed": "incomplete"}.get(state, state)
    if state not in service.EXEMPT | service.DELIVERED | {"missing", "overdue", "pending"}:
        raise HTTPException(422, "Estado documental inválido")
    if state in service.EXEMPT | {"incomplete", "rejected", "overdue"} and len(notes.strip()) < 3:
        raise HTTPException(422, "El estado requiere una justificación verificable")
    if kind == "cotizaciones" and state == "approved":
        from .control_models import ContributionControl
        from .platform_models import PaymentFinding
        controls = db.scalars(select(ContributionControl).where(ContributionControl.org_id == user.org_id, ContributionControl.association_id == association_id, ContributionControl.period == period)).all()
        control_ids = [r.id for r in controls]
        findings = {r.control_id: r for r in db.scalars(select(PaymentFinding).where(PaymentFinding.org_id == user.org_id, PaymentFinding.control_id.in_(control_ids)))} if control_ids else {}
        for control in controls:
            if subject != "contractor" and control.subject_key != subject:
                continue
            required_days = control.attendance_days if control.attendance_days is not None else control.required_days
            finding = findings.get(control.id)
            if (control.payment_confirmed and required_days is not None and control.paid_days is not None and required_days > control.paid_days and not control.justification.strip()) or (finding and finding.state == "insufficient"):
                raise HTTPException(422, "Cotizaciones incompletas: regulariza o justifica la diferencia registrada antes de aprobar")
    if document_type.level == "worker":
        assignment = db.scalar(select(WorkerAssignment).where(WorkerAssignment.id == subject, WorkerAssignment.org_id == user.org_id, WorkerAssignment.contractor_id == company.id, WorkerAssignment.worksite_id == link.worksite_id))
        if assignment is None:
            raise HTTPException(422, "Selecciona un trabajador asociado a este contratista y obra")
    elif subject != "contractor":
        raise HTTPException(422, "Este documento se revisa a nivel de contratista")
    effective = service.legacy_requirements(db, user.org_id, link, company, period).get(kind)
    if effective and not effective["applicable"] and state not in service.EXEMPT:
        raise HTTPException(422, "El documento no es exigible para este contratista y período; configura su regla primero")
    if subject == "contractor":
        record = db.scalar(select(MonthlyDocument).where(MonthlyDocument.org_id == user.org_id, MonthlyDocument.association_id == association_id, MonthlyDocument.period == period, MonthlyDocument.kind == kind).order_by(MonthlyDocument.updated_at.desc(), MonthlyDocument.id.desc()).limit(1))
        if record is None:
            record = MonthlyDocument(org_id=user.org_id, association_id=link.id, contractor_id=company.id, period=period, kind=kind, created_by=user.id, document_id=None, review_status="pending", notes="")
            db.add(record)
            db.flush()
        if record.document_id and state == "missing":
            raise HTTPException(422, "Existe documentación entregada para este requisito; registra pendiente, incompleto o rechazado sin perder el original")
        old = {"state": record.review_status, "notes": record.notes}
        record.review_status, record.notes = state, notes.strip()
        record.updated_at = utcnow()
    else:
        record = db.scalar(select(DocumentReview).where(DocumentReview.org_id == user.org_id, DocumentReview.association_id == association_id, DocumentReview.period == period, DocumentReview.requirement.in_([kind] + {"contrato_trabajo": ["Contrato"], "anexos_contrato": ["Anexo"], "finiquito": ["Finiquito"]}.get(kind, [])), DocumentReview.subject == subject).order_by(DocumentReview.reviewed_at.desc(), DocumentReview.id.desc()).limit(1))
        if record is None:
            record = DocumentReview(org_id=user.org_id, association_id=association_id, period=period, requirement=kind, subject=subject, reviewed_by=user.id)
            db.add(record)
            db.flush()
        old = {"state": record.state, "notes": record.observation}
        record.state, record.observation = state, notes.strip()
    record.reviewed_by, record.reviewed_at = user.id, utcnow()
    config.version += 1
    audit_change(db, user, "configuration_review", record.id, {"action": "Revisión documental registrada", "association_id": association_id,
        "site_id": link.worksite_id, "period": period, "document": document_type.name, "reason": notes.strip(), "subject": subject,
        "before": old, "after": {"state": state, "notes": notes.strip(), "source": "manual_without_upload"}})
    return record


@router.put("/reviews")
def review(body: ReviewInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    service.validate_period(body.period)
    type_record = type_for(db, user, body.document_type_id)
    record = save_review_record(db, user, body.association_id, body.period, type_record.code, body.state, body.notes, body.subject)
    db.commit()
    return {"id": record.id, "state": body.state, "reviewed_by": service.display_names(db, user.org_id).get(user.id), "reviewed_at": record.reviewed_at}


@router.put("/alerts")
def alerts(body: AlertsInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    config = lock_admin(db, user)
    old = service.settings_view(config)
    config.alert_days, config.repeated_periods = body.alert_days, body.repeated_periods
    config.version += 1
    audit_change(db, user, "configuration_alerts", user.org_id, {"action": "Umbrales de alertas actualizados", "reason": body.reason, "before": old, "after": service.settings_view(config)})
    db.commit()
    return service.settings_view(config)


@router.get("/audit")
def audit(association_id: str | None = None, site_id: str | None = None, period: str | None = None,
          user_id: str | None = None, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
          user: User = Depends(administrator), db: Session = Depends(get_db)):
    validate_filters(db, user, site_id, association_id)
    if period:
        service.validate_period(period)
    if user_id and not db.scalar(select(User.id).where(User.org_id == user.org_id, User.id == user_id)):
        raise HTTPException(404, "Responsable no encontrado")
    return service.audit_rows(db, user.org_id, association_id, site_id, period, user_id, limit, offset)


def gate_view(row, names):
    return {"id": row.id, "association_id": row.association_id, "period": row.period, "worker_name": row.worker_name,
            "worker_rut": row.worker_rut, "movement_date": row.movement_date, "notes": row.notes,
            "created_by": names.get(row.created_by, "Responsable sin nombre registrado"), "created_at": row.created_at}


@router.get("/gate-movements")
def gate_movements(association_id: str, period: str | None = None, user: User = Depends(administrator), db: Session = Depends(get_db)):
    association_for(db, user.org_id, association_id)
    if period:
        service.validate_period(period)
    query = select(GateMovement).where(GateMovement.org_id == user.org_id, GateMovement.association_id == association_id)
    if period:
        query = query.where(GateMovement.period == period)
    names = service.display_names(db, user.org_id)
    return [gate_view(r, names) for r in db.scalars(query.order_by(GateMovement.movement_date.desc()))]


@router.post("/gate-movements", status_code=201)
def create_gate_movement(body: GateInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    config = lock_admin(db, user)
    link, _ = association_for(db, user.org_id, body.association_id)
    worker_key = body.worker_rut or service.normalized(body.worker_name)
    duplicate = db.scalar(select(GateMovement.id).where(GateMovement.org_id == user.org_id, GateMovement.association_id == link.id, GateMovement.period == body.period, GateMovement.worker_key == worker_key, GateMovement.movement_date == body.movement_date.isoformat()))
    if duplicate:
        raise HTTPException(409, "El movimiento de esta persona y fecha ya fue registrado")
    record = GateMovement(org_id=user.org_id, association_id=link.id, period=body.period, worker_key=worker_key,
                          worker_name=body.worker_name, worker_rut=body.worker_rut, movement_date=body.movement_date.isoformat(), notes=body.notes, created_by=user.id)
    db.add(record)
    db.flush()
    config.version += 1
    audit_change(db, user, "configuration_gate", record.id, {"action": "Movimiento de portería transcrito manualmente", "association_id": link.id,
        "site_id": link.worksite_id, "period": body.period, "document": "Informe de Portería", "reason": body.notes, "before": None,
        "after": jsonable_encoder(gate_view(record, service.display_names(db, user.org_id)))})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "El movimiento ya fue registrado por otro administrador") from None
    return gate_view(record, service.display_names(db, user.org_id))
