#!/usr/bin/env python3
"""Evaluate signed Messenger conversations on a fresh SQLite DB with simulated Meta."""
import argparse
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "apps/backend/tests/fixtures"
DEFAULT_PROFILE = {
    "name": "Interesado de Facebook", "interest_type": "unknown", "entity_type": "unknown",
    "trades": [], "work_communes": [], "availability": "", "experience": "",
    "team_available": None, "workers": None, "has_employees": None,
    "documents_state": "unverified", "name_opt_out": False, "ai_consent": False,
}

KNOWN_FIELD_QUESTIONS = {
    "name": ("cual es tu nombre", "como te llamas", "como prefieres que te llamemos"),
    "trades": ("que oficio", "que trabajo realizas", "que trabajo haces"),
    "interest_type": ("ofreces trabajos por tu cuenta",),
    "work_communes": ("en que comuna",),
    "availability": ("desde cuando",),
    "experience": ("cuanto tiempo llevas",),
    "team_available": ("trabajas solo",),
    "workers": ("cuantas personas",),
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
            if not isinstance(turn.get("message"), str) or set(turn.get("profile", {})) - DEFAULT_PROFILE.keys():
                raise ValueError(f'{case["id"]} contiene un mensaje o campo no admitido.')
    return cases


def metrics(values):
    if not values:
        return {"p50_ms": None, "p95_ms": None}
    ordered = sorted(values)
    return {"p50_ms": round(median(ordered), 3),
            "p95_ms": round(ordered[math.ceil(.95 * len(ordered)) - 1], 3)}


def run(dataset, source_root):
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
    from app.main import app as _full_app  # Register related tables on Base.
    from app.models import Organization
    from app.facebook_chat_worker import process_chat_next

    cases = load_cases(dataset)
    application = FastAPI()
    application.include_router(router)
    sent, measurements, results = [], [], []
    calls = {"graph_send": 0, "graph_sender_action": 0, "external_ai": 0}

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
            "FACEBOOK_PAGE_TOKEN": "simulated-meta", "FACEBOOK_AI_PROVIDER": "openai",
            "FACEBOOK_AI_API_KEY": "", "GALANCITO_LOCAL_AI_ENABLED": "false",
        }
        with (patch.dict(os.environ, env),
              patch("app.facebook_chat_worker.graph_send", graph_send),
              patch("app.facebook_chat_worker.graph_sender_action", graph_action),
              patch("app.facebook_chat_worker.generate_text", unexpected_ai),
              TestClient(application) as client):
            settings.cache_clear()
            for index, case in enumerate(cases, start=1):
                psid = str(70000000000 + index)
                expected = dict(DEFAULT_PROFILE)
                turns = []
                for number, turn in enumerate(case["turns"], start=1):
                    expected.update(turn.get("profile", {}))
                    mid = f"synthetic-{index}-{number}"
                    data = json.dumps({"object": "page", "entry": [{"id": env["FACEBOOK_PAGE_ID"],
                        "messaging": [{"sender": {"id": psid},
                                       "message": {"mid": mid, "text": turn["message"]}}]}]}).encode()
                    signature = hmac.new(env["FACEBOOK_APP_SECRET"].encode(), data, hashlib.sha256).hexdigest()
                    headers = {"X-Hub-Signature-256": f"sha256={signature}"}
                    started, start_count = perf_counter(), len(sent)
                    response = client.post("/api/v1/network/facebook/webhook", content=data, headers=headers)
                    if turn.get("replay"):
                        replay = client.post("/api/v1/network/facebook/webhook", content=data, headers=headers)
                    if turn.get("flush", True):
                        for _ in range(5):
                            if not process_chat_next(session):
                                break
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
                        persisted = len(db.scalars(select(FacebookChatMessage.id).where(
                            FacebookChatMessage.lead_id == lead.id, FacebookChatMessage.remote_id == mid,
                            FacebookChatMessage.direction == "inbound")).all())
                    expected["trades"] = sorted(expected["trades"])
                    expected["work_communes"] = sorted(expected["work_communes"])
                    replies = sent[start_count:]
                    answer = replies[-1] if replies else ""
                    answer_norm = plain(answer)
                    errors = {key: {"expected": value, "actual": actual[key]}
                              for key, value in expected.items() if value != actual[key]}
                    required = turn.get("reply_contains", [])
                    forbidden = [*turn.get("reply_excludes", []), "ya estás contratado", "te adjudicamos",
                                 "contratación garantizada", "envíame tu RUT"]
                    question = plain(answer.rsplit("¿", 1)[-1]) if "?" in answer else ""
                    repeated = [field for field, phrases in KNOWN_FIELD_QUESTIONS.items()
                                if expected[field] != DEFAULT_PROFILE[field]
                                and any(phrase in question for phrase in phrases)]
                    checks = {
                        "webhook": response.status_code == 200 and (not turn.get("replay") or replay.status_code == 200),
                        "persisted_once": persisted == 1,
                        "single_coherent_reply": len(replies) <= 1 and answer.count("?") <= 1,
                        "expected_reply": (not turn.get("flush", True) or bool(answer)) and
                                          all(plain(x) in answer_norm for x in required),
                        "avoids_known_questions": not repeated,
                        "no_unsupported_reply": not any(plain(x) in answer_norm for x in forbidden),
                        "profile": not errors,
                    }
                    turns.append({"turn": number, "checks": checks, "profile_errors": errors,
                                  "repeated_fields": repeated, "reply": answer,
                                  "elapsed_ms": round(elapsed, 3)})
                results.append({"id": case["id"], "passed": all(all(t["checks"].values()) for t in turns),
                                "turns": turns})
            settings.cache_clear()
        engine.dispose()
    return {"dataset": dataset.name, "conversations": len(cases), "turns": len(measurements),
            "passed": sum(r["passed"] for r in results),
            "failed_checks": sum(not check for r in results for turn in r["turns"] for check in turn["checks"].values()),
            "latency": metrics(measurements), "calls_simulated": calls, "tokens": 0, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DATA / "galancito_regresion_40.jsonl")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.cases, args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False))
    return 0 if report["passed"] == report["conversations"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
