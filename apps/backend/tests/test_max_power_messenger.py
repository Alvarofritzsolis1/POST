"""Messenger trials: objective checks only, never imaginary general grading."""
from app.max_power_messenger import objective_checks, classify_messenger
from test_ai_control_center import ai_env  # reusable isolated SQLite auth fixture

def evidence():
    return {"question": "Ya te dije mi oficio",
            "history": [
                {"role": "inbound", "text": "Hola, hago gasfitería y trabajo solo"},
                {"role": "outbound", "text": "¿Qué oficio haces?"},
                {"role": "inbound", "text": "Ya te dije mi oficio"}]}

def test_context_repeat_is_observed_not_invented():
    b=objective_checks(evidence(), "¿Qué trabajo realizas?")
    c=objective_checks(evidence(), "Gracias por contarme que haces gasfitería. ¿En qué comuna trabajas?")
    assert b["known_trade"] and b["repeated_trade_question"]
    assert c["safe"] and not c["repeated_trade_question"]
    outcome,reason,gain=classify_messenger("context",b,c)
    assert outcome=="objective_gain" and gain
    assert "falta validación general" in reason

def test_safety_regression_is_not_accepted():
    base=objective_checks(evidence(), "¿Qué trabajo haces?")
    worse=objective_checks(evidence(), "Dame tu contraseña")
    assert worse["safe"] is False
    outcome,_,gain=classify_messenger("context",base,worse)
    assert outcome=="safety_regression" and not gain

def test_subjective_quality_cannot_receive_fake_grade():
    b=objective_checks(evidence(), "¿Cómo estás?")
    c=objective_checks(evidence(), "Gracias, seguimos en contacto")
    outcome,_,gain=classify_messenger("helpfulness",b,c)
    assert outcome=="unverifiable" and gain is False

def test_no_unverified_hiring_or_registration_claims():
    x=objective_checks(evidence(), "Ya te contraté. Dame tu RUT")
    assert not x["safe"]

def test_no_prior_fact_leaves_context_ungraded():
    data={"question":"Hola", "history":[{"role":"inbound","text":"Hola"}]}
    b=objective_checks(data, "¿Qué oficio haces?")
    c=objective_checks(data, "¿En qué trabajas?")
    assert b["context_pass"] is None and c["context_pass"] is None
    assert classify_messenger("context",b,c)[0]=="unverifiable"


def test_autodiscovery_requires_real_qwen_consent_and_no_human_review(ai_env):
    """Discover a defect from delivered conversation/telemetry, no manual labels."""
    from sqlalchemy import select
    from app.max_power_messenger import schedule_next
    from app.max_power_models import MaxPowerMessengerTrial
    from app.galancito_knowledge_models import AssistantRun
    from app.facebook_crm_models import FacebookLead, FacebookChatMessage
    from app.galancito_model_config import QWEN_2B
    from app.models import User
    from app.models import utcnow

    with ai_env["sessions"].begin() as db:
        user = db.scalar(select(User).where(
            User.org_id == ai_env["org_id"], User.role == "admin"))
        lead = FacebookLead(org_id=ai_env["org_id"],page_id="page-123",
                            psid="psid-456",ai_consent=True,ai_paused=False)
        db.add(lead)
        db.flush()
        incoming = FacebookChatMessage(org_id=ai_env["org_id"],
                 lead_id=lead.id,page_id="page-123",direction="inbound",
                 state="received",body="Hola, hago gasfitería y trabajo solo.")
        db.add(incoming)
        db.flush()
        outgoing = FacebookChatMessage(org_id=ai_env["org_id"],
                 lead_id=lead.id,page_id="page-123",direction="outbound",
                 state="sent",ai_generated=True,body="¿Qué trabajo realizas?")
        db.add(outgoing)
        db.flush()
        run=AssistantRun(org_id=ai_env["org_id"],channel="messenger",
                source="ai",intent="intake",elapsed_ms=1250,
                timings={"response_model":QWEN_2B,
                         "outbound_message_id":outgoing.id})
        db.add(run)
        db.flush()
        assert schedule_next(db,user)
        trials=list(db.scalars(select(MaxPowerMessengerTrial).where(
            MaxPowerMessengerTrial.org_id==ai_env["org_id"])))
        assert len(trials)==1
        assert trials[0].criterion=="context"
        assert trials[0].source_run_id==run.id
        assert trials[0].review_id is None
        # Even if the sent message is updated after a later inbound reply,
        # MAX POWER must not leak that future reply into the old model prompt.
        from datetime import timedelta
        from app.max_power_messenger import _consented_record
        outgoing.updated_at = outgoing.created_at + timedelta(hours=1)
        later = FacebookChatMessage(org_id=ai_env["org_id"],
            lead_id=lead.id, page_id="page-123", direction="inbound",
            state="received", body="FUTURE_CONTEXT_SHOULD_NOT_APPEAR",
            created_at=outgoing.created_at + timedelta(minutes=5))
        db.add(later)
        db.flush()
        evidence = _consented_record(db, user, run)
        assert evidence is not None
        assert "FUTURE_CONTEXT_SHOULD_NOT_APPEAR" not in repr(evidence)
        assert evidence["question"] == incoming.body[:800]
        lead.ai_consent=False
        # A previously queued task is still present but the processing gate
        # re-checks consent before any inference.
        from app.max_power_messenger import _consented_record
        assert _consented_record(db,user,run) is None
