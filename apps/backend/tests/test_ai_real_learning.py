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


def test_real_chat_trial_requires_audited_failure_and_human_review(ai_env, monkeypatch):
    from app import ai_real_learning_api
    from app.config import settings

    client, sessions = ai_env["client"], ai_env["sessions"]
    with sessions.begin() as db:
        for n in range(2):
            lead = FacebookLead(org_id=ai_env["org_id"], page_id="test-page", psid=f"test-psid-{n}")
            db.add(lead)
            db.flush()
            db.add(FacebookChatMessage(org_id=ai_env["org_id"], lead_id=lead.id,
                                       page_id="test-page", direction="inbound",
                                       state="received", body="Hola, hago gasfitería y trabajo solo"))
            db.flush()
            out = FacebookChatMessage(org_id=ai_env["org_id"], lead_id=lead.id,
                                      page_id="test-page", direction="outbound",
                                      state="sent", ai_generated=True,
                                      body="¿Qué trabajo realizas?")
            db.add(out)
            db.flush()

    assert client.get("/api/v1/admin/ai/real-learning/plan").status_code == 401
    signin(client, "resident")
    assert client.get("/api/v1/admin/ai/real-learning/plan").status_code == 403
    headers = signin(client)
    base = "/api/v1/admin/ai"
    queue = client.get(base + "/audit/queue?channel=messenger").json()["items"]
    assert len(queue) == 2
    ids = [item["run_id"] for item in queue]
    rubric = {"understanding": True, "profile": True, "context": False,
              "naturalness": True, "safety": True, "helpfulness": True}
    not_audited = client.post(base + "/real-learning/replay", headers=headers,
                              json={"source_id": ids[0], "criterion": "context"})
    assert not_audited.status_code == 409
    for ident in ids:
        review = client.post(base + "/audit/reviews", headers=headers,
                             json={"run_id": ident, "ratings": rubric,
                                   "source_reviewed": True})
        assert review.status_code == 201, review.text

    data = client.get(base + "/real-learning/plan").json()
    item = next(x for x in data["channels"]["messenger"]["items"] if x["criterion"] == "context")
    assert item["failed"] == 2 and item["proposal_ready"] is False
    assert item["failure_percent"] == 100

    before = client.post(base + "/real-learning/proposals", headers=headers,
                         json={"channel": "messenger", "criterion": "context"})
    assert before.status_code == 409

    monkeypatch.setenv("GALANCITO_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("GALANCITO_LOCAL_MODEL", "qwen3.5:4b-q4_K_M")
    settings.cache_clear()
    seen = []
    def model(instructions, prompt, max_chars, thinking):
        seen.append((instructions, prompt, thinking))
        return "Entiendo que ya trabajas en gasfitería. ¿En qué comuna puedes trabajar?"
    monkeypatch.setattr(ai_real_learning_api, "generate_local_text", model)
    monkeypatch.setattr(ai_real_learning_api, "infer", lambda db, fn: fn())
    for ident in ids:
        reply = client.post(base + "/real-learning/replay", headers=headers,
                            json={"source_id": ident, "criterion": "context"})
        assert reply.status_code == 200, reply.text
        assert reply.json()["source"] == "actual_local_qwen_on_audited_production_chat"
        assert "hago gasfitería" in seen[-1][1]
        assert seen[-1][2] is False
        assert "¿Qué trabajo realizas?" == reply.json()["original"]
        trial_id = reply.json()["trial_id"]
        assert client.post(base + "/real-learning/replay", headers=headers,
                           json={"source_id": ident, "criterion": "context"}).status_code == 409
        verdict = client.post(base + "/real-learning/trials/" + trial_id + "/review",
                              headers=headers, json={"outcome": "better", "source_reviewed": True})
        assert verdict.status_code == 200, verdict.text
        assert verdict.json()["overall_improvement_proven"] is False
        assert client.post(base + "/real-learning/trials/" + trial_id + "/review",
                           headers=headers, json={"outcome": "better",
                                                   "source_reviewed": True}).status_code == 409

    plan = client.get(base + "/real-learning/plan").json()
    item = next(x for x in plan["channels"]["messenger"]["items"] if x["criterion"] == "context")
    assert item["proposal_ready"] is True and item["practice"]["better"] == 2
    proposal = client.post(base + "/real-learning/proposals", headers=headers,
                           json={"channel": "messenger", "criterion": "context"})
    assert proposal.status_code == 201, proposal.text
    assert proposal.json()["status"] == "pending"
    with sessions() as db:
        assert approved_coaching(db, ai_env["org_id"], "messenger") == ""
        trials = list(db.scalars(select(AIRealPracticeTrial)))
        assert len(trials) == 2
        # Persist no original question or Qwen-generated candidate.
        assert not hasattr(trials[0], "question") and not hasattr(trials[0], "answer")
    row = next(row for row in client.get("/api/v1/network/galancito/knowledge").json()
               if row["id"] == proposal.json()["id"])
    assert client.post("/api/v1/network/galancito/knowledge/" + row["id"] + "/state",
                       headers=headers, json={"version": row["version"], "state": "approved"}).status_code == 200
    with sessions() as db:
        assert "no repitas" in approved_coaching(db, ai_env["org_id"], "messenger").lower()

    signin(client, "outside")
    separate = client.get(base + "/real-learning/plan").json()
    assert separate["channels"]["messenger"]["reviewed_cases"] == 0
    settings.cache_clear()
