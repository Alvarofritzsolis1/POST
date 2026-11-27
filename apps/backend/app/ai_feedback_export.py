"""Read-only, tenant-scoped evidence export for Red de Obras diagnostics."""
import re
import hashlib
from pathlib import Path
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .config import settings
from .ai_models import AIConnection, AIOrchestration, AIUsage
from .galancito_training_models import TrainingRound, TrainingCase
from .max_power_models import MaxPowerState, MaxPowerEvent, MaxPowerMessengerTrial
from .galancito_training import summarize
from .security import administrator
from .models import User, utcnow
from .version import VERSION, SOURCE_COMMIT
from .galancito_contact_profile import contact_profile
from .facebook_crm_models import FacebookLead, FacebookChatMessage, FacebookTradeGuide, FacebookLeadTrade, FacebookLeadTrace, FacebookNeedAssociation
from .facebook_publication_models import FacebookPostComment, FacebookPostSnapshot, FacebookPostJob
from .network_models import NetworkItem, NetworkPendingItem, NetworkCoordination, NetworkAward, NetworkRequirement, NetworkFacebookPost, NetworkFacebookManual, NetworkCandidateFollowUp, NetworkCapacity, NetworkMatch
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
    "trade_guides": (FacebookTradeGuide, "updated_at", "id slug trade aliases explanation document_guidance approved updated_at"),
    "requirement_items": (NetworkItem, "created_at", "id requirement_id name description quantity unit position start_date end_date notes created_at"),
    "capacity_items": (NetworkPendingItem, "created_at", "id capacity_id name quantity unit end_date created_at"),
    "coordinations": (NetworkCoordination, "updated_at", "id match_id state reason version created_at updated_at"),
    "awards": (NetworkAward, "created_at", "id item_id capacity_id coordination_id quantity executed workers start_date end_date state created_at version"),
    "ai_usage": (AIUsage, "created_at", "id connection_id task status input_tokens output_tokens total_tokens estimated_cost_usd duration_ms created_at"),
    "ai_connections": (AIConnection, "updated_at", "id provider model enabled last_status last_checked_at updated_at"),
    "training_rounds": (TrainingRound, "created_at", "id state target completed attempts dataset_hash system_version prompt_version created_at finished_at previous_id"),
    "max_power_events": (MaxPowerEvent, "created_at", "id event round_id created_at"),
    "max_power_trials": (MaxPowerMessengerTrial, "created_at", "id review_id source_run_id criterion variant status attempts started_at completed_at outcome created_at"),
    "knowledge": (Knowledge, "updated_at", "id title category kind scope status version content phrases created_at updated_at"),
}
TEXT_FIELDS = {"name", "notes", "reason", "aliases", "explanation", "document_guidance", "specialty", "trade", "public_location", "slug", "category","body", "message", "title", "description", "public_summary", "experience", "availability", "work_area", "work_communes", "phrases", "content"}
TIMING_IDS = {"outbound_message_id", "inbound_message_id", "lead_id"}
TIMING_LABELS = {"reply_origin", "provider", "model", "response_model", "source", "delivery_state", "error_type", "release", "revision", "question_field", "fallback_reason", "model_error_type", "verified_guidance", "guided_followup", "ai_route"}
TRACE_LISTS = {"semantic_fields", "profile_fields_before", "profile_fields_after", "candidate_history_ids"}
METRIC_KEYS = {"passed", "failed", "turns", "fields", "correct_fields", "questions", "repeated_questions", "critical", "judged_cases", "judged_turns", "latency_ms", "input_tokens", "output_tokens", "peak_worker_ram_mb", "peak_host_cpu_percent", "real_holdout_gain_cases", "real_holdout_regressions", "synthetic_holdout_gains", "synthetic_holdout_regressions", "real_learning_demonstrated", "objective_gain", "paired_latency_delta_ms", "baseline_ms", "candidate_ms", "elapsed_ms", "safe", "understanding_check"}

def numeric_metrics(value):
    return {key: val for key, val in (value or {}).items() if key in METRIC_KEYS and type(val) in (int, float, bool)}

def safe_timings(value):
    return {k: v for k, v in (value or {}).items() if type(v) in (int, float, bool) or
            (k in TIMING_IDS and isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F-]{36}", v)) or
            (k in TIMING_LABELS and isinstance(v, str) and re.fullmatch(r"[\w.:/-]{1,160}", v)) or
            (k in TRACE_LISTS and isinstance(v, list) and all(isinstance(x, str) and re.fullmatch(r"[\w-]{1,64}", x) for x in v))}

def source_inventory(include_code=False):
    # Only shipped application Python sources; never environment files, keys or logs.
    root = Path(__file__).resolve().parent
    prefixes = ("galancito_", "facebook_", "network_", "ai_", "max_power_")
    files = []
    for path in sorted(root.glob("*.py")):
        if not path.name.startswith(prefixes) or path.is_symlink():
            continue
        data = path.read_bytes()
        record = {"path": "apps/backend/app/" + path.name, "sha256": hashlib.sha256(data).hexdigest()}
        if include_code:
            record["source"] = data.decode("utf-8")
        files.append(record)
    return files

def profile_provenance(row, remote_to_local):
    sources = row.profile_sources or {}
    declared = sources.get("_declared_context") or {}
    merged = {**{k: v for k, v in sources.items() if not k.startswith("_")}, **declared}
    return {k: {"source": v.get("source"), "state": v.get("state"), "at": v.get("at"),
                "message_id": remote_to_local.get((row.id, v.get("message_id"))),
                "source_message_recorded": bool(v.get("message_id"))}
            for k, v in merged.items() if isinstance(v, dict) and re.fullmatch(r"[a-z_]{1,60}", k)}

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
    if model is AIUsage:
        stmt = stmt.where(model.task.in_(("messenger", "red_obras", "review")))
    if model is Knowledge:
        stmt = stmt.where(model.scope.in_(("red_obras", "messenger")))
    if since is not None and model not in (AIConnection, FacebookTradeGuide, Knowledge):
        stmt = stmt.where(getattr(model, date_field) >= since)
    return stmt.order_by(getattr(model, date_field))

@router.get("/red-obras/feedback-export")
def feedback_export(days: int = Query(default=0, ge=0, le=90),
                    include_text: bool = Query(default=False),
                    include_code: bool = Query(default=False),
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
    # Source mapping never exports raw Meta message identifiers.
    result = {}
    remote_to_local = {}
    for key, (model, date_field, field_list) in sorted(DATASETS.items(), key=lambda entry: entry[0] != "messages"):
        rows = []
        for row in db.scalars(selection(model, user.org_id, date_field, since).limit(MAX_ROWS + 1)):
            if len(rows) >= MAX_ROWS:
                raise HTTPException(413, f"{key}: excede {MAX_ROWS} registros. Elige un período menor.")
            if model is TrainingRound and (row.config or {}).get("profile", "postulantes") == "interno":
                continue
            item = {}
            for field in field_list.split():
                value = getattr(row, field)
                if field in TEXT_FIELDS:
                    item[field] = safe_text(value, names) if include_text else None
                else:
                    item[field] = value
            if model is FacebookChatMessage and row.remote_id:
                remote_to_local[(row.lead_id, row.remote_id)] = row.id
            if model is FacebookLead:
                item["field_provenance"] = profile_provenance(row, remote_to_local)
                item.update(phone_recorded=bool(row.contact_phone), email_recorded=bool(row.contact_email),
                            name_recorded=bool(row.display_name and row.display_name not in ("Interesado de Facebook", "Contacto sin nombre")))
                profile = contact_profile(row)
                item["profile_completion"] = {key: profile[key] for key in ("completed", "total", "percent", "missing", "field_states", "contact_state", "additional_services_pending")}
                item["declared_context"] = {key: safe_text(value.get("value"), names) if isinstance(value.get("value"), str) and include_text else value.get("value") if type(value.get("value")) in (bool, int, float) else None
                                            for key, value in profile["declared_context"].items() if key in ("declared_origin", "crew_size", "preferred_contact", "worked_at_galilea", "crew_expandable", "notice_trade", "additional_services_pending") and isinstance(value, dict)}
            if model in (FacebookChatMessage, FacebookPostJob, NetworkFacebookPost, NetworkFacebookManual):
                error = getattr(row, "error", None) or getattr(row, "last_error", None)
                item["error_recorded"] = bool(error)
                if error:
                    item["error_codes"] = {label: int(match.group(1)) for label, pattern in (("http", r"HTTP (\d{3})"), ("meta", r"código Meta (\d+)"), ("subcode", r"subcódigo (\d+)")) if (match := re.search(pattern, error))}
            if model is AssistantRun:
                item["timings"] = safe_timings(row.timings)
            if model is TrainingRound:
                metrics = summarize(row.metrics or {}, "postulantes")
                item["metrics"] = {k: v for k, v in metrics.items() if v is None or type(v) in (bool, int, float)}
                item["models"] = {role: {k: spec.get(k) for k in ("id", "model") if isinstance(spec.get(k), str)}
                                  for role in ("model", "judge", "corrector")
                                  if isinstance(spec := (row.config or {}).get(role), dict)}
            if model is MaxPowerMessengerTrial:
                item["metrics"] = numeric_metrics(row.metrics)
            if model is MaxPowerEvent:
                item["metrics"] = numeric_metrics(row.evidence)
            rows.append(item)
        result[key] = rows
    round_ids = [row["id"] for row in result["training_rounds"]]
    cases = []
    if round_ids:
        stmt = select(TrainingCase).join(TrainingRound, TrainingCase.round_id == TrainingRound.id).where(
            TrainingRound.org_id == user.org_id, TrainingCase.round_id.in_(round_ids)).order_by(TrainingCase.round_id, TrainingCase.position).limit(MAX_ROWS + 1)
        for row in db.scalars(stmt):
            if len(cases) >= MAX_ROWS:
                raise HTTPException(413, "Demasiados casos de práctica. Elige un período menor.")
            cases.append({"round_id": row.round_id, "position": row.position, "case_id": row.case_id,
                          "passed": row.passed, "metrics": numeric_metrics(row.result)})
    result["training_cases"] = cases
    state = db.get(MaxPowerState, user.org_id)
    result["max_power_state"] = [{key: getattr(state, key) for key in ("enabled", "worker_seen_at", "last_tick_at", "on_seconds", "sessions", "experiments", "examined_cases", "lab_gains", "regressions", "active_round_id", "last_round_id", "last_status", "updated_at")}] if state else []
    policy = db.get(AIOrchestration, user.org_id)
    cfg = settings()
    runtime = {key: getattr(cfg, key) for key in ("facebook_local_processing_authorized", "facebook_ai_enabled", "facebook_ai_ad_enabled", "facebook_ai_provider", "facebook_ai_model", "galancito_ai_enabled", "galancito_ai_provider", "galancito_ai_model", "galancito_local_ai_enabled", "galancito_local_model", "galancito_contextual_messenger_enabled", "galancito_keep_alive", "galancito_num_predict", "galancito_num_ctx", "galancito_num_thread", "galancito_timeout_seconds", "galancito_memory_reserve_mb")}
    messenger_runs = [row for row in result["runs"] if row["channel"] == "messenger"]
    outbound_ids = {row["id"] for row in result["messages"] if row["direction"] == "outbound"}
    sent_ids = {row["id"] for row in result["messages"] if row["direction"] == "outbound" and row["state"] == "sent"}
    coverage = {"messenger_runs": len(messenger_runs),
                "runs_linked_to_exported_message": sum(row["timings"].get("outbound_message_id") in outbound_ids for row in messenger_runs),
                "runs_linked_to_sent_message": sum(row["timings"].get("outbound_message_id") in sent_ids for row in messenger_runs),
                "runs_with_trace_v2": sum(row["timings"].get("trace_version", 0) >= 2 for row in messenger_runs),
                "profile_sources_linked": sum(bool(v["message_id"]) for row in result["leads"] for v in row["field_provenance"].values()),
                "profile_sources_recorded": sum(v["source_message_recorded"] for row in result["leads"] for v in row["field_provenance"].values())}
    findings = {
        "messages_with_recorded_error": sum(row["error_recorded"] for row in result["messages"]),
        "failed_outbound_messages": sum(row["direction"] == "outbound" and row["state"] == "failed" for row in result["messages"]),
        "failed_publication_jobs": sum(row["state"] == "failed" for row in result["publication_jobs"]),
        "failed_publication_refreshes": sum(row["state"] == "failed" and row["action"] == "refresh" for row in result["publication_jobs"]),
        "leads_missing_profile_fields": sum(bool(row["profile_completion"]["missing"]) for row in result["leads"]),
        "leads_needing_support": sum(row["needs_support"] for row in result["leads"]),
        "leads_ai_paused": sum(row["ai_paused"] for row in result["leads"]),
        "runs_reported_incorrect": sum(row["feedback"] == "incorrect" for row in result["runs"]),
        "runs_with_fallback": sum(row["source"] == "fallback" for row in result["runs"]),
        "messenger_runs_with_fallback": sum(row["source"] == "fallback" for row in messenger_runs),
        "red_obras_runs_with_fallback": sum(row["source"] == "fallback" and row["channel"] == "red_obras" for row in result["runs"]),
        "runs_without_message_link": sum(row["channel"] == "messenger" and not row["timings"].get("outbound_message_id") for row in result["runs"]),
        "runs_with_unavailable_message_link": sum(bool(row["timings"].get("outbound_message_id")) and row["timings"].get("outbound_message_id") not in outbound_ids for row in messenger_runs),
    }
    payload = {
        "schema_version": 2, "version": VERSION, "source_commit": SOURCE_COMMIT,
        "generated_at": now, "since": since, "period_days": days,
        "scope": "red_obras", "include_text": include_text,
        "counts": {key: len(rows) for key, rows in result.items()},
        "findings": findings,
        "coverage": coverage,
        "runtime_configuration": runtime,
        "orchestration": {"enabled": policy.enabled, "fallback_enabled": policy.fallback_enabled, "review_enabled": policy.review_enabled} if policy else None,
        "source_inventory": source_inventory(include_code),
        "include_code": include_code,
        "repository": "https://github.com/Alvarofritzsolis1/POST",
        "findings_note": "Indicadores observados; campos pendientes, fallback y falta de vínculo no son por sí solos errores de IA.",
        "limitations": [
            "Solo registros persistidos de la organización autenticada.",
            "Los filtros temporales se aplican por fecha indicada en cada colección; configuración, guías y conocimiento se incluyen en su estado actual. Las fichas no son reconstrucciones históricas.",
            "No incluye chats internos privados, credenciales, archivos ni razonamiento interno del modelo.",
            "Los errores de proveedor se indican por presencia, no por logs sin filtrar.",
            "El texto opcional tiene redacción parcial de identificadores; revisar antes de compartir.",
            "Sin trazas vinculadas no se puede determinar si la respuesta provino del modelo o de una regla.",
            "Inventario de código del backend con hashes y fuente opcional. El frontend y el resto del repositorio se obtienen mediante source_commit. No incluye archivos de configuración privados.",
            "candidate_history_ids identifica mensajes candidatos recuperados, no garantiza inclusión exacta en el prompt.",
            "Configuración actual, no necesariamente la utilizada en cada respuesta histórica. Los resultados de práctica no equivalen a producción.",
            "Referencias de mensajes fuera del período o borrados pueden faltar. Los chats internos privados quedan excluidos.",
        ],
        "date_fields": {key: spec[1] for key, spec in DATASETS.items()},
        "datasets": result,
    }
    response = JSONResponse(jsonable_encoder(payload), headers={"Cache-Control": "no-store",
        "Content-Disposition": 'attachment; filename="galant-red-obras-diagnostico.json"'})
    if len(response.body) > MAX_BYTES:
        raise HTTPException(413, "El diagnóstico supera 24 MiB. Elige un período menor.")
    return response
