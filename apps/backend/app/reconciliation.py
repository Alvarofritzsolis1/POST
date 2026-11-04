"""Auditable contractor classification recovery from recorded source values."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .bulk_import import FREQUENCY_VALUES, NATURE_VALUES, classified_value, digest
from .config import settings
from .db import get_db
from .models import Organization, User, utcnow
from .ops_api import audit_change, has_active_workers
from .ops_import import _key
from .ops_models import Contractor, ContractorWorksite, OpsChange, WorkerAssignment, Worksite
from .platform_models import BackupCheckpoint
from .security import administrator

router = APIRouter(prefix="/api/v1/admin/reconciliation", tags=["Reconciliación"])


class ManualCorrection(BaseModel):
    association_id: str
    nature: Literal["with_workers", "independent"] | None = None
    frequency: Literal["fixed", "sporadic"] | None = None
    contract_status: Literal["active", "suspended", "inactive"] | None = None


class ApplyReconciliation(BaseModel):
    token: str
    backup_id: str
    corrections: list[ManualCorrection] = Field(default_factory=list, max_length=10000)


def _direct(value, valid):
    if isinstance(value, dict):
        value = value.get("to")
    return value if value in valid else None


def _source_value(raw, field):
    if not isinstance(raw, dict):
        return None
    value = str(raw.get(field) or "").strip()
    if not value:
        return None
    values = NATURE_VALUES if field == "nature" else FREQUENCY_VALUES
    return classified_value(value, values, field, [])


def _events(db, org_id):
    rows = db.scalars(select(OpsChange).where(
        OpsChange.org_id == org_id,
        OpsChange.entity_type.in_(("contractor", "contractor_worksite", "contractors")),
    ).order_by(OpsChange.created_at, OpsChange.id)).all()
    by_entity = defaultdict(list)
    for event in rows:
        by_entity[(event.entity_type, event.entity_id)].append(event)
    return by_entity


def recovery_report(db: Session, org_id: str):
    companies = db.scalars(select(Contractor).where(Contractor.org_id == org_id)).all()
    links = db.scalars(select(ContractorWorksite).where(ContractorWorksite.org_id == org_id)).all()
    sites = {s.id: s.name for s in db.scalars(select(Worksite).where(Worksite.org_id == org_id))}
    history = _events(db, org_id)
    by_company = defaultdict(list)
    for link in links:
        by_company[link.contractor_id].append(link)
    rut_index = defaultdict(list)
    active_companies = set(db.scalars(select(WorkerAssignment.contractor_id).where(
        WorkerAssignment.org_id == org_id, WorkerAssignment.active.is_(True))).all())
    for company in companies:
        if company.rut:
            rut_index[re.sub(r"[^0-9kK]", "", company.rut).upper()].append(company.id)
    records = []
    for company in companies:
        company_events = history.get(("contractor", company.id), []) + history.get(("contractors", company.id), [])
        for link in by_company[company.id]:
            evidence = defaultdict(list)
            for event in company_events + history.get(("contractor_worksite", link.id), []):
                changes = event.changes or {}
                raw = changes.get("values")
                if raw and changes.get("relationship_id") not in {None, link.id}:
                    continue
                if raw and changes.get("relationship_id") is None and raw.get("site") and _key(raw["site"]) != _key(sites.get(link.worksite_id, "")):
                    continue
                for field in ("nature", "frequency"):
                    val = _source_value(raw, field)
                    if val:
                        evidence[field].append({"value": val, "event_id": event.id, "source": "import_row"})
                if isinstance(raw, dict) and raw.get("classification") in {"CT", "CI", "ESP"}:
                    legacy = raw["classification"]
                    field = "frequency" if legacy == "ESP" else "nature"
                    value = "sporadic" if legacy == "ESP" else "independent" if legacy == "CI" else "with_workers"
                    evidence[field].append({"value": value, "event_id": event.id, "source": "explicit_legacy_classification"})
                if isinstance(raw, dict) and _key(raw.get("historical_code")) == "ci":
                    evidence["nature"].append({"value": "independent", "event_id": event.id, "source": "code_ci"})
                for field, allowed in (("nature", {"with_workers", "independent"}),
                                       ("frequency", {"fixed", "sporadic"})):
                    val = _direct(changes.get(field), allowed)
                    if val:
                        evidence[field].append({"value": val, "event_id": event.id, "source": "explicit_change"})
            if _key(link.historical_code) == "ci":
                evidence["nature"].append({"value": "independent", "source": "stored_code_ci"})
            changes, conflicts, warnings = {}, [], []
            for field, current in (("nature", company.nature), ("frequency", link.frequency)):
                found = {v["value"] for v in evidence[field]}
                if len(found) > 1:
                    conflicts.append(f"{field}: fuentes históricas contradictorias")
                elif found:
                    value = next(iter(found))
                    if current == "unclassified":
                        changes[field] = {"from": current, "to": value}
                    elif current != value:
                        conflicts.append(f"{field}: valor actual contradice la evidencia")
                elif current == "unclassified":
                    warnings.append(f"{field}: sin evidencia verificable")
            if changes.get("nature", {}).get("to") == "independent" and company.id in active_companies:
                changes.pop("nature")
                conflicts.append("Independiente con trabajadores activos")
            if company.name.strip().isdigit() or not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", company.name):
                warnings.append("Nombre sospechoso; revisar identidad")
            if len(rut_index.get(re.sub(r"[^0-9kK]", "", company.rut or "").upper(), [])) > 1:
                conflicts.append("RUT duplicado dentro de la organización")
            category = "conflict" if conflicts else "recoverable" if changes else "unresolved" if warnings else "unchanged"
            records.append({
                "contractor_id": company.id, "association_id": link.id,
                "name": company.name, "rut": company.rut, "site": sites.get(link.worksite_id),
                "current": {"nature": company.nature, "frequency": link.frequency,
                            "historical_code": link.historical_code, "contract_status": link.contract_status},
                "category": category, "changes": changes, "evidence": dict(evidence),
                "conflicts": conflicts, "warnings": warnings,
            })
    # Include companies without a site as unresolved instead of silently omitting them.
    for company in companies:
        if not by_company[company.id]:
            records.append({"contractor_id": company.id, "association_id": None,
                            "name": company.name, "rut": company.rut, "site": None,
                            "category": "unresolved", "changes": {}, "evidence": {},
                            "conflicts": [], "warnings": ["Contratista sin relación con obra"]})
    counts = {key: sum(r["category"] == key for r in records)
              for key in ("recoverable", "unchanged", "unresolved", "conflict")}
    return {"records": records, "summary": counts, "state": digest(records)}


@router.get("/preview")
def preview(user: User = Depends(administrator), db: Session = Depends(get_db)):
    report = recovery_report(db, user.org_id)
    token = jwt.encode({"purpose": "contractor-reconciliation", "org": user.org_id,
                        "user": user.id, "state": report["state"],
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=30)},
                       settings().app_secret, algorithm="HS256")
    return {**report, "token": token}


@router.get("/backups")
def backups(user: User = Depends(administrator), db: Session = Depends(get_db)):
    rows = db.scalars(select(BackupCheckpoint).where(
        BackupCheckpoint.org_id == user.org_id,
    ).order_by(BackupCheckpoint.created_at.desc()).limit(10)).all()
    return [{"id": row.id, "sha256": row.sha256, "created_at": row.created_at} for row in rows]


@router.post("/commit")
def commit(body: ApplyReconciliation, user: User = Depends(administrator), db: Session = Depends(get_db)):
    try:
        claim = jwt.decode(body.token, settings().app_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(422, "Vista previa inválida o vencida") from None
    if any(claim.get(k) != v for k, v in {"purpose": "contractor-reconciliation",
                                          "org": user.org_id, "user": user.id}.items()):
        raise HTTPException(422, "Vista previa no corresponde a esta organización")
    backup = db.scalar(select(BackupCheckpoint).where(BackupCheckpoint.id == body.backup_id,
                                                      BackupCheckpoint.org_id == user.org_id))
    backup_time = backup.created_at if backup and backup.created_at.tzinfo else (
        backup.created_at.replace(tzinfo=timezone.utc) if backup else None)
    if not backup or backup_time < datetime.now(timezone.utc) - timedelta(hours=24):
        raise HTTPException(422, "Registra un respaldo verificable reciente antes de corregir datos")
    db.scalar(select(Organization).where(Organization.id == user.org_id).with_for_update())
    db.scalars(select(Contractor).where(Contractor.org_id == user.org_id).with_for_update()).all()
    db.scalars(select(ContractorWorksite).where(ContractorWorksite.org_id == user.org_id).with_for_update()).all()
    report = recovery_report(db, user.org_id)
    if report["state"] != claim.get("state"):
        raise HTTPException(409, "Los datos cambiaron; vuelve a previsualizar")
    by_link = {r["association_id"]: r for r in report["records"] if r["association_id"]}
    if len({c.association_id for c in body.corrections}) != len(body.corrections):
        raise HTTPException(422, "Corrección repetida")
    corrections = {c.association_id: c for c in body.corrections}
    if any(key not in by_link for key in corrections):
        raise HTTPException(404, "Relación de contratista no encontrada")
    updates = []
    for record in report["records"]:
        link_id = record["association_id"]
        if not link_id:
            continue
        manual = corrections.get(link_id)
        if record["category"] == "conflict" and not manual:
            continue
        fields = {k: v["to"] for k, v in record["changes"].items()} if record["category"] == "recoverable" else {}
        if manual:
            fields.update(manual.model_dump(exclude_none=True, exclude={"association_id"}))
        if fields:
            updates.append((record, fields, bool(manual)))
    # A contractor has one nature across every site. Reject contradictory manual decisions.
    proposed_natures = defaultdict(set)
    for record, fields, _ in updates:
        if "nature" in fields:
            proposed_natures[record["contractor_id"]].add(fields["nature"])
    if any(len(values) > 1 for values in proposed_natures.values()):
        raise HTTPException(422, "Naturaleza contradictoria entre obras de una misma empresa")
    changed = []
    for record, fields, manual in updates:
        company = db.get(Contractor, record["contractor_id"])
        link = db.get(ContractorWorksite, record["association_id"])
        if fields.get("nature") == "independent" and has_active_workers(db, user.org_id, company.id):
            raise HTTPException(422, "No se puede clasificar como independiente con trabajadores activos")
        before = {key: getattr(company if key == "nature" else link, key) for key in fields}
        for key, value in fields.items():
            setattr(company if key == "nature" else link, key, value)
        company.updated_at = link.updated_at = utcnow()
        audit_change(db, user, "contractor_reconciliation", link.id,
                     {"before": before, "after": fields, "manual": manual,
                      "backup_sha256": backup.sha256, "evidence": record["evidence"]})
        changed.append({"association_id": link.id, "before": before, "after": fields, "manual": manual})
    db.commit()
    return {"corrected": len(changed), "unchanged": report["summary"]["unchanged"],
            "unresolved": report["summary"]["unresolved"], "conflicts": report["summary"]["conflict"],
            "records": changed, "backup_sha256": backup.sha256}
