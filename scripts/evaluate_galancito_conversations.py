#!/usr/bin/env python3
"""Evaluate signed Messenger conversations on a fresh SQLite DB with simulated Meta."""
import argparse
import hashlib
import hmac
import json
import math
import os
import re
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter, sleep
from unittest.mock import patch
from contextlib import nullcontext
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "apps/backend/tests/fixtures"
DEFAULT_PROFILE = {
    "name": "Interesado de Facebook", "interest_type": "unknown", "entity_type": "unknown",
    "trades": [], "work_communes": [], "availability": "", "experience": "",
    "team_available": None, "workers": None, "has_employees": None,
    "documents_state": "unverified", "name_opt_out": False, "ai_consent": False,
}

EXTRA_PROFILE = {"specialty", "contact_phone", "contact_email", "declared_origin",
                 "crew_size", "preferred_contact", "needs_support", "ai_paused", "has_employees", "worked_at_galilea", "notice_trade"}

KNOWN_FIELD_QUESTIONS = {
    "name": ("cual es tu nombre", "como te llamas", "como prefieres que te llamemos"),
    "trades": ("que oficio", "que trabajo realizas", "que trabajo haces"),
    "interest_type": ("ofreces trabajos por tu cuenta",),
    "work_communes": ("en que comuna",),
    "availability": ("desde cuando",),
    "experience": ("cuanto tiempo llevas",),
    "team_available": ("trabajas solo",),
    "workers": ("cuantas personas",),
    "worked_at_galilea": ("has trabajado antes en galilea", "has trabajado en galilea"),
}


def load_cases(path):
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = {case.get("id") for case in cases}
    if not cases or None in ids or len(ids) != len(cases):
        raise ValueError("Se requieren identificadores de conversación únicos.")
    for case in cases:
        if not case.get("turns"):
            raise ValueError(f'{case["id"]} no tiene turnos con el formato documentado.')
        for turn in case["turns"]:
            if not isinstance(turn.get("message"), str) or set(turn.get("profile", {})) - (DEFAULT_PROFILE.keys() | EXTRA_PROFILE):
                raise ValueError(f'{case["id"]} contiene un mensaje o campo no admitido.')
    return cases


def metrics(values):
    if not values:
        return {"p50_ms": None, "p95_ms": None}
    ordered = sorted(values)
    return {"p50_ms": round(median(ordered), 3),
            "p95_ms": round(ordered[math.ceil(.95 * len(ordered)) - 1], 3)}


def run(dataset, source_root, *, real_local=False, contextual=False, loopback=False, limit=None, offset=0):
    sys.path.insert(0, str(source_root / "apps/backend"))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from app.config import settings
    from app.db import Base, get_db
    from app.facebook_crm import router
    from app.facebook_crm_models import FacebookChatMessage, FacebookLead, FacebookLeadTrade
    from app.galancito_triage import plain
    from app import galancito_local
    from app.galancito_phone import redact_mobile_for_intake
    from app.galancito_contact_email import redact_email_for_intake
    from app.galancito_knowledge_models import AssistantRun
    from app.galancito_model_config import QWEN_2B
    from app.main import app as _full_app  # Register related tables on Base.
    from app.models import Organization
    from app.facebook_chat_worker import process_chat_next

    cases = load_cases(dataset)[offset:offset + limit if limit is not None else None]
    if not cases:
        raise ValueError("El intervalo no contiene casos")
    if loopback:
        galancito_local.INTERNAL_URL = "http://127.0.0.1:11434/api/chat"

    def redact(value):
        if isinstance(value, str):
            return redact_email_for_intake(redact_mobile_for_intake(value)) if value else value
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value
    application = FastAPI()
    application.include_router(router)
    sent, measurements, results = [], [], []
    calls = {"graph_send": 0, "graph_sender_action": 0, "external_ai": 0}
    observed_models, local_calls, input_tokens, output_tokens = set(), 0, 0, 0

    def graph_send(page, psid, body, token):
        calls["graph_send"] += 1
        sent.append(body)
        return f"simulated-{uuid4()}"

    def graph_action(*_args):
        calls["graph_sender_action"] += 1

    def unexpected_ai(*_args, **_kwargs):
        calls["external_ai"] += 1
        raise AssertionError("El evaluador local no debía invocar un proveedor de IA.")

    with TemporaryDirectory() as temp:
        engine = create_engine("sqlite:///" + temp + "/test.db")
        Base.metadata.create_all(engine)
        session = sessionmaker(engine, expire_on_commit=False)

        def get_test_db():
            with session() as db:
                yield db

        application.dependency_overrides[get_db] = get_test_db
        with session.begin() as db:
            org = Organization(name="Evaluación sintética de Galancito")
            db.add(org)
            db.flush()
            org_id = org.id

        env = {
            "FACEBOOK_MESSAGING_ENABLED": "true", "FACEBOOK_AI_ENABLED": "true",
            "FACEBOOK_ORG_ID": org_id, "FACEBOOK_PAGE_ID": "123450000",
            "FACEBOOK_APP_SECRET": "only-for-synthetic-evaluation",
            "FACEBOOK_PAGE_TOKEN": "simulated-meta", "FACEBOOK_AI_PROVIDER": "ollama" if real_local else "openai",
            "FACEBOOK_AI_API_KEY": "", "GALANCITO_LOCAL_AI_ENABLED": "true" if real_local else "false",
            "GALANCITO_LOCAL_MODEL": QWEN_2B,
            "GALANCITO_CONTEXTUAL_MESSENGER_ENABLED": str(contextual).lower(),
        }
        with (patch.dict(os.environ, env),
              patch("app.facebook_chat_worker.graph_send", graph_send),
              patch("app.facebook_chat_worker.graph_sender_action", graph_action),
              patch("app.facebook_chat_worker.orchestrated_text", unexpected_ai),
              (nullcontext() if real_local else patch("app.facebook_chat_worker.generate_text", unexpected_ai)),
              TestClient(application) as client):
            settings.cache_clear()
            for index, case in enumerate(cases, start=1):
                psid = str(70000000000 + index)
                expected = {} if real_local else dict(DEFAULT_PROFILE)
                if real_local:
                    # This explicit synthetic authorization is never written to production.
                    with session.begin() as db:
                        db.add(FacebookLead(org_id=org_id, page_id=env["FACEBOOK_PAGE_ID"], psid=psid,
                            ai_consent=True, ai_consent_state="accepted", ai_consent_provider="ollama"))
                turns = []
                pending_inputs = []
                awaiting_human = False
                case_model_calls = 0
                case_model_output = 0
                for number, turn in enumerate(case["turns"], start=1):
                    pending_inputs.append(turn["message"])
                    expected.update(turn.get("profile", {}))
                    mid = f"synthetic-{index}-{number}"
                    data = json.dumps({"object": "page", "entry": [{"id": env["FACEBOOK_PAGE_ID"],
                        "messaging": [{"sender": {"id": psid},
                                       "message": {"mid": mid, "text": turn["message"]}}]}]}).encode()
                    signature = hmac.new(env["FACEBOOK_APP_SECRET"].encode(), data, hashlib.sha256).hexdigest()
                    headers = {"X-Hub-Signature-256": f"sha256={signature}"}
                    started, start_count = perf_counter(), len(sent)
                    with session() as db:
                        seen_runs = {r.id for r in db.scalars(select(AssistantRun))} if real_local else set()
                    response = client.post("/api/v1/network/facebook/webhook", content=data, headers=headers)
                    if turn.get("replay"):
                        replay = client.post("/api/v1/network/facebook/webhook", content=data, headers=headers)
                    if turn.get("flush", True):
                        for _ in range(5):
                            if not process_chat_next(session):
                                break
                    if contextual and turn.get("flush", True) and len(sent) == start_count:
                        # Drive the normal worker after the persisted quiet window.
                        sleep(.72)
                        process_chat_next(session)
                    elapsed = (perf_counter() - started) * 1000
                    measurements.append(elapsed)
                    with session() as db:  # Fresh session on every turn.
                        lead = db.scalar(select(FacebookLead).where(FacebookLead.org_id == org_id,
                                                                    FacebookLead.psid == psid))
                        trades = list(db.scalars(select(FacebookLeadTrade.trade).where(
                            FacebookLeadTrade.lead_id == lead.id, FacebookLeadTrade.active.is_(True))))
                        actual = {key: getattr(lead, key) for key in DEFAULT_PROFILE
                                  if key not in {"trades", "work_communes", "name"}}
                        actual.update(name=lead.display_name,
                                      trades=sorted(trades or ([lead.specialty] if lead.specialty else [])),
                                      work_communes=sorted(getattr(lead, "work_communes", []) or []))
                        actual.update({key: getattr(lead, key) for key in EXTRA_PROFILE
                                       if hasattr(lead, key)})
                        for key in ("declared_origin", "crew_size", "preferred_contact", "worked_at_galilea", "notice_trade"):
                            entry = (lead.profile_sources or {}).get("_declared_context", {}).get(key) or {}
                            actual[key] = entry.get("value")
                        persisted = len(db.scalars(select(FacebookChatMessage.id).where(
                            FacebookChatMessage.lead_id == lead.id, FacebookChatMessage.remote_id == mid,
                            FacebookChatMessage.direction == "inbound")).all())
                        observed = []
                        if real_local:
                            for run_record in db.scalars(select(AssistantRun)):
                                if run_record.id in seen_runs:
                                    continue
                                stats = run_record.timings or {}
                                observed.append({"source": run_record.source, "intent": run_record.intent,
                                    "model": stats.get("response_model"), "fallback_reason": stats.get("fallback_reason"),
                                    "question_field": stats.get("question_field"),
                                    "guided_followup": stats.get("guided_followup"),
                                    "verified_guidance": stats.get("verified_guidance"),
                                    "fragments": stats.get("fragment_count"), "semantic_updates": stats.get("semantic_updates"),
                                    "elapsed_ms": run_record.elapsed_ms, "conversation_ms": stats.get("conversation_ms"),
                                    "input_tokens": stats.get("input_tokens"), "output_tokens": stats.get("output_tokens")})
                                calls_now = int(stats.get("local_model_calls") or 0)
                                local_calls += calls_now
                                case_model_calls += calls_now
                                input_tokens += int(stats.get("input_tokens") or 0)
                                output_tokens += int(stats.get("output_tokens") or 0)
                                if stats.get("response_model") == QWEN_2B:
                                    case_model_output += int(stats.get("output_tokens") or 0)
                                if stats.get("response_model"):
                                    observed_models.add(stats["response_model"])
                    if "trades" in expected:
                        expected["trades"] = sorted(expected["trades"])
                    if "work_communes" in expected:
                        expected["work_communes"] = sorted(expected["work_communes"])
                    replies = sent[start_count:]
                    answer = replies[-1] if replies else ""
                    answer_norm = plain(answer)
                    errors = {key: {"expected": value, "actual": actual[key]}
                              for key, value in expected.items() if
                              (plain(value) != plain(actual[key] or "") if key in {"crew_size", "declared_origin", "specialty"}
                               and isinstance(value, str) else value != actual[key])}
                    required = turn.get("reply_contains", [])
                    human_review = bool(actual["needs_support"])
                    handoff_without_reply = (human_review and actual["ai_paused"]
                                             and not awaiting_human and len(replies) == 0)
                    awaiting_human = human_review
                    # A turn that asks for a delivery must opt in to a silent handoff.
                    # Required answer content still needs to reach the user.
                    allows_handoff = (handoff_without_reply and not required
                                      and (not turn.get("replies", 0) or turn.get("allow_silent_handoff", False)))
                    forbidden = [*turn.get("reply_excludes", []), "ya estás contratado", "te adjudicamos",
                                 "contratación garantizada", "envíame tu RUT"]
                    question = plain(answer.rsplit("¿", 1)[-1]) if "?" in answer else ""
                    repeated = [field for field, phrases in KNOWN_FIELD_QUESTIONS.items()
                                if field in expected and expected[field] != DEFAULT_PROFILE.get(field)
                                and any(phrase in question for phrase in phrases)]
                    expected_intents = turn.get("intents", [])
                    checks = {
                        "webhook": response.status_code == 200 and (not turn.get("replay") or replay.status_code == 200),
                        "persisted_once": persisted == 1,
                        "single_coherent_reply": len(replies) <= 1 and answer.count("?") <= 1,
                        "expected_reply": (not turn.get("flush", True) or bool(answer) or allows_handoff) and
                                          all(plain(x) in answer_norm for x in required),
                        "does_not_echo_sender": not any(
                            plain(message) == answer_norm
                            and len(answer_norm.split()) >= (3 if "?" in message else 4)
                            for message in pending_inputs
                        ),
                        "avoids_known_questions": not repeated,
                        "no_unsupported_reply": not any(plain(x) in answer_norm for x in forbidden),
                        "profile": not errors,
                        **({"trade_coverage": all(plain(term) in plain(" ".join(actual["trades"]))
                                                  for term in turn["trade_terms"])}
                           if "trade_terms" in turn else {}),
                        **({"intent": any(item["intent"] in expected_intents for item in observed)}
                           if expected_intents else {}),
                        **({"batched": len(replies) == turn["replies"] or allows_handoff}
                           if "replies" in turn else {}),
                    }
                    turns.append({"turn": number, "message": redact(turn["message"]), "checks": checks,
                                  "profile_errors": redact(errors), "expected_profile": redact(expected),
                                  "extracted_profile": redact(actual), "runs": observed,
                                  "handoff_without_reply": handoff_without_reply,
                                  "repeated_fields": repeated, "reply": redact(answer),
                                  "elapsed_ms": round(elapsed, 3)})
                    if replies or turn.get("flush", True):
                        pending_inputs.clear()
                actual_inference = case_model_calls > 0 if real_local else None
                model_requirement_met = not case.get("requires_model", real_local) or case_model_output > 0
                results.append({"id": case["id"], "passed": all(all(t["checks"].values()) for t in turns)
                                and model_requirement_met, "model_requirement_met": model_requirement_met,
                                "real_model_output_tokens": case_model_output,
                                "category": case.get("category"), "real_model_attempted": actual_inference,
                                "model_calls": case_model_calls, "turns": turns})
                if real_local:
                    print(f'{case["id"]}: {("PASS" if results[-1]["passed"] else "FAIL")}', file=sys.stderr, flush=True)
            settings.cache_clear()
        engine.dispose()
    report = {"dataset": dataset.name, "conversations": len(cases), "turns": len(measurements),
            "passed": sum(r["passed"] for r in results),
            "failed_checks": sum(not check for r in results for turn in r["turns"] for check in turn["checks"].values()),
            "latency": metrics(measurements), "calls_simulated": calls, "tokens": input_tokens + output_tokens, "results": results}
    report["checks"] = {key: {"passed": sum(bool(turn["checks"].get(key)) for result in results for turn in result["turns"]),
                              "total": sum(key in turn["checks"] for result in results for turn in result["turns"])}
                        for key in sorted({key for result in results for turn in result["turns"] for key in turn["checks"]})}
    report["profile_fields"] = {
        "checked": sum(len(turn["expected_profile"]) for result in results for turn in result["turns"]),
        "errors": sum(len(turn["profile_errors"]) for result in results for turn in result["turns"])}
    if real_local:
        report.update(contextual_enabled=contextual, mode="real_local", local_model_calls=local_calls, input_tokens=input_tokens,
                      output_tokens=output_tokens, observed_models=sorted(observed_models),
                      real_model_verified=bool(output_tokens and observed_models == {QWEN_2B}),
                      production_verified=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DATA / "galancito_regresion_40.jsonl")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--real-local", action="store_true", help="Use real isolated Qwen; Meta stays simulated. Requires a Qwen-ready environment and explicit synthetic dataset.")
    parser.add_argument("--contextual", action="store_true", help="Enable the candidate Messenger runtime.")
    parser.add_argument("--ollama-loopback", action="store_true", help="Use Ollama on 127.0.0.1 for isolated evaluation.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    if args.real_local and args.cases == DATA / "galancito_regresion_40.jsonl":
        parser.error("Real-local mode requires a dedicated dataset with explicit independent expectations.")
    report = run(args.cases, args.source_root, real_local=args.real_local, contextual=args.contextual,
                 loopback=args.ollama_loopback, limit=args.limit, offset=args.offset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False))
    return 0 if report["passed"] == report["conversations"] and (not args.real_local or report["real_model_verified"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
