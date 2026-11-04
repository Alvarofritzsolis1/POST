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
from .ops_api import audit_change, has_active_workers, normalize_rut
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
        "NATURALEZA",
        "FRECUENCIA",
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
        "CONTRATO",
        "TIPO",
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


def source_rows(content, filename, mapping):
    result = []
    for sheet, grid in _read_sheets(content, filename):
        if not grid:
            continue
        header_index = next(
            (i for i, row in enumerate(grid[:25]) if "rut" in [_key(v) for v in row]),
            None,
        )
        if header_index is None:
            raise ValueError(f"{sheet}: no se encontró encabezado RUT")
        headers = [_key(v) for v in grid[header_index]]
        columns = {}
        for field, aliases in ALIASES.items():
            wanted = _key(mapping[field]) if field in mapping else None
            matches = [
                i
                for i, heading in enumerate(headers)
                if heading and (heading == wanted if wanted else heading in aliases)
            ]
            if len(matches) > 1:
                raise ValueError(f"Encabezado ambiguo: {field}; indica el mapeo")
            if wanted and not matches:
                raise ValueError(f"Encabezado no encontrado: {mapping[field]}")
            if matches:
                columns[field] = matches[0]
        for i, raw in enumerate(grid[header_index + 1 :], header_index + 2):
            if any(raw):
                result.append(
                    {
                        "row_id": f"{sheet}:{i}",
                        **{
                            field: raw[col] if col < len(raw) else ""
                            for field, col in columns.items()
                        },
                    }
                )
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
            status = row.get("status", "")
            code = _key(row.get("historical_code"))
            if code and code not in {"ct", "ci"} and code not in class_map:
                errors.append("COD desconocido; configurar catálogo antes de importar")
            if status and _key(status) not in status_map:
                errors.append("Estado sin mapeo; configurar catálogo o corregir")
            classification = row.get("classification", "") or class_map.get(
                _key(row.get("historical_code")), ""
            )
            if classification and classification not in {"CT", "CI", "ESP"}:
                errors.append("Clasificación explícita debe ser CT, CI o ESP")
            nature = classified_value(row.get("nature", ""), NATURE_VALUES, "Naturaleza", errors)
            frequency = classified_value(row.get("frequency", ""), FREQUENCY_VALUES, "Frecuencia", errors)
            legacy_nature = {"CT": "with_workers", "CI": "independent"}.get(classification)
            if nature and legacy_nature and nature != legacy_nature:
                errors.append("Naturaleza contradice la clasificación explícita")
            nature = nature or legacy_nature
            if classification == "ESP":
                if frequency and frequency != "sporadic":
                    errors.append("Frecuencia contradice la clasificación ESP explícita")
                frequency = frequency or "sporadic"
            # CI denotes independent by definition; CT alone does not establish
            # whether people are employed, and neither code defines frequency.
            if code == "ci":
                if nature and nature != "independent":
                    errors.append("COD CI contradice la naturaleza indicada")
                nature = nature or "independent"
            if not nature and (not existing or existing.nature == "unclassified"):
                warnings.append("Naturaleza sin determinar; indicar NATURALEZA")
            if not frequency and (not link or link.frequency == "unclassified"):
                warnings.append("Frecuencia sin determinar; indicar FRECUENCIA")
            if row["name"].isdigit():
                errors.append("Nombre sospechoso: contiene únicamente números")
            if (
                existing
                and nature == "independent"
                and has_active_workers(db, user.org_id, existing.id)
            ):
                errors.append(
                    "Independiente con trabajadores activos; corregir primero las asignaciones"
                )
            target = {"name": row["name"]}
            if nature:
                target["nature"] = nature
            extra = {
                k: row[k]
                for k in (
                    "external_id",
                    "specialty",
                    "contact",
                    "phone",
                    "email",
                    "legal_representative",
                    "legal_representative_rut",
                )
                if row.get(k)
            }
            link_target = (
                {"historical_code": row["historical_code"]}
                if row.get("historical_code")
                else {}
            )
            if len(row.get("historical_code", "")) > 20:
                errors.append("COD supera 20 caracteres")
            if status and _key(status) in status_map:
                link_target["contract_status"] = status_map[_key(status)]
            if frequency:
                link_target["frequency"] = frequency
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
                for field, val in extra.items():
                    old = details.get(existing.id, {}).get(field)
                    if old != val:
                        changes[field] = {"from": old, "to": val}
                if link:
                    for field, val in link_target.items():
                        if getattr(link, field) != val:
                            changes[field] = {"from": getattr(link, field), "to": val}
            identity = (row["rut"], site.id if site else row.get("site"))
            general = {**target, **extra}
            if row["rut"] in identities and identities[row["rut"]] != general:
                errors.append(
                    "Mismo RUT con información general contradictoria en el archivo"
                )
            identities[row["rut"]] = general
            resolved = {"target": target, "extra": extra, "link_target": link_target}
        else:
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
            elif contractor.nature == "independent":
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
                    parse_date(row.get("end_date")),
                )
                row["start_date"], row["end_date"] = (
                    start.isoformat(),
                    end.isoformat() if end else "",
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
                row["contract_type"] = CONTRACT_TYPES.get(
                    _key(row.get("contract_type")), row.get("contract_type", "")
                )
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
                        if old != val:
                            changes[key] = {"from": old, "to": val}
            except ValueError as exc:
                errors.append(str(exc))
            kind = CONTRACT_TYPES.get(
                _key(row.get("contract_type")), row.get("contract_type", "")
            )
            row["contract_type"] = kind
            if kind not in {"fixed_term", "indefinite", "project", "services"}:
                errors.append(
                    "Tipo de contrato desconocido: indicar indefinido, por obra, plazo fijo o servicios"
                )
            if kind == "fixed_term" and not row.get("end_date"):
                errors.append("Contrato a plazo fijo requiere fecha término")
            if kind == "indefinite" and row.get("end_date"):
                errors.append(
                    "Un contrato indefinido no lleva término automático; registrar su baja expresamente"
                )
            if len(row.get("contract_type", "")) > 100:
                errors.append("Tipo de contrato supera 100 caracteres")
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
        rows = source_rows(data, file.filename or "", mapping)
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
                extra.values = {**(extra.values or {}), **item["extra"]}
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
                start, end = parse_date(r["start_date"]), parse_date(r.get("end_date"))
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
                link.active = any(
                    e.status == "active"
                    for e in all_episodes
                )
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
