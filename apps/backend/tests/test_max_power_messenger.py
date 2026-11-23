"""Messenger trials: objective checks only, never imaginary general grading."""
from app.max_power_messenger import objective_checks, classify_messenger

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
    assert "pendiente" in reason

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
