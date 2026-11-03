"""Weighted management dashboard and CT/CI reports using verified manual records."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .control_admin import list_alerts, list_contracts, list_tasks
from .control_api import list_contributions, monthly_matrix, validated_period, today
from .control_models import MonthlyActivity, OffboardingCase
from .db import get_db
from .models import User
from .ops_api import site_for
from .ops_models import Contractor, ContractorWorksite, Worksite, WorkerAssignment
from .security import authorized_user

router = APIRouter(prefix="/api/v1/control/reports", tags=["Informes operativos"])


def site_rows(db: Session, user: User, site_id: str | None):
    if site_id:
        site_for(db, user.org_id, site_id)
    query = select(Worksite).where(Worksite.org_id == user.org_id)
    if site_id:
        query = query.where(Worksite.id == site_id)
    return db.scalars(query.order_by(Worksite.name)).all()


@router.get("/overview")
def overview(period: str, site_id: str | None = None,
             user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    validated_period(period)
    sites = site_rows(db, user, site_id)
    summaries = []
    unique_companies = set()
    unique_workers = set()
    totals = {"ct": 0, "ci": 0, "sporadic": 0, "active": 0,
              "workers": 0, "without_movements": 0, "offboarding_open": 0}
    total_applicable = total_approved = total_reviewed = 0
    for site in sites:
        result = monthly_matrix(site.id, period, user, db)
        ids = [row["association_id"] for row in result["contractors"]]
        for item in result["contractors"]:
            unique_companies.add(item["contractor_id"])
            if item["code"] == "CT":
                totals["ct"] += 1
            if item["code"] == "CI":
                totals["ci"] += 1
            if item["frequency"] == "sporadic":
                totals["sporadic"] += 1
            if item["status"] == "active":
                totals["active"] += 1
        workers = 0
        if ids:
            worker_ids = db.scalars(select(WorkerAssignment.worker_id).where(
                WorkerAssignment.org_id == user.org_id,
                WorkerAssignment.worksite_id == site.id,
                WorkerAssignment.active.is_(True))).all()
            workers = len(worker_ids)
            unique_workers.update(worker_ids)
            movements = db.scalar(select(func.count(MonthlyActivity.id)).where(
                MonthlyActivity.org_id == user.org_id,
                MonthlyActivity.association_id.in_(ids),
                MonthlyActivity.period == period,
                MonthlyActivity.status == "no_movements")) or 0
            totals["without_movements"] += movements
        totals["workers"] += workers
        numbers = result["summary"]
        total_applicable += numbers["applicable"]
        total_approved += numbers["approved"]
        total_reviewed += numbers["reviewed"]
        summaries.append({"site_id": site.id, "site": site.name,
                          "contractors": len(result["contractors"]),
                          "workers": workers, **numbers})
    totals["workers"] = len(unique_workers)
    totals["unique_companies"] = len(unique_companies)
    totals["associations"] = sum(s["contractors"] for s in summaries)
    contributions = list_contributions(period, site_id, user, db)
    totals["unverified_payments"] = sum(not c["payment_confirmed"] for c in contributions)
    totals["days_missing"] = sum(c["missing_days"] or 0 for c in contributions)
    totals["retention_proposed"] = str(sum(
        (Decimal(c["retention_suggested"]) for c in contributions
         if c["missing_days"] and c["retention_suggested"] is not None), Decimal("0.00")))
    active_contracts = list_contracts(site_id=site_id, user=user, db=db)
    totals["expiring_contracts"] = sum(bool(c["expiry_alert"]) for c in active_contracts)
    tasks = list_tasks(site_id=site_id, status="open", user=user, db=db)
    totals["open_tasks"] = len(tasks)
    query = select(func.count(OffboardingCase.id)).join(
        ContractorWorksite, ContractorWorksite.id == OffboardingCase.association_id).where(
        OffboardingCase.org_id == user.org_id, ContractorWorksite.org_id == user.org_id,
        OffboardingCase.status == "open")
    if site_id:
        query = query.where(ContractorWorksite.worksite_id == site_id)
    totals["offboarding_open"] = db.scalar(query) or 0
    return {"period": period, "site_id": site_id, "sites": summaries,
            "totals": totals, "applicable": total_applicable,
            "approved": total_approved, "reviewed": total_reviewed,
            "compliance": round(100 * total_approved / total_applicable, 1) if total_applicable else None,
            "progress": round(100 * total_reviewed / total_applicable, 1) if total_applicable else None}


def format_book(book: Workbook, filename: str):
    for sheet in book.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="172D4E")
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(wrap_text=True)
        for column in sheet.columns:
            cells = list(column)
            max_size = min(42, max(12, max(len(str(c.value or "")) for c in cells) + 3))
            sheet.column_dimensions[cells[0].column_letter].width = max_size
    stream = BytesIO()
    book.save(stream)
    return Response(content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "Cache-Control": "no-store"})


@router.get("/cotizaciones.xlsx")
def cotizaciones_excel(period: str, site_id: str | None = None,
                       user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    validated_period(period)
    sites = site_rows(db, user, site_id)
    entries = list_contributions(period, site_id, user, db)
    by_association: dict[str, list[dict]] = {}
    for entry in entries:
        by_association.setdefault(entry["association_id"], []).append(entry)
    wb = Workbook()
    sh = wb.active
    sh.title = "Cotizaciones CT y CI"
    sh.append(["Obra", "Contratista", "RUT", "Código", "Período", "Trabajador",
               "Asistencia", "Días exigibles", "Días pagados", "Días faltantes",
               "Retención sugerida CLP", "Pago confirmado manualmente", "Estado de revisión",
               "Retención", "Justificación", "Observaciones", "Responsable"])
    total_missing = 0
    total_retention = Decimal("0.00")
    for site in sites:
        rows = db.execute(select(ContractorWorksite, Contractor).join(
            Contractor, Contractor.id == ContractorWorksite.contractor_id).where(
            ContractorWorksite.org_id == user.org_id,
            Contractor.org_id == user.org_id,
            ContractorWorksite.worksite_id == site.id,
            ContractorWorksite.historical_code.in_(("CT", "CI")),
        ).order_by(Contractor.name)).all()
        for link, company in rows:
            current = by_association.get(link.id, [])
            if not current:
                sh.append([site.name, company.name, company.rut, link.historical_code,
                           period, "Sin registros", None, None, None, None, None,
                           "Sin verificar", "Sin evaluar"])
                continue
            for row in current:
                total_missing += row["missing_days"] or 0
                proposal = (Decimal(row["retention_suggested"])
                            if row["retention_suggested"] is not None else None)
                total_retention += proposal or Decimal("0.00")
                sh.append([site.name, company.name, company.rut, link.historical_code,
                           period, row["worker"] or "Independiente",
                           row["attendance_days"], row["required_days"], row["paid_days"],
                           row["missing_days"], float(proposal) if proposal is not None else None,
                           "Sí (registro manual)" if row["payment_confirmed"] else "Pendiente",
                           row["review_status"], row["retention_status"],
                           row["justification"], row["notes"], row["reviewer_id"]])
    summary = wb.create_sheet("Resumen")
    summary.append(["Métrica", "Valor"])
    summary.append(["Período", period])
    summary.append(["Total días faltantes CT (sin compensaciones)", total_missing])
    summary.append(["Retenciones sugeridas totales CLP", float(total_retention)])
    summary.append(["Importante", "Propuestas administrativas; no se aplican automáticamente"])
    return format_book(wb, f"GALANT_COTIZACIONES_CT_CI_{period}.xlsx")


@router.get("/mensual.xlsx")
def monthly_excel(period: str, site_id: str | None = None,
                  user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    validated_period(period)
    wb = Workbook()
    sh = wb.active
    sh.title = "Matriz mensual"
    sh.append(["Obra", "Mes", "Contratista", "RUT", "Código", "Frecuencia",
               "Requisito", "Aplicable", "Estado", "Origen", "Observaciones",
               "Inicio de solicitud", "Vencimiento", "Revisor"])
    sites = site_rows(db, user, site_id)
    for site in sites:
        matrix = monthly_matrix(site.id, period, user, db)
        for contractor in matrix["contractors"]:
            for item in contractor["requirements"]:
                sh.append([site.name, period, contractor["name"], contractor["rut"],
                           contractor["code"], contractor["frequency"], item["kind"],
                           "Por confirmar" if item["applicable"] is None else
                           "Sí" if item["applicable"] else "No",
                           item["state"], item["source"], item["notes"],
                           item["request_date"], item["due_date"], item["reviewed_by"]])
    return format_book(wb, f"GALANT_MATRIZ_MENSUAL_{period}.xlsx")


def month_shift(period: str, offset: int) -> str:
    year, month = (int(x) for x in period.split("-"))
    index = year * 12 + month - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@router.get("/trends")
def monthly_trends(
    period: str, months: int = 12, site_id: str | None = None,
    user: User = Depends(authorized_user), db: Session = Depends(get_db),
):
    """Series reales; meses sin evaluaciones se representan como null, nunca 100%."""
    validated_period(period)
    if not 1 <= months <= 24:
        from fastapi import HTTPException
        raise HTTPException(422, "Selecciona entre 1 y 24 meses")
    sites = site_rows(db, user, site_id)
    periods = [month_shift(period, offset) for offset in range(1 - months, 1)]
    series = []
    for target in periods:
        per_site = []
        applicable = approved = reviewed = 0
        for site in sites:
            matrix = monthly_matrix(site.id, target, user, db)
            metrics = matrix["summary"]
            per_site.append({
                "site_id": site.id, "site": site.name,
                "applicable": metrics["applicable"],
                "approved": metrics["approved"],
                "reviewed": metrics["reviewed"],
                "compliance": metrics["compliance"],
                "progress": metrics["progress"],
                "pending": max(0, metrics["applicable"] - metrics["approved"]),
            })
            applicable += metrics["applicable"]
            approved += metrics["approved"]
            reviewed += metrics["reviewed"]
        contribs = list_contributions(target, site_id, user, db)
        suggested = sum(
            (Decimal(item["retention_suggested"]) for item in contribs
             if item["retention_suggested"] is not None), Decimal("0"))
        series.append({
            "period": target, "site_summaries": per_site,
            "applicable": applicable, "approved": approved, "reviewed": reviewed,
            "pending": max(0, applicable - approved),
            "compliance": round(100 * approved / applicable, 1) if applicable else None,
            "progress": round(100 * reviewed / applicable, 1) if applicable else None,
            "retention_suggested": str(suggested),
            "missing_days": sum(item["missing_days"] or 0 for item in contribs),
            "unverified_payments": sum(not item["payment_confirmed"] for item in contribs),
        })
    return {"until": period, "months": months, "sites": [
        {"id": s.id, "name": s.name} for s in sites], "series": series}


@router.get("/analytics")
def analytics(
    period: str, site_id: str | None = None,
    user: User = Depends(authorized_user), db: Session = Depends(get_db)
):
    """Datos auditables para diagramas de gestión por obra; sin estimaciones."""
    validated_period(period)
    worksites = site_rows(db, user, site_id)
    summaries = []
    distribution = {"ct": 0, "ci": 0, "other": 0, "sporadic": 0}
    states = {status: 0 for status in (
        "approved", "pending", "observed", "rejected", "overdue",
        "not_yet_required", "needs_classification", "schedule_not_configured", "not_applicable"
    )}
    expiry = {key: 0 for key in ("expired", "7_days", "15_days", "30_days", "not_due", "no_end_date")}
    for site in worksites:
        matrix = monthly_matrix(site.id, period, user, db)
        contributions = list_contributions(period, site.id, user, db)
        contracts = list_contracts(site.id, user, db)
        site_states = dict.fromkeys(states, 0)
        site_dist = dict.fromkeys(distribution, 0)
        site_expiry = dict.fromkeys(expiry, 0)
        for company in matrix["contractors"]:
            code = company["code"].lower() if company["code"] in ("CT", "CI") else "other"
            site_dist[code] += 1
            if company["frequency"] == "sporadic":
                site_dist["sporadic"] += 1
            for req in company["requirements"]:
                status = req["state"]
                site_states[status] = site_states.get(status, 0) + 1
        for contract in contracts:
            if contract["expiry_alert"]:
                site_expiry[contract["expiry_alert"]] += 1
            elif contract["end_date"] is None:
                site_expiry["no_end_date"] += 1
            else:
                site_expiry["not_due"] += 1
        for key, value in site_dist.items():
            distribution[key] += value
        for key, value in site_states.items():
            states[key] += value
        for key, value in site_expiry.items():
            expiry[key] += value
        summaries.append({
            "site_id": site.id, "site": site.name,
            "distribution": site_dist, "document_states": site_states,
            "contract_expiry": site_expiry,
            "missing_days": sum(c["missing_days"] or 0 for c in contributions),
            "retention_suggested": str(sum(
                (Decimal(c["retention_suggested"]) for c in contributions
                 if c["retention_suggested"] is not None), Decimal("0"))),
            "unverified_payments": sum(not c["payment_confirmed"] for c in contributions),
            "open_tasks": len(list_tasks(site.id, status="open", user=user, db=db)),
        })
    return {
        "period": period, "worksites": summaries,
        "distribution": distribution, "document_states": states,
        "contract_expiry": expiry,
        "missing_days": sum(row["missing_days"] for row in summaries),
        "retention_suggested": str(sum(
            (Decimal(row["retention_suggested"]) for row in summaries), Decimal("0"))),
    }
