"""Read-only, tenant-scoped evidence export for Red de Obras diagnostics."""
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .security import administrator
from .models import User, utcnow
from .version import VERSION, SOURCE_COMMIT
from .facebook_crm_models import FacebookLead, FacebookChatMessage, FacebookLeadTrade, FacebookLeadTrace, FacebookNeedAssociation
from .facebook_publication_models import FacebookPostComment, FacebookPostSnapshot, FacebookPostJob
from .network_models import NetworkRequirement, NetworkFacebookPost, NetworkFacebookManual, NetworkCandidateFollowUp, NetworkCapacity, NetworkMatch
from .galancito_knowledge_models import AssistantRun, Knowledge
from .ai_quality_models import AIResponseReview, AIRealPracticeTrial

router = APIRouter(prefix="/api/v1/admin/ai", tags=["Sobrealimentación IA"])
MAX_ROWS = 20000
MAX_BYTES = 24 * 1024 * 1024
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\w)(?:\+?56[\s-]*)?(?:\d[\s().-]*){8,11}\d(?!\w)")
RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
SECRET = re.compile(r"(?i)(?:bearer\s+[\w.-]+|(?:access[_ -]?token|api[_ -]?key|password|contraseña)\s*[:=]\s*\S+|(?:sk-|nvapi-)[A-Za-z0-9_-]{8,})")

# Explicit field allowlists. No credential tables, Meta IDs, private internal
# chats, attachment paths, operator IDs, or unstructured runtime errors.
DATASETS = {
    "leads": (FacebookLead, "updated_at", "id specialty specialty_source workers availability experience status requirement_id ai_paused needs_support entity_type has_employees employee_count interest_type team_available work_area work_communes phone_source phone_opt_out email_source email_opt_out created_at updated_at last_inbound_at"),
    "messages": (FacebookChatMessage, "created_at", "id lead_id direction state ai_generated consent_decision body created_at updated_at"),
    "trades": (FacebookLeadTrade, "updated_at", "id lead_id trade source active first_seen_at updated_at"),
    "lead_events": (FacebookLeadTrace, "created_at", "id lead_id requirement_id trade event source created_at"),
    "associations": (FacebookNeedAssociation, "updated_at", "id lead_id requirement_id state created_at updated_at"),
    "requirements": (NetworkRequirement, "updated_at", "id specialty title description priority workers start_date end_date deadline state public_location public_summary start_date_pending version created_at updated_at"),
    "publications": (NetworkFacebookPost, "updated_at", "id requirement_id target_version action state attempts created_at updated_at"),
    "manual_publications": (NetworkFacebookManual, "updated_at", "id action state title message attempts created_at updated_at"),
    "publication_snapshots": (FacebookPostSnapshot, "checked_at", "post_record_id message comment_count reaction_count share_count checked_at"),
    "comments": (FacebookPostComment, "fetched_at", "id post_record_id body classification classification_source classification_score review_state is_deleted is_hidden posted_at fetched_at private_reply_state"),
    "publication_jobs": (FacebookPostJob, "updated_at", "id post_record_id action message state created_at updated_at"),
    "candidate_followup": (NetworkCandidateFollowUp, "updated_at", "id requirement_id lead_id stage follow_up_on created_at updated_at"),
    "capacity": (NetworkCapacity, "updated_at", "id specialty situation available_date workers mode availability state expires_on version created_at updated_at"),
    "matches": (NetworkMatch, "created_at", "id requirement_id capacity_id score active created_at"),
    "runs": (AssistantRun, "created_at", "id channel source intent elapsed_ms feedback created_at"),
    "reviews": (AIResponseReview, "source_at", "id run_id channel evidence_kind evidence_id rubric_version ratings source_at created_at"),
    "practice": (AIRealPracticeTrial, "created_at", "id review_id channel criterion model elapsed_ms policy_version variant provenance stage outcome criterion_resolved safety_passed created_at reviewed_at"),
    "knowledge": (Knowledge, "updated_at", "id title category kind scope status version content phrases created_at updated_at"),
}
TEXT_FIELDS = {"body", "message", "title", "description", "public_summary", "experience", "availability", "work_area", "work_communes", "phrases", "content"}
TIMING_IDS = {"outbound_message_id", "inbound_message_id", "lead_id"}
TIMING_LABELS = {"provider", "model", "source", "delivery_state", "error_type"}

def redact(text, names=()):
    for name in names:
        if name and len(name) >= 3:
            text = re.sub(r"\b" + re.escape(name) + r"\b", "[NOMBRE]", text, flags=re.I)
    return SECRET.sub("[CREDENCIAL]", PHONE.sub("[TELÉFONO]", RUT.sub("[RUT]", EMAIL.sub("[CORREO]", text))))

def safe_text(value, names):
    if isinstance(value, str):
        return redact(value, names)
    if isinstance(value, list):
        return [safe_text(item, names) for item in value if isinstance(item, str)]
    return value

def selection(model, org_id, date_field, since):
    stmt = select(model).where(model.org_id == org_id)
    if model in (AssistantRun, AIResponseReview, AIRealPracticeTrial):
        stmt = stmt.where(model.channel.in_(("messenger", "red_obras")))
    if model is Knowledge:
        stmt = stmt.where(model.scope.in_(("red_obras", "messenger")))
    if since is not None:
        stmt = stmt.where(getattr(model, date_field) >= since)
    return stmt.order_by(getattr(model, date_field))

@router.get("/red-obras/feedback-export")
def feedback_export(days: int = Query(default=0, ge=0, le=90),
                    include_text: bool = Query(default=False),
                    user: User = Depends(administrator), db: Session = Depends(get_db)):
    if days not in (0, 7, 30, 90):
        raise HTTPException(422, "Período no admitido.")
    now = utcnow()
    since = now - timedelta(days=days) if days else None
    # Use tenant-local known names only; redaction is best effort, not anonymity.
    names = []
    if include_text:
        names = [value for value in db.scalars(select(FacebookLead.display_name).where(
            FacebookLead.org_id == user.org_id).distinct().limit(MAX_ROWS + 1))
                 if value and value != "Interesado de Facebook"]
        if len(names) > MAX_ROWS:
            raise HTTPException(413, "Demasiados nombres para redactar de forma segura.")
    result = {}
    for key, (model, date_field, field_list) in DATASETS.items():
        rows = []
        for row in db.scalars(selection(model, user.org_id, date_field, since).limit(MAX_ROWS + 1)):
            if len(rows) >= MAX_ROWS:
                raise HTTPException(413, f"{key}: excede {MAX_ROWS} registros. Elige un período menor.")
            item = {}
            for field in field_list.split():
                value = getattr(row, field)
                if field in TEXT_FIELDS:
                    item[field] = safe_text(value, names) if include_text else None
                else:
                    item[field] = value
            if model is FacebookLead:
                item.update(phone_recorded=bool(row.contact_phone), email_recorded=bool(row.contact_email),
                            name_recorded=bool(row.display_name and row.display_name != "Interesado de Facebook"))
            if model in (FacebookChatMessage, FacebookPostJob, NetworkFacebookPost, NetworkFacebookManual):
                item["error_recorded"] = bool(getattr(row, "error", None) or getattr(row, "last_error", None))
            if model is AssistantRun:
                item["timings"] = {k: v for k, v in (row.timings or {}).items()
                                   if type(v) in (int, float, bool) or
                                   (k in TIMING_IDS and isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F-]{36}", v)) or
                                   (k in TIMING_LABELS and isinstance(v, str) and re.fullmatch(r"[\w.:/-]{1,100}", v))}
            rows.append(item)
        result[key] = rows
    payload = {
        "schema_version": 1, "version": VERSION, "source_commit": SOURCE_COMMIT,
        "generated_at": now, "since": since, "period_days": days,
        "scope": "red_obras", "include_text": include_text,
        "counts": {key: len(rows) for key, rows in result.items()},
        "limitations": [
            "Solo registros persistidos de la organización autenticada.",
            "Los filtros temporales se aplican por fecha indicada en cada colección; las fichas son su estado actual, no reconstrucciones históricas.",
            "No incluye chats internos privados, credenciales, archivos ni razonamiento interno del modelo.",
            "Los errores de proveedor se indican por presencia, no por logs sin filtrar.",
            "El texto opcional tiene redacción parcial de identificadores; revisar antes de compartir.",
            "Sin trazas vinculadas no se puede determinar si la respuesta provino del modelo o de una regla.",
        ],
        "date_fields": {key: spec[1] for key, spec in DATASETS.items()},
        "datasets": result,
    }
    response = JSONResponse(jsonable_encoder(payload), headers={"Cache-Control": "no-store",
        "Content-Disposition": 'attachment; filename="galant-red-obras-diagnostico.json"'})
    if len(response.body) > MAX_BYTES:
        raise HTTPException(413, "El diagnóstico supera 24 MiB. Elige un período menor.")
    return response
