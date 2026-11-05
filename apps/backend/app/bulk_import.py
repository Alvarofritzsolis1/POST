"""Specialized flows extend the existing import center and bounded XLSX reader."""

import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
import jwt
from fastapi import Depends, File, Form, HTTPException, Response, UploadFile
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import Organization, User
from .ops_api import audit_change, contractor_classification, normalize_rut
from .ops_import import MAX_IMPORT_BYTES, _key, _read_sheets
from .ops_import_api import router
from .ops_models import (
    Contractor,
    ContractorWorksite,
    Worker,
    WorkerAssignment,
    Worksite,
)
from .platform_models import ContractorDetails, ImportBatch
from .admin_api import catalogs_for
from .control_models import ContractRegister
from .control_api import today as chile_today
from .contract_import import CONTRACT_TYPES, date_from_cell
from .security import authorized_user, editor

# Exact headers confirmed by the user; blank columns preserve their positions.
HEADERS = {
    "contractors": [
        "ID",
        "OBRA",
        "ESPECIALIDAD",
        "NOMBRECONTRATISTA",
        "RUT",
        "COD",
        "ESTADO",
        "TELEFONO",
        "CORREO",
        "REPRESENTANTE LEGAL",
        "RUTR.LEGAL",
    ],
    "workers": [
        "NOMBRE CONTRATISTA",
        "NOMBRE TRABAJADOR",
        "RUT",
        "F.INGRESO",
        "F.TERMINO",
        "COD",
    ],
}
ALIASES = {
    "site": ["obra", "nombre obra"],
    "name": ["nombre", "razon social", "nombre trabajador", "nombrecontratista"],
    "rut": ["rut", "rut trabajador"],
    "contractor_name": ["contratista", "empresa", "nombre contratista"],
    "contractor_rut": ["rut contratista"],
    "external_id": ["id"],
    "historical_code": ["cod", "codigo"],
    "nature": ["naturaleza", "tipo contratista", "naturaleza contratista"],
    "frequency": ["frecuencia", "periodicidad"],
    "status": ["estado"],
    "specialty": ["especialidad"],
    "contact": ["contacto"],
    "phone": ["telefono"],
    "email": ["correo", "email"],
    "legal_representative": ["representante legal"],
    "start_date": ["fecha ingreso", "fecha de ingreso", "f ingreso"],
    "end_date": ["fecha termino", "fecha de termino", "f termino"],
    "contract_type": ["tipo contrato", "tipo de contrato", "tipo"],
    "classification": ["clasificacion explicita"],
    "legal_representative_rut": ["rutr legal"],
    "contract_reference": ["contrato"],
    "worker_code": ["cod"],
}

NATURE_VALUES = {
    "con trabajadores": "with_workers", "contratista con trabajadores": "with_workers",
    "with workers": "with_workers", "dependiente": "with_workers",
    "independiente": "independent", "contratista independiente": "independent",
    "independiente sin trabajadores": "independent", "sin trabajadores": "independent",
    "independent": "independent", "with workers": "with_workers",
}
FREQUENCY_VALUES = {
    "fijo": "fixed", "fija": "fixed", "fixed": "fixed",
    "esporadico": "sporadic", "esporadica": "sporadic", "sporadic": "sporadic",
}


def classified_value(raw: str, values: dict[str, str], label: str, errors: list[str]):
    if not raw:
        return None
    resolved = values.get(_key(raw))
    if resolved is None:
        errors.append(f"{label} desconocida: {raw[:50]}")
    return resolved


class ReviewImport(BaseModel):
    kind: Literal["contractors", "workers"]
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=10000)
    filename: str = Field(default="correcciones.xlsx", max_length=240)
    file_sha256: str = Field(default="", max_length=64)


class ApplyImport(ReviewImport):
    token: str
    approve_updates: bool = False


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def parse_date(value, required=False):
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError("Falta fecha de ingreso")
        return None
    parsed = date_from_cell(text)
    if parsed:
        return parsed
    raise ValueError(f"Fecha inválida: {text}; utiliza dd/mm/aaaa")


def worker_end_date(value):
    """INDEFINIDO is explicit; an empty end-date is not an indefinite contract."""
    if _key(value) == "indefinido":
        return None
    if not str(value or "").strip():
        raise ValueError("F.TERMINO obligatorio: usa INDEFINIDO o fecha DD-MM-AAAA")
    return parse_date(value)


def source_rows(content, filename, mapping, kind="workers"):
    result = []
    for sheet, grid in _read_sheets(content, filename):
        if not grid:
            continue
        if kind == "contractors":
            # v10.9: the contractor spreadsheet has exactly eleven source columns.
            expected = [_key(label) for label in HEADERS["contractors"]]
            header_index = next(
                (i for i, row in enumerate(grid[:25])
                 if [_key(cell) for cell in row[:6]] == expected
             and not any(_key(cell) for cell in row[6:])),
                None,
            )
            if header_index is None:
                raise ValueError(
                    f"{sheet}: encabezados incorrectos; utiliza exclusivamente las 11 columnas "
                    + ", ".join(HEADERS["contractors"])
                )
            fields = (
                "external_id", "site", "specialty", "name", "rut",
                "historical_code", "status", "phone", "email",
                "legal_representative", "legal_representative_rut",
            )
            for i, raw in enumerate(grid[header_index + 1:], header_index + 2):
                if any(raw):
                    if any(str(value).strip() for value in raw[len(fields):]):
                        raise ValueError(f"{sheet}:{i}: datos fuera de las 11 columnas")
                    result.append({
                        "row_id": f"{sheet}:{i}",
                        **{field: raw[pos] if pos < len(raw) else ""
                           for pos, field in enumerate(fields)},
                    })
            continue
        # Workers: one unambiguous six-column layout; the worksite is selected in UI.
        expected = [_key(label) for label in HEADERS["workers"]]
        header_index = next(
            (i for i, row in enumerate(grid[:25])
             if [_key(cell) for cell in row if _key(cell)] == expected),
            None,
        )
        if header_index is None:
            raise ValueError(
                f"{sheet}: encabezados incorrectos; usa exactamente estas seis columnas: "
                + ", ".join(HEADERS["workers"])
            )
        fields = ("contractor_name", "name", "rut", "start_date", "end_date", "worker_code")
        for i, raw in enumerate(grid[header_index + 1:], header_index + 2):
            if any(raw):
                if any(str(value).strip() for value in raw[len(fields):]):
                    raise ValueError(f"{sheet}:{i}: datos fuera de las seis columnas")
                result.append({
                    "row_id": f"{sheet}:{i}",
                    **{field: raw[pos] if pos < len(raw) else ""
                       for pos, field in enumerate(fields)},
                })
    if not 1 <= len(result) <= 10000:
        raise ValueError("La carga debe contener entre 1 y 10000 filas")
    return result


def columns_of(record):
    return (
        {c.name: getattr(record, c.name) for c in record.__table__.columns}
        if record
        else None
    )


def prepare(body, user, db):
    sites = list(db.scalars(select(Worksite).where(Worksite.org_id == user.org_id)))
    companies = list(
        db.scalars(select(Contractor).where(Contractor.org_id == user.org_id))
    )
    by_rut = {c.rut: c for c in companies if c.rut}
    links = {
        (l.worksite_id, l.contractor_id): l
        for l in db.scalars(
            select(ContractorWorksite).where(ContractorWorksite.org_id == user.org_id)
        )
    }
    workers = {
        w.rut: w
        for w in db.scalars(select(Worker).where(Worker.org_id == user.org_id))
        if w.rut
    }
    assignments = {
        (a.worksite_id, a.contractor_id, a.worker_id): a
        for a in db.scalars(
            select(WorkerAssignment).where(WorkerAssignment.org_id == user.org_id)
        )
    }
    details = {
        r.contractor_id: r.values
        for r in db.scalars(
            select(ContractorDetails).where(
                ContractorDetails.contractor_id.in_([c.id for c in companies])
            )
        )
    }
    episodes = {
        (e.worker_assignment_id, e.start_date): e
        for e in db.scalars(
            select(ContractRegister).where(ContractRegister.org_id == user.org_id)
        )
    }
    catalogs = catalogs_for(db, user.org_id)
    status_map = {_key(k): v for k, v in catalogs["status_mapping"].items()}
    class_map = {_key(k): v for k, v in catalogs["classification_mapping"].items()}
    result, seen, identities, snapshot, incoming_episodes = [], set(), {}, [], {}
    for index, original in enumerate(body.rows):
        row = {
            k: str(v if v is not None else "").strip()
            for k, v in original.items()
            if k in ALIASES or k == "row_id"
        }
        row["row_id"] = row.get("row_id") or str(index + 1)
        errors, warnings, changes = [], [], {}
        existing, link, employment = None, None, None
        matches = [s for s in sites if _key(s.name) == _key(row.get("site"))]
        site = matches[0] if len(matches) == 1 else None
        if site is None:
            errors.append(
                "Obra no identificada; un administrador debe crearla o corregir el nombre"
            )
        try:
            row["rut"] = normalize_rut(row.get("rut")) or ""
            if not row["rut"]:
                errors.append("Falta RUT")
        except ValueError:
            errors.append("RUT inválido o dígito verificador incorrecto")
        row["name"] = " ".join(row.get("name", "").split())
        if not 1 <= len(row["name"]) <= 180:
            errors.append("Nombre incompleto o superior a 180 caracteres")
        if any(len(v) > 500 for v in row.values()):
            errors.append("Un campo supera 500 caracteres")
        if body.kind == "contractors":
            existing = by_rut.get(row["rut"])
            link = links.get((site.id, existing.id)) if site and existing else None
            code = row.get("historical_code", "").strip().upper()
            status = row.get("status", "").strip().upper()
            row["historical_code"], row["status"] = code, status
            if code not in {"CT", "CE", "CI"}:
                errors.append("COD inválido: solo se permite CT, CE o CI")
            if status not in {"ACTIVO", "INACTIVO"}:
                errors.append("ESTADO inválido: solo se permite ACTIVO o INACTIVO")
            if row["name"].isdigit():
                errors.append("Nombre sospechoso: contiene únicamente números")
            if code == "CI" and site and existing:
                active_here = db.scalar(
                    select(WorkerAssignment.id).where(
                        WorkerAssignment.org_id == user.org_id,
                        WorkerAssignment.contractor_id == existing.id,
                        WorkerAssignment.worksite_id == site.id,
                        WorkerAssignment.active.is_(True),
                    ).limit(1)
                )
                if active_here:
                    errors.append(
                        "CI tiene trabajadores activos en esta obra; revisar sus asignaciones antes de cambiar COD"
                    )
            # Contractor identity is global by RUT. Classification is per obra.
            target = {"name": row["name"]}
            expected_nature = "independent" if code == "CI" else "with_workers"
            associated_sites = (
                [entry for entry in links.values() if existing and entry.contractor_id == existing.id]
                if existing else []
            )
            # Keep a legacy nature hint only where a single site makes it unambiguous.
            if code in {"CT", "CE", "CI"} and (
                (not existing and row["rut"] not in identities)
                or (existing and (not associated_sites or
                    (len(associated_sites) == 1 and site and associated_sites[0].worksite_id == site.id)))
            ):
                target["nature"] = expected_nature
            extra = {
                k: row[k]
                for k in (
                    "phone", "email", "legal_representative",
                    "legal_representative_rut",
                )
                if row.get(k)
            }
            scoped_extra = {
                k: row[k]
                for k in ("external_id", "specialty")
                if row.get(k)
            }
            link_target = {}
            if code in {"CT", "CE", "CI"}:
                link_target["historical_code"] = code
                if code in {"CT", "CE"}:
                    link_target["frequency"] = "fixed" if code == "CT" else "sporadic"
            if status in {"ACTIVO", "INACTIVO"}:
                link_target["contract_status"] = (
                    "active" if status == "ACTIVO" else "inactive"
                )
            if extra.get("legal_representative_rut"):
                try:
                    extra["legal_representative_rut"] = normalize_rut(
                        extra["legal_representative_rut"]
                    )
                except ValueError:
                    errors.append("RUT representante legal inválido")
            if existing:
                for field, val in target.items():
                    if getattr(existing, field) != val:
                        changes[field] = {"from": getattr(existing, field), "to": val}
                old_details = details.get(existing.id, {}) or {}
                for field, val in extra.items():
                    if old_details.get(field) != val:
                        changes[field] = {"from": old_details.get(field), "to": val}
                old_site_extra = (
                    (old_details.get("worksites") or {}).get(site.id, {})
                    if site else {}
                )
                for field, val in scoped_extra.items():
                    old = old_site_extra.get(field)
                    if old != val:
                        changes[f"obra.{field}"] = {"from": old, "to": val}
                if link:
                    for field, val in link_target.items():
                        if getattr(link, field) != val:
                            changes[field] = {"from": getattr(link, field), "to": val}
            identity = (row["rut"], site.id if site else row.get("site"))
            general = {"name": row["name"], **extra}
            if row["rut"] in identities and identities[row["rut"]] != general:
                errors.append(
                    "Mismo RUT con información general contradictoria en el archivo"
                )
            identities[row["rut"]] = general
            resolved = {
                "target": target, "extra": extra,
                "scoped_extra": scoped_extra, "link_target": link_target,
            }
        else:
            row["worker_code"] = row.get("worker_code", "").strip().upper()
            if row["worker_code"] not in {"TH", "TM", "F"}:
                errors.append("COD de trabajador inválido: utiliza TH, TM o F")
            matches = [
                c
                for c in companies
                if site
                and (site.id, c.id) in links
                and _key(c.name) == _key(row.get("contractor_name"))
            ]
            if row.get("contractor_rut"):
                try:
                    rut = normalize_rut(row["contractor_rut"])
                    matches = [
                        c
                        for c in companies
                        if c.rut == rut and site and (site.id, c.id) in links
                    ]
                except ValueError:
                    matches = []
            contractor = matches[0] if len(matches) == 1 else None
            if not contractor:
                errors.append(
                    "Contratista no identificado o ambiguo; indica su RUT o corrige nombre y obra"
                )
            elif contractor_classification(links[(site.id, contractor.id)], contractor) == "CI":
                errors.append("Un independiente no admite trabajadores dependientes")
            existing = workers.get(row["rut"])
            link = (
                assignments.get((site.id, contractor.id, existing.id))
                if site and contractor and existing
                else None
            )
            try:
                start, end = (
                    parse_date(row.get("start_date"), True),
                    worker_end_date(row.get("end_date")),
                )
                row["start_date"], row["end_date"] = (
                    start.isoformat(),
                    end.isoformat() if end else "INDEFINIDO",
                )
                if end and end < start:
                    errors.append("Fecha término anterior al ingreso")
                employment = episodes.get((link.id, start)) if link else None
                if link and not employment:
                    for (assignment_id, old_start), old in episodes.items():
                        if (
                            assignment_id == link.id
                            and (old.end_date is None or old.end_date >= start)
                            and (end is None or end >= old_start)
                        ):
                            errors.append(
                                "Período laboral superpuesto; revisar fechas históricas"
                            )
                # Excel contains no legal modality: keep an existing reviewed type.
                # New rows use a provisional date-derived type, never an OCR approval.
                row["contract_type"] = (employment.contract_type if employment else
                                        CONTRACT_TYPES.get(_key(row.get("contract_type")),
                                        row.get("contract_type")) if row.get("contract_type") else
                                        ("fixed_term" if end else "indefinite"))
                if not employment and end:
                    warnings.append("Modalidad provisional por fecha; verifica el contrato firmado")
                episode_key = (
                    row["rut"],
                    site.id if site else "",
                    contractor.id if contractor else "",
                )
                for other_start, other_end in incoming_episodes.get(episode_key, []):
                    if (other_end is None or other_end >= start) and (
                        end is None or end >= other_start
                    ):
                        errors.append(
                            "Fechas laborales duplicadas o superpuestas dentro del archivo"
                        )
                incoming_episodes.setdefault(episode_key, []).append((start, end))
                if employment:
                    for key, val in {
                        "end_date": row["end_date"],
                        "contract_type": row.get("contract_type", ""),
                    }.items():
                        old = getattr(employment, key)
                        old = old.isoformat() if isinstance(old, date) else old or ""
                        comparison = "" if key == "end_date" and val == "INDEFINIDO" else val
                        if old != comparison:
                            changes[key] = {"from": old, "to": val}
            except ValueError as exc:
                errors.append(str(exc))
            kind = row.get("contract_type", "")
            row["contract_type"] = kind
            if kind not in {"fixed_term", "indefinite", "project", "services"}:
                errors.append(
                    "Tipo de contrato desconocido: indicar indefinido, por obra, plazo fijo o servicios"
                )
            if kind == "fixed_term" and not row.get("end_date"):
                errors.append("Contrato a plazo fijo requiere fecha término")
            if kind == "indefinite" and row.get("end_date") != "INDEFINIDO" and row.get("end_date"):
                errors.append(
                    "Un contrato indefinido no lleva término automático; registrar su baja expresamente"
                )
            if len(row.get("contract_type", "")) > 100:
                errors.append("Tipo de contrato supera 100 caracteres")
            old_code = (link.imported_statuses or {}).get("worker_code", "") if link else ""
            if link and old_code != row["worker_code"]:
                changes["worker_code"] = {"from": old_code, "to": row["worker_code"]}
            if link and row["worker_code"] == "F" and link.active:
                changes["active"] = {"from": True, "to": False}
            if existing and existing.name != row["name"]:
                changes["name"] = {"from": existing.name, "to": row["name"]}
            identity = (
                row["rut"],
                site.id if site else "",
                contractor.id if contractor else "",
                row.get("start_date"),
            )
            if row["rut"] in identities and identities[row["rut"]] != row["name"]:
                errors.append("Mismo RUT con nombres contradictorios")
            identities[row["rut"]] = row["name"]
            resolved = {"contractor_id": contractor.id if contractor else None}
        if identity in seen:
            errors.append("Fila duplicada para la misma relación; conservar una sola")
        seen.add(identity)
        snapshot.append(
            [
                columns_of(existing),
                columns_of(link),
                columns_of(employment),
                details.get(existing.id) if existing else None,
            ]
        )
        category = (
            "error"
            if errors
            else "updatable"
            if changes
            else "existing"
            if link and (body.kind == "contractors" or employment)
            else "new"
        )
        result.append(
            {
                "row": row,
                "category": category,
                "errors": errors,
                "warnings": warnings,
                "changes": changes,
                "site_id": site.id if site else None,
                "existing_id": existing.id if existing else None,
                **resolved,
            }
        )
    return result, digest(
        [
            snapshot,
            catalogs,
            [columns_of(s) for s in sites],
            [columns_of(c) for c in companies],
            [columns_of(a) for a in assignments.values()],
            [columns_of(e) for e in episodes.values()],
        ]
    )


def reviewed(body, user, db):
    prepared, state = prepare(body, user, db)
    token = jwt.encode(
        {
            "purpose": "specialized-import",
            "org": user.org_id,
            "user": user.id,
            "digest": digest(body.model_dump()),
            "state": state,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        },
        settings().app_secret,
        algorithm="HS256",
    )
    return {
        "rows": prepared,
        "token": token,
        "input": body.model_dump(),
        "summary": {
            key: sum(r["category"] == key for r in prepared)
            for key in ("new", "existing", "updatable", "error")
        },
    }


def safe_cell(value):
    return (
        "'" + value
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@"))
        else value
    )


def workbook_response(wb, name="galant.xlsx"):
    stream = io.BytesIO()
    wb.save(stream)
    return Response(
        stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/bulk/templates/{kind}")
def template(kind: str, user: User = Depends(authorized_user)):
    if kind not in HEADERS:
        raise HTTPException(404, "Plantilla no encontrada")
    wb = Workbook()
    wb.active.append(HEADERS[kind])
    return workbook_response(wb, f"galant-{kind}.xlsx")


@router.get("/bulk/history")
def import_history(page: int = 1, user: User = Depends(authorized_user),
                   db: Session = Depends(get_db)):
    if page < 1:
        raise HTTPException(422, "Página inválida")
    rows = db.scalars(select(ImportBatch).where(ImportBatch.org_id == user.org_id)
                      .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
                      .limit(50).offset((page - 1) * 50)).all()
    return [{"id": r.id, "filename": r.filename, "sha256": r.sha256,
             "kind": r.kind, "result": r.result, "created_at": r.created_at}
            for r in rows]


@router.post("/bulk/preview")
async def preview(
    file: UploadFile = File(...),
    kind: Literal["contractors", "workers"] = Form(...),
    column_map: str = Form("{}"),
    default_site: str = Form(""),
    user: User = Depends(editor),
    db: Session = Depends(get_db),
):
    try:
        data = await file.read(MAX_IMPORT_BYTES + 1)
        mapping = json.loads(column_map)
        if not isinstance(mapping, dict) or any(
            k not in ALIASES or not isinstance(v, str) for k, v in mapping.items()
        ):
            raise ValueError("Mapeo de columnas inválido")
        if mapping:
            raise ValueError("La carga masiva usa encabezados fijos; no requiere mapeo")
        if kind == "workers" and not default_site:
            raise ValueError("Selecciona una obra antes de importar trabajadores")
        rows = source_rows(data, file.filename or "", mapping, kind)
        if default_site:
            from .ops_api import site_for

            selected = site_for(db, user.org_id, default_site)
            for row in rows:
                if not row.get("site"):
                    row["site"] = selected.name
        body = ReviewImport(
            kind=kind,
            rows=rows,
            filename=(file.filename or "archivo.xlsx")[:240],
            file_sha256=hashlib.sha256(data).hexdigest(),
        )
        return reviewed(body, user, db)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        await file.close()


@router.post("/bulk/review")
def review(
    body: ReviewImport, user: User = Depends(editor), db: Session = Depends(get_db)
):
    return reviewed(body, user, db)


@router.post("/bulk/observations")
def observations(
    body: ReviewImport, user: User = Depends(editor), db: Session = Depends(get_db)
):
    rows, _ = prepare(body, user, db)
    wb = Workbook()
    fields = ["row_id", *ALIASES]
    wb.active.append([*fields, "Resultado", "Observaciones", "Cambios"])
    for r in rows:
        values = [r["row"].get(k, "") for k in fields] + [
            r["category"],
            "; ".join(r["errors"] + r["warnings"]),
            json.dumps(r["changes"], ensure_ascii=False),
        ]
        wb.active.append([safe_cell(v) for v in values])
    return workbook_response(wb, "observaciones.xlsx")


@router.post("/bulk/commit")
def commit(
    body: ApplyImport, user: User = Depends(editor), db: Session = Depends(get_db)
):
    clean = ReviewImport.model_validate(body.model_dump())
    try:
        attestation = jwt.decode(
            body.token, settings().app_secret, algorithms=["HS256"]
        )
    except jwt.PyJWTError:
        raise HTTPException(422, "Vista previa inválida o vencida") from None
    if any(
        attestation.get(k) != v
        for k, v in {
            "purpose": "specialized-import",
            "org": user.org_id,
            "user": user.id,
            "digest": digest(clean.model_dump()),
        }.items()
    ):
        raise HTTPException(
            422, "Los datos cambiaron; revisa de nuevo antes de confirmar"
        )
    db.scalar(
        select(Organization).where(Organization.id == user.org_id).with_for_update()
    )
    prepared, state = prepare(clean, user, db)
    if state != attestation.get("state"):
        raise HTTPException(
            409, "Otro usuario modificó los registros; vuelve a revisar los cambios"
        )
    if any(r["errors"] for r in prepared):
        raise HTTPException(422, "Corrige todas las observaciones antes de importar")
    if any(r["changes"] for r in prepared) and not body.approve_updates:
        raise HTTPException(
            422, "Debes aprobar explícitamente los campos que cambiarán"
        )
    if body.file_sha256 and all(r["category"] == "existing" for r in prepared):
        prior = db.scalar(select(ImportBatch).where(
            ImportBatch.org_id == user.org_id, ImportBatch.kind == body.kind,
            ImportBatch.sha256 == body.file_sha256,
        ).order_by(ImportBatch.created_at.desc()).limit(1))
        if prior:
            return {"batch_id": prior.id, "new": 0, "existing": len(prepared),
                    "updatable": 0, "duplicate": True}
    counters = {key: 0 for key in ("new", "existing", "updatable")}
    try:
        for item in prepared:
            r = item["row"]
            if body.kind == "contractors":
                obj = db.scalar(
                    select(Contractor).where(
                        Contractor.org_id == user.org_id, Contractor.rut == r["rut"]
                    )
                )
                if obj is None:
                    obj = Contractor(org_id=user.org_id, rut=r["rut"], **item["target"])
                    db.add(obj)
                    db.flush()
                else:
                    for k, v in item["target"].items():
                        setattr(obj, k, v)
                extra = db.get(ContractorDetails, obj.id)
                if extra is None:
                    extra = ContractorDetails(contractor_id=obj.id, values={})
                    db.add(extra)
                values = {**(extra.values or {}), **item["extra"]}
                if item["scoped_extra"]:
                    scopes = dict(values.get("worksites") or {})
                    scope = dict(scopes.get(item["site_id"]) or {})
                    scope.update(item["scoped_extra"])
                    scopes[item["site_id"]] = scope
                    values["worksites"] = scopes
                extra.values = values
                link = db.scalar(
                    select(ContractorWorksite).where(
                        ContractorWorksite.org_id == user.org_id,
                        ContractorWorksite.contractor_id == obj.id,
                        ContractorWorksite.worksite_id == item["site_id"],
                    )
                )
                if link is None:
                    link = ContractorWorksite(
                        org_id=user.org_id,
                        worksite_id=item["site_id"],
                        contractor_id=obj.id,
                    )
                    db.add(link)
                for k, v in item["link_target"].items():
                    setattr(link, k, v)
            else:
                obj = db.scalar(
                    select(Worker).where(
                        Worker.org_id == user.org_id, Worker.rut == r["rut"]
                    )
                )
                if obj is None:
                    obj = Worker(org_id=user.org_id, rut=r["rut"], name=r["name"])
                    db.add(obj)
                    db.flush()
                obj.name = r["name"]
                link = db.scalar(
                    select(WorkerAssignment).where(
                        WorkerAssignment.org_id == user.org_id,
                        WorkerAssignment.worker_id == obj.id,
                        WorkerAssignment.contractor_id == item["contractor_id"],
                        WorkerAssignment.worksite_id == item["site_id"],
                    )
                )
                if link is None:
                    link = WorkerAssignment(
                        org_id=user.org_id,
                        worker_id=obj.id,
                        contractor_id=item["contractor_id"],
                        worksite_id=item["site_id"],
                    )
                    db.add(link)
                    db.flush()
                start, end = parse_date(r["start_date"]), worker_end_date(r.get("end_date"))
                episode = db.scalar(
                    select(ContractRegister).where(
                        ContractRegister.worker_assignment_id == link.id,
                        ContractRegister.start_date == start,
                    )
                )
                if episode is None:
                    association = db.scalar(
                        select(ContractorWorksite).where(
                            ContractorWorksite.org_id == user.org_id,
                            ContractorWorksite.worksite_id == item["site_id"],
                            ContractorWorksite.contractor_id == item["contractor_id"],
                        )
                    )
                    episode = ContractRegister(
                        org_id=user.org_id,
                        association_id=association.id,
                        worker_assignment_id=link.id,
                        start_date=start,
                        created_by=user.id,
                        updated_by=user.id,
                    )
                    db.add(episode)
                episode.end_date, episode.contract_type = (
                    end,
                    r.get("contract_type", ""),
                )
                if not episode.notes:
                    episode.notes = "Contrato importado: " + r.get(
                        "contract_reference", ""
                    )
                if item["category"] != "existing":
                    episode.updated_by = user.id
                    # A planned end date is not proof of an effective termination.
                    if episode.status != "ended":
                        episode.status = "active"
                db.flush()
                all_episodes = db.scalars(
                    select(ContractRegister).where(
                        ContractRegister.worker_assignment_id == link.id
                    )
                ).all()
                # COD F is an operational inactive flag, not proof of a signed finiquito.
                statuses = dict(link.imported_statuses or {})
                statuses["worker_code"] = r["worker_code"]
                link.imported_statuses = statuses
                link.active = (r["worker_code"] != "F" and any(
                    e.status == "active" for e in all_episodes
                ))
            db.flush()
            if item["category"] != "existing":
                audit_change(
                    db,
                    user,
                    body.kind,
                    obj.id,
                    {
                        "imported": True,
                        "filename": body.filename,
                        "row_id": r["row_id"],
                        "changes": item["changes"],
                        "relationship_id": link.id,
                        "values": r,
                    },
                )
            counters[item["category"]] += 1
        batch = ImportBatch(
            org_id=user.org_id,
            user_id=user.id,
            filename=body.filename,
            sha256=body.file_sha256,
            kind=body.kind,
            result=counters,
        )
        db.add(batch)
        db.commit()
        return {"batch_id": batch.id, **counters}
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "Conflicto concurrente; vuelve a previsualizar. No se importaron filas"
        ) from None
    except Exception:
        db.rollback()
        raise
