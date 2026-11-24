"""Contract tests for audited real-conversation practice (no external model calls)."""
from types import SimpleNamespace

from sqlalchemy import select

from test_ai_control_center import ai_env, signin
from app.ai_defect_learning import approved_coaching, learning_plan
from app.ai_quality_models import AIRealPracticeTrial
from app.facebook_crm_models import FacebookChatMessage, FacebookLead


def test_diagnosis_never_creates_fake_evidence():
    no_data = learning_plan([], "messenger")
    assert no_data["quality_grade"] is None
    assert all(x["priority"] == "sin_evidencia" and x["failure_percent"] is None
               for x in no_data["items"])
    reviews = [
        SimpleNamespace(ratings={"context": False, "safety": True}),
        SimpleNamespace(ratings={"context": True, "safety": False}),
    ]
    plan = learning_plan(reviews, "messenger")
    context = next(x for x in plan["items"] if x["criterion"] == "context")
    safety = next(x for x in plan["items"] if x["criterion"] == "safety")
    assert context["failed"] == 1 and context["failure_percent"] == 50
    assert safety["priority"] == "critica"
    assert plan["quality_grade"] is None


def test_unverifiable_criteria_are_not_counted_as_real_failures():
    from app.ai_quality_audit import ReviewInput
    valid = ReviewInput(run_id="0" * 36,
                        ratings={"context": None, "safety": True},
                        source_reviewed=True)
    assert valid.ratings["context"] is None
    sample = learning_plan([
        SimpleNamespace(ratings={"context": None, "safety": True}),
        SimpleNamespace(ratings={"context": False, "safety": None}),
    ], "messenger")
    context = next(row for row in sample["items"] if row["criterion"] == "context")
    assert context["reviewed"] == 1
    assert context["failed"] == 1 and context["failure_percent"] == 100
    assert context["not_assessable"] == 1
    safety = next(row for row in sample["items"] if row["criterion"] == "safety")
    assert safety["failed"] == 0 and safety["reviewed"] == 1


def test_real_chat_trial_requires_provenance_nonoverlap_and_human_review(ai_env, monkeypatch):
    from app import ai_real_learning_api
    from app.config import settings
    from app.galancito_knowledge_models import AssistantRun

    client, sessions = ai_env["client"], ai_env["sessions"]
    with sessions.begin() as db:
        for n in range(6):
            lead = FacebookLead(org_id=ai_env["org_id"], page_id="test-page",
                                psid=f"test-psid-{n}")
            db.add(lead)
            db.flush()
            db.add(FacebookChatMessage(org_id=ai_env["org_id"], lead_id=lead.id,
                                       page_id="test-page", direction="inbound",
                                       state="received",
                                       body="Hola, hago gasfitería y trabajo solo"))
            db.flush()
            outbound = FacebookChatMessage(org_id=ai_env["org_id"], lead_id=lead.id,
                                           page_id="test-page", direction="outbound",
                                           state="sent", ai_generated=True,
                                           body="¿Qué trabajo realizas?")
            db.add(outbound)
            db.flush()
            db.add(AssistantRun(org_id=ai_env["org_id"], channel="messenger",
                                source="ai", intent="intake", elapsed_ms=1500,
                                timings={"response_model": "qwen3.5:2b-q4_K_M",
                                         "outbound_message_id": outbound.id}))
    assert client.get("/api/v1/admin/ai/real-learning/plan").status_code == 401
    signin(client, "resident")
    assert client.get("/api/v1/admin/ai/real-learning/plan").status_code == 403
    headers = signin(client)
    base = "/api/v1/admin/ai"
    queue = client.get(base + "/audit/queue?channel=messenger").json()["items"]
    assert len(queue) == 6
    ids = [item["run_id"] for item in queue]
    criteria = {"understanding": True, "profile": True, "context": False,
                "naturalness": True, "safety": True, "helpfulness": True}
    rejected = client.post(base + "/real-learning/replay", headers=headers,
                           json={"source_id": ids[0], "criterion": "context"})
    assert rejected.status_code == 409
    for source_id in ids:
        result = client.post(base + "/audit/reviews", headers=headers, json={
            "run_id": source_id, "ratings": criteria, "source_reviewed": True})
        assert result.status_code == 201, result.text

    cases = client.get(base + "/real-learning/cases?channel=messenger").json()["items"]
    assert len(cases) == 6 and all(c["model_verified"] for c in cases)
    before = client.post(base + "/real-learning/proposals", headers=headers,
                         json={"channel": "messenger", "criterion": "context"})
    assert before.status_code == 409

    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("GALANCITO_LOCAL_MODEL", "qwen3.5:2b-q4_K_M")
    settings.cache_clear()
    calls = []

    def real_model(instructions, prompt, max_chars, thinking, seed):
        calls.append((instructions, prompt, thinking, seed))
        return ("Ya me contaste que haces gasfitería. ¿En qué comuna puedes trabajar?"
                if "CORRECCIÓN EN ENSAYO" in instructions else "¿Qué trabajo realizas?")

    monkeypatch.setattr(ai_real_learning_api, "generate_local_text", real_model)
    monkeypatch.setattr(ai_real_learning_api, "infer", lambda db, fn: fn())
    monkeypatch.setattr(
        ai_real_learning_api, "last_timings",
        SimpleNamespace(get=lambda: {"response_model": "other/model"}),
    )
    mismatch = client.post(base + "/real-learning/replay", headers=headers,
                           json={"source_id": ids[0], "criterion": "context"})
    assert mismatch.status_code == 503
    monkeypatch.setattr(
        ai_real_learning_api, "last_timings",
        SimpleNamespace(get=lambda: {"response_model": "qwen3.5:2b-q4_K_M",
                                     "generation_ms": 1800}),
    )
    for i, source_id in enumerate(ids):
        reply = client.post(base + "/real-learning/replay", headers=headers,
                            json={"source_id": source_id, "criterion": "context",
                                  "variant": "focused"})
        assert reply.status_code == 200, reply.text
        body = reply.json()
        assert body["source"] == "actual_local_qwen_on_audited_production_chat"
        assert body["provenance"] == "model_verified"
        assert body["stage"] == ("practice" if i < 2 else "holdout")
        assert "hago gasfitería" in calls[-1][1]
        assert calls[-1][2] is False
        assert body["original"] == "¿Qué trabajo realizas?"
        assert body["candidate"] and body["baseline"] and body["candidate"] != body["baseline"]
        assert calls[-1][3] == calls[-2][3]
        assert client.get(base + "/real-learning/pending").json()["items"]
        trial_id = body["trial_id"]
        assert client.post(base + "/real-learning/replay", headers=headers,
                           json={"source_id": source_id,
                                 "criterion": "context"}).status_code == 409
        fake_rating = client.post(base + "/real-learning/trials/" + trial_id +
                                  "/review", headers=headers, json={
            "outcome": "better", "verification_nonce": "0" * 36,
            "source_reviewed": True})
        assert fake_rating.status_code == 409
        verdict = client.post(base + "/real-learning/trials/" + trial_id +
                              "/review", headers=headers, json={
            "outcome": "better",
            "verification_nonce": body["verification_nonce"],
            "criterion_resolved": True, "safety_passed": True,
            "source_reviewed": True})
        assert verdict.status_code == 200, verdict.text
        assert verdict.json()["overall_improvement_proven"] is False
        assert client.post(base + "/real-learning/trials/" + trial_id +
                           "/review", headers=headers, json={
            "outcome": "better",
            "verification_nonce": body["verification_nonce"],
            "source_reviewed": True}).status_code == 409
        if i == 1:
            not_yet = client.post(base + "/real-learning/proposals", headers=headers,
                                  json={"channel": "messenger",
                                        "criterion": "context"})
            assert not_yet.status_code == 409

    status = client.get(base + "/real-learning/plan").json()
    item = next(i for i in status["channels"]["messenger"]["items"]
                if i["criterion"] == "context")
    assert item["proposal_ready"] is True
    assert item["holdout"]["practice_wins"] == 2
    assert item["holdout"]["holdout_wins"] == 4
    assert item["practice"]["better"] == 6

    proposal = client.post(base + "/real-learning/proposals", headers=headers,
                           json={"channel": "messenger", "criterion": "context"})
    assert proposal.status_code == 201, proposal.text
    assert proposal.json()["status"] == "pending"
    with sessions() as db:
        assert approved_coaching(db, ai_env["org_id"], "messenger") == ""
        trials = list(db.scalars(select(AIRealPracticeTrial)))
        assert len(trials) == 6
        assert not hasattr(trials[0], "question") and not hasattr(trials[0], "answer")

    knowledge = client.get("/api/v1/network/galancito/knowledge").json()
    row = next(r for r in knowledge if r["id"] == proposal.json()["id"])
    changed = client.post("/api/v1/network/galancito/knowledge/" + row["id"] +
                          "/state", headers=headers,
                          json={"version": row["version"], "state": "approved"})
    assert changed.status_code == 200, changed.text
    with sessions() as db:
        assert "No repitas" in approved_coaching(db, ai_env["org_id"], "messenger")

    signin(client, "outside")
    separate = client.get(base + "/real-learning/plan").json()
    assert separate["channels"]["messenger"]["reviewed_cases"] == 0
    settings.cache_clear()


def test_cancel_lost_trial_and_retry_without_fabricating_result(ai_env, monkeypatch):
    from app import ai_real_learning_api
    from app.config import settings
    from app.galancito_knowledge_models import AssistantRun
    client, sessions = ai_env["client"], ai_env["sessions"]
    with sessions.begin() as db:
        lead = FacebookLead(org_id=ai_env["org_id"], page_id="test-page",
                            psid="test-psid-new")
        db.add(lead)
        db.flush()
        db.add(FacebookChatMessage(org_id=ai_env["org_id"], lead_id=lead.id,
                                   page_id="test-page", direction="inbound",
                                   state="received", body="Trabajo en carpintería"))
        db.flush()
        message = FacebookChatMessage(org_id=ai_env["org_id"], lead_id=lead.id,
                                      page_id="test-page", direction="outbound",
                                      state="sent", ai_generated=True,
                                      body="¿En qué oficio trabajas?")
        db.add(message)
        db.flush()
        db.add(AssistantRun(org_id=ai_env["org_id"], channel="messenger",
                            source="ai", intent="intake", elapsed_ms=2000,
                            timings={"response_model": "qwen3.5:2b-q4_K_M",
                                     "outbound_message_id": message.id}))
        source_id = message.id
    headers = signin(client)
    base = "/api/v1/admin/ai"
    rubric = {"understanding": True, "profile": True, "context": False,
              "naturalness": True, "safety": True, "helpfulness": True}
    assert client.post(base + "/audit/reviews", headers=headers,
                       json={"run_id": source_id, "ratings": rubric,
                             "source_reviewed": True}).status_code == 201
    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("GALANCITO_LOCAL_MODEL", "qwen3.5:2b-q4_K_M")
    settings.cache_clear()
    monkeypatch.setattr(ai_real_learning_api, "infer", lambda _db, fn: fn())
    monkeypatch.setattr(ai_real_learning_api, "generate_local_text",
                        lambda instructions, *_a, **_kw: (
                            "Ya me dijiste carpintería. ¿En qué comuna trabajas?"
                            if "CORRECCIÓN EN ENSAYO" in instructions else "¿En qué oficio trabajas?"))
    monkeypatch.setattr(ai_real_learning_api, "last_timings",
                        SimpleNamespace(get=lambda: {"response_model": "qwen3.5:2b-q4_K_M"}))
    first = client.post(base + "/real-learning/replay", headers=headers,
                        json={"source_id": source_id, "criterion": "context"})
    assert first.status_code == 200, first.text
    trial_id = first.json()["trial_id"]
    assert trial_id in [x["id"] for x in client.get(base + "/real-learning/pending").json()["items"]]
    reset = client.post(base + "/real-learning/trials/" + trial_id + "/cancel",
                        headers=headers)
    assert reset.status_code == 200, reset.text
    assert not client.get(base + "/real-learning/pending").json()["items"]
    assert client.post(base + "/real-learning/trials/" + trial_id + "/review",
                       headers=headers, json={"outcome": "better",
                       "verification_nonce": first.json()["verification_nonce"],
                       "source_reviewed": True}).status_code == 409
    retry = client.post(base + "/real-learning/replay", headers=headers,
                        json={"source_id": source_id, "criterion": "context",
                              "variant": "alternative"})
    assert retry.status_code == 200 and retry.json()["trial_id"] != trial_id
    settings.cache_clear()


def test_corrections_dont_exceed_local_prompt_or_override_safety():
    from app.facebook_ai import LOCAL_REPLY_INSTRUCTIONS
    from app.galancito_local import MAX_INSTRUCTIONS_CHARS
    from app.ai_defect_learning import candidate_policy, diagnostic_route, eligible_for_proposal
    assert "No finjas ser humano" in LOCAL_REPLY_INSTRUCTIONS
    assert "NUNCA solicites RUT" in LOCAL_REPLY_INSTRUCTIONS
    for channel in ("messenger", "general"):
        for key in ("context", "safety"):
            for variant in ("focused", "alternative"):
                prompt = LOCAL_REPLY_INSTRUCTIONS + candidate_policy(channel, key, variant)
                assert len(prompt) < MAX_INSTRUCTIONS_CHARS
    assert diagnostic_route(None, "context")["replay_fidelity"] == "parcial"
    assert not eligible_for_proposal([])["ready"]



def test_approved_coaching_uses_system_instructions_and_rejects_truncation(monkeypatch):
    from app import facebook_ai
    from app.galancito_local import MAX_INSTRUCTIONS_CHARS
    cfg = SimpleNamespace(facebook_ai_provider="ollama", facebook_ai_enabled=True,
                          galancito_local_ai_enabled=True)
    monkeypatch.setattr(facebook_ai, "settings", lambda: cfg)
    captured = []
    def fake_model(instructions, supplied, max_chars):
        captured.append((instructions, supplied, max_chars))
        return "Mensaje de prueba"
    monkeypatch.setattr(facebook_ai, "generate_local_text", fake_model)
    policy = "No repitas una pregunta respondida."
    output = facebook_ai.generate_text(facebook_ai.REPLY_INSTRUCTIONS,
                                       "¿En qué comuna trabajas?", 550,
                                       approved_policy=policy)
    assert output == "Mensaje de prueba"
    instructions, supplied, _ = captured[0]
    assert instructions.startswith(facebook_ai.LOCAL_REPLY_INSTRUCTIONS)
    assert instructions.endswith(policy)
    assert len(instructions) < MAX_INSTRUCTIONS_CHARS
    assert supplied == "¿En qué comuna trabajas?"
    from pytest import raises
    with raises(ValueError):
        facebook_ai.generate_text(facebook_ai.REPLY_INSTRUCTIONS,
                                  "Consulta breve", 550,
                                  approved_policy="no" * MAX_INSTRUCTIONS_CHARS)
    assert len(captured) == 1
