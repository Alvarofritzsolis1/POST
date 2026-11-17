"""Tests: assistance-first intake and conditional entry documents for small trades."""
from app.facebook_onboarding import assistance_signal, reply_for_support, onboarding_guide


def test_assistance_detection_is_explicit_and_does_not_profile_literacy():
    assert assistance_signal("no entiendo eso de loh papeles")
    assert assistance_signal("no se como sacar el f30")
    assert assistance_signal("qué documentos piden para entrar a obra")
    assert assistance_signal("", is_audio=True)
    # An informal writing style alone must never flag or disqualify a contractor.
    assert assistance_signal("ola soy gasfite con dos ayudante") is None
    assert assistance_signal("kiero pega pa carpinteria") is None
    assert assistance_signal("no necesito ayuda") is None


def test_support_reply_is_short_and_asks_at_most_one_question():
    for reason in ["Solicitó orientación sobre documentación o ingreso a obra",
                   "La persona expresó dificultades con la explicación o el trámite",
                   "Solicitó comunicación por audio; requiere atención humana para escucharlo"]:
        for trade_known in [False, True]:
            message = reply_for_support(reason, trade_known)
            assert len(message) < 380
            assert message.count("?") <= 1
            assert "F-30" not in message and "Contrato de trabajo" not in message
            assert "asistente virtual" in message.lower()


def test_conditional_documents_do_not_overwhelm_persona_natural():
    solo = onboarding_guide("individual", False, "gasfiteria", needs_support=True)
    assert solo["phase"] == "help_first"
    assert solo["ask_for_files_now"] is False
    assert solo["human_followup"] is True
    assert not any("constitución de la sociedad" in doc.lower()
                   for doc in solo["required_for_review"] + solo["conditional"])
    assert not any("contratos de trabajo" in doc.lower()
                   for doc in solo["required_for_review"])
    assert any("gasfitería" in item.lower() for item in solo["prevention_examples"])
    company = onboarding_guide("company", True, "carpinteria")
    assert any("constitución" in item.lower() for item in company["required_for_review"])
    assert any("contratos de trabajo" in item.lower() for item in company["required_for_review"])
    assert any("f-30" in item.lower() for item in company["required_for_review"])
    uncertain = onboarding_guide()
    assert uncertain["next_question"] == "¿Trabajas con una empresa o a tu propio nombre?"
    assert not uncertain["required_for_review"]
