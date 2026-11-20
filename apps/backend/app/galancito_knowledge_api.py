"""Administrative teaching and explicitly submitted corrections; no weight training."""
from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path
from statistics import mean, median
from typing import Annotated, Literal
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import fitz
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .db import get_db
from .config import settings
from .models import User, utcnow
from .security import administrator, authorized_user
from .galancito_knowledge import search_value
from .galancito_knowledge_models import Knowledge, KnowledgeVersion, AssistantRun
from .galancito_triage import private_data, plain

router = APIRouter(prefix="/api/v1/network/galancito", tags=["Galancito conocimientos"])
Phrase = Annotated[str, StringConstraints(min_length=2, max_length=180)]


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=180)
    category: str = Field(default="General", min_length=2, max_length=80)
    kind: Literal["faq", "procedure", "trade", "example", "correction", "avoid", "handoff"] = "faq"
    scope: Literal["red_obras", "messenger", "both"] = "red_obras"
    content: str = Field(min_length=2, max_length=24000)
    phrases: list[Phrase] = Field(default_factory=list, max_length=20)

    @field_validator("title", "category", "content")
    @classmethod
    def clean(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Escribe contenido, no solo espacios")
        if private_data(value):
            raise ValueError("Elimina datos personales, claves y tokens del conocimiento")
        return value

    @field_validator("phrases")
    @classmethod
    def clean_phrases(cls, values):
        if any(private_data(v) or len(v.strip()) < 2 for v in values):
            raise ValueError("Las frases deben tener contenido sin datos privados")
        return [v.strip() for v in values]


class KnowledgeEdit(KnowledgeInput):
    version: int = Field(ge=1)


class StateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    state: Literal["approved", "disabled", "pending"]


def view(row: Knowledge):
    return {name: getattr(row, name) for name in (
        "id", "title", "category", "kind", "scope", "content", "phrases", "status", "version",
        "updated_by", "approved_by", "created_at", "updated_at")}


def own(db, user, knowledge_id):
    row = db.scalar(select(Knowledge).where(Knowledge.id == knowledge_id, Knowledge.org_id == user.org_id,
                                              Knowledge.scope != "training")
                    .with_for_update())
    if row is None:
        raise HTTPException(404, "Conocimiento no encontrado")
    return row


def persist(db, row, user):
    row.updated_by, row.updated_at = user.id, utcnow()
    row.search_text = search_value(row.title, row.content, row.phrases)
    try:
        db.flush()
        snapshot = {k: v for k, v in view(row).items() if k not in {"created_at", "updated_at"}}
        db.add(KnowledgeVersion(org_id=user.org_id, knowledge_id=row.id,
                               version=row.version, snapshot=snapshot, responsible_id=user.id))
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(409, "Otra persona modificó el conocimiento; vuelve a cargarlo") from None
    return view(row)


def create(db, body, user):
    row = Knowledge(org_id=user.org_id, **body.model_dump(), status="pending", updated_by=user.id)
    db.add(row)
    return persist(db, row, user)


@router.get("/knowledge")
def list_knowledge(q: str = Query(default="", max_length=100),
                   state: Literal["pending", "approved", "disabled"] | None = None,
                   user: User = Depends(administrator), db: Session = Depends(get_db)):
    query = select(Knowledge).where(Knowledge.org_id == user.org_id, Knowledge.scope != "training")
    if q.strip():
        query = query.where(Knowledge.search_text.contains(plain(q)))
    if state:
        query = query.where(Knowledge.status == state)
    return [view(row) for row in db.scalars(query.order_by(Knowledge.updated_at.desc()).limit(100))]


@router.post("/knowledge", status_code=201)
def add_knowledge(body: KnowledgeInput, user: User = Depends(administrator), db: Session = Depends(get_db)):
    return create(db, body, user)


@router.put("/knowledge/{knowledge_id}")
def edit_knowledge(knowledge_id: str, body: KnowledgeEdit,
                   user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = own(db, user, knowledge_id)
    if row.version != body.version:
        raise HTTPException(409, "Versión desactualizada; vuelve a cargar el conocimiento")
    for k, v in body.model_dump(exclude={"version"}).items():
        setattr(row, k, v)
    # Editing always revokes approval, including previously active documents.
    row.status, row.approved_by = "pending", None
    return persist(db, row, user)


@router.post("/knowledge/{knowledge_id}/state")
def change_state(knowledge_id: str, body: StateInput,
                 user: User = Depends(administrator), db: Session = Depends(get_db)):
    row = own(db, user, knowledge_id)
    if row.version != body.version:
        raise HTTPException(409, "La versión cambió; revisa el contenido antes de aprobar")
    if row.status == body.state:
        return view(row)
    row.status = body.state
    row.approved_by = user.id if body.state == "approved" else None
    return persist(db, row, user)


@router.get("/knowledge/{knowledge_id}/versions")
def versions(knowledge_id: str, user: User = Depends(administrator), db: Session = Depends(get_db)):
    own(db, user, knowledge_id)
    rows = db.scalars(select(KnowledgeVersion).where(
        KnowledgeVersion.org_id == user.org_id, KnowledgeVersion.knowledge_id == knowledge_id)
        .order_by(KnowledgeVersion.version.desc()).limit(50))
    return [{"version": r.version, "responsible_id": r.responsible_id,
             "created_at": r.created_at, "snapshot": r.snapshot} for r in rows]


def extract_document(data: bytes, suffix: str) -> str:
    try:
        if suffix == ".txt":
            result = data.decode("utf-8-sig")
        elif suffix == ".pdf":
            with fitz.open(stream=data, filetype="pdf") as doc:
                if doc.needs_pass or len(doc) > 30:
                    raise ValueError()
                result = "\n".join(page.get_text() for page in doc)
        elif suffix == ".docx":
            with ZipFile(BytesIO(data)) as archive:
                if (len(archive.infolist()) > 200 or
                        sum(i.file_size for i in archive.infolist()) > 4 * 1024**2):
                    raise ValueError()
                xml = archive.read("word/document.xml")
                if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                    raise ValueError()
                root = ElementTree.fromstring(xml)
                ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                result = "\n".join("".join(p.itertext()) for p in root.iter(ns + "p"))
        else:
            raise HTTPException(422, "Usa PDF con texto, Word .docx o texto UTF-8 .txt")
    except (ValueError, RuntimeError, KeyError, BadZipFile, ElementTree.ParseError):
        raise HTTPException(422, "Documento ilegible, protegido o fuera de los límites") from None
    if not 2 <= len(result.strip()) <= 24000:
        raise HTTPException(422, "Se requieren 2 a 24000 caracteres de texto; divide el documento o transcribe el escaneo")
    return result.strip()


@router.post("/knowledge-import", status_code=201)
async def import_document(file: UploadFile = File(...),
                          scope: Literal["red_obras", "messenger", "both"] = Form("red_obras"),
                          user: User = Depends(administrator), db: Session = Depends(get_db)):
    data = await file.read(2 * 1024**2 + 1)
    if len(data) > 2 * 1024**2:
        raise HTTPException(413, "Máximo 2 MiB por documento")
    name = Path((file.filename or "documento").replace("\\", "/")).name
    content = extract_document(data, Path(name).suffix.lower())
    try:
        body = KnowledgeInput(title=Path(name).stem[:180], content=content, kind="procedure", scope=scope)
    except ValueError:
        raise HTTPException(422, "Revisa el título y elimina datos privados antes de importar") from None
    # Store extracted text only, never the upload or an external document URL.
    return create(db, body, user)


@router.post("/knowledge-examples", status_code=201)
def import_examples(user: User = Depends(administrator), db: Session = Depends(get_db)):
    examples = json.loads(Path(__file__).with_name("galancito_examples.json").read_text())
    created = 0
    for example in examples:
        if not db.scalar(select(Knowledge.id).where(Knowledge.org_id == user.org_id,
                                                    Knowledge.title == example["title"])):
            create(db, KnowledgeInput(**example), user)
            created += 1
    return {"created": created, "status": "pending"}


def _curriculum_20() -> list[dict]:
    """Twenty curated, static learning units. Each must pass normal input validation."""
    path = Path(__file__).with_name("galancito_curriculum_20.json")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if len(rows) != 20 or [row["epoch"] for row in rows] != list(range(1, 21)):
        raise RuntimeError("El currículo Galancito requiere exactamente 20 etapas consecutivas")
    return rows


@router.post("/knowledge-curriculum", status_code=201)
def import_curriculum_20(user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Idempotent import: pending until approved; never changes existing teachings."""
    units = _curriculum_20()
    existing = set(db.scalars(select(Knowledge.title).where(
        Knowledge.org_id == user.org_id,
        Knowledge.title.in_([item["title"] for item in units]))))
    created = 0
    for item in units:
        if item["title"] in existing:
            continue
        body = KnowledgeInput(**{k: v for k, v in item.items() if k != "epoch"})
        create(db, body, user)
        created += 1
    return {"created": created, "total": len(units), "status": "pending",
            "message": "Cada unidad requiere aprobación administrativa antes de utilizarse."}


@router.get("/knowledge-curriculum/progress")
def curriculum_progress(user: User = Depends(administrator), db: Session = Depends(get_db)):
    """Percentage represents verified, approved knowledge, NOT neural-network training."""
    units = _curriculum_20()
    rows = list(db.scalars(select(Knowledge).where(
        Knowledge.org_id == user.org_id,
        Knowledge.title.in_([item["title"] for item in units]))))
    by_title = {row.title: row for row in rows}
    stages = []
    for item in units:
        row = by_title.get(item["title"])
        state = row.status if row else "missing"
        if row and row.scope not in {"red_obras", "both"}:
            state = "out_of_scope"
        stages.append({"epoch": item["epoch"], "title": item["title"],
                       "state": state})
    approved = sum(stage["state"] == "approved" for stage in stages)
    pending = sum(stage["state"] == "pending" for stage in stages)
    return {"total": len(stages), "approved": approved, "pending": pending,
            "percent": round(approved * 100 / len(stages)),
            "remaining": [stage["title"] for stage in stages if stage["state"] != "approved"],
            "stages": stages,
            "metric": "Cobertura de conocimientos aprobados, no épocas de ajuste del modelo"}


class ConfirmCurriculum(BaseModel):
    """A deliberate administrator action, never an automatic deployment approval."""
    confirm: Literal[True]


@router.post("/knowledge-curriculum/approve")
def approve_curriculum_20(body: ConfirmCurriculum, user: User = Depends(administrator),
                          db: Session = Depends(get_db)):
    """Approve all twenty ONLY when every text matches the reviewed bundled curriculum."""
    units = _curriculum_20()
    titles = [item["title"] for item in units]
    rows = list(db.scalars(select(Knowledge).where(
        Knowledge.org_id == user.org_id, Knowledge.title.in_(titles)).with_for_update()))
    by_title = {row.title: row for row in rows}
    if len(rows) != 20 or set(by_title) != set(titles):
        raise HTTPException(409, "Carga primero las veinte unidades y revisa su contenido")
    for unit in units:
        row = by_title[unit["title"]]
        expected = {k: v for k, v in unit.items() if k != "epoch"}
        actual = {key: getattr(row, key) for key in expected}
        if actual != expected or row.status == "disabled":
            raise HTTPException(409, "Una unidad fue editada o desactivada; requiere revisión individual")
    approved = 0
    for item in units:
        row = by_title[item["title"]]
        if row.status == "approved":
            continue
        row.status, row.approved_by = "approved", user.id
        row.updated_by, row.updated_at = user.id, utcnow()
        db.flush()
        snapshot = {k: v for k, v in view(row).items() if k not in {"created_at", "updated_at"}}
        db.add(KnowledgeVersion(org_id=user.org_id, knowledge_id=row.id, version=row.version,
                                snapshot=snapshot, responsible_id=user.id))
        approved += 1
    db.commit()
    return {"approved_now": approved, "total": len(units), "percent": 100,
            "message": "Las veinte unidades aprobadas ya están disponibles para consultas."}


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["useful", "incorrect"]
    correction: KnowledgeInput | None = None


@router.post("/runs/{run_id}/feedback")
def feedback(run_id: str, body: FeedbackInput, user: User = Depends(authorized_user), db: Session = Depends(get_db)):
    row = db.scalar(select(AssistantRun).where(AssistantRun.id == run_id, AssistantRun.org_id == user.org_id))
    if not row or (row.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Respuesta no encontrada")
    if body.correction and user.role != "admin":
        raise HTTPException(403, "Solo administración puede proponer conocimientos")
    row.feedback = body.rating
    proposal = None
    if body.correction:
        proposal = create(db, body.correction.model_copy(update={"kind": "correction"}), user)
    else:
        db.commit()
    return {"saved": True, "proposal": proposal}


@router.get("/performance")
def performance(user: User = Depends(administrator), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(AssistantRun).where(AssistantRun.org_id == user.org_id,
        AssistantRun.created_at >= utcnow() - timedelta(hours=24))
        .order_by(AssistantRun.created_at.desc()).limit(500)))
    times = sorted(r.elapsed_ms for r in rows)
    messenger = [r for r in rows if r.channel == "messenger" and "graph_calls" in r.timings]
    attempted = [r for r in messenger if not r.timings.get("cancelled")]
    messenger_times = sorted(r.timings["conversation_ms"] for r in attempted if "conversation_ms" in r.timings)

    cfg = settings()
    from .galancito_local import model_status
    health = model_status() if cfg.galancito_local_ai_enabled else {"state": "disabled", "model_ram_bytes": None}
    return {"sample_limit": 500, "period_hours": 24, "queries": len(rows),
            "average_ms": round(mean(times)) if times else None,
            "p50_ms": median(times) if times else None,
            "p95_ms": times[min(len(times) - 1, int(len(times) * .95))] if times else None,
            "sources": {s: sum(r.source == s for r in rows) for s in {r.source for r in rows}},
            "messenger": {
                "replies": len(attempted),
                "cancelled": len(messenger) - len(attempted),
                "p50_ms": median(messenger_times) if messenger_times else None,
                "p95_ms": messenger_times[(95 * len(messenger_times) + 99) // 100 - 1]
                          if messenger_times else None,
                "delivery_errors": sum(bool(r.timings.get("delivery_error")) for r in messenger),
                "model_errors": sum(bool(r.timings.get("model_error")) for r in messenger),
                "graph_calls": sum(r.timings["graph_calls"] for r in messenger),
                "external_model_calls": sum(r.timings.get("external_model_calls", 0) for r in messenger),
                "local_model_calls": sum(r.timings.get("local_model_calls", 0) for r in messenger),
                "input_tokens": sum(r.timings["input_tokens"] for r in messenger if "input_tokens" in r.timings),
                "output_tokens": sum(r.timings["output_tokens"] for r in messenger if "output_tokens" in r.timings),
                "replies_with_token_counts": sum("input_tokens" in r.timings and "output_tokens" in r.timings
                                                 for r in messenger),
            },
            "incorrect": sum(r.feedback == "incorrect" for r in rows),
            "model": "qwen3:1.7b", "health": health,
            "keep_alive": cfg.galancito_keep_alive, "num_predict": cfg.galancito_num_predict,
            "cpu_limit": 1.5, "ram_limit_gib": 3, "cpu_usage": None,
            "stages_ms": {k: round(mean(r.timings[k] for r in rows if k in r.timings))
                          for k in ("db_ms", "load_ms", "prompt_ms", "generation_ms", "transport_ms", "queue_ms")
                          if any(k in r.timings for r in rows)}}
