"""Historical evidence covers all retained metadata, without using raw chat text."""
from datetime import timedelta
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from app.ai_quality_models import AIResponseReview, AIRealPracticeTrial
from app.facebook_crm_models import FacebookChatMessage, FacebookLead
from app.galancito_knowledge_models import AssistantRun
from app.galancito_finetune_dataset import bucket, load_approved, verified_match
from app.models import User, utcnow
from test_ai_control_center import ai_env, signin


BASE = "/api/v1/admin/ai/real-learning"


def test_historical_inventory_is_private_and_includes_old_records(ai_env):
    client, sessions, org_id = ai_env["client"], ai_env["sessions"], ai_env["org_id"]
    old = utcnow() - timedelta(days=160)
    with sessions.begin() as db:
        reviewer = db.query(User).filter(User.org_id == org_id, User.role == "admin").one()
        lead = FacebookLead(org_id=org_id, page_id="history-page", psid="historic-only")
        db.add(lead)
        db.flush()
        db.add(FacebookChatMessage(org_id=org_id, lead_id=lead.id, page_id="history-page",
                                   direction="outbound", state="sent", ai_generated=True,
                                   body="CONFIDENTIAL-HISTORIC-MESSAGE", created_at=old))
        run = AssistantRun(org_id=org_id, channel="messenger", source="ai",
                           elapsed_ms=16000, feedback="incorrect", created_at=old,
                           timings={"trace_version": 1, "context_truncated": True,
                                    "model_requested": True, "context_turns": 0})
        db.add(run)
        db.flush()
        review = AIResponseReview(
            org_id=org_id, reviewer_id=reviewer.id, channel="messenger",
            rubric_version=1, evidence_kind="messenger_message",
            evidence_id="11111111-1111-1111-1111-111111111111",
            source_at=old, ratings={"context": False, "safety": None})
        db.add(review)
        db.flush()
        db.add(AIRealPracticeTrial(org_id=org_id, review_id=review.id,
                                   reviewer_id=reviewer.id, channel="messenger",
                                   criterion="context", model="qwen3.5:4b-q4_K_M",
                                   elapsed_ms=1500, outcome="better", created_at=old))

    assert client.get(BASE + "/history").status_code == 401
    signin(client, "resident")
    assert client.get(BASE + "/history").status_code == 403
    signin(client, "admin")
    response = client.get(BASE + "/history?months=0")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["window"] == "all_retained"
    assert result["sources"]["runs"]["count"] == 1
    assert result["sources"]["delivered_messenger"]["count"] == 1
    assert sum(row["count"] for row in result["timeline"]["messenger_delivered"]) == 1
    assert result["sources"]["reviews"]["count"] == 1
    assert result["sources"]["practice_trials"]["count"] == 1
    assert result["audited_deficiencies"]["messenger"]["context"]["failed"] == 1
    assert result["audited_deficiencies"]["messenger"]["context"]["failure_percent"] == 100
    assert result["audited_deficiencies"]["messenger"]["safety"]["assessed"] == 0
    assert result["runs_by_channel"]["messenger"]["reported_incorrect"] == 1
    forensic = result["diagnostic_telemetry"]
    assert forensic["full_coverage"] is True
    assert forensic["signals"]["context_truncated"] == 1
    assert forensic["signals"]["model_called_without_history"] == 1
    assert forensic["signals"]["slow_turns_over_15s"] == 1
    assert result["historical_quality_grade"] is None
    assert result["weights_updated"] is None
    assert result["neural_training_evidence"] == "not_recorded_in_galant"
    assert "CONFIDENTIAL-HISTORIC-MESSAGE" not in response.text
    recent = client.get(BASE + "/history?months=1").json()
    assert recent["sources"]["runs"]["count"] == 0
    assert recent["sources"]["reviews"]["count"] == 0
    assert client.get(BASE + "/history?months=61").status_code == 422
    signin(client, "outside")
    other = client.get(BASE + "/history").json()
    assert other["sources"]["runs"]["count"] == 0
    assert other["sources"]["reviews"]["count"] == 0


def _example(number):
    return {
        "source": "human_reviewed_real",
        "approved_by": "00000000-0000-0000-0000-000000000001",
        "usage_authorized": True, "privacy_reviewed": True,
        "case_group": sha256(f"group:{number}".encode()).hexdigest(),
        "criterion": "reasoning", "verifier": "exact",
        "reference_answer": f"Resultado {number + 2}",
        "messages": [
            {"role": "user", "content": f"Calcula: {number} más dos"},
            {"role": "assistant", "content": f"Resultado {number + 2}"},
        ],
    }


def test_training_data_gate_rejects_synthetic_private_and_duplicate(tmp_path):
    path = tmp_path / "training.jsonl"
    examples = [_example(n) for n in range(200)]
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in examples) + "\n",
                    encoding="utf-8")
    ready = load_approved(path)
    assert all(ready["sizes"][name] >= minimum
               for name, minimum in {"train": 30, "validation": 10, "test": 10}.items())
    assert sum(ready["sizes"].values()) == 200
    assert ready["attestations_present"] is True
    assert ready["human_approval_independently_verified"] is False
    assert ready["dataset_digest"] and "samples" in ready
    assert verified_match("Respuesta final", "respuesta final", "exact") is True
    assert verified_match("No es respuesta final", "respuesta final", "exact") is False
    assert verified_match("Valor 14", "14", "contains") is True

    bad = _example(1000)
    bad["source"] = "synthetic"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="no autorizado"):
        load_approved(path, enforce_minimum=False)
    bad["source"] = "human_reviewed_real"
    bad["usage_authorized"] = False
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="no autorizado"):
        load_approved(path, enforce_minimum=False)
    bad["usage_authorized"] = True
    bad["messages"][0]["content"] = "Mi correo es nombre@example.cl"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="dato personal"):
        load_approved(path, enforce_minimum=False)
    one = _example(800)
    path.write_text(json.dumps(one), encoding="utf-8")
    with pytest.raises(ValueError, match="insuficientes"):
        load_approved(path)
    path.write_text(json.dumps(one) + "\n" + json.dumps(one), encoding="utf-8")
    with pytest.raises(ValueError, match="pregunta repetida"):
        load_approved(path, enforce_minimum=False)


def test_historical_history_is_sql_aggregated_not_chat_content(ai_env):
    client = ai_env["client"]
    signin(client)
    response = client.get(BASE + "/history")
    assert response.status_code == 200
    result = response.json()
    assert result["sources"]["delivered_messenger"]["count"] == 0
    assert result["historical_quality_grade"] is None
    assert all(item for item in result["limitations"])



def test_next_practice_uses_historic_reviews_to_prioritize_recent_evidence(ai_env):
    """Old approved labels steer new practice; old private chat is never replayed."""
    client, sessions, org_id = ai_env["client"], ai_env["sessions"], ai_env["org_id"]
    old = utcnow() - timedelta(days=160)
    now = utcnow()
    with sessions.begin() as db:
        reviewer = db.query(User).filter(User.org_id == org_id, User.role == "admin").one()
        for n in range(4):
            db.add(AIResponseReview(
                org_id=org_id, reviewer_id=reviewer.id, channel="messenger",
                rubric_version=1, evidence_kind="messenger_message",
                evidence_id=f"22222222-2222-2222-2222-{n:012d}",
                source_at=old, ratings={"profile": False, "context": True}))
        for n, failed in enumerate(("context", "profile")):
            lead = FacebookLead(org_id=org_id, page_id="recent-page",
                                psid=f"priority-lead-{n}")
            db.add(lead)
            db.flush()
            db.add(FacebookChatMessage(
                org_id=org_id, lead_id=lead.id, page_id="recent-page",
                direction="inbound", state="received",
                body="Soy carpintero de obra y busco trabajo", created_at=now))
            db.flush()
            outbound = FacebookChatMessage(
                org_id=org_id, lead_id=lead.id, page_id="recent-page",
                direction="outbound", state="sent", ai_generated=True,
                body="¿Cuál es tu oficio?", created_at=now)
            db.add(outbound)
            db.flush()
            db.add(AssistantRun(
                org_id=org_id, channel="messenger", source="ai",
                elapsed_ms=1234, created_at=now,
                timings={"response_model": "qwen3.5:4b-q4_K_M",
                         "outbound_message_id": outbound.id}))
            db.add(AIResponseReview(
                org_id=org_id, reviewer_id=reviewer.id, channel="messenger",
                rubric_version=1, evidence_kind="messenger_message",
                evidence_id=outbound.id, source_at=now,
                ratings={"context": failed != "context",
                         "profile": failed != "profile"}))
    signin(client)
    next_case = client.get(BASE + "/next?channel=messenger")
    assert next_case.status_code == 200, next_case.text
    result = next_case.json()
    assert result["available"] is True
    assert result["criterion"] == "profile"
    assert result["observed_defects"] == 5
    assert result["historically_assessed"] == 5
    assert result["recent_defects"] == 1
    assert result["recently_assessed"] == 2
    assert result["source_id"]
    assert "frecuencia histórica" in result["reason"]



def test_signed_training_manifest_requires_exact_dataset_and_known_ed25519_key(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from app.galancito_finetune_dataset import MODEL, verified_training_manifest

    dataset_path = tmp_path / "human-reviewed.jsonl"
    dataset_path.write_text(json.dumps(_example(95), ensure_ascii=False) + "\n",
                            encoding="utf-8")
    digest = sha256(dataset_path.read_bytes()).hexdigest()
    signing_key = Ed25519PrivateKey.generate()
    public = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    statement = {
        "dataset_sha256": digest,
        "approved_by": "00000000-0000-0000-0000-000000000001",
        "approved_at": "2026-11-23T02:00:00Z",
        "privacy_reviewed": True, "usage_authorized": True,
        "training_model": MODEL, "purpose": "offline_galant_finetune_qwen",
    }
    canonical = json.dumps(statement, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":")).encode()
    signature = signing_key.sign(canonical).hex()
    manifest = tmp_path / "approval.json"
    manifest.write_text(json.dumps({**statement, "signature_ed25519": signature}),
                        encoding="utf-8")
    verified = verified_training_manifest(dataset_path, manifest, public)
    assert verified["signed"] is True
    assert verified["dataset_digest"] == digest
    with pytest.raises(ValueError, match="Firma"):
        verified_training_manifest(dataset_path, manifest, "00" * 32)
    dataset_path.write_text(dataset_path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manifiesto no aprueba|manifiesto no aprueba|no aprueba"):
        verified_training_manifest(dataset_path, manifest, public)
    dataset_path.write_text(json.dumps(_example(95)) + "\n", encoding="utf-8")
    statement["usage_authorized"] = False
    manifest.write_text(json.dumps({**statement, "signature_ed25519": signature}),
                        encoding="utf-8")
    with pytest.raises(ValueError, match="Firma"):
        verified_training_manifest(dataset_path, manifest, public)



def test_model_does_not_claim_learning_when_context_was_truncated(ai_env):
    from app.galancito_knowledge_models import AssistantRun
    client, sessions, org_id = ai_env["client"], ai_env["sessions"], ai_env["org_id"]
    with sessions.begin() as db:
        reviewer = db.query(User).filter(User.org_id == org_id, User.role == "admin").one()
        lead = FacebookLead(org_id=org_id, page_id="context-page", psid="context-lead")
        db.add(lead)
        db.flush()
        db.add(FacebookChatMessage(
            org_id=org_id, lead_id=lead.id, page_id="context-page",
            direction="inbound", state="received", body="Hago electricidad, ya lo expliqué"))
        db.flush()
        reply = FacebookChatMessage(
            org_id=org_id, lead_id=lead.id, page_id="context-page",
            direction="outbound", state="sent", ai_generated=True,
            body="¿En qué oficio trabajas?")
        db.add(reply)
        db.flush()
        db.add(AssistantRun(org_id=org_id, channel="messenger",
                            source="ai", elapsed_ms=2500,
                            timings={"response_model": "qwen3.5:4b-q4_K_M",
                                     "context_truncated": True,
                                     "outbound_message_id": reply.id}))
        db.add(AIResponseReview(
            org_id=org_id, reviewer_id=reviewer.id,
            channel="messenger", evidence_kind="messenger_message",
            evidence_id=reply.id, source_at=utcnow(),
            ratings={"context": False, "profile": True},
            rubric_version=1))
    signin(client)
    result = client.get(BASE + "/next?channel=messenger")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["available"] is False
    assert body["engineering_findings"][0]["hypothesis"] == "contexto_truncado"
    assert body["engineering_findings"][0]["mechanism"] == "reducir_contexto_o_priorizar_memoria"
    assert body["automatic_approval"] is False
